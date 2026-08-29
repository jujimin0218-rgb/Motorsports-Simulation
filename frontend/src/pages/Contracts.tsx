/**
 * The transfer market.
 *
 * A negotiation is not a price check, so the screen is built to show *why* an
 * answer came back.  The asking price is per team — a driver charges a slow
 * team more — and a refusal names which part of the offer was weakest, so the
 * player learns that no amount of money fixes "not convinced by the car".
 */

import { useState } from 'react'

import { money, percent, rating, titleCase } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useGame, useLoadedGame } from '../hooks/useGame'
import { ApiFailure, api } from '../services/api'
import type { DriverRow, NegotiationAnswer } from '../types/api'

export default function Contracts() {
  const game = useLoadedGame()
  const { refresh } = useGame()
  const market = useAsync(() => api.drivers(true), [])

  const [target, setTarget] = useState<DriverRow | null>(null)
  const [salary, setSalary] = useState('')
  const [seasons, setSeasons] = useState(2)
  const [seat, setSeat] = useState(0)
  const [answer, setAnswer] = useState<NegotiationAnswer | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [note, setNote] = useState<string | null>(null)

  function choose(driver: DriverRow) {
    setTarget(driver)
    setAnswer(null)
    setNote(null)
    setError(null)
    setSalary('')
  }

  async function ask() {
    if (!target) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.negotiate({
        driver_id: target.id,
        salary: Number(salary) || target.market_value,
        seasons,
      })
      setAnswer(result)
      if (!salary) setSalary(result.asking_price.toFixed(1))
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!target) return
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      await api.signDriver({
        driver_id: target.id,
        salary: Number(salary),
        seasons,
        seat,
      })
      setNote(`${target.name} signed for ${money(Number(salary))} a season.`)
      setTarget(null)
      setAnswer(null)
      await refresh()
      market.reload()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHead
        title="Contracts"
        subtitle="A driver decides on the car first and the money second — and charges a slow team more in the first place."
      />

      <ErrorNotice error={error ?? market.error} />
      {note && <div className="notice ok">{note}</div>}

      <Panel title="Your line-up">
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Seat</th>
                <th>Driver</th>
                <th className="right">Rating</th>
                <th className="right">Age</th>
                <th className="right">Salary</th>
                <th className="right">Seasons left</th>
                <th className="right">Worth</th>
              </tr>
            </thead>
            <tbody>
              {game.drivers.map((driver, index) => (
                <tr key={driver.id} className="you">
                  <td className="pos">{index + 1}</td>
                  <td>{driver.name}</td>
                  <td className="right num">{rating(driver.overall)}</td>
                  <td className="right num">{driver.age}</td>
                  <td className="right num">
                    {driver.contract ? money(driver.contract.salary) : '—'}
                  </td>
                  <td className="right num">
                    {driver.contract?.seasons_remaining ?? '—'}
                  </td>
                  <td className="right num muted">{money(driver.market_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {target && (
        <Panel
          title={`Offer to ${target.name}`}
          action={
            <button className="ghost" onClick={() => setTarget(null)}>
              Cancel
            </button>
          }
        >
          <div className="row">
            <div className="field" style={{ maxWidth: 170 }}>
              <label>Salary (millions)</label>
              <input
                value={salary}
                onChange={(event) => setSalary(event.target.value.replace(/[^\d.]/g, ''))}
                placeholder={target.market_value.toFixed(1)}
              />
            </div>
            <div className="field" style={{ maxWidth: 130 }}>
              <label>Seasons</label>
              <select
                value={seasons}
                onChange={(event) => setSeasons(Number(event.target.value))}
              >
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ maxWidth: 200 }}>
              <label>Replace</label>
              <select value={seat} onChange={(event) => setSeat(Number(event.target.value))}>
                {game.drivers.map((driver, index) => (
                  <option key={driver.id} value={index}>
                    {driver.name}
                  </option>
                ))}
              </select>
            </div>
            <button disabled={busy} onClick={() => void ask()}>
              Ask
            </button>
            <button
              className="primary"
              disabled={busy || !answer?.accepted}
              onClick={() => void confirm()}
            >
              Sign
            </button>
          </div>

          {answer && (
            <>
              <hr className="rule" />
              <div className="spread">
                <div className="stack">
                  <strong className={answer.accepted ? 'good' : 'warn'}>
                    {answer.accepted ? 'Would sign' : 'Turns it down'}
                  </strong>
                  <span className="subtitle">{answer.reason}</span>
                </div>
                <div className="stack" style={{ alignItems: 'flex-end' }}>
                  <span className="tag">asking</span>
                  <span className="num" style={{ fontSize: 18 }}>
                    {money(answer.asking_price)}
                  </span>
                </div>
              </div>
              <div className="grid four" style={{ marginTop: 12 }}>
                {Object.entries(answer.breakdown).map(([key, value]) => (
                  <div key={key}>
                    <div className="stat-label">{titleCase(key)}</div>
                    <div className="bar" style={{ marginTop: 6 }}>
                      <span
                        className=""
                        style={{ width: `${value * 100}%` }}
                      />
                    </div>
                    <div className="num" style={{ fontSize: 12, marginTop: 4 }}>
                      {percent(value)}
                    </div>
                  </div>
                ))}
              </div>
              <p className="subtitle" style={{ marginBottom: 0, marginTop: 12 }}>
                The car is the largest part of the decision. A driver who is not
                convinced by it does not change their mind for a fair salary — only for
                a lot more than one.
              </p>
            </>
          )}
        </Panel>
      )}

      <Panel title="Free agents" note="Drivers without a seat, best first.">
        {market.loading && <Loading />}
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Driver</th>
                <th className="right">Rating</th>
                <th className="right">Potential</th>
                <th className="right">Age</th>
                <th className="right">Reputation</th>
                <th className="right">Worth</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(market.data ?? []).map((driver) => (
                <tr key={driver.id} className={target?.id === driver.id ? 'you' : ''}>
                  <td>
                    {driver.name}
                    <span className="tag"> {driver.nationality}</span>
                  </td>
                  <td className="right num">{rating(driver.overall)}</td>
                  <td className="right num muted">{rating(driver.potential)}</td>
                  <td className="right num">{driver.age}</td>
                  <td className="right num">{rating(driver.reputation, 2)}</td>
                  <td className="right num">{money(driver.market_value)}</td>
                  <td className="right">
                    <button className="ghost" onClick={() => choose(driver)}>
                      Approach
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="What a driver is">
        <p className="subtitle" style={{ marginTop: 0 }}>
          Six of the eleven ratings carry the race engine's own names and are handed
          straight to it. The other five exist because the engine has nowhere to put
          them: attack and defence are stored apart because the engine settles a fight
          with one number, and <em>starts</em>, <em>feedback</em> and <em>mentality</em>{' '}
          drive things the engine does not model.
        </p>
        {target && (
          <div className="grid three" style={{ marginTop: 12 }}>
            {Object.entries(target.skills).map(([skill, value]) => (
              <div key={skill}>
                <div className="stat-label">{titleCase(skill)}</div>
                <div className="bar" style={{ marginTop: 6 }}>
                  <span style={{ width: `${value * 100}%` }} />
                </div>
                <div className="num" style={{ fontSize: 12, marginTop: 4 }}>
                  {rating(value)}
                </div>
              </div>
            ))}
          </div>
        )}
        {!target && (
          <div className="inline">
            <Pill tone="off">approach a driver to see their ratings</Pill>
          </div>
        )}
      </Panel>
    </>
  )
}
