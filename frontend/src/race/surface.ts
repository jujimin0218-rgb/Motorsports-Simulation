/**
 * What is beside the road, and how much of it there is.
 *
 * The engine's own world model classifies every point as "corner" or "not
 * corner" and gives the two cases a fixed run-off depth. That is a step
 * function, and a step function in this particular place is very visible: the
 * wall jumps twenty metres sideways over the length of a car, so a circuit
 * reads as gravel, then suddenly a narrow wall, then gravel again, and a car
 * sliding through the run-off hits a barrier that was not there a moment ago.
 *
 * A real circuit is not laid out that way. How much room there is beside a
 * piece of road is decided by **how fast a car arrives there and which way it
 * would leave** -- deep asphalt and gravel on the outside of a fast corner,
 * barriers close on the inside, a verge along a straight nobody leaves. So
 * that is what this computes, per sample and per side, from a reference speed
 * profile of the circuit itself, and then smooths, because the real thing is
 * continuous too.
 */

import { Circuit, clamp, smoothRing } from './geometry'

export type Surface = 'track' | 'kerb' | 'runoff' | 'gravel' | 'grass' | 'wall'

/** What a car can use of its grip on each, as a fraction of the road's. */
export const SURFACE_GRIP: Record<Surface, number> = {
  track: 1.0,
  kerb: 0.88,
  runoff: 0.72,
  gravel: 0.34,
  grass: 0.40,
  wall: 0.1,
}

/** Metres of kerb outside the white line, where a car would use one. */
const KERB_M = 1.3

/**
 * How hard a car slows once it is off the road, m/s^2.
 *
 * Asphalt run-off and then gravel: not a lot, which is exactly why a fast
 * corner needs so much more room than a slow one.
 */
const ESCAPE_DECEL = 6.5

/** Bounds on how much room a circuit ever gives, m. */
const MIN_RUNOFF = 5.5
const MAX_RUNOFF = 46

/** How much of a corner's room the inside gets. Barriers sit closer there. */
const INSIDE_SHARE = 0.38
/** And a straight, which cars leave far less often. */
const STRAIGHT_SHARE = 0.5

/** Where gravel starts within the run-off, as a fraction of its depth. */
const GRAVEL_FROM = 0.68

/** Below this arrival speed a corner gets asphalt run-off and no gravel. */
const GRAVEL_SPEED = 42

/** Index 0 is the left of the road, index 1 the right. */
type PerSide<T> = [T, T]

export class TrackSurface {
  circuit: Circuit
  /** Kerb width outside the white line, per side. */
  kerb: PerSide<Float64Array>
  /** Run-off depth outside the kerb, per side. */
  runoff: PerSide<Float64Array>
  /** Where gravel starts within that depth, 0..1. One means no gravel. */
  gravelFrom: PerSide<Float64Array>
  /** Distance from the centreline to the barrier, per side. */
  wall: PerSide<Float64Array>
  /** The reference speed a car would be doing here, m/s -- also used to decide
   *  where DRS boards and run-off go, and worth having for the picture. */
  reference: Float64Array

  constructor(circuit: Circuit) {
    this.circuit = circuit
    const n = circuit.n
    this.reference = referenceSpeed(circuit)

    // How much room a car leaving the road *here* would need to stop.
    const need = new Float64Array(n)
    for (let i = 0; i < n; i++) {
      const v = this.reference[i]
      need[i] = clamp((v * v) / (2 * ESCAPE_DECEL), MIN_RUNOFF, MAX_RUNOFF)
    }

    // A car does not leave the road where it is standing: it leaves where it
    // lost it, and arrives some way further on. So the requirement is carried
    // *forwards* along the road, decaying, which is why the run-off at a
    // corner reaches well past the exit -- and why it tapers rather than ends.
    const carried = new Float64Array(n)
    const reach = Math.max(1, Math.round(140 / circuit.ds))
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 0; i < n; i++) carried[i] = Math.max(carried[i], need[i])
      for (let q = 0; q < reach; q++) {
        const fade = 1 - q / reach
        for (let i = 0; i < n; i++) {
          const j = circuit.wrap(i + q)
          carried[j] = Math.max(carried[j], need[i] * fade)
        }
      }
    }

    // Which side. A car runs wide to the outside of a corner, so that is the
    // side that needs the room; the inside gets a barrier much closer, the way
    // a real circuit does.
    const left = new Float64Array(n)
    const right = new Float64Array(n)
    const bend = smoothRing(Float64Array.from(circuit.k), 8)
    for (let i = 0; i < n; i++) {
      const turning = clamp(Math.abs(bend[i]) * 400, 0, 1)
      const outsideIsLeft = bend[i] < 0
      const room = carried[i]
      const outside = room
      const inside = room * INSIDE_SHARE
      const straight = room * STRAIGHT_SHARE
      left[i] = turning === 0 ? straight
        : outsideIsLeft
          ? straight + (outside - straight) * turning
          : straight + (inside - straight) * turning
      right[i] = turning === 0 ? straight
        : outsideIsLeft
          ? straight + (inside - straight) * turning
          : straight + (outside - straight) * turning
    }

    // Smoothed hard. Whatever else is true of a circuit, its barriers do not
    // move twenty metres between one car length and the next.
    const smooth = Math.max(2, Math.round(70 / circuit.ds))
    this.runoff = [smoothRing(left, smooth), smoothRing(right, smooth)]

    // Kerbs where a car would actually put a wheel on one: turn-in, apex and
    // exit. Tapered, so a kerb starts and stops rather than appearing.
    const kerbRaw = new Float64Array(n)
    for (let i = 0; i < n; i++) kerbRaw[i] = Math.abs(bend[i]) > 1 / 700 ? KERB_M : 0
    const kerbBoth = smoothRing(kerbRaw, Math.max(2, Math.round(24 / circuit.ds)))
    this.kerb = [Float64Array.from(kerbBoth), Float64Array.from(kerbBoth)]

    // Gravel only where a car would arrive fast enough to need it, and only on
    // the outside. Everywhere else the run-off is asphalt, then grass.
    const gravelLeft = new Float64Array(n)
    const gravelRight = new Float64Array(n)
    for (let i = 0; i < n; i++) {
      const fast = clamp((this.reference[i] - GRAVEL_SPEED) / 25, 0, 1)
      const outsideIsLeft = bend[i] < 0
      const turning = clamp(Math.abs(bend[i]) * 400, 0, 1)
      const share = 1 - fast * turning * (1 - GRAVEL_FROM)
      gravelLeft[i] = outsideIsLeft ? share : 1
      gravelRight[i] = outsideIsLeft ? 1 : share
    }
    const gsm = Math.max(2, Math.round(50 / circuit.ds))
    this.gravelFrom = [smoothRing(gravelLeft, gsm), smoothRing(gravelRight, gsm)]

    this.wall = [new Float64Array(n), new Float64Array(n)]
    for (let side = 0; side < 2; side++) {
      for (let i = 0; i < n; i++) {
        this.wall[side][i] =
          circuit.halfWidth[i] + this.kerb[side][i] + this.runoff[side][i]
      }
    }
  }

  /** Which side of the road a lateral offset is on. */
  private side(lat: number): 0 | 1 {
    return lat >= 0 ? 0 : 1
  }

  /** What is under a point on the road. */
  at(i: number, lat: number): Surface {
    const w = this.circuit.wrap(i)
    const half = this.circuit.halfWidth[w]
    const distance = Math.abs(lat)
    if (distance <= half) return 'track'
    const s = this.side(lat)
    const edge = distance - half
    const kerb = this.kerb[s][w]
    if (edge <= kerb) return 'kerb'
    const depth = this.runoff[s][w]
    if (edge <= kerb + depth) {
      const from = this.gravelFrom[s][w]
      if (from >= 0.995) return 'grass'
      return edge >= kerb + depth * from ? 'gravel' : 'runoff'
    }
    return 'wall'
  }

  /** Where the barrier is on the side a car has run off to, m from the centre. */
  wallFor(i: number, lat: number): number {
    return this.wall[this.side(lat)][this.circuit.wrap(i)]
  }
}

/**
 * A speed profile for the circuit itself, before any car is on it.
 *
 * Not a lap time -- a reference for how quick each piece of road is, which is
 * what decides how much room beside it a circuit needs, where the gravel goes
 * and where a braking board belongs. Computed with a single set of plausible
 * numbers rather than any particular car's, because a circuit's layout does
 * not change when a different team turns up.
 */
export function referenceSpeed(circuit: Circuit): Float64Array {
  const n = circuit.n
  const LAT = 26 // m/s^2, a modern car through a medium corner
  const BRAKE = 32
  const ACCEL = 9
  const VMAX = 92
  const v = new Float64Array(n)
  const k = smoothRing(Float64Array.from(circuit.k), 4)
  for (let i = 0; i < n; i++) {
    const radius = 1 / Math.max(Math.abs(k[i]), 1e-6)
    v[i] = Math.min(VMAX, Math.sqrt(LAT * radius))
  }
  // Backward pass for braking, forward for acceleration, twice round so the
  // loop is consistent with itself.
  for (let pass = 0; pass < 2; pass++) {
    for (let q = n - 1; q >= 0; q--) {
      const j = circuit.wrap(q + 1)
      v[q] = Math.min(v[q], Math.sqrt(v[j] * v[j] + 2 * BRAKE * circuit.ds))
    }
    for (let q = 0; q < n; q++) {
      const p = circuit.wrap(q - 1)
      v[q] = Math.min(v[q], Math.sqrt(v[p] * v[p] + 2 * ACCEL * circuit.ds))
    }
  }
  return v
}
