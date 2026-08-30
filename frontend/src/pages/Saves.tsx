/**
 * Saves, and the two things about a game that a player sets.
 *
 * Both settings exist for a measured reason rather than as options for their
 * own sake, and the page says so: a full grand prix is ten minutes of
 * simulation because every car is simulated on every lap, and difficulty
 * changes how well the AI decides rather than how fast it goes.
 */

import { useState } from 'react'

import { percent, when } from '../components/format'
import { ErrorNotice, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useGame, useLoadedGame } from '../hooks/useGame'
import { ApiFailure, api } from '../services/api'

export default function Saves() {
  const game = useLoadedGame()
  const { refresh } = useGame()
  const saves = useAsync(() => api.saves(), [])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [note, setNote] = useState<string | null>(null)

  async function act(work: () => Promise<unknown>, describe: string) {
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      await work()
      setNote(describe)
      await refresh()
      saves.reload()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHead
        title="Saves & settings"
        subtitle={`${game.name} · seed ${game.seed}`}
      />

      <ErrorNotice error={error ?? saves.error} />
      {note && <div className="notice ok">{note}</div>}

      <Panel
        title="This game"
        note="A change takes effect from the next race — a round already run stays the length it was run at."
      >
        <div className="grid three">
          <div>
            <label>Race distance</label>
            <select
              value={game.settings.race_distance}
              disabled={busy}
              onChange={(event) =>
                void act(
                  () =>
                    api.updateSettings({ race_distance: Number(event.target.value) }),
                  `Races are now ${percent(Number(event.target.value))} distance.`,
                )
              }
            >
              {[0.25, 0.35, 0.5, 0.75, 1].map((value) => (
                <option key={value} value={value}>
                  {percent(value)}
                </option>
              ))}
            </select>
            <div className="stat-note" style={{ marginTop: 6 }}>
              A shorter race, not a cheaper one — every lap is simulated. A full
              grand prix is about ten minutes of it.
            </div>
          </div>
          <div>
            <label>Difficulty</label>
            <select
              value={game.settings.difficulty}
              disabled={busy}
              onChange={(event) =>
                void act(
                  () => api.updateSettings({ difficulty: event.target.value }),
                  `Difficulty set to ${event.target.value}.`,
                )
              }
            >
              {['easy', 'normal', 'hard'].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
            <div className="stat-note" style={{ marginTop: 6 }}>
              Changes how well the AI decides, never how fast its cars go.
            </div>
          </div>
          <div>
            <label>Hazards</label>
            <select
              value={game.settings.hazards ? 'on' : 'off'}
              disabled={busy}
              onChange={(event) =>
                void act(
                  () => api.updateSettings({ hazards: event.target.value === 'on' }),
                  `Hazards ${event.target.value}.`,
                )
              }
            >
              <option value="on">on</option>
              <option value="off">off</option>
            </select>
            <div className="stat-note" style={{ marginTop: 6 }}>
              Failures, contact and safety cars, all from the engine.
            </div>
          </div>
        </div>
      </Panel>

      <Panel title="Save">
        <div className="row">
          <div className="field" style={{ maxWidth: 280 }}>
            <label>Name</label>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={game.name}
            />
          </div>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              void act(() => api.save({ name: name || null }), 'Saved.')
            }
          >
            Save now
          </button>
        </div>
        <p className="subtitle" style={{ marginBottom: 0 }}>
          The game also autosaves after every step of a weekend. Losing a race that took
          ten minutes to a closed tab is not an experience worth shipping.
        </p>
      </Panel>

      <Panel title="Saved games">
        {(saves.data ?? []).length === 0 ? (
          <div className="empty">Nothing saved yet.</div>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Team</th>
                  <th className="right">Season</th>
                  <th className="right">Round</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(saves.data ?? []).map((save) => (
                  <tr key={save.id}>
                    <td>
                      {save.name}
                      {save.slot && (
                        <>
                          {' '}
                          <Pill tone="off">{save.slot}</Pill>
                        </>
                      )}
                    </td>
                    <td className="muted">{save.player_team}</td>
                    <td className="right num">{save.season}</td>
                    <td className="right num">{save.round}</td>
                    <td className="dim">{when(save.updated_at)}</td>
                    <td className="right">
                      <div className="inline" style={{ justifyContent: 'flex-end' }}>
                        <button
                          disabled={busy}
                          onClick={() =>
                            void act(
                              () => api.load({ save_id: save.id }),
                              `Loaded ${save.name}.`,
                            )
                          }
                        >
                          Load
                        </button>
                        <button
                          className="ghost"
                          disabled={busy}
                          onClick={() =>
                            void act(() => api.deleteSave(save.id), 'Deleted.')
                          }
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="subtitle" style={{ marginBottom: 0, marginTop: 12 }}>
          A save carries the seed, so reloading it and re-running a round gives the same
          race — which is what makes trying a different strategy a comparison rather than
          two different afternoons.
        </p>
      </Panel>
    </>
  )
}
