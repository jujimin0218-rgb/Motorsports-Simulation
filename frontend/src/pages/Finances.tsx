/**
 * Money, as lines rather than a number.
 *
 * Every line is a thing the team agreed to — two salaries, an engine deal, a
 * head count, the sponsors it managed to attract — so a player who is running
 * out can see which of their own decisions is doing it.  The projection to the
 * flag is the one number that changes behaviour: it is the difference between
 * "we have plenty" and "we have plenty until August".
 */

import { useState } from 'react'

import { money, percent, signedMoney, titleCase } from '../components/format'
import { ErrorNotice, Loading, PageHead, Panel, Pill, Stat } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useGame, useLoadedGame } from '../hooks/useGame'
import { ApiFailure, api } from '../services/api'

const FACILITY_COST: Record<number, number> = { 2: 14, 3: 24, 4: 40, 5: 65 }

export default function Finances() {
  const game = useLoadedGame()
  const { refresh } = useGame()
  const finances = useAsync(() => api.finances(), [game.team.budget])
  const sponsors = useAsync(() => api.sponsors(), [game.team.reputation])

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [note, setNote] = useState<string | null>(null)

  async function act(work: () => Promise<unknown>, describe: (r: any) => string) {
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      const result = await work()
      setNote(describe(result))
      await refresh()
      finances.reload()
      sponsors.reload()
    } catch (caught) {
      setError(caught as ApiFailure)
    } finally {
      setBusy(false)
    }
  }

  const data = finances.data
  if (finances.loading && !data) return <Loading what="Opening the books" />

  const projected = data?.projected_to_season_end ?? 0
  const bankrupt = data ? projected < data.bankruptcy_limit : false

  return (
    <>
      <PageHead
        title="Finances"
        subtitle="Salaries are outside the cost cap, as they are in the real regulation. Building parts is not."
      />

      <ErrorNotice error={error ?? finances.error} />
      {note && <div className="notice ok">{note}</div>}

      <div className="grid four">
        <Stat
          label="In the bank"
          value={money(data?.budget ?? 0)}
          tone={(data?.budget ?? 0) < 20 ? 'bad' : ''}
        />
        <Stat
          label="Per round"
          value={signedMoney(data?.per_round.total ?? 0, 2)}
          tone={(data?.per_round.total ?? 0) < 0 ? 'warn' : 'good'}
          note={`${data?.rounds_remaining ?? 0} rounds left`}
        />
        <Stat
          label="At the flag"
          value={money(projected)}
          tone={bankrupt ? 'bad' : projected < 20 ? 'warn' : 'good'}
          note={bankrupt ? 'below the bankruptcy limit' : 'projected'}
        />
        <Stat
          label="Cost cap"
          value={money(data?.cap_headroom ?? 0, 0)}
          note={`${money(data?.season_spending ?? 0, 0)} of ${money(data?.cap ?? 0, 0)} spent`}
          tone={(data?.cap_headroom ?? 0) < 15 ? 'warn' : ''}
        />
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        <Panel title="Where a round's money goes">
          <table>
            <tbody>
              {(data?.per_round.lines ?? []).map((line, index) => (
                <tr key={index}>
                  <td>{line.label}</td>
                  <td
                    className={`right num ${line.amount > 0 ? 'good' : 'bad'}`}
                    style={{ width: 110 }}
                  >
                    {signedMoney(line.amount, 3)}
                  </td>
                </tr>
              ))}
              <tr>
                <td>
                  <strong>Net</strong>
                </td>
                <td
                  className={`right num ${(data?.per_round.total ?? 0) > 0 ? 'good' : 'bad'}`}
                >
                  <strong>{signedMoney(data?.per_round.total ?? 0, 3)}</strong>
                </td>
              </tr>
            </tbody>
          </table>
          <p className="subtitle" style={{ marginBottom: 0, marginTop: 10 }}>
            Prize money is paid on last season's finish, in instalments through this one
            — which is what keeps a team solvent between January and the first cheque.
          </p>
        </Panel>

        <Panel
          title="Facilities"
          note="The slowest advantage in the game and the one that lasts: a facility does not make the car quicker, it makes every future development in that area worth more."
        >
          <table>
            <tbody>
              {Object.entries(game.team.facilities).map(([name, level]) => (
                <tr key={name}>
                  <td>{titleCase(name)}</td>
                  <td style={{ width: 120 }}>
                    <span className="bar good">
                      <span style={{ width: `${(level / 5) * 100}%` }} />
                    </span>
                  </td>
                  <td className="right num" style={{ width: 34 }}>
                    {level}
                  </td>
                  <td className="right" style={{ width: 116 }}>
                    {level >= 5 ? (
                      <span className="tag">maxed</span>
                    ) : (
                      <button
                        className="ghost"
                        disabled={busy || (data?.cap_headroom ?? 0) < FACILITY_COST[level + 1]}
                        onClick={() =>
                          void act(
                            () => api.upgradeFacility(name),
                            (r) => `${titleCase(name)} is now level ${r.level}.`,
                          )
                        }
                      >
                        {money(FACILITY_COST[level + 1], 0)}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <Panel
        title="Sponsors"
        note="The big money will not go on a car nobody is watching, which is what makes reputation worth building."
      >
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Sponsor</th>
                <th>Sector</th>
                <th className="right">Per season</th>
                <th>Target</th>
                <th className="right">Bonus</th>
                <th className="right">Penalty</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(sponsors.data ?? []).map((sponsor) => (
                <tr key={sponsor.id} className={sponsor.signed ? 'you' : ''}>
                  <td>{sponsor.name}</td>
                  <td className="muted">{sponsor.sector}</td>
                  <td className="right num">{money(sponsor.base_payment, 0)}</td>
                  <td className="muted">{sponsor.target_description}</td>
                  <td className="right num good">
                    {sponsor.bonus ? `+${money(sponsor.bonus, 0)}` : '—'}
                  </td>
                  <td className="right num bad">
                    {sponsor.penalty ? `-${money(sponsor.penalty, 0)}` : '—'}
                  </td>
                  <td className="right">
                    {sponsor.signed ? (
                      <Pill tone="on">signed</Pill>
                    ) : sponsor.available ? (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => api.signSponsor(sponsor.id),
                            () =>
                              `${sponsor.name} signed for ${sponsor.seasons} season${sponsor.seasons === 1 ? '' : 's'}.`,
                          )
                        }
                      >
                        Sign
                      </button>
                    ) : (
                      <span className="tag">
                        needs +{percent(sponsor.reputation_shortfall, 1)} rep
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  )
}
