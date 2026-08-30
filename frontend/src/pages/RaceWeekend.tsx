/**
 * The weekend, one legal step at a time.
 *
 * The buttons here mirror the phase machine on the server, and the server is
 * the one enforcing it -- a refusal comes back as `InvalidGamePhase` and is
 * shown as such.  The screen disables what cannot be done as a courtesy; it is
 * not what stops it.
 *
 * Qualifying and the race are **jobs**.  A grand prix is minutes of simulation
 * with every car simulated on every lap, so the screen follows the job and
 * shows it moving rather than freezing on a promise that may not settle for ten
 * minutes.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { lapTime, ordinal, percent, titleCase } from '../components/format'
import WeatherPanel from '../components/WeatherPanel'
import {
  ErrorNotice,
  Notice,
  PageHead,
  Panel,
  Pill,
  Progress,
} from '../components/ui'
import { useGame, useLoadedGame } from '../hooks/useGame'
import { ApiFailure, api, runJob } from '../services/api'
import type {
  Job,
  PracticeReport,
  QualifyingReport,
  RaceReport,
  RoundPhase,
} from '../types/api'

const ORDER: RoundPhase[] = [
  'not_started',
  'practice',
  'qualifying',
  'strategy',
  'race',
  'result',
  'development',
  'complete',
]

const LABEL: Record<RoundPhase, string> = {
  not_started: 'Not started',
  practice: 'Practice',
  qualifying: 'Qualifying',
  strategy: 'Strategy',
  race: 'Race',
  result: 'Result',
  development: 'Development',
  complete: 'Complete',
}

export default function RaceWeekend() {
  const game = useLoadedGame()
  const { refresh } = useGame()

  const [busy, setBusy] = useState<string | null>(null)
  const [job, setJob] = useState<Job<unknown> | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [practice, setPractice] = useState<PracticeReport | null>(null)
  const [qualifying, setQualifying] = useState<QualifyingReport | null>(null)
  const [race, setRace] = useState<RaceReport | null>(null)

  const round = game.current_round
  const phase = round?.phase ?? 'complete'
  const at = ORDER.indexOf(phase)

  const driverName = (id: string) =>
    game.standings.drivers.find((row) => row.driver === id)?.driver ?? id

  async function step(name: string, work: () => Promise<unknown>) {
    setBusy(name)
    setError(null)
    try {
      await work()
      await refresh()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(null)
      setJob(null)
    }
  }

  const runQualifying = () =>
    step('qualifying', async () => {
      setRace(null)
      const report = await runJob<QualifyingReport>(
        () => api.startQualifying(),
        (current) => setJob(current as Job<unknown>),
      )
      setQualifying(report)
    })

  const runRace = () =>
    step('race', async () => {
      const report = await runJob<RaceReport>(
        () => api.startRace(),
        (current) => setJob(current as Job<unknown>),
      )
      setRace(report)
    })

  if (!round) {
    return (
      <>
        <PageHead title="Season complete" subtitle={`${game.season} is done.`} />
        <Notice kind="ok">
          Every round has been run. The championship is on the standings page.
        </Notice>
      </>
    )
  }

  return (
    <>
      <PageHead
        title={`Round ${round.number} — ${round.circuit.name}`}
        subtitle={`${round.circuit.city}, ${round.circuit.country} · ${round.race_laps} laps of ${round.circuit.length_km} km`}
        action={
          <div className="inline">
            <Pill>{round.circuit.corner_count} corners</Pill>
            <Pill>{round.circuit.drs_zones} DRS</Pill>
            <Pill tone="off">{round.circuit.physics_track.replace('synthetic_', '')}</Pill>
          </div>
        }
      />

      <div className="phases">
        {ORDER.slice(0, 7).map((step_, index) => (
          <span
            key={step_}
            className={`phase ${index === at ? 'now' : index < at ? 'done' : ''}`}
          >
            {LABEL[step_]}
          </span>
        ))}
      </div>

      <ErrorNotice error={error} />

      {job && (job.status === 'pending' || job.status === 'running') && (
        <Progress
          label={job.kind === 'race' ? 'The grand prix is running' : 'Qualifying is running'}
          value={job.progress}
          since={job.started_at}
          detail={
            job.kind === 'race'
              ? `${round.race_laps} laps, every car simulated on every one of them.`
              : 'Three segments, real out-laps and real flying laps.'
          }
        />
      )}

      {!job && (
        <Panel title="What happens next">
          <div className="inline">
            <button
              className="primary"
              disabled={phase !== 'not_started' || busy !== null}
              onClick={() => void step('start', () => api.startRound())}
            >
              Start the weekend
            </button>
            <button
              disabled={phase !== 'practice' || busy !== null}
              onClick={() =>
                void step('practice', async () => setPractice(await api.runPractice()))
              }
            >
              Run practice
            </button>
            <button
              className={phase === 'qualifying' ? 'primary' : ''}
              disabled={phase !== 'qualifying' || busy !== null}
              onClick={() => void runQualifying()}
            >
              Qualify
            </button>
            <button
              className={phase === 'strategy' ? 'primary' : ''}
              disabled={phase !== 'strategy' || busy !== null}
              onClick={() => void runRace()}
            >
              Race
            </button>
            <button
              className={phase === 'result' ? 'primary' : ''}
              disabled={phase !== 'result' || busy !== null}
              onClick={() => void step('development', () => api.runDevelopment())}
            >
              Close the round
            </button>
          </div>
          <p className="subtitle" style={{ marginBottom: 0 }}>
            The order is enforced by the server, not by these buttons — posting to the
            race endpoint without qualifying gets a refusal, not a race.
          </p>
        </Panel>
      )}

      {(practice ?? qualifying ?? race) && (
        <Panel
          title="Conditions"
          note="The engine's own weather and track models. One sky runs through the weekend."
        >
          <WeatherPanel
            weather={(race ?? qualifying ?? practice)!.weather}
            forecast={practice?.forecast}
          />
        </Panel>
      )}

      {qualifying && (
        <Panel
          title="Qualifying"
          note={`Pole: ${driverName(qualifying.pole ?? '')}`}
        >
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th className="right">#</th>
                  <th>Driver</th>
                  <th>Team</th>
                  <th className="right">Best</th>
                  <th>Out in</th>
                </tr>
              </thead>
              <tbody>
                {qualifying.qualifying.map((row) => (
                  <tr key={row.driver} className={row.team === game.player_team ? 'you' : ''}>
                    <td className="pos">{row.position}</td>
                    <td>{row.driver}</td>
                    <td className="muted">{row.team}</td>
                    <td className="right num">{lapTime(row.best)}</td>
                    <td className="tag">{row.eliminated_in ?? 'Q3'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {race && (
        <Panel
          title="Race result"
          note={`${race.retirements} retirement${race.retirements === 1 ? '' : 's'} · ${race.flags.length} flag period${race.flags.length === 1 ? '' : 's'}`}
          action={
            <Link to={`/replay?race=${race.race_id}`} className="button primary">
              Watch the replay ▸
            </Link>
          }
        >
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th className="right">#</th>
                  <th>Driver</th>
                  <th>Team</th>
                  <th className="right">Started</th>
                  <th className="right">Gained</th>
                  <th className="right">Laps</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {race.classification.map((row) => {
                  const gained = row.started - row.position
                  return (
                    <tr key={row.driver} className={row.team === game.player_team ? 'you' : ''}>
                      <td className="pos">{row.position}</td>
                      <td>{row.driver}</td>
                      <td className="muted">{row.team}</td>
                      <td className="right num dim">{row.started || '—'}</td>
                      <td
                        className={`right num ${gained > 0 ? 'good' : gained < 0 ? 'bad' : 'dim'}`}
                      >
                        {gained > 0 ? `+${gained}` : gained || '—'}
                      </td>
                      <td className="right num">{row.laps_completed}</td>
                      <td>
                        <div className="inline">
                          {row.retired && <Pill tone="warn">DNF</Pill>}
                          {row.fastest_lap && <Pill tone="hot">FL</Pill>}
                          {row.pole && <Pill tone="on">POLE</Pill>}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {race.penalties.length > 0 && (
            <>
              <hr className="rule" />
              <h2 style={{ marginBottom: 8 }}>Stewards</h2>
              <table>
                <tbody>
                  {race.penalties.map((penalty, index) => (
                    <tr key={index}>
                      <td style={{ width: 130 }}>
                        <Pill
                          tone={
                            penalty.kind === 'time'
                              ? 'hot'
                              : penalty.kind === 'grid'
                                ? 'warn'
                                : 'off'
                          }
                        >
                          {penalty.kind === 'time'
                            ? `${penalty.seconds.toFixed(0)}s`
                            : penalty.kind === 'grid'
                              ? `${penalty.places} places`
                              : 'reprimand'}
                        </Pill>
                      </td>
                      <td>{penalty.driver}</td>
                      <td className="muted">{penalty.reason}</td>
                      <td className="right dim num">
                        {penalty.lap ? `lap ${penalty.lap}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="subtitle" style={{ marginBottom: 0, marginTop: 10 }}>
                A time penalty is applied before the points are, so five seconds that
                change a result change the championship too.
              </p>
            </>
          )}

          {race.flags.length > 0 && (
            <>
              <hr className="rule" />
              <div className="inline">
                {race.flags.map((flag, index) => (
                  <Pill key={index} tone="warn">
                    lap {flag.lap} · {titleCase(flag.flag)} · {flag.reason}
                  </Pill>
                ))}
              </div>
            </>
          )}
        </Panel>
      )}

      <Panel title="What this circuit asks for">
        <div className="grid three">
          {Object.entries(round.circuit.characteristics).map(([key, value]) => (
            <div key={key}>
              <div className="stat-label">{titleCase(key)}</div>
              <div className="num" style={{ fontSize: 18, marginTop: 2 }}>
                {percent(value)}
              </div>
              <div className="bar" style={{ marginTop: 6 }}>
                <span style={{ width: `${value * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
        <p className="subtitle" style={{ marginBottom: 0, marginTop: 14 }}>
          These weight the car's six areas rather than adjusting a lap time. The wing
          the car runs here comes off the downforce requirement, and the engine works
          out what that is worth — which is why the {ordinal(1)}-placed car overall is
          not always the quickest one here.
        </p>
      </Panel>
    </>
  )
}
