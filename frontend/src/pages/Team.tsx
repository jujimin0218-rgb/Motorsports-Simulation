/**
 * The team, and the grid it is in.
 *
 * The comparison table is the point: a car is six areas, and this is where a
 * player can see that they are third overall and first on mechanical grip,
 * which decides which circuits are worth spending a strategy on.
 */

import { money, percent, rating, titleCase } from '../components/format'
import { ErrorNotice, Loading, Meter, PageHead, Panel, Pill, Stat } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'
import type { CarPerformance } from '../types/api'

const AREAS: (keyof CarPerformance)[] = [
  'aero',
  'chassis',
  'power_unit',
  'mechanical_grip',
  'tyre_management',
  'reliability',
]

export default function Team() {
  const game = useLoadedGame()
  const teams = useAsync(() => api.teams(), [game.current_round?.number])

  if (teams.loading && !teams.data) return <Loading what="Reading the grid" />

  const rows = [...(teams.data ?? [])].sort((a, b) => b.car_overall - a.car_overall)
  const best = (area: keyof CarPerformance) =>
    Math.max(...rows.map((row) => row.car[area]))

  return (
    <>
      <PageHead
        title={game.team.name}
        subtitle={`${game.team.nationality} · ${game.team.staff} people · ${game.team.engine.name} power`}
        action={
          <div className="inline">
            <Pill tone="off">reputation {rating(game.team.reputation, 2)}</Pill>
            <Pill>last season P{game.team.prize_position}</Pill>
          </div>
        }
      />

      <ErrorNotice error={teams.error} />

      <div className="grid four">
        <Stat label="Car" value={rating(game.team.car_overall)} note="unweighted mean" />
        <Stat label="Budget" value={money(game.team.budget)} />
        <Stat label="Research" value={game.team.rd_points.toFixed(0)} note="banked" />
        <Stat
          label="Facilities"
          value={(
            Object.values(game.team.facilities).reduce((a, b) => a + b, 0) / 6
          ).toFixed(1)}
          note="average level, of 5"
        />
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        <Panel title="Your car" note="Against the best in the field, area by area.">
          {AREAS.map((area) => (
            <div key={area}>
              <Meter
                name={area}
                value={game.team.car[area]}
                tone={game.team.car[area] >= best(area) - 0.0001 ? 'good' : undefined}
              />
            </div>
          ))}
        </Panel>

        <Panel title="Your engine">
          {(
            [
              ['ice_output', game.team.engine.ice_output],
              ['kers_output', game.team.engine.kers_output],
              ['fuel_efficiency', game.team.engine.fuel_efficiency],
              ['cooling', game.team.engine.cooling],
              ['reliability', game.team.engine.reliability],
            ] as const
          ).map(([name, value]) => (
            <Meter key={name} name={name} value={value} />
          ))}
          <hr className="rule" />
          <div className="inline">
            <Pill tone={game.team.engine.works_team === game.team.id ? 'on' : 'off'}>
              {game.team.engine.works_team === game.team.id
                ? 'works team — no charge'
                : `customer — ${money(game.team.engine.cost_per_season, 0)} a season`}
            </Pill>
          </div>
        </Panel>
      </div>

      <Panel title="The grid" note="Where every car stands, area by area.">
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Team</th>
                <th>Engine</th>
                <th className="right">Overall</th>
                {AREAS.map((area) => (
                  <th key={area} className="right">
                    {titleCase(area).split(' ')[0]}
                  </th>
                ))}
                <th className="right">Budget</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={row.id === game.player_team ? 'you' : ''}>
                  <td>{row.name}</td>
                  <td className="muted">{row.engine_name}</td>
                  <td className="right num">{rating(row.car_overall)}</td>
                  {AREAS.map((area) => (
                    <td
                      key={area}
                      className={`right num ${row.car[area] >= best(area) - 0.0001 ? 'good' : ''}`}
                    >
                      {row.car[area].toFixed(3)}
                    </td>
                  ))}
                  <td className="right num dim">{money(row.budget, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="subtitle" style={{ marginBottom: 0, marginTop: 12 }}>
          None of these numbers reach the physics directly. Each is spent on a real
          property of the car — downforce area, mass, centre-of-gravity height, engine
          power — and the race engine works out what that is worth at each circuit.
        </p>
      </Panel>

      <Panel title="Facilities">
        <div className="grid three">
          {Object.entries(game.team.facilities).map(([name, level]) => (
            <div key={name}>
              <div className="stat-label">{titleCase(name)}</div>
              <div className="bar good" style={{ marginTop: 6 }}>
                <span style={{ width: `${(level / 5) * 100}%` }} />
              </div>
              <div className="num" style={{ fontSize: 12, marginTop: 4 }}>
                level {level} · {percent(level / 5)}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </>
  )
}
