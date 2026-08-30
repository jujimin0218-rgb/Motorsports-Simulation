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

import TrackMap, { type CarOnTrack } from '../components/TrackMap'
import { lapTime, titleCase } from '../components/format'
import { ErrorNotice, Empty, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'

/** Colour-blind-safe, and stable per team so a car keeps its colour. */
const PALETTE = [
  '#0072B2', '#E69F00', '#009E73', '#CC79A7',
  '#56B4E9', '#D55E00', '#F0E442', '#8c8c8c',
  '#7B68EE', '#2E8B57',
]

const SPEEDS = [1, 2, 5, 10, 30]

export default function Replay() {
  const game = useLoadedGame()
  const [params, setParams] = useSearchParams()

  // The server says which races it still has a track for -- only the most
  // recent few are kept, and asking for one it does not have to find out would
  // be a 404 as a lookup.
  const available = game.replays
  const raceId = params.get('race') ?? available[available.length - 1] ?? ''

  const finished = useMemo(
    () => Math.max(0, (game.current_round?.number ?? 23) - 1),
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

  const [step, setStep] = useState(0)
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

  const teams = [...new Set(data.cars.map((car) => car.team))].sort()
  const colourOf = (teamId: string) => PALETTE[teams.indexOf(teamId) % PALETTE.length]

  const order = [...data.cars]
    .map((car) => ({ car, distance: car.distances[Math.min(step, steps - 1)] ?? 0 }))
    .sort((a, b) => b.distance - a.distance)

  const elapsed = step * data.interval
  const cars: CarOnTrack[] = order.map(({ car, distance }, index) => ({
    carNumber: car.car_number,
    distance,
    label: String(index + 1),
    colour: colourOf(car.team),
    isPlayer: car.team === game.player_team,
    retired: car.stopped_at !== null && elapsed >= car.stopped_at,
  }))

  const leader = order[0]?.distance ?? 0
  const lap = Math.min(data.laps, Math.floor(leader / data.lap_length) + 1)

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

      <div
        className="grid two"
        style={{ gridTemplateColumns: 'minmax(0, 1.55fr) minmax(0, 1fr)' }}
      >
        <Panel
          title={`Lap ${lap} of ${data.laps}`}
          action={
            <div className="inline">
              <Pill tone="off">{lapTime(elapsed)}</Pill>
              <Pill>{Math.round(leader).toLocaleString()} m</Pill>
            </div>
          }
        >
          <TrackMap geometry={geometry.data} cars={cars} height={430} />

          <div className="row" style={{ marginTop: 12, alignItems: 'center' }}>
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
          </div>
          <p className="subtitle" style={{ marginBottom: 0 }}>
            Positions were sampled from the engine's own timing tower every{' '}
            {data.interval} seconds of race time. Nothing here is interpolated
            between lap times.
          </p>
        </Panel>

        <Panel title="Order">
          <div className="scroll">
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
                      className={car.team === game.player_team ? 'you' : ''}
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
        </Panel>
      </div>

      {data.events.length > 0 && (
        <Panel title="What happened">
          <div className="scroll">
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
