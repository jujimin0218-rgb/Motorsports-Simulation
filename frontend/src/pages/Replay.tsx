/**
 * A race, played back.
 *
 * Every car's position comes from samples the server took off the engine's own
 * timing tower when the race ran — so what moves on the screen is where the
 * simulation actually had the car, not an interpolation between lap times.
 *
 * The running order is computed from *total* distance covered rather than
 * distance round the lap, which is the difference between a leader who has just
 * crossed the line and a leader who appears to be last.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import TelemetryTrace from '../components/TelemetryTrace'
import TrackMap, { type CarOnTrack } from '../components/TrackMap'
import WorldMap, { placeOnWorld } from '../components/WorldMap'
import { teamColours } from '../components/teamColour'
import { lapTime, titleCase } from '../components/format'
import { ErrorNotice, Empty, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'

const SPEEDS = [1, 2, 5, 10, 30]

/** A second of dirty air at racing speed, in metres of road. */
const WAKE_METRES = 70

export default function Replay() {
  const game = useLoadedGame()
  const [params, setParams] = useSearchParams()

  // The server says which races it still has a track for -- only the most
  // recent few are kept, and asking for one it does not have to find out would
  // be a 404 as a lookup.
  const available = game.replays
  const raceId = params.get('race') ?? available[available.length - 1] ?? ''

  // The last round that has been run: the one before the current one, or the
  // final round of the season once there is no current one left.
  const finished = useMemo(
    () => Math.max(0, (game.current_round?.number ?? game.rounds + 1) - 1),
    [game],
  )

  const replay = useAsync(
    () => (raceId ? api.replay(raceId) : Promise.reject(new Error('nothing yet'))),
    [raceId],
  )
  const geometry = useAsync(
    () => api.track(finished > 0 ? finished : undefined),
    [finished],
  )
  const world = useAsync(
    () => api.trackWorld(finished > 0 ? finished : undefined),
    [finished],
  )

  const [step, setStep] = useState(0)
  /** Cars whose telemetry is on screen. Two compare; more is a tangle. */
  const [picked, setPicked] = useState<number[]>([])
  const [corners, setCorners] = useState(false)
  const [laidOut, setLaidOut] = useState(true)
  /** A car to keep centred, so a fight can be watched rather than found. */
  const [follow, setFollow] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(5)
  const timer = useRef<number | null>(null)

  const data = replay.data
  const steps = data?.cars[0]?.distances.length ?? 0

  useEffect(() => {
    if (!playing || steps === 0) return
    timer.current = window.setInterval(() => {
      setStep((current) => {
        if (current + 1 >= steps) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, 1000 / speed)
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [playing, speed, steps])

  if (!raceId) {
    return (
      <>
        <PageHead title="Replay" />
        <Empty>
          Nothing to play back yet — run a race and it will appear here.
        </Empty>
      </>
    )
  }
  if (replay.loading || geometry.loading) return <Loading what="Loading the replay" />
  if (replay.error) {
    return (
      <>
        <PageHead title="Replay" />
        <ErrorNotice error={replay.error} />
        <Empty>Run a race and it can be played back here.</Empty>
      </>
    )
  }
  if (!data || !geometry.data) return <Empty>Nothing to play back yet.</Empty>

  const colourOf = teamColours(data.cars.map((car) => car.team))

  const frame = Math.min(step, steps - 1)
  const order = [...data.cars]
    .map((car) => ({
      car,
      distance: car.distances[frame] ?? 0,
      offset: car.offsets?.[frame] ?? 0,
    }))
    .sort((a, b) => b.distance - a.distance)

  const elapsed = step * data.interval
  const cars: CarOnTrack[] = order.map(({ car, distance, offset }, index) => {
    // Within a second of the car in front is the engine's own wake threshold,
    // and a second at racing speed is about seventy metres of road.
    const ahead = order[index - 1]
    return {
      carNumber: car.car_number,
      distance,
      offset,
      label: String(index + 1),
      colour: colourOf(car.team),
      isPlayer: car.team === game.player_team,
      retired: car.stopped_at !== null && elapsed >= car.stopped_at,
      inWake: index > 0 && ahead.distance - distance < WAKE_METRES,
    }
  })

  const leader = order[0]?.distance ?? 0
  const lap = Math.min(data.laps, Math.floor(leader / data.lap_length) + 1)

  // Whatever is being watched: the lap on screen, for the cars picked out of
  // the running order.  A lap run behind a safety car was never simulated as a
  // lap, so it has no trace and the panel says so rather than drawing nothing.
  const traced = picked
    .map((carNumber) => {
      const car = data.cars.find((c) => c.car_number === carNumber)
      const samples = data.telemetry?.[String(carNumber)]?.[String(lap)]
      return car && samples
        ? {
            carNumber,
            driver: car.driver_name,

            samples,
          }
        : null
    })
    .filter((entry): entry is NonNullable<typeof entry> => entry !== null)

  // The last few things that happened at or before this moment, newest first,
  // so an incident is on screen when it is on screen.
  const happening = [...data.events]
    .filter((event) => (event.lap ?? 0) <= lap)
    .slice(-4)
    .reverse()

  return (
    <>
      <PageHead
        title="Replay"
        subtitle={`${data.track} · ${data.laps} laps · race ${data.race_id}`}
        action={
          available.length > 1 && (
            <select
              value={raceId}
              onChange={(event) => {
                setParams({ race: event.target.value })
                setStep(0)
                setPlaying(false)
              }}
              style={{ width: 170 }}
            >
              {[...available].reverse().map((id) => (
                <option key={id} value={id}>
                  Round {Number(id.split('-')[1])}
                </option>
              ))}
            </select>
          )
        }
      />

      <div className="raceview">
        {laidOut && world.data ? (
          <WorldMap
            world={world.data}
            cars={order.map(({ car, distance, offset }, index) => {
              const at = placeOnWorld(world.data!, distance, offset)
              return {
                car_number: car.car_number,
                x: at.x,
                y: at.y,
                heading: at.heading,
                label: String(index + 1),
                colour: colourOf(car.team),
                is_player: car.team === game.player_team,
                retired: car.stopped_at !== null && elapsed >= car.stopped_at,
                in_wake: index > 0 && order[index - 1].distance - distance < WAKE_METRES,
              }
            })}
            height="100%"
            follow={follow}
          />
        ) : (
          <TrackMap
            geometry={geometry.data}
            cars={cars}
            height="100%"
            showCorners={corners}
            follow={follow}
          />
        )}

        <div className="raceview-panel raceview-head">
          <h2>
            Lap {lap} of {data.laps}
          </h2>
          <span className="raceview-key">
            <span className="num dim">{lapTime(elapsed)}</span>
            <span>
              <i style={{ background: '#e3a33a' }} /> dirty air{' '}
              {cars.filter((c) => c.inWake && !c.retired).length}
            </span>
            {cars.some((c) => c.retired) && (
              <span>
                <i style={{ background: '#8b94a3' }} /> out{' '}
                {cars.filter((c) => c.retired).length}
              </span>
            )}
          </span>
        </div>

        {happening.length > 0 && (
          <div className="raceview-panel raceview-events">
            {happening.map((event, index) => (
              <div key={index}>
                <b>Lap {event.lap}</b> · {event.kind === 'incident' ? '⚠ ' : ''}
                {event.car_number ? `car ${event.car_number} ` : ''}
                {event.detail}
              </div>
            ))}
          </div>
        )}

        <div className="raceview-panel raceview-foot">
          <div className="row" style={{ alignItems: 'center', width: '100%' }}>
            <button className="primary" onClick={() => setPlaying((on) => !on)}>
              {playing ? 'Pause' : step >= steps - 1 ? 'Replay' : 'Play'}
            </button>
            <button
              className="ghost"
              onClick={() => {
                setStep(0)
                setPlaying(false)
              }}
            >
              Restart
            </button>
            <div className="field" style={{ flex: '1 1 220px', marginTop: 0 }}>
              <input
                type="range"
                min={0}
                max={Math.max(0, steps - 1)}
                value={step}
                onChange={(event) => {
                  setStep(Number(event.target.value))
                  setPlaying(false)
                }}
              />
            </div>
            <select
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
              style={{ width: 90 }}
            >
              {SPEEDS.map((value) => (
                <option key={value} value={value}>
                  ×{value}
                </option>
              ))}
            </select>
            <button className="ghost" onClick={() => setLaidOut((on) => !on)}>
              {laidOut ? 'Schematic' : 'Track'}
            </button>
            {!laidOut && (
              <button className="ghost" onClick={() => setCorners((c) => !c)}>
                {corners ? 'Hide corners' : 'Corners'}
              </button>
            )}
          </div>
        </div>

        <div className="raceview-panel raceview-tower">
          <div className="scroll-tall">
            <table>
              <thead>
                <tr>
                  <th className="right">#</th>
                  <th>Driver</th>
                  <th className="right">Gap</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {order.map(({ car, distance }, index) => {
                  const behind = leader - distance
                  const lapped = behind >= data.lap_length
                  const stopped = car.stopped_at !== null && elapsed >= car.stopped_at
                  return (
                    <tr
                      key={car.car_number}
                      onClick={() =>
                        setPicked((now) =>
                          now.includes(car.car_number)
                            ? now.filter((n) => n !== car.car_number)
                            : [...now, car.car_number].slice(-2),
                        )
                      }
                      onDoubleClick={() =>
                        setFollow((now) =>
                          now === car.car_number ? null : car.car_number,
                        )
                      }
                      title="Click to trace, double-click to follow on the map"
                      className={[
                        car.team === game.player_team ? 'you' : '',
                        picked.includes(car.car_number) ? 'followed' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="pos">{index + 1}</td>
                      <td>
                        <span
                          style={{
                            display: 'inline-block',
                            width: 8,
                            height: 8,
                            borderRadius: 2,
                            background: colourOf(car.team),
                            marginRight: 7,
                          }}
                        />
                        {car.driver_name}
                      </td>
                      <td className="right num dim">
                        {index === 0
                          ? '—'
                          : lapped
                            ? `+${Math.floor(behind / data.lap_length)}L`
                            : `${Math.round(behind)}m`}
                      </td>
                      <td>{stopped && <Pill tone="warn">out</Pill>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <Panel
        title={`Telemetry — lap ${lap}`}
        note="The engine's own lap simulation, kept as the race ran. Pick a car in the order to trace it; two compare."
      >
        {traced.length ? (
          <TelemetryTrace cars={traced} lapLength={data.lap_length} />
        ) : (
          <Empty>
            {picked.length
              ? `No trace for lap ${lap} — a lap run behind a safety car is not simulated as one.`
              : 'Pick a car in the running order above.'}
          </Empty>
        )}
      </Panel>

      {data.events.length > 0 && (
        <Panel title="What happened" note={`${data.events.length} moments`}>
          <div className="scroll-tall">
            <table>
              <thead>
                <tr>
                  <th className="right">Lap</th>
                  <th>Event</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.events.map((event, index) => (
                  <tr key={index}>
                    <td className="pos">{event.lap ?? '—'}</td>
                    <td>
                      <Pill
                        tone={
                          event.kind === 'flag'
                            ? 'warn'
                            : event.kind === 'incident'
                              ? 'hot'
                              : 'on'
                        }
                      >
                        {titleCase(event.kind)}
                      </Pill>
                    </td>
                    <td className="muted">
                      {event.car_number ? `car ${event.car_number} · ` : ''}
                      {event.flag ? `${titleCase(event.flag)} · ` : ''}
                      {event.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </>
  )
}
