/**
 * Where the research goes.
 *
 * The screen is built around the one question worth asking: not "which area is
 * weakest" but "where do the next points buy the most lap time over the races
 * that are *left*".  So each area is shown with what it would gain, what the
 * remaining calendar asks of it, and the product of the two — which is the
 * number the AI teams are optimising and is therefore the number the player is
 * competing on.
 */

import { useState } from 'react'

import { money, percent, rating, titleCase } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useGame, useLoadedGame } from '../hooks/useGame'
import { ApiFailure, api } from '../services/api'

export default function Development() {
  const game = useLoadedGame()
  const { refresh } = useGame()
  const options = useAsync(() => api.development(), [game.team.rd_points, game.team.budget])
  const upgrades = useAsync(() => api.upgrades(), [game.team.rd_points])

  const [area, setArea] = useState<string>('aero')
  const [points, setPoints] = useState('')
  const [rushed, setRushed] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const data = options.data
  const committed = Number(points) || 0
  const cost = data ? committed * data.cost_per_point * (1 + 0.5 * rushed) : 0

  async function commission() {
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      const upgrade = await api.invest({ area, points: committed, rushed })
      setNote(
        `${titleCase(upgrade.area)} project started — ${money(upgrade.cost, 2)}, ` +
          `arrives at round ${upgrade.arrives_at_round}, ` +
          `${percent(upgrade.failure_chance)} chance it produces nothing.`,
      )
      setPoints('')
      await refresh()
      options.reload()
      upgrades.reload()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  if (options.loading && !data) return <Loading what="Reading the factory" />

  // Rank on what a *fixed* hundred points would buy, not on what the team
  // happens to have banked.  Otherwise a team with nothing in the bank sees
  // every row at zero and the order is whatever the areas were declared in.
  const worthOf = (row: { gain_per_100: number; remaining_demand: number }) =>
    row.gain_per_100 * row.remaining_demand
  const ranked = [...(data?.areas ?? [])].sort((a, b) => worthOf(b) - worthOf(a))
  const best = ranked[0]
  const banked = (data?.rd_points ?? 0) > 0

  return (
    <>
      <PageHead
        title="Development"
        subtitle="Research is the design. Building it costs money, takes rounds, and can fail."
        action={
          <div className="inline">
            <Pill>{data?.rd_points.toFixed(0)} research</Pill>
            <Pill tone={(data?.cap_headroom ?? 0) < 15 ? 'warn' : 'off'}>
              {money(data?.cap_headroom ?? 0, 0)} cap left
            </Pill>
          </div>
        }
      />

      <ErrorNotice error={error ?? options.error} />
      {note && <div className="notice ok">{note}</div>}

      <Panel
        title="Where research is worth the most"
        note="Gain per hundred points × what the remaining calendar asks for. The AI teams are optimising the same product."
      >
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Area</th>
                <th className="right">Now</th>
                <th className="right">Per 100</th>
                <th className="right">All of it</th>
                <th className="right">Demand</th>
                <th className="right">Worth</th>
                <th className="right">Efficiency</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {ranked.map((row) => (
                  <tr key={row.area} className={area === row.area ? 'you' : ''}>
                    <td>{titleCase(row.area)}</td>
                    <td className="right num">{rating(row.current)}</td>
                    <td className="right num good">+{row.gain_per_100.toFixed(4)}</td>
                    <td className={`right num ${banked ? 'good' : 'dim'}`}>
                      {banked ? `+${row.gain_at_current_points.toFixed(4)}` : '—'}
                    </td>
                    <td className="right num muted">{percent(row.remaining_demand)}</td>
                    <td className="right num">{(worthOf(row) * 1000).toFixed(2)}</td>
                    <td
                      className={`right num ${row.efficiency > 1 ? 'good' : row.efficiency < 1 ? 'warn' : 'dim'}`}
                    >
                      ×{row.efficiency.toFixed(2)}
                    </td>
                    <td className="right">
                      <button className="ghost" onClick={() => setArea(row.area)}>
                        Pick
                      </button>
                    </td>
                  </tr>
              ))}
            </tbody>
          </table>
        </div>
        {best && (
          <p className="subtitle" style={{ marginBottom: 0, marginTop: 12 }}>
            On the rounds that are left, <strong>{titleCase(best.area)}</strong> is where
            research buys the most. Efficiency is the facility in that area — a level
            above three develops faster and a level below it slower.
            {!banked && ' There is nothing banked yet; a round of development fills it.'}
          </p>
        )}
      </Panel>

      <Panel title="Commission a project">
        <div className="row">
          <div className="field" style={{ maxWidth: 200 }}>
            <label>Area</label>
            <select value={area} onChange={(event) => setArea(event.target.value)}>
              {(data?.areas ?? []).map((row) => (
                <option key={row.area} value={row.area}>
                  {titleCase(row.area)}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ maxWidth: 170 }}>
            <label>Research points</label>
            <input
              value={points}
              onChange={(event) => setPoints(event.target.value.replace(/[^\d.]/g, ''))}
              placeholder={data?.rd_points.toFixed(0)}
            />
          </div>
          <div className="field" style={{ maxWidth: 200 }}>
            <label>Rush ({percent(rushed)})</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.25}
              value={rushed}
              onChange={(event) => setRushed(Number(event.target.value))}
            />
          </div>
          <button
            className="primary"
            disabled={busy || committed <= 0 || !data || committed > data.rd_points}
            onClick={() => void commission()}
          >
            {busy ? 'Starting…' : `Commission (${money(cost, 2)})`}
          </button>
        </div>
        <p className="subtitle" style={{ marginBottom: 0 }}>
          Rushing halves the time, costs half again the money, and materially worsens the
          chance the part works. A failed project is not a refund — the research and the
          money went either way.
        </p>
      </Panel>

      <Panel title="In the factory and on the car">
        {(upgrades.data ?? []).length === 0 ? (
          <div className="empty">Nothing commissioned yet this season.</div>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Area</th>
                  <th>Status</th>
                  <th className="right">Points</th>
                  <th className="right">Cost</th>
                  <th className="right">Ordered</th>
                  <th className="right">Arrives</th>
                  <th className="right">Expected</th>
                  <th className="right">Delivered</th>
                </tr>
              </thead>
              <tbody>
                {[...(upgrades.data ?? [])]
                  .reverse()
                  .map((upgrade) => (
                    <tr key={upgrade.id}>
                      <td>{titleCase(upgrade.area)}</td>
                      <td>
                        <Pill
                          tone={
                            upgrade.status === 'fitted'
                              ? 'on'
                              : upgrade.status === 'failed'
                                ? 'warn'
                                : 'off'
                          }
                        >
                          {titleCase(upgrade.status)}
                        </Pill>
                      </td>
                      <td className="right num">{upgrade.points.toFixed(0)}</td>
                      <td className="right num">{money(upgrade.cost, 2)}</td>
                      <td className="right num dim">R{upgrade.commissioned_at_round}</td>
                      <td className="right num">R{upgrade.arrives_at_round}</td>
                      <td className="right num muted">
                        +{upgrade.expected_gain.toFixed(4)}
                      </td>
                      <td
                        className={`right num ${upgrade.actual_gain > 0 ? 'good' : upgrade.status === 'failed' ? 'bad' : 'dim'}`}
                      >
                        {upgrade.status === 'in_development'
                          ? '—'
                          : `+${upgrade.actual_gain.toFixed(4)}`}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  )
}
