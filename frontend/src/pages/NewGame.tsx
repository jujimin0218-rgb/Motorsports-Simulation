/**
 * Choosing a team, which is choosing a difficulty.
 *
 * The list is shown with the three things that actually differ -- the car, the
 * money and the reputation -- because taking the quickest car is the easy game
 * and taking the smallest budget is the hard one, and the player should be able
 * to see which is which before committing to a season.
 */

import { useState } from 'react'

import { money, rating } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useGame } from '../hooks/useGame'
import { ApiFailure, api } from '../services/api'

export default function NewGame() {
  const { refresh } = useGame()
  const teams = useAsync(() => api.selectableTeams(), [])
  const saves = useAsync(() => api.saves(), [])

  const [chosen, setChosen] = useState<string | null>(null)
  const [seed, setSeed] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)

  async function start() {
    if (!chosen) return
    setBusy(true)
    setError(null)
    try {
      await api.newGame({
        player_team: chosen,
        seed: seed.trim() === '' ? null : Number(seed),
      })
      await refresh()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  async function load(saveId: string) {
    setBusy(true)
    setError(null)
    try {
      await api.load({ save_id: saveId })
      await refresh()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 980, margin: '0 auto' }}>
      <PageHead
        title="Take over a team"
        subtitle="One season, twenty-two rounds, and every race simulated by the engine underneath."
      />

      <ErrorNotice error={error} />

      {saves.data && saves.data.length > 0 && (
        <Panel title="Carry on" note="Saves already on this machine.">
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Save</th>
                  <th>Team</th>
                  <th className="right">Season</th>
                  <th className="right">Round</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {saves.data.map((save) => (
                  <tr key={save.id}>
                    <td>
                      {save.name}
                      {save.slot && <span className="tag"> · {save.slot}</span>}
                    </td>
                    <td className="muted">{save.player_team}</td>
                    <td className="right num">{save.season}</td>
                    <td className="right num">{save.round}</td>
                    <td className="right">
                      <button disabled={busy} onClick={() => void load(save.id)}>
                        Load
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <Panel
        title="Or start a new season"
        note="Quickest car is the easy game; smallest budget is the hard one."
      >
        {teams.loading && <Loading what="Reading the grid" />}
        <ErrorNotice error={teams.error} />
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th />
                <th>Team</th>
                <th>Engine</th>
                <th className="right">Car</th>
                <th className="right">Budget</th>
                <th className="right">Reputation</th>
                <th>Drivers</th>
              </tr>
            </thead>
            <tbody>
              {(teams.data ?? []).map((team) => (
                <tr
                  key={team.id}
                  className={chosen === team.id ? 'you' : ''}
                  onClick={() => setChosen(team.id)}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <input
                      type="radio"
                      style={{ width: 'auto' }}
                      checked={chosen === team.id}
                      onChange={() => setChosen(team.id)}
                    />
                  </td>
                  <td>{team.name}</td>
                  <td className="muted">{team.engine}</td>
                  <td className="right num">{rating(team.car_rating)}</td>
                  <td className="right num">{money(team.budget, 0)}</td>
                  <td className="right num">{rating(team.reputation, 2)}</td>
                  <td className="muted">{team.drivers.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <hr className="rule" />

        <div className="row">
          <div className="field" style={{ maxWidth: 220 }}>
            <label>Seed (optional)</label>
            <input
              value={seed}
              onChange={(event) => setSeed(event.target.value.replace(/\D/g, ''))}
              placeholder="leave blank for a fresh one"
            />
          </div>
          <button className="primary" disabled={!chosen || busy} onClick={() => void start()}>
            {busy ? 'Starting…' : 'Start the season'}
          </button>
        </div>
        <p className="subtitle" style={{ marginTop: 10 }}>
          The seed decides everything the game will ever draw. Left blank one is taken
          from the clock and then stored, so a season is reproducible from its first
          moment rather than from its first save.
        </p>
      </Panel>
    </div>
  )
}
