/**
 * Both championships.
 *
 * Computed on the server from the race results every time they are asked for,
 * so there is no running total anywhere that can drift out of step with the
 * races that produced it — which is why this page has no state of its own.
 */

import { ordinal } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'

export default function Standings() {
  const game = useLoadedGame()
  const standings = useAsync(() => api.standings(), [game.current_round?.number])

  if (standings.loading && !standings.data) return <Loading what="Counting" />

  const data = standings.data ?? game.standings
  const raced = data.drivers.some((row) => row.starts > 0)

  return (
    <>
      <PageHead
        title="Championship"
        subtitle={
          raced
            ? 'Points, then wins, then podiums, then the best single result.'
            : 'Nothing has been run yet.'
        }
      />

      <ErrorNotice error={standings.error} />

      <div className="grid two">
        <Panel title="Drivers">
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th className="right">#</th>
                  <th>Driver</th>
                  <th>Team</th>
                  <th className="right">Pts</th>
                  <th className="right">W</th>
                  <th className="right">P</th>
                  <th className="right">Pole</th>
                  <th className="right">DNF</th>
                </tr>
              </thead>
              <tbody>
                {data.drivers.map((row) => (
                  <tr
                    key={row.driver}
                    className={row.team === game.player_team ? 'you' : ''}
                  >
                    <td className="pos">{row.position}</td>
                    <td>{row.driver_name}</td>
                    <td className="muted">{row.team_name}</td>
                    <td className="right num">{row.points}</td>
                    <td className="right num">{row.wins || ''}</td>
                    <td className="right num">{row.podiums || ''}</td>
                    <td className="right num">{row.poles || ''}</td>
                    <td className="right num dim">{row.dnfs || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Constructors">
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th className="right">#</th>
                  <th>Team</th>
                  <th className="right">Pts</th>
                  <th className="right">W</th>
                  <th className="right">P</th>
                  <th className="right">Best</th>
                </tr>
              </thead>
              <tbody>
                {data.teams.map((row) => (
                  <tr key={row.team} className={row.team === game.player_team ? 'you' : ''}>
                    <td className="pos">{row.position}</td>
                    <td>{row.team_name}</td>
                    <td className="right num">{row.points}</td>
                    <td className="right num">{row.wins || ''}</td>
                    <td className="right num">{row.podiums || ''}</td>
                    <td className="right num dim">
                      {row.best_finish ? ordinal(row.best_finish) : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!raced && (
            <div className="inline" style={{ marginTop: 12 }}>
              <Pill tone="off">everybody starts on zero</Pill>
            </div>
          )}
        </Panel>
      </div>
    </>
  )
}
