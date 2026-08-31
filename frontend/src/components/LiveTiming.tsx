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

import { lapTime } from './format'
import { Pill } from './ui'
import type { Job, LiveQualifying, LiveRace } from '../types/api'
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

function RaceBoard({ live }: { live: LiveRace }) {
  return (
    <>
      <div className="scroll-tall">
        <table>
          <thead>
            <tr>
              <th className="right">#</th>
              <th>Driver</th>
              <th>Team</th>
              <th className="right">Gap</th>
              <th className="right">Interval</th>
            </tr>
          </thead>
          <tbody>
            {live.order.map((row) => (
              <tr
                key={row.car_number}
                className={`${row.is_player ? 'you' : ''} ${row.retired ? 'dim' : ''}`}
              >
                <td className="pos">{row.position ?? '—'}</td>
                <td>{row.driver}</td>
                <td className="muted">{row.team}</td>
                <td className="right num">{row.retired ? '' : row.position === 1 ? '—' : row.gap}</td>
                <td className="right num dim">
                  {row.retired ? <Pill tone="warn">DNF</Pill> : row.position === 1 ? '—' : row.interval}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {live.fastest_lap && (
        <p className="subtitle" style={{ marginBottom: 0, marginTop: 10 }}>
          Fastest so far: {live.fastest_lap.driver} — {lapTime(live.fastest_lap.lap_time)} on
          lap {live.fastest_lap.lap}.
        </p>
      )}
    </>
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

export default function LiveTiming({ job }: { job: Job<unknown> }) {
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
      {live &&
        (isLiveRace(live) ? <RaceBoard live={live} /> : <QualifyingBoard live={live} />)}
    </div>
  )
}
