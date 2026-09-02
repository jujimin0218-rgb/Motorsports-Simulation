/**
 * Every driver in the game.
 *
 * Sortable because the useful question changes: who is best *now* is a
 * different question from who is worth signing, which is a different question
 * again from who is about to be out of contract.
 */

import { useState } from 'react'

import { money, rating, titleCase } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'
import type { DriverRow } from '../types/api'

type SortKey = 'overall' | 'potential' | 'age' | 'market_value' | 'reputation'

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'overall', label: 'Rating' },
  { key: 'potential', label: 'Potential' },
  { key: 'market_value', label: 'Value' },
  { key: 'reputation', label: 'Reputation' },
  { key: 'age', label: 'Age' },
]

export default function Drivers() {
  const game = useLoadedGame()
  const drivers = useAsync(() => api.drivers(), [])
  const [sort, setSort] = useState<SortKey>('overall')
  const [open, setOpen] = useState<DriverRow | null>(null)

  if (drivers.loading && !drivers.data) return <Loading what="Reading the field" />

  const rows = [...(drivers.data ?? [])].sort((a, b) =>
    sort === 'age' ? a.age - b.age : (b[sort] as number) - (a[sort] as number),
  )

  return (
    <>
      <PageHead
        title="Drivers"
        subtitle="Eleven ratings: six the race engine uses under its own names, five the game keeps because the engine has nowhere to put them."
        action={
          <div className="inline">
            {SORTS.map((option) => (
              <button
                key={option.key}
                className={sort === option.key ? 'primary' : 'ghost'}
                style={{ padding: '5px 11px' }}
                onClick={() => setSort(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      />

      <ErrorNotice error={drivers.error} />

      <Panel>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Driver</th>
                <th>Team</th>
                <th className="right">Rating</th>
                <th className="right">Potential</th>
                <th className="right">Age</th>
                <th className="right">Reputation</th>
                <th className="right">Form</th>
                <th className="right">Value</th>
                <th className="right">Contract</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((driver) => (
                <tr
                  key={driver.id}
                  className={driver.team === game.player_team ? 'you' : ''}
                >
                  <td>
                    {driver.name}
                    <span className="tag"> {driver.abbreviation}</span>
                  </td>
                  <td className="muted">{driver.team ?? <em className="dim">free</em>}</td>
                  <td className="right num">{rating(driver.overall)}</td>
                  <td className="right num muted">{rating(driver.potential)}</td>
                  <td className="right num">{driver.age}</td>
                  <td className="right num">{rating(driver.reputation, 2)}</td>
                  <td
                    className={`right num ${driver.form > 0.1 ? 'good' : driver.form < -0.1 ? 'bad' : 'dim'}`}
                  >
                    {driver.form >= 0 ? '+' : ''}
                    {driver.form.toFixed(2)}
                  </td>
                  <td className="right num">{money(driver.market_value)}</td>
                  <td className="right num dim">
                    {driver.contract
                      ? `${driver.contract.seasons_remaining}y`
                      : '—'}
                  </td>
                  <td className="right">
                    <button
                      className="ghost"
                      onClick={() => setOpen(open?.id === driver.id ? null : driver)}
                    >
                      {open?.id === driver.id ? 'Hide' : 'Skills'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {open && (
        <Panel
          title={open.name}
          note={`${open.nationality} · ${open.age} · ${open.team ?? 'free agent'}`}
          action={
            <div className="inline">
              <Pill>worth {money(open.market_value)}</Pill>
              {open.contract && (
                <Pill tone={open.contract.seasons_remaining <= 1 ? 'warn' : 'off'}>
                  {money(open.contract.salary)}/season ·{' '}
                  {open.contract.seasons_remaining} left
                </Pill>
              )}
            </div>
          }
        >
          <div className="grid three">
            {Object.entries(open.skills).map(([skill, value]) => (
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
        </Panel>
      )}
    </>
  )
}
