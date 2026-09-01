/**
 * A race, driven.
 *
 * The other race screens in here read a session the server has already
 * simulated -- a timing tower that moves a lap at a time. This one *is* the
 * simulation: twenty cars with their own physics and their own drivers, being
 * driven round the circuit in front of you at sixty frames a second, and the
 * order, the gaps and the incidents are read off that.
 *
 * The circuit and the field come from the game (the round's real geometry, the
 * teams' cars, the drivers' ratings). Everything after lights out comes from
 * the loop.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ErrorNotice, Loading, Pill } from '../components/ui'
import { teamColours } from '../components/teamColour'
import { useAsync } from '../hooks/useAsync'
import { api } from '../services/api'
import { AVERAGE_DRIVER, traitsFrom } from '../race/ai'
import { Entry, Race, RaceCar, formatLap } from '../race/race'
import { CameraMode, Renderer } from '../race/render'
import { speedOf } from '../race/physics'
import type { DriverRow, TeamRow, TrackWorld } from '../types/api'

/** Simulated seconds per real second. */
const SPEEDS = [0.25, 0.5, 1, 2, 4]

function buildField(drivers: DriverRow[], teams: TeamRow[]): Entry[] {
  const colourOf = teamColours(teams.map((t) => t.id))
  const byTeam = new Map(teams.map((t) => [t.id, t]))
  const racing = drivers.filter((d) => d.team && byTeam.has(d.team)).slice(0, 20)
  // Ordered by how quick the package is, which is a reasonable grid before
  // anybody has qualified.
  const ranked = [...racing].sort((a, b) => {
    const ca = byTeam.get(a.team!)!.car_overall
    const cb = byTeam.get(b.team!)!.car_overall
    return cb + (b.overall ?? 0) - (ca + (a.overall ?? 0))
  })
  return ranked.map((d, index) => {
    const team = byTeam.get(d.team!)!
    const performance = team.car_overall > 1.5 ? team.car_overall / 100 : team.car_overall
    return {
      car: index + 1,
      driver: d.name,
      abbrev: d.abbreviation,
      team: team.name,
      colour: colourOf(team.id),
      performance,
      powerBias: 0.5,
      traits: d.skills ? traitsFrom(d.skills, d.form ?? 0) : AVERAGE_DRIVER,
      grid: index + 1,
    }
  })
}

function Bar({ value, colour }: { value: number; colour: string }) {
  return (
    <div className="livebar">
      <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: colour }} />
    </div>
  )
}

function Tower({
  cars,
  follow,
  onFollow,
  leader,
}: {
  cars: RaceCar[]
  follow: number | null
  onFollow: (car: number) => void
  leader: RaceCar | null
}) {
  return (
    <div className="livetower">
      {cars.map((car) => {
        const gap =
          car.position === 1
            ? 'Leader'
            : car.status === 'retired'
              ? 'OUT'
              : leader && car.lap < leader.lap
                ? `+${leader.lap - car.lap}L`
                : `+${car.interval.toFixed(3)}`
        return (
          <button
            key={car.number}
            type="button"
            className={[
              'liverow',
              follow === car.number ? 'followed' : '',
              car.status === 'retired' ? 'out' : '',
              car.entry.isPlayer ? 'player' : '',
            ].join(' ')}
            onClick={() => onFollow(car.number)}
            title={`Watch from ${car.entry.driver}`}
          >
            <span className="pos num">{car.status === 'retired' ? '–' : car.position}</span>
            <span className="dash" style={{ background: car.entry.colour }} />
            <span className="who">
              <span className="abbrev">{car.entry.abbrev}</span>
              <span className="team dim">{car.entry.team}</span>
            </span>
            <span className="state">
              {car.status === 'pit' ? (
                <Pill tone="warn">PIT</Pill>
              ) : car.drsOpen ? (
                <Pill tone="on">DRS</Pill>
              ) : car.intent === 'attacking' || car.intent === 'switchback' ? (
                <Pill tone="on">ATT</Pill>
              ) : car.intent === 'defending' ? (
                <Pill>DEF</Pill>
              ) : car.inWake > 0.35 ? (
                <Pill>AIR</Pill>
              ) : null}
            </span>
            <span className="gap num">{gap}</span>
            <span className="last num dim">{car.lastLap ? formatLap(car.lastLap) : '—'}</span>
            <span className="stops num dim">{car.stops}</span>
          </button>
        )
      })}
    </div>
  )
}

export default function LiveRace() {
  const world = useAsync<TrackWorld>(() => api.trackWorld(), [])
  const drivers = useAsync<DriverRow[]>(() => api.drivers(), [])
  const teams = useAsync<TeamRow[]>(() => api.teams(), [])

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const raceRef = useRef<Race | null>(null)
  const rendererRef = useRef<Renderer | null>(null)
  const rafRef = useRef<number | null>(null)

  const [laps, setLaps] = useState(8)
  const [speed, setSpeed] = useState(1)
  const [running, setRunning] = useState(true)
  const [mode, setMode] = useState<CameraMode>('tv')
  const [follow, setFollow] = useState<number | null>(null)
  const [, forceTick] = useState(0)
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1e9))
  const [error, setError] = useState<Error | null>(null)

  const field = useMemo(
    () => (drivers.data && teams.data ? buildField(drivers.data, teams.data) : null),
    [drivers.data, teams.data],
  )

  // Build the race whenever the circuit, the field or the settings change.
  useEffect(() => {
    if (!world.data || !field || field.length === 0) return
    try {
      const race = new Race(world.data, field, { laps, seed })
      raceRef.current = race
      rendererRef.current = new Renderer(race)
      rendererRef.current.watch(follow, mode)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
    }
    // `follow`/`mode` are applied separately; rebuilding on them would restart
    // the race every time somebody looked at a different car.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [world.data, field, laps, seed])

  useEffect(() => {
    rendererRef.current?.watch(follow, mode)
  }, [follow, mode])

  // The loop. Simulated time advances by real time times the chosen speed, so
  // the race is watched rather than waited for.
  useEffect(() => {
    let last = performance.now()
    let sinceTick = 0
    const frame = (now: number) => {
      rafRef.current = requestAnimationFrame(frame)
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      const race = raceRef.current
      const renderer = rendererRef.current
      const canvas = canvasRef.current
      if (!race || !renderer || !canvas) return

      if (running && !race.cars.every((c) => c.status === 'finished' || c.status === 'retired')) {
        // Sub-stepped by the race itself; here we only decide how much time
        // passed. Capped so a background tab does not simulate ten minutes in
        // one frame when it comes back.
        race.step(Math.min(0.05, dt * speed))
      }
      renderer.update(dt)

      const ratio = window.devicePixelRatio || 1
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
        canvas.width = Math.round(w * ratio)
        canvas.height = Math.round(h * ratio)
      }
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.save()
      ctx.scale(ratio, ratio)
      renderer.draw(ctx, w, h)
      ctx.restore()

      sinceTick += dt
      if (sinceTick > 0.12) {
        sinceTick = 0
        forceTick((n) => n + 1)
      }
    }
    rafRef.current = requestAnimationFrame(frame)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [running, speed])

  const onCanvasClick = useCallback((event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    const renderer = rendererRef.current
    if (!canvas || !renderer) return
    const box = canvas.getBoundingClientRect()
    const picked = renderer.pick(
      event.clientX - box.left, event.clientY - box.top, box.width, box.height,
    )
    if (picked !== null) {
      setFollow(picked)
      if (mode === 'tv') setMode('chase')
    }
  }, [mode])

  if (world.error || drivers.error || teams.error) {
    return <ErrorNotice error={world.error ?? drivers.error ?? teams.error} />
  }
  if (!world.data || !drivers.data || !teams.data) return <Loading what="the circuit and the field" />
  if (error) return <ErrorNotice error={error} />

  const race = raceRef.current
  const standings = race ? race.standings() : []
  const leader = standings.find((c) => c.position === 1) ?? null
  const watched = follow !== null ? race?.cars.find((c) => c.number === follow) ?? null : null
  const recent = race ? race.events.slice(-14).reverse() : []

  return (
    <div className="live">
      <header className="live-head">
        <div className="stack">
          <h1>{world.data.name}</h1>
          <span className="subtitle">
            {race
              ? `Lap ${Math.min(race.leaderLap + (race.started ? 1 : 0), laps)} / ${laps} · ${race.circuit.corners.length} corners · ${(race.circuit.length / 1000).toFixed(3)} km`
              : 'building the circuit…'}
          </span>
        </div>
        <div className="live-controls">
          <button className="ghost" onClick={() => setRunning((r) => !r)}>
            {running ? 'Pause' : 'Resume'}
          </button>
          <div className="seg">
            {SPEEDS.map((s) => (
              <button
                key={s}
                className={speed === s ? 'on' : ''}
                onClick={() => setSpeed(s)}
                type="button"
              >
                {s}×
              </button>
            ))}
          </div>
          <div className="seg">
            {(['tv', 'chase', 'onboard'] as CameraMode[]).map((m) => (
              <button
                key={m}
                className={mode === m ? 'on' : ''}
                type="button"
                onClick={() => {
                  setMode(m)
                  if (m === 'tv') setFollow(null)
                  else if (follow === null && leader) setFollow(leader.number)
                }}
              >
                {m === 'tv' ? 'Trackside' : m === 'chase' ? 'Chase' : 'Onboard'}
              </button>
            ))}
          </div>
          <label className="seg-label">
            Laps
            <input
              type="number"
              min={1}
              max={40}
              value={laps}
              onChange={(e) => setLaps(Math.max(1, Math.min(40, Number(e.target.value) || 1)))}
            />
          </label>
          <button className="ghost" onClick={() => setSeed(Math.floor(Math.random() * 1e9))}>
            Restart
          </button>
        </div>
      </header>

      <div className="live-body">
        <div className="live-canvas">
          <canvas ref={canvasRef} onClick={onCanvasClick} />
          {watched ? (
            <div className="hud">
              <div className="hud-name" style={{ borderColor: watched.entry.colour }}>
                <strong>{watched.entry.driver}</strong>
                <span className="dim">{watched.entry.team}</span>
              </div>
              <div className="hud-speed num">
                {(speedOf(watched.state) * 3.6).toFixed(0)}
                <span className="unit">km/h</span>
              </div>
              <div className="hud-inputs">
                <span className="dim">THR</span>
                <Bar value={watched.controls.throttle} colour="#4ade80" />
                <span className="dim">BRK</span>
                <Bar value={watched.controls.brake} colour="#f87171" />
                <span className="dim">TYRE</span>
                <Bar value={1 - watched.state.tyreWear} colour="#fbbf24" />
              </div>
              <div className="hud-line">
                <span>{watched.intent}</span>
                <span className="dim">line: {watched.lineId}</span>
                {watched.drsOpen ? <Pill tone="on">DRS</Pill> : null}
                {watched.surface !== 'track' && watched.surface !== 'kerb' ? (
                  <Pill tone="hot">{watched.surface}</Pill>
                ) : null}
              </div>
            </div>
          ) : null}
          <div className="live-hint dim">
            Click a car, or a row in the tower, to watch from it · Trackside / Chase / Onboard
          </div>
        </div>

        <aside className="live-side">
          <Tower cars={standings} follow={follow} onFollow={(n) => {
            setFollow(n)
            if (mode === 'tv') setMode('chase')
          }} leader={leader} />
          <div className="live-feed">
            {recent.map((e) => (
              <div key={e.id} className={`feed-row kind-${e.kind}`}>
                <span className="num dim">L{e.lap}</span>
                <span>{e.text}</span>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  )
}
