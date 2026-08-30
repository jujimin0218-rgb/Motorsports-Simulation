/**
 * The season, and what each circuit will ask for.
 *
 * The two bars on each row are the thing worth seeing: a circuit is a *demand*
 * on a car, and a season is a sequence of different demands.  A team that is
 * strong on power and weak in the slow corners can read its own year off this
 * page.
 */

import { percent, titleCase } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel, Pill } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'

export default function Calendar() {
  const game = useLoadedGame()
  const calendar = useAsync(() => api.calendar(), [game.current_round?.number])

  if (calendar.loading && !calendar.data) return <Loading what="Reading the calendar" />

  const rows = calendar.data ?? []
  const current = game.current_round?.number ?? rows.length + 1
  const totalKm = rows.reduce((sum, row) => sum + row.circuit.length_km * row.race_laps, 0)

  return (
    <>
      <PageHead
        title={`${game.season} calendar`}
        subtitle={`${rows.length} rounds · ${totalKm.toFixed(0)} km of racing at ${percent(game.settings.race_distance)} distance`}
      />

      <ErrorNotice error={calendar.error} />

      <Panel>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th className="right">R</th>
                <th>Circuit</th>
                <th>Country</th>
                <th className="right">Length</th>
                <th className="right">Laps</th>
                <th className="right">Corners</th>
                <th style={{ width: 120 }}>Power</th>
                <th style={{ width: 120 }}>Downforce</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const c = row.circuit
                return (
                  <tr key={row.number} className={row.number === current ? 'you' : ''}>
                    <td className="pos">{row.number}</td>
                    <td>
                      {c.name}
                      <span className="tag"> {c.city}</span>
                    </td>
                    <td className="muted">{c.country}</td>
                    <td className="right num">{c.length_km.toFixed(3)}</td>
                    <td className="right num">{row.race_laps}</td>
                    <td className="right num">{c.corner_count}</td>
                    <td>
                      <span className="bar accent">
                        <span
                          style={{ width: `${c.characteristics.power_sensitivity * 100}%` }}
                        />
                      </span>
                    </td>
                    <td>
                      <span className="bar">
                        <span
                          style={{
                            width: `${c.characteristics.downforce_requirement * 100}%`,
                          }}
                        />
                      </span>
                    </td>
                    <td>
                      {row.number < current ? (
                        <Pill tone="on">done</Pill>
                      ) : row.number === current ? (
                        <Pill tone="hot">{titleCase(row.phase)}</Pill>
                      ) : (
                        <span className="tag">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Where the season is decided">
        <p className="subtitle" style={{ marginTop: 0 }}>
          Length, corner count and race distance are the published figures for these
          circuits. The two bars are game-balance weights describing what each one asks
          of a car — they are not measurements, and they are what makes a car that is
          third overall able to be first here.
        </p>
        <div className="grid three" style={{ marginTop: 12 }}>
          {(
            [
              ['Most power-sensitive', 'power_sensitivity'],
              ['Most downforce', 'downforce_requirement'],
              ['Hardest on tyres', 'tyre_stress'],
            ] as const
          ).map(([label, key]) => {
            const top = [...rows]
              .sort((a, b) => b.circuit.characteristics[key] - a.circuit.characteristics[key])
              .slice(0, 3)
            return (
              <div key={key}>
                <div className="stat-label">{label}</div>
                {top.map((row) => (
                  <div key={row.number} className="spread" style={{ marginTop: 6 }}>
                    <span className="muted" style={{ fontSize: 12.5 }}>
                      {row.circuit.city}
                    </span>
                    <span className="num" style={{ fontSize: 12 }}>
                      {percent(row.circuit.characteristics[key])}
                    </span>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
        <hr className="rule" />
        <div className="inline">
          <Pill tone="off">
            engine circuits: {new Set(rows.map((r) => r.circuit.physics_track)).size} in use
          </Pill>
          <span className="subtitle" style={{ margin: 0 }}>
            Real surveyed geometry for these twenty-two does not exist yet, so each round
            is driven on the engine circuit closest to its character.
          </span>
        </div>
      </Panel>
    </>
  )
}
