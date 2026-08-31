/**
 * A session while it is still running.
 *
 * Qualifying and a race are minutes of simulation, and what the player used to
 * get for those minutes was a bar and a percentage -- the same picture whether
 * their car was leading or three laps down.  The server now sends the timing
 * screen along with the progress, so this shows the session instead of the
 * wait for it.
 *
 * Deliberately the same shape as the tables the finished session is read back
 * in: a race that is being watched and a race that is over should not look
 * like two different games.
 */

import { useState } from 'react'

import TrackMap, { type CarOnTrack } from './TrackMap'
import WorldMap, { placeOnWorld } from './WorldMap'
import { lapTime } from './format'
import { teamColours } from './teamColour'
import { Pill } from './ui'
import { useAsync } from '../hooks/useAsync'
import { api } from '../services/api'
import type {
  Job,
  LiveQualifying,
  LiveRace,
  LiveRaceRow,
  TrackWorld,
  WorldCar,
} from '../types/api'
import { isLiveRace } from '../types/api'

/** Seconds since the job started, for a session that cannot say how far along it is. */
function elapsedSince(started: number | undefined): string {
  if (!started) return '…'
  return `${Math.max(0, Math.round(Date.now() / 1000 - started))}s`
}

function Bar({ value }: { value: number }) {
  const known = value > 0
  return (
    <div className={`bar accent progress-bar ${known ? '' : 'indeterminate'}`}>
      <span style={known ? { width: `${Math.max(2, value * 100)}%` } : undefined} />
    </div>
  )
}

/** The tyre a car is on, as a letter and a colour, the way a broadcast shows it. */
function Tyre({ compound, age }: { compound: string | null; age: number }) {
  if (!compound) return null
  const letter = compound[0]?.toUpperCase() ?? '?'
  const colour =
    { S: '#e2544a', M: '#e3a33a', H: '#e6e9ee', I: '#35c07a', W: '#4d9be6' }[letter] ??
    '#8b94a3'
  return (
    <span className="tyre" title={`${compound}, ${age} lap${age === 1 ? '' : 's'} old`}>
      <span className="tyre-mark" style={{ borderColor: colour, color: colour }}>
        {letter}
      </span>
      <span className="num dim">{age}</span>
    </span>
  )
}

/** Places made up on the grid slot, as an arrow rather than a signed number. */
function Change({ gained }: { gained: number | null }) {
  if (gained === null || gained === 0) return <span className="dim">–</span>
  return (
    <span className={gained > 0 ? 'good' : 'bad'}>
      {gained > 0 ? '▲' : '▼'}
      {Math.abs(gained)}
    </span>
  )
}

function Tower({
  live,
  colourOf,
  follow,
  onFollow,
}: {
  live: LiveRace
  colourOf: (team: string) => string
  follow: number | null
  onFollow: (car: number | null) => void
}) {
  return (
    <div className="scroll-tall">
      <table className="tower">
        <thead>
          <tr>
            <th className="right">#</th>
            <th />
            <th>Driver</th>
            <th className="right">Gap</th>
            <th className="right">Int</th>
            <th className="right">Last</th>
            <th>Tyre</th>
            <th className="right">Stop</th>
          </tr>
        </thead>
        <tbody>
          {live.order.map((row) => (
            <tr
              key={row.car_number}
              onClick={() => onFollow(follow === row.car_number ? null : row.car_number)}
              className={[
                row.is_player ? 'you' : '',
                row.retired ? 'dim' : '',
                follow === row.car_number ? 'followed' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <td className="pos">{row.position ?? '—'}</td>
              <td style={{ width: 4, padding: 0 }}>
                <span
                  style={{
                    display: 'block',
                    width: 3,
                    height: 18,
                    borderRadius: 2,
                    background: colourOf(row.team),
                    opacity: row.retired ? 0.4 : 1,
                  }}
                />
              </td>
              <td>
                {row.driver}
                {row.fastest_lap && (
                  <span className="tag" style={{ marginLeft: 6, color: '#CC79A7' }}>
                    FL
                  </span>
                )}
                <span className="tower-team muted">{row.team}</span>
              </td>
              <td className="right num">
                {row.retired ? '' : row.position === 1 ? '—' : row.gap}
              </td>
              <td
                className={`right num ${
                  !row.retired && row.position !== 1 && row.interval.startsWith('+0.')
                    ? 'good'
                    : 'dim'
                }`}
              >
                {row.retired ? <Pill tone="warn">DNF</Pill> : row.position === 1 ? '—' : row.interval}
              </td>
              <td className="right num dim">{lapTime(row.last_lap)}</td>
              <td>
                <Tyre compound={row.compound} age={row.tyre_age} />
              </td>
              <td className="right num dim">
                <Change gained={row.gained} /> <span className="dim">{row.stops}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RaceBoard({ live, world }: { live: LiveRace; world: TrackWorld | null }) {
  const track = useAsync(() => api.track(), [])
  const [follow, setFollow] = useState<number | null>(null)
  const [corners, setCorners] = useState(false)
  // Two pictures of the same race: the schematic for where everybody is round
  // the lap, the laid-out circuit for what is happening on a piece of road.
  const [laidOut, setLaidOut] = useState(true)

  const colourOf = teamColours(live.order.map((row) => row.team))
  const cars: CarOnTrack[] = live.order.map((row: LiveRaceRow) => ({
    carNumber: row.car_number,
    distance: row.distance,
    offset: row.offset,
    label: String(row.position ?? ''),
    colour: colourOf(row.team),
    isPlayer: row.is_player,
    retired: row.retired,
    drs: row.drs,
    inWake: row.in_wake,
    pitting: row.pitted,
  }))
  const followed = live.order.find((row) => row.car_number === follow)

  const placed: WorldCar[] = world
    ? live.order.map((row) => {
        const at = placeOnWorld(world, row.distance, row.offset)
        return {
          car_number: row.car_number,
          x: at.x,
          y: at.y,
          heading: at.heading,
          label: String(row.position ?? ''),
          colour: colourOf(row.team),
          is_player: row.is_player,
          retired: row.retired,
          drs: row.drs,
          in_wake: row.in_wake,
        }
      })
    : []

  const racing = live.order.filter((row) => !row.retired)
  const inWake = racing.filter((row) => row.in_wake).length
  const withDrs = racing.filter((row) => row.drs).length

  return (
    <div className="raceview">
      {laidOut && world ? (
        <WorldMap world={world} cars={placed} height="100%" follow={follow} />
      ) : track.data ? (
        <TrackMap
          geometry={track.data}
          cars={cars}
          height="100%"
          showCorners={corners}
          follow={follow}
        />
      ) : (
        <div className="empty">Drawing the circuit…</div>
      )}

      <div className="raceview-panel raceview-head">
        <h2>
          Lap {live.lap} of {live.laps}
        </h2>
        <span className="raceview-key">
          <span>
            <i style={{ background: '#35c07a' }} /> DRS {withDrs}
          </span>
          <span>
            <i style={{ background: '#e3a33a' }} /> dirty air {inWake}
          </span>
          {live.retired > 0 && (
            <span>
              <i style={{ background: '#8b94a3' }} /> out {live.retired}
            </span>
          )}
        </span>
      </div>

      <div className="raceview-panel raceview-tower">
        <Tower live={live} colourOf={colourOf} follow={follow} onFollow={setFollow} />
      </div>

      <div className="raceview-panel raceview-foot">
        <button className="ghost" onClick={() => setLaidOut((on) => !on)}>
          {laidOut ? 'Schematic' : 'Track'}
        </button>
        {!laidOut && (
          <button className="ghost" onClick={() => setCorners((c) => !c)}>
            {corners ? 'Hide corners' : 'Corners'}
          </button>
        )}
        {followed ? (
          <button className="ghost" onClick={() => setFollow(null)}>
            Following {followed.driver} — stop
          </button>
        ) : (
          <span className="subtitle" style={{ margin: 0 }}>
            Pick a car in the tower to follow it · scroll to zoom · drag to pan
          </span>
        )}
        {live.fastest_lap && (
          <span className="subtitle" style={{ margin: 0 }}>
            Fastest: {live.fastest_lap.driver} {lapTime(live.fastest_lap.lap_time)}
          </span>
        )}
      </div>
    </div>
  )
}

function QualifyingBoard({ live }: { live: LiveQualifying }) {
  return (
    <div className="scroll-tall">
      <table>
        <thead>
          <tr>
            <th className="right">#</th>
            <th>Driver</th>
            <th>Team</th>
            <th className="right">Best</th>
            <th className="right">Gap</th>
            <th>Set in</th>
          </tr>
        </thead>
        <tbody>
          {live.order.map((row) => (
            <tr key={row.car_number} className={row.is_player ? 'you' : ''}>
              <td className="pos">{row.position ?? '—'}</td>
              <td>{row.driver}</td>
              <td className="muted">{row.team}</td>
              <td className="right num">{row.best === null ? 'no time' : lapTime(row.best)}</td>
              <td className="right num dim">
                {row.gap === null ? '' : row.gap === 0 ? '—' : `+${row.gap.toFixed(3)}`}
              </td>
              <td className="tag">{row.segment ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function LiveTiming({
  job,
  world = null,
}: {
  job: Job<unknown>
  /** The laid-out circuit, fetched by the page before the race starts. */
  world?: TrackWorld | null
}) {
  const live = job.live
  const racing = job.kind === 'race'

  // Until the first lap lands there is nothing to show but the clock, which is
  // the honest version of "this has started and has not got anywhere yet".
  const heading = !live
    ? racing
      ? 'The grand prix is starting'
      : 'Qualifying is running'
    : isLiveRace(live)
      ? `Lap ${live.lap} of ${live.laps}`
      : `${live.segment} ${live.complete ? 'complete' : 'running'}`

  // A race with cars on the road takes the screen; anything else -- qualifying,
  // or the moment before the first lap lands -- is a panel like any other.
  if (live && isLiveRace(live)) return <RaceBoard live={live} world={world} />

  return (
    <div className="panel">
      <div className="spread" style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>{heading}</h2>
        <span className="num dim">
          {job.progress > 0
            ? `${Math.round(job.progress * 100)}%`
            : elapsedSince(job.started_at)}
        </span>
      </div>
      <Bar value={job.progress} />
      <p className="subtitle" style={{ marginTop: 10 }}>
        {racing
          ? 'Every car on every lap, and this is where they are.'
          : 'Three knockout segments, each one an order of its own.'}
      </p>
      {live && <QualifyingBoard live={live} />}
    </div>
  )
}
