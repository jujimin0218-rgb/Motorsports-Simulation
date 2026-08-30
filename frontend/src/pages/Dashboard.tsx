/**
 * Everything at a glance.
 *
 * The five numbers that decide what the player should do next: where the
 * championship stands, what the car is, what is in the bank, what is in the
 * factory, and what the next circuit will ask for.  The last one is the reason
 * the car is shown per area rather than as one rating -- a car that is third
 * overall can be first at the circuit that is next.
 */

import { Link } from 'react-router-dom'

import { money, ordinal, percent, rating, titleCase } from '../components/format'
import { ErrorNotice, Meter, PageHead, Panel, Pill, Stat } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useLoadedGame } from '../hooks/useGame'
import { api } from '../services/api'

export default function Dashboard() {
  const game = useLoadedGame()
  const upgrades = useAsync(() => api.upgrades(), [game.team.rd_points])

  const round = game.current_round
  const teamRow = game.standings.teams.find((row) => row.team === game.player_team)
  const position = teamRow?.position ?? null
  const weights = round ? round.circuit.characteristics : null

  // What the next circuit asks of the car, in the same order the car is shown.
  const nextDemands = weights
    ? [
        ['power_unit', weights.power_sensitivity],
        ['aero', weights.downforce_requirement],
        ['mechanical_grip', 1 - weights.power_sensitivity],
        ['tyre_management', weights.tyre_stress],
      ]
        .sort((a, b) => (b[1] as number) - (a[1] as number))
        .slice(0, 3)
    : []

  const building = (upgrades.data ?? []).filter((u) => u.status === 'in_development')

  return (
    <>
      <PageHead
        title={game.team.name}
        subtitle={
          round
            ? `Round ${round.number} of ${game.standings.teams.length && 22} · ${round.circuit.name}`
            : `${game.season} season complete`
        }
        action={
          round && (
            <Link to="/weekend" className="button primary" style={{ padding: '8px 14px' }}>
              Go to the weekend
            </Link>
          )
        }
      />

      <div className="grid four">
        <Stat
          label="Constructors"
          value={position ? ordinal(position) : '—'}
          note={`${teamRow?.points ?? 0} points`}
        />
        <Stat
          label="Budget"
          value={money(game.team.budget)}
          tone={game.team.budget < 20 ? 'bad' : game.team.budget < 50 ? 'warn' : ''}
          note={`${money(game.team.season_spending, 0)} against the cap`}
        />
        <Stat
          label="Research banked"
          value={game.team.rd_points.toFixed(0)}
          note={building.length ? `${building.length} in the factory` : 'nothing building'}
        />
        <Stat
          label="Car"
          value={rating(game.team.car_overall)}
          note={`${game.team.engine.name} power`}
        />
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        <Panel
          title="The car, area by area"
          note="A car is not one number: what each area is worth depends on the circuit."
        >
          {Object.entries(game.team.car).map(([area, value]) => (
            <Meter key={area} name={area} value={value} />
          ))}
        </Panel>

        <Panel title="Your drivers">
          {game.drivers.map((driver) => (
            <div key={driver.id} style={{ marginBottom: 14 }}>
              <div className="spread">
                <div className="stack">
                  <strong>{driver.name}</strong>
                  <span className="tag">
                    {driver.nationality} · {driver.age} · {driver.abbreviation}
                  </span>
                </div>
                <div className="stack" style={{ alignItems: 'flex-end' }}>
                  <span className="num">{rating(driver.overall)}</span>
                  <span className="tag">
                    {driver.championship_position
                      ? ordinal(driver.championship_position)
                      : '—'}
                  </span>
                </div>
              </div>
              <div className="inline" style={{ marginTop: 6 }}>
                {driver.contract && (
                  <Pill>
                    {money(driver.contract.salary)}/season ·{' '}
                    {driver.contract.seasons_remaining} left
                  </Pill>
                )}
                <Pill tone={driver.form > 0.1 ? 'on' : driver.form < -0.1 ? 'warn' : 'off'}>
                  form {driver.form >= 0 ? '+' : ''}
                  {driver.form.toFixed(2)}
                </Pill>
              </div>
            </div>
          ))}
        </Panel>
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        {round && (
          <Panel
            title={`Next: ${round.circuit.name}`}
            note={`${round.circuit.length_km} km · ${round.circuit.corner_count} corners · ${round.race_laps} laps`}
          >
            <p className="subtitle" style={{ marginTop: 0 }}>
              What it asks for most:
            </p>
            {nextDemands.map(([area, value]) => (
              <Meter
                key={area as string}
                name={area as string}
                value={value as number}
                tone="accent"
                suffix={percent(value as number)}
              />
            ))}
            <hr className="rule" />
            <div className="inline">
              <Pill>{round.circuit.drs_zones} DRS zones</Pill>
              <Pill tone={round.circuit.characteristics.overtaking_ease > 0.5 ? 'on' : 'warn'}>
                overtaking {percent(round.circuit.characteristics.overtaking_ease)}
              </Pill>
              <Pill>{titleCase(round.phase)}</Pill>
            </div>
          </Panel>
        )}

        <Panel
          title="In the factory"
          note="A part commissioned now arrives in a few rounds, and can still fail."
          action={
            <Link to="/development" className="button ghost" style={{ padding: '5px 11px' }}>
              Development
            </Link>
          }
        >
          {building.length === 0 ? (
            <div className="empty">Nothing being built.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Area</th>
                  <th className="right">Arrives</th>
                  <th className="right">Expected</th>
                  <th className="right">Risk</th>
                </tr>
              </thead>
              <tbody>
                {building.map((upgrade) => (
                  <tr key={upgrade.id}>
                    <td>{titleCase(upgrade.area)}</td>
                    <td className="right num">R{upgrade.arrives_at_round}</td>
                    <td className="right num good">
                      +{upgrade.expected_gain.toFixed(4)}
                    </td>
                    <td className="right num warn">
                      {percent(upgrade.failure_chance)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <ErrorNotice error={upgrades.error} />
        </Panel>
      </div>

      <Panel title="Championship" action={<Link to="/standings" className="tag">full table</Link>}>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th className="right">#</th>
                <th>Team</th>
                <th className="right">Points</th>
                <th className="right">Wins</th>
                <th className="right">Podiums</th>
              </tr>
            </thead>
            <tbody>
              {game.standings.teams.slice(0, 6).map((row) => (
                <tr key={row.team} className={row.team === game.player_team ? 'you' : ''}>
                  <td className="pos">{row.position}</td>
                  <td>{row.team_name}</td>
                  <td className="right num">{row.points}</td>
                  <td className="right num">{row.wins}</td>
                  <td className="right num">{row.podiums}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  )
}
