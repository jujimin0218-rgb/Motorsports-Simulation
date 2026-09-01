/**
 * The line, and the lines that come off it.
 *
 * **The racing line.**  A car does not drive the middle of the road.  It goes
 * to the outside before a corner, crosses to the inside at the apex and lets
 * the car run back out to the outside at the exit, because that path has the
 * biggest radius the road allows and speed goes as the square root of radius.
 * That is out-in-out, and it is not a rule applied here -- it is what falls
 * out of asking for the straightest path the road can hold.
 *
 * So the solver asks exactly that.  Every sample carries a lateral offset from
 * the centreline, bounded by the road; the offset is repeatedly moved toward
 * whatever would make the path locally straight (the midpoint of its
 * neighbours), and clamped back inside the white line.  Run coarse first and
 * fine afterwards -- a corner is a long-wavelength shape and relaxation is bad
 * at long wavelengths -- it shrink-wraps onto the minimum-curvature path.
 * Outside on the way in, inside at the apex, outside on the way out, with no
 * step of the algorithm ever mentioning any of those three words.
 *
 * **The apex is then moved.**  Minimum curvature gives the *geometric* apex,
 * which is the quickest way through a corner considered on its own.  A real
 * corner is not on its own: one that opens onto a long straight is worth
 * entering slower and later so the car can be straight, and therefore on full
 * throttle, sooner -- a power apex.  So each corner's offset profile is
 * delayed along the road by an amount scaled by the straight that follows it,
 * and re-clamped.  A hairpin onto a kilometre of full throttle gets a very
 * late apex; a kink between two other corners gets almost none.
 *
 * **The derived lines.**  Racing is not one line.  A defender takes the inside
 * early and pays for it on the exit.  An attacker brakes deeper still and
 * apexes later again.  A driver who has been out-braked gives up the entry to
 * get a better exit and takes the place back on the next straight.  Each of
 * those is a real path with its own curvature, and because the AI builds its
 * speed profile from whichever line it is actually on, the *cost* of each is
 * never written down anywhere: a tighter exit radius simply is a lower exit
 * speed.
 */

import { Circuit, Line, clamp, lerp, smoothRing, smoothstep } from './geometry'

export type { Line }

export type LineId = 'racing' | 'defend' | 'dive' | 'switchback' | 'outside'

export interface LineSet {
  racing: Line
  defend: Line
  dive: Line
  switchback: Line
  outside: Line
}

/**
 * Solve the minimum-curvature offsets on one grid.
 *
 * The curvature of a path a lateral distance `n` from a road of curvature
 * `kappa` is, to first order, `kappa + n''`.  So the straightest line the road
 * can hold is the one that minimises
 *
 *     J = sum_i w_i (kappa_i + n''_i)^2      subject to  |n_i| <= limit_i
 *
 * Differentiating it properly is the whole thing.  The obvious move -- push
 * each point toward the midpoint of its neighbours -- is the gradient of
 * *length*, not of curvature, and on a closed loop that is curve-shortening
 * flow: the line contracts until every sample is pinned against the inside
 * edge of the road and the lap is driven with two wheels on the grass.  It is
 * a real failure and it looks plausible until the radii are measured.
 *
 * The actual gradient touches three terms, because `n_i` appears in `n''` at
 * `i-1`, `i` and `i+1`.  Setting it to zero gives a fourth-order (biharmonic)
 * system, which *does* have a periodic solution, and whose answer is the shape
 * a driver would recognise.  Solved by projected Gauss-Seidel: sweep, relax
 * each point onto the stencil, clamp it back inside the white line, repeat.
 *
 * `w` is what turns a minimum-*sum* answer into something closer to a
 * minimum-*peak* one.  A lap time is made of peaks -- the tightest point of a
 * corner sets the speed through the whole of it -- so the caller re-weights
 * toward wherever the line is currently tightest and solves again.
 *
 * What it does *not* capture is that sitting a constant distance inside a
 * corner tightens the path even though `n''` is zero there.  On a long
 * constant-radius corner that omission lets the line park against the inside
 * kerb and come out tighter than the road; `guardWideCorners` below is what
 * catches it.
 */
function relaxOffsets(
  kappa: Float64Array,
  limit: Float64Array,
  weight: Float64Array,
  h: number,
  init: Float64Array | null,
  sweeps: number,
  omega: number,
): Float64Array {
  const n = kappa.length
  const off = init ? Float64Array.from(init) : new Float64Array(n)
  const h2 = h * h
  const at = (i: number) => (i < 0 ? i + n : i >= n ? i - n : i)
  for (let sweep = 0; sweep < sweeps; sweep++) {
    for (let i = 0; i < n; i++) {
      const im2 = at(i - 2), im1 = at(i - 1), ip1 = at(i + 1), ip2 = at(i + 2)
      const wm = weight[im1], wc = weight[i], wp = weight[ip1]
      const denom = wm + 4 * wc + wp
      if (denom < 1e-12) continue
      const road = h2 * (wm * kappa[im1] - 2 * wc * kappa[i] + wp * kappa[ip1])
      const neighbours =
        wm * (off[im2] - 2 * off[im1]) -
        2 * wc * (off[im1] + off[ip1]) +
        wp * (off[ip2] - 2 * off[ip1])
      const target = (-road - neighbours) / denom
      off[i] = clamp(off[i] + omega * (target - off[i]), -limit[i], limit[i])
    }
  }
  return off
}

/** Every `factor`-th value, for solving the lap coarsely first. */
function decimate(values: Float64Array, factor: number): Float64Array {
  const out = new Float64Array(Math.floor(values.length / factor))
  for (let i = 0; i < out.length; i++) out[i] = values[i * factor]
  return out
}

/** A coarse answer spread back over the fine grid. */
function interpolateUp(coarse: Float64Array, fine: number, factor: number): Float64Array {
  const out = new Float64Array(fine)
  const m = coarse.length
  for (let i = 0; i < fine; i++) {
    const f = i / factor
    const a = Math.floor(f) % m
    out[i] = lerp(coarse[a], coarse[(a + 1) % m], f - Math.floor(f))
  }
  return out
}

/**
 * The minimum-curvature line, solved coarse-to-fine and then sharpened.
 *
 * Coarse first because relaxation clears short-wavelength error quickly and
 * long-wavelength error almost not at all, and a racing line is nearly all
 * long wavelength -- it varies over the length of a corner, not between two
 * samples two metres apart.  Run on the fine grid alone the offsets barely
 * leave zero.
 *
 * Then two re-weighted passes.  The plain solve minimises the *sum* of squared
 * curvature; a lap time cares about the *peak*.  Weighting each sample by how
 * tight the line currently is there, and solving again, pulls road out of the
 * places the line is not using and spends it where the corner is tightest.
 */
function minCurvature(circuit: Circuit): Float64Array {
  const n = circuit.n
  const limit = new Float64Array(n)
  for (let i = 0; i < n; i++) limit[i] = circuit.limit(i)
  const kappa = circuit.k

  let off: Float64Array | null = null
  const uniform = (count: number) => {
    const w = new Float64Array(count)
    w.fill(1)
    return w
  }
  for (const factor of [16, 8, 4, 2, 1]) {
    const count = Math.floor(n / factor)
    if (count < 24) continue
    const k = decimate(kappa, factor)
    const lim = decimate(limit, factor)
    const start = off ? decimate(off, factor) : null
    const solved = relaxOffsets(k, lim, uniform(count), circuit.ds * factor, start, 900, 1.35)
    off = interpolateUp(solved, n, factor)
  }
  let best = off ?? new Float64Array(n)

  for (let pass = 0; pass < 2; pass++) {
    const line = circuit.makeLine(best, 'probe')
    const weight = new Float64Array(n)
    let peak = 1e-6
    for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(line.k[i]))
    for (let i = 0; i < n; i++) {
      // Somewhere between uniform and "only the tightest point matters".
      weight[i] = 0.25 + Math.pow(Math.abs(line.k[i]) / peak, 1.2)
    }
    const smoothed = smoothRing(weight, 4)
    best = relaxOffsets(kappa, limit, smoothed, circuit.ds, best, 700, 1.25)
  }
  return guardWideCorners(circuit, best)
}

/**
 * Never let the line come out tighter than the road it is on.
 *
 * The linearised objective the solver minimises thinks a constant offset is
 * free -- `n''` is zero, so the curvature is unchanged -- but hugging the
 * inside of a corner genuinely tightens the path.  On a long constant-radius
 * corner nothing else pushes back, so the solver parks the line against the
 * inside kerb for two hundred metres and hands back a line of *smaller* radius
 * than the centreline: a path slower than driving down the middle, run at the
 * absolute limit for the whole corner with no margin for traffic, dirty air or
 * a worn tyre.
 *
 * Measured on a twenty car race, that single corner produced half of every
 * incident on the lap.  So the invariant is stated and enforced: within a
 * corner, the line's tightest radius is at least the road's.  Where it is not,
 * the offsets through that corner are eased back toward the centreline -- with
 * ramps at both ends so nothing kinks -- until it is.
 */
function guardWideCorners(circuit: Circuit, offsets: Float64Array): Float64Array {
  let off = offsets
  for (let pass = 0; pass < 4; pass++) {
    const line = circuit.makeLine(off, 'probe')
    let changed = false
    const next = Float64Array.from(off)
    for (const cn of circuit.corners) {
      const len = ((cn.to - cn.from + circuit.n) % circuit.n) + 1
      let tightest = 0
      for (let q = 0; q < len; q++) {
        tightest = Math.max(tightest, Math.abs(line.k[circuit.wrap(cn.from + q)]))
      }
      const lineRadius = 1 / Math.max(tightest, 1e-6)
      // A little better than the road, not merely equal: a line that is only
      // as good as the centreline is not a racing line either.
      const wanted = cn.radius * 1.02
      if (lineRadius >= wanted) continue
      changed = true
      const ease = Math.round(30 / circuit.ds)
      const shrink = clamp(lineRadius / wanted, 0.5, 0.97)
      for (let q = -ease; q < len + ease; q++) {
        const i = circuit.wrap(cn.from + q)
        const edge = Math.min(
          smoothstep(clamp((q + ease) / ease, 0, 1)),
          smoothstep(clamp((len + ease - q) / ease, 0, 1)),
        )
        next[i] *= 1 - (1 - shrink) * edge
      }
    }
    if (!changed) break
    off = smoothRing(next, 2)
  }
  return off
}

/**
 * Which way a corner's radius is going, from its first third to its last.
 *
 * Returned as a signed fraction: negative tightens (a decreasing radius
 * corner), positive opens out (increasing radius), zero is constant. Read off
 * the road's own curvature rather than assumed per corner, so a circuit gets
 * whatever it actually has.
 */
function radiusTrend(circuit: Circuit, corner: Circuit['corners'][number]): number {
  const len = ((corner.to - corner.from + circuit.n) % circuit.n) + 1
  if (len < 6) return 0
  const mean = (from: number, to: number) => {
    let sum = 0
    let count = 0
    for (let q = from; q < to; q++) {
      sum += Math.abs(circuit.k[circuit.wrap(corner.from + q)])
      count++
    }
    return count ? sum / count : 0
  }
  const early = mean(0, Math.floor(len / 3))
  const late = mean(Math.ceil((len * 2) / 3), len)
  if (early < 1e-6 || late < 1e-6) return 0
  // Curvature up means radius down. Clamped: a chicane can read as an enormous
  // trend and a chicane is not a decreasing radius corner.
  return clamp((early - late) / Math.max(early, late), -1, 1)
}

/** Delay an offset profile along the road, per sample. Moves apexes later. */
function delayProfile(circuit: Circuit, off: Float64Array, delay: Float64Array): Float64Array {
  const n = circuit.n
  const out = new Float64Array(n)
  for (let i = 0; i < n; i++) {
    const src = i - delay[i] / circuit.ds
    const i0 = Math.floor(src)
    const t = src - i0
    out[i] = lerp(off[circuit.wrap(i0)], off[circuit.wrap(i0 + 1)], t)
  }
  return out
}

/** The optimal line: minimum curvature, then apexes moved for the exit. */
export function solveRacingLine(circuit: Circuit): Line {
  const geometric = minCurvature(circuit)

  // How much later each corner's apex should be.
  //
  // Two things set it, and they are the two things a driver is taught.
  //
  // **What follows.** A corner is worth sacrificing entry speed for only in
  // proportion to how long the car will then spend accelerating, so the
  // straight after it sets the size of the sacrifice: a hairpin onto a
  // kilometre of full throttle gets a very late apex, a kink between two other
  // corners almost none.
  //
  // **Which way the radius is going.** A corner that tightens on itself -- a
  // decreasing radius -- has to be apexed late, because the tightest part is
  // at the end and a car that has used the road early arrives at it with
  // nowhere to go. One that opens out -- increasing radius -- is the opposite:
  // apex early, get the car straight, and use the exit that is opening in
  // front of it.
  const delay = new Float64Array(circuit.n)
  for (const cn of circuit.corners) {
    const trend = radiusTrend(circuit, cn)
    const amount =
      clamp(2 + cn.exitStraight * 0.030, 2, 0.30 * cn.length + 4) +
      // Negative trend is a corner that tightens; positive one that opens.
      clamp(-trend * cn.length * 0.22, -0.18 * cn.length, 0.28 * cn.length)
    const len = ((cn.to - cn.from + circuit.n) % circuit.n) + 1
    const lead = Math.round(25 / circuit.ds)
    const tail = Math.round(35 / circuit.ds)
    for (let q = -lead; q < len + tail; q++) {
      const i = circuit.wrap(cn.from + q)
      const t = clamp((q + lead) / (len + lead + tail), 0, 1)
      // Ramped in and out so the delay does not step at the corner's edges,
      // which would put a kink in the line exactly at turn-in.
      delay[i] = Math.max(delay[i], amount * Math.sin(Math.PI * t))
    }
  }
  const smoothDelay = smoothRing(delay, 10)
  let off = delayProfile(circuit, geometric, smoothDelay)
  for (let i = 0; i < circuit.n; i++) off[i] = clamp(off[i], -circuit.limit(i), circuit.limit(i))
  off = smoothRing(off, 3)
  return circuit.makeLine(off, 'racing')
}

interface BiasOptions {
  /** How far toward the inside edge, as a fraction. Negative goes outside. */
  inside: number
  /** Metres before turn-in that the move across is made. */
  lead: number
  /** Extra metres of apex delay on top of the racing line's. */
  apexDelay: number
  /** How much of the road to give back on the exit, 0..1. */
  exitWiden: number
  /** Pull toward the *outside* before turn-in, 0..1 -- a set-up for a switchback. */
  entryOutside: number
}

/**
 * A variant of the racing line that commits to one side through a corner.
 *
 * The shape is always the same: move across during the braking zone, hold the
 * chosen side to the apex, release back toward the racing line on the exit.
 * What changes between the derived lines is how far, how early, and how late
 * the apex is -- which is the whole vocabulary of a corner fight.
 */
function biasedLine(circuit: Circuit, racing: Line, id: string, opts: BiasOptions): Line {
  const off = Float64Array.from(racing.off)
  for (const cn of circuit.corners) {
    const len = ((cn.to - cn.from + circuit.n) % circuit.n) + 1
    const lead = Math.max(2, Math.round(opts.lead / circuit.ds))
    const tail = Math.max(2, Math.round((40 + opts.exitWiden * 30) / circuit.ds))
    const total = len + lead + tail
    const apexU = (lead + len * 0.5 + opts.apexDelay / circuit.ds) / total
    for (let q = -lead; q < len + tail; q++) {
      const i = circuit.wrap(cn.from + q)
      const lim = circuit.limit(i)
      const u = (q + lead) / total
      // Weight: nothing before the braking zone, full from turn-in to the
      // apex, fading out over the exit.
      const rampIn = smoothstep(clamp((q + lead) / lead, 0, 1))
      const release = u <= apexU ? 1 : 1 - smoothstep(clamp((u - apexU) / Math.max(0.08, 1 - apexU), 0, 1))
      let weight = rampIn * release

      // The inside of a left-hander is to the left, which is +normal.
      let target = cn.dir * lim * opts.inside
      if (opts.entryOutside > 0 && u < apexU) {
        const eu = smoothstep(clamp(u / Math.max(0.05, apexU), 0, 1))
        target = lerp(-cn.dir * lim * opts.entryOutside, target, eu)
        weight = Math.max(weight, rampIn * (1 - eu) * opts.entryOutside)
      }
      if (opts.exitWiden > 0 && u > apexU) {
        const xu = smoothstep(clamp((u - apexU) / (1 - apexU), 0, 1))
        target = lerp(target, -cn.dir * lim, xu * opts.exitWiden)
        weight = Math.max(weight, xu * opts.exitWiden)
      }
      off[i] = clamp(lerp(off[i], target, weight), -lim, lim)
    }
  }
  return circuit.makeLine(smoothRing(off, 5), id)
}

export function buildLines(circuit: Circuit): LineSet {
  const racing = solveRacingLine(circuit)
  return {
    racing,
    // Defence: the inside is taken before the braking zone so there is no room
    // to be passed into the corner. The apex comes early and the exit is
    // tight, which is exactly the cost of defending -- and it is a cost this
    // line's own curvature charges, not a penalty applied afterwards.
    defend: biasedLine(circuit, racing, 'defend', {
      inside: 0.92, lead: 75, apexDelay: -8, exitWiden: 0, entryOutside: 0,
    }),
    // The lunge: as deep as the road allows, hard on the inside, apex very
    // late, and the car runs to the far edge on the way out. Fast in,
    // compromised out.
    dive: biasedLine(circuit, racing, 'dive', {
      inside: 0.99, lead: 42, apexDelay: 26, exitWiden: 0.9, entryOutside: 0,
    }),
    // The switchback: give up the entry, get the car turned early, be on the
    // throttle first and cross back over on the way out.
    switchback: biasedLine(circuit, racing, 'switchback', {
      inside: 0.8, lead: 60, apexDelay: 40, exitWiden: 0.5, entryOutside: 0.95,
    }),
    // Round the outside. It usually does not work. Sometimes it does.
    outside: biasedLine(circuit, racing, 'outside', {
      inside: -0.88, lead: 70, apexDelay: 6, exitWiden: 0, entryOutside: 0,
    }),
  }
}

/** What a corner's line actually did, for checking it is out-in-out. */
export interface ApexReport {
  corner: number
  name: string
  /** Offsets signed so that positive is toward the *outside* of the corner. */
  entry: number
  apex: number
  exit: number
  /** Where the tightest part of the line is, as a fraction through the corner.
   *  Above 0.5 is a late apex. */
  apexAt: number
  outInOut: boolean
  /** Radius of the road at its tightest, and of the line at the same place. */
  roadRadius: number
  lineRadius: number
}

/**
 * Check the line against the thing it is supposed to be.
 *
 * Not decoration: the solver is iterative and the apex delay is a heuristic,
 * so "did it actually come out wide, cut in, and run wide again" is a question
 * worth being able to answer for every corner on any circuit the game loads.
 */
export function reportApexes(circuit: Circuit, line: Line): ApexReport[] {
  return circuit.corners.map((cn) => {
    const len = ((cn.to - cn.from + circuit.n) % circuit.n) + 1
    // Signed so positive is outside the corner, whichever way it bends.
    const outward = (i: number) => -cn.dir * line.off[circuit.wrap(i)]
    const entry = outward(cn.from - Math.round(18 / circuit.ds))
    const exit = outward(cn.to + Math.round(18 / circuit.ds))
    let tightest = 0
    let apexIdx = cn.from
    for (let q = 0; q < len; q++) {
      const i = circuit.wrap(cn.from + q)
      const towardInside = -outward(i)
      if (towardInside > tightest) { tightest = towardInside; apexIdx = i }
    }
    const apex = outward(apexIdx)
    const apexAt = (((apexIdx - cn.from + circuit.n) % circuit.n)) / Math.max(1, len - 1)
    let maxK = 0
    for (let q = 0; q < len; q++) maxK = Math.max(maxK, Math.abs(line.k[circuit.wrap(cn.from + q)]))
    return {
      corner: cn.index + 1,
      name: cn.name,
      entry, apex, exit, apexAt,
      // Out-in-out: wider than the apex on the way in, and again on the way
      // out. A tolerance of 20 cm, because a kink is allowed to be a kink.
      outInOut: entry > apex + 0.2 && exit > apex + 0.2,
      roadRadius: cn.radius,
      lineRadius: 1 / Math.max(maxK, 1e-6),
    }
  })
}
