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
import { teamColours } from '../components/teamColour'
import { lapTime, titleCase } from '../components/format'
import { ErrorNotice, Empty, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'

const SPEEDS = [1, 2, 5, 10, 30]

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

  const [step, setStep] = useState(0)
  /** Cars whose telemetry is on screen. Two compare; more is a tangle. */
  const [picked, setPicked] = useState<number[]>([])
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
            colour: colourOf(car.team),
            samples,
          }
        : null
    })
    .filter((entry): entry is NonNullable<typeof entry> => entry !== null)

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
                      onClick={() =>
                        setPicked((now) =>
                          now.includes(car.car_number)
                            ? now.filter((n) => n !== car.car_number)
                            : [...now, car.car_number].slice(-2),
                        )
                      }
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
        </Panel>
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
