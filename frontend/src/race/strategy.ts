/**
 * When to stop, and on what.
 *
 * A pit stop is the one decision in a race that is not made with the steering
 * wheel, and it is the one the driver model has no business making: it is a
 * judgement about the whole race -- how much the tyres have left, what a stop
 * costs here, who is behind, whether the safety car has just made it free.
 *
 * So it lives here, and it is a judgement rather than a lap number. The old
 * version drew a lap out of a hat before the start and pitted on it come what
 * may, which put twenty cars in a nine-hundred-metre lane within two laps of
 * each other -- and a queue in a pit lane is a pile-up.
 *
 * The rule it actually uses is the one a strategist uses: **stop when the
 * tyres you have are costing you more than the stop would.** Everything else
 * -- the free stop under a safety car, not rejoining into a train, keeping
 * something in hand for the end -- is a modifier on that.
 */

import { clamp } from './geometry'

export type Compound = 'soft' | 'medium' | 'hard'

export interface CompoundSpec {
  /** Peak grip, as a multiplier on the car's own. */
  grip: number
  /** How fast it wears, relative to a medium. */
  wear: number
  label: string
  colour: string
}

/**
 * Three compounds, a step apart.
 *
 * The numbers are the shape of the real trade: about three tenths a lap
 * between steps, and a soft that is gone in half the distance of a hard.
 */
export const COMPOUNDS: Record<Compound, CompoundSpec> = {
  soft: { grip: 1.028, wear: 1.62, label: 'S', colour: '#e2544a' },
  medium: { grip: 1.0, wear: 1.0, label: 'M', colour: '#e3a33a' },
  hard: { grip: 0.974, wear: 0.66, label: 'H', colour: '#e6e9ee' },
}

/** What the strategist can see. */
export interface StrategyView {
  /** Laps completed and laps in the race. */
  lap: number
  laps: number
  /** Wear on the current set, 0 fresh. */
  wear: number
  /** Laps done on this set. */
  tyreAge: number
  compound: Compound
  stops: number
  /** Seconds a stop costs here, pit lane and all. */
  pitLoss: number
  /** How much of that a safety car or virtual safety car gives back, 0..1. */
  discount: number
  /** Cars already in the lane heading for a box. */
  queue: number
  /** Whether the race is running green. */
  racing: boolean
  /** Seconds to the car behind, for judging whether a stop loses the place. */
  behind: number
}

export interface StrategyCall {
  pit: boolean
  compound: Compound
  why: string
}

/** How much a lap costs, in seconds, at a given wear. Quadratic, as it is. */
export function wearCost(wear: number, spec: CompoundSpec): number {
  const w = Math.max(0, wear)
  // Falling off the cliff: gentle at first and then not, which is what makes
  // a stop worth taking rather than nursing a set to the end.
  return (0.9 * w * w + 0.35 * w) / spec.wear ** 0.35
}

/**
 * The stint a set of these tyres is good for, in laps, at this wear rate.
 *
 * Not "how long until they are gone" -- how long until they are costing more
 * per lap than they are worth, which is a different and earlier number.
 */
export function usefulStint(ratePerLap: number, spec: CompoundSpec): number {
  if (ratePerLap <= 1e-6) return 99
  return clamp(0.82 / (ratePerLap * spec.wear), 4, 60)
}

/**
 * Should this car stop at the end of this lap, and on what?
 *
 * Called once per lap per car. It answers no far more often than yes.
 */
export function callStrategy(view: StrategyView, rng: () => number): StrategyCall {
  const spec = COMPOUNDS[view.compound]
  const left = view.laps - view.lap
  const ratePerLap = view.tyreAge > 0 ? view.wear / view.tyreAge : 0.05

  // Nothing to gain from stopping with the flag in sight.
  if (left <= 2) return { pit: false, compound: view.compound, why: 'too late to stop' }

  // What the current set will cost over what is left, against a fresh one plus
  // the stop. This is the whole decision; the rest are reasons to move it.
  const stayCost = costOver(left, view.wear, ratePerLap, spec)
  const freshChoice = bestCompound(left, ratePerLap, view)
  const swapCost = costOver(left, 0, ratePerLap, COMPOUNDS[freshChoice]) +
    view.pitLoss * (1 - view.discount)

  // A car in the queue does not get its stop for free either.
  const queueCost = view.queue * 2.4
  const worthIt = stayCost - (swapCost + queueCost)

  // Under a safety car a stop is most of the way to free, and everybody knows
  // it: the discount is what makes the whole field dive in at once, which is
  // what really happens.
  if (view.discount > 0.4 && view.stops === 0 && left > 4) {
    return { pit: true, compound: freshChoice, why: 'free stop under the flags' }
  }

  // The rule everybody races to: two compounds, so at least one stop.
  const mustStop = view.stops === 0 && view.laps >= 8
  if (mustStop && left <= 3) {
    return { pit: true, compound: freshChoice, why: 'has to use a second compound' }
  }

  if (view.wear > 0.94) {
    return { pit: true, compound: freshChoice, why: 'tyres are finished' }
  }

  if (worthIt > 0) {
    // Do not all dive in on the same lap. A strategist who is a lap either
    // side of the crossover is not wrong, and twenty of them arriving together
    // is a queue.
    const jitter = rng()
    const margin = worthIt / Math.max(view.pitLoss, 1)
    if (margin > 0.12 || jitter < margin * 2.5) {
      return { pit: true, compound: freshChoice, why: 'the fresh set is worth the stop' }
    }
  }

  return { pit: false, compound: view.compound, why: 'staying out' }
}

/** Seconds lost to tyre wear over `laps`, starting from `wear`. */
function costOver(laps: number, wear: number, ratePerLap: number, spec: CompoundSpec): number {
  let total = 0
  let w = wear
  for (let q = 0; q < laps; q++) {
    total += wearCost(w, spec)
    w += ratePerLap * spec.wear
  }
  return total
}

/** Which compound gets to the end best from here. */
function bestCompound(left: number, ratePerLap: number, view: StrategyView): Compound {
  let best: Compound = 'medium'
  let bestCost = Infinity
  for (const name of ['soft', 'medium', 'hard'] as Compound[]) {
    if (name === view.compound && view.stops > 0) continue
    const spec = COMPOUNDS[name]
    const stint = usefulStint(ratePerLap, spec)
    // A set that will not reach the end means another stop, and another stop
    // is another pit loss.
    const extra = left > stint ? view.pitLoss : 0
    const cost = costOver(Math.min(left, Math.ceil(stint)), 0, ratePerLap, spec) + extra
    if (cost < bestCost) {
      bestCost = cost
      best = name
    }
  }
  return best
}
