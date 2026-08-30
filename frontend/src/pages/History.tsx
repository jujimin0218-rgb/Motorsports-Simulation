/**
 * The history book, and the end of a season.
 *
 * Two things share this page because they are the same moment from either
 * side: the year that has just finished and every year before it. A season is
 * settled here (which pays it out and files it) and the winter is taken here
 * (which is where the cars are rebased, the drivers age, and the contracts run
 * out).
 *
 * They are two buttons rather than one deliberately. A player should be able
 * to look at a finished championship before committing to the next season,
 * because once the winter has happened the grid is a different grid.
 */

import { useState } from 'react'

import { money, ordinal, rating } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel, Pill, Stat } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useGame, useLoadedGame } from '../hooks/useGame'
import { ApiFailure, api } from '../services/api'
import type { SeasonSummary, WinterReport } from '../types/api'

export default function History() {
  const game = useLoadedGame()
  const { refresh } = useGame()
  const history = useAsync(() => api.history(), [game.season])

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [summary, setSummary] = useState<SeasonSummary | null>(null)
  const [winter, setWinter] = useState<WinterReport | null>(null)

  async function act<T>(work: () => Promise<T>, then: (result: T) => void) {
    setBusy(true)
    setError(null)
    try {
      then(await work())
      await refresh()
      history.reload()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  const settled = (history.data ?? []).some((row) => row.season === game.season)
  const teamName = (id: string) =>
    game.standings.teams.find((row) => row.team === id)?.team_name ?? id
  const driverName = (id: string) =>
    game.standings.drivers.find((row) => row.driver === id)?.driver_name ?? id

  return (
    <>
      <PageHead
        title="History"
        subtitle={
          game.season_complete
            ? `The ${game.season} season is over.`
            : `${game.season} is still running — round ${game.current_round?.number}.`
        }
        action={
          game.season_complete && (
            <div className="inline">
              <button
                className={settled ? '' : 'primary'}
                disabled={busy || settled}
                onClick={() => void act(() => api.closeSeason(), setSummary)}
              >
                Settle {game.season}
              </button>
              <button
                className={settled ? 'primary' : ''}
                disabled={busy || !settled}
                onClick={() =>
                  void act(() => api.startNextSeason(), (report) => {
                    setWinter(report)
                    setSummary(null)
                  })
                }
              >
                Start {game.season + 1}
              </button>
            </div>
          )
        }
      />

      <ErrorNotice error={error ?? history.error} />

      {summary && (
        <Panel
          title={`${summary.season} settled`}
          note="Prize money paid, and the year filed in the book."
        >
          <div className="grid three">
            <Stat
              label="Drivers' champion"
              value={driverName(summary.driver_champion)}
            />
            <Stat
              label="Constructors' champion"
              value={teamName(summary.constructor_champion)}
            />
            <Stat
              label="You finished"
              value={summary.player_position ? ordinal(summary.player_position) : '—'}
            />
          </div>
          {summary.settlements[game.player_team] && (
            <>
              <hr className="rule" />
              <table>
                <tbody>
                  {summary.settlements[game.player_team].lines.map((line, index) => (
                    <tr key={index}>
                      <td>{line.label}</td>
                      <td
                        className={`right num ${line.amount > 0 ? 'good' : 'bad'}`}
                        style={{ width: 110 }}
                      >
                        {line.amount > 0 ? '+' : ''}
                        {money(line.amount, 2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Panel>
      )}

      {winter && (
        <Panel
          title={`The winter — ${winter.season} is ready`}
          note="Every winter is a new car, built from where the old one got to. The spread the teams earned is kept; the level is not, or the grid runs out of headroom."
        >
          <div className="grid three">
            <Stat label="Rounds" value={winter.rounds} />
            <Stat
              label="Retired"
              value={winter.retired.length}
              note={winter.retired.map(driverName).join(', ') || 'nobody'}
            />
            <Stat
              label="Out of contract"
              value={winter.contracts_expired.length}
              note="now in the market"
            />
          </div>
          <hr className="rule" />
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Team</th>
                  <th className="right">New car</th>
                  <th className="right">Reputation</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(winter.rebased)
                  .sort((a, b) => b[1] - a[1])
                  .map(([teamId, level]) => (
                    <tr key={teamId} className={teamId === game.player_team ? 'you' : ''}>
                      <td>{teamName(teamId)}</td>
                      <td className="right num">{rating(level)}</td>
                      <td className="right num muted">
                        {rating(winter.reputations[teamId] ?? 0, 2)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <Panel title="Seasons">
        {history.loading && <Loading />}
        {(history.data ?? []).length === 0 ? (
          <div className="empty">
            No season has been settled yet. The book fills up as you go.
          </div>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th className="right">Season</th>
                  <th>Drivers' champion</th>
                  <th>Constructors' champion</th>
                  <th className="right">You</th>
                  <th className="right">Winners</th>
                </tr>
              </thead>
              <tbody>
                {[...(history.data ?? [])].reverse().map((record) => {
                  const winners = new Set(record.race_winners)
                  const driverRow = record.standings.drivers.find(
                    (row) => row.driver === record.driver_champion,
                  )
                  const teamRow = record.standings.teams.find(
                    (row) => row.team === record.constructor_champion,
                  )
                  return (
                    <tr key={record.season}>
                      <td className="pos">{record.season}</td>
                      <td>
                        {driverRow?.driver_name ?? record.driver_champion}
                        {driverRow && (
                          <span className="tag"> {driverRow.points} pts</span>
                        )}
                      </td>
                      <td>
                        {teamRow?.team_name ?? record.constructor_champion}
                        {teamRow && <span className="tag"> {teamRow.points} pts</span>}
                      </td>
                      <td className="right">
                        <Pill
                          tone={
                            record.player_team_position <= 3
                              ? 'on'
                              : record.player_team_position <= 6
                                ? 'off'
                                : 'warn'
                          }
                        >
                          {ordinal(record.player_team_position)}
                        </Pill>
                      </td>
                      <td className="right num dim">
                        {winners.size} of {record.race_winners.length}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {(history.data ?? []).length > 0 && (
        <Panel title="Every champion so far">
          <div className="grid three">
            {(() => {
              const titles = new Map<string, number>()
              for (const record of history.data ?? []) {
                titles.set(
                  record.constructor_champion,
                  (titles.get(record.constructor_champion) ?? 0) + 1,
                )
              }
              return [...titles.entries()]
                .sort((a, b) => b[1] - a[1])
                .map(([teamId, count]) => (
                  <div key={teamId}>
                    <div className="stat-label">{teamName(teamId)}</div>
                    <div className="num" style={{ fontSize: 22, marginTop: 2 }}>
                      {count}
                    </div>
                    <div className="stat-note">
                      {count === 1 ? 'title' : 'titles'}
                    </div>
                  </div>
                ))
            })()}
          </div>
        </Panel>
      )}
    </>
  )
}
