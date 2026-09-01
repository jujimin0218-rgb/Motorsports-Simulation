/**
 * A circuit as something a car can be driven round.
 *
 * The server lays the track out as a place -- a centreline in metres, a width
 * either side, and the surfaces beside it.  That is enough to *draw*.  Driving
 * it needs more: which way the road is pointing at every metre, how tightly it
 * bends, where the corners begin and end, and how much room there is to move
 * about in.  This works all of that out once, when the circuit arrives, and
 * hands it to the line solver, the AI and the renderer.
 *
 * Everything is in metres and radians, in the same frame the server sent.  No
 * screen units get in here; the renderer owns those.
 */

export interface Vec2 {
  x: number
  y: number
}

export const TAU = Math.PI * 2

export const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v)
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t
export const smoothstep = (t: number) => t * t * (3 - 2 * t)

/** Wrap an angle into (-pi, pi]. */
export function wrapAngle(a: number): number {
  a = (a + Math.PI) % TAU
  if (a < 0) a += TAU
  return a - Math.PI
}

/** The shortest signed distance from `a` to `b` round a loop of `len`. */
export function wrapDelta(d: number, len: number): number {
  d %= len
  if (d > len / 2) d -= len
  if (d < -len / 2) d += len
  return d
}

/** A moving average round a loop. Used a lot: every profile here is periodic. */
export function smoothRing(values: Float64Array, passes: number): Float64Array {
  const n = values.length
  let cur = values
  for (let p = 0; p < passes; p++) {
    const out = new Float64Array(n)
    for (let i = 0; i < n; i++) {
      out[i] = 0.25 * cur[(i - 1 + n) % n] + 0.5 * cur[i] + 0.25 * cur[(i + 1) % n]
    }
    cur = out
  }
  return cur
}

/** Signed curvature of the circle through three points. Positive turns left. */
export function curvatureOf(
  ax: number, ay: number, bx: number, by: number, cx: number, cy: number,
): number {
  const a = Math.hypot(bx - ax, by - ay)
  const b = Math.hypot(cx - bx, cy - by)
  const c = Math.hypot(cx - ax, cy - ay)
  if (a < 1e-6 || b < 1e-6 || c < 1e-6) return 0
  const cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
  return (2 * cross) / (a * b * c)
}

/** A stretch of road that bends. Everything the AI plans is planned per corner. */
export interface Corner {
  index: number
  /** Sample indices: where the bend starts, is tightest, and stops. */
  from: number
  apex: number
  to: number
  /** Signed: +1 turns left, -1 turns right. */
  dir: number
  /** Radius of the road at its tightest, m. */
  radius: number
  /** Arc length of the corner, m. */
  length: number
  /** Road between this corner's exit and the next one's entry, m. */
  exitStraight: number
  /** Road between the previous corner's exit and this one's entry, m. */
  entryStraight: number
  sIn: number
  sApex: number
  sOut: number
  name: string
}

/** One driveable path round the lap, as a lateral offset from the centreline. */
export interface Line {
  id: string
  /** Metres left of the centreline at each sample. */
  off: Float64Array
  x: Float64Array
  y: Float64Array
  /** Signed curvature of *this* path, which is what sets its speed. */
  k: Float64Array
  /** Heading of the path at each sample. */
  head: Float64Array
  /** Distance along this path from sample i to i+1. Not `ds`: a line that
   *  cuts a corner is shorter than the road, and that difference is real. */
  seg: Float64Array
}

/** How the circuit arrives from the server. */
export interface WorldPayload {
  name: string
  length: number
  step: number
  centre: [number, number][]
  half_width: number[]
  bands?: { surface: string; polygon: [number, number][] }[]
  barriers?: [number, number][][]
  pit_path?: [number, number][]
  bounds: [number, number, number, number]
}

/** A grand prix car, in metres. What collides, and what has to be got past. */
export const CAR_LENGTH = 5.6
export const CAR_WIDTH = 2.0
export const CAR_HALF_WIDTH = CAR_WIDTH / 2
/**
 * How much road the line leaves itself, m.
 *
 * A real driver puts the outside wheel on the white line and no further, but a
 * real driver also tracks the line perfectly. This one does not: it has a
 * steering controller with an error of a few tens of centimetres at speed. A
 * line that uses every last centimetre turns that ordinary tracking error into
 * a trip through the grass at every corner exit, so the line keeps something
 * back -- which is also what a driver does on a lap they are not on the limit
 * of.
 */
export const EDGE_MARGIN = 0.85

const SAMPLE_M = 2.5

/**
 * How wide a stencil the curvature is measured over, m.
 *
 * This number decides what counts as a corner. A surveyed centreline wanders
 * by a few centimetres between samples; measured over two metres that noise is
 * a 40 m radius, which is a hairpin, and a driver planning off it brakes on
 * the straights. Measured over eight it is the road.
 */
const CURVATURE_SPAN_M = 8.0

export class Circuit {
  name: string
  /** Lap distance, m. */
  length: number
  /** Metres between samples. */
  ds: number
  n: number

  x: Float64Array
  y: Float64Array
  /** Distance round the lap at each sample. */
  s: Float64Array
  head: Float64Array
  /** Left-hand normal at each sample. */
  nx: Float64Array
  ny: Float64Array
  /** Signed curvature of the road itself. */
  k: Float64Array
  halfWidth: Float64Array

  corners: Corner[] = []
  /** Which corner each sample belongs to, or -1. */
  cornerAt: Int32Array
  /** Distance to the start of the next corner, m -- what a driver looks at. */
  toCorner: Float64Array

  bounds: { minx: number; miny: number; maxx: number; maxy: number }
  pitPath: [number, number][]
  bands: { surface: string; polygon: [number, number][] }[]
  barriers: [number, number][][]

  constructor(world: WorldPayload) {
    this.name = world.name
    const src = world.centre
    const count = src.length
    // The centreline arrives at whatever spacing the server chose. Resample it
    // to something a car-length-scale simulation can plan on, keeping the loop
    // closed: the last sample joins the first.
    const rawLen = world.length
    this.n = Math.max(64, Math.round(rawLen / SAMPLE_M))
    this.ds = rawLen / this.n
    this.length = rawLen
    this.x = new Float64Array(this.n)
    this.y = new Float64Array(this.n)
    this.s = new Float64Array(this.n)
    this.halfWidth = new Float64Array(this.n)

    // Arc length along the *source* polyline, so resampling is by distance
    // rather than by index -- the server's own step can drift on tight corners.
    const cum = new Float64Array(count + 1)
    for (let i = 0; i < count; i++) {
      const a = src[i]
      const b = src[(i + 1) % count]
      cum[i + 1] = cum[i] + Math.hypot(b[0] - a[0], b[1] - a[1])
    }
    const total = cum[count]
    for (let i = 0; i < this.n; i++) {
      const target = (i / this.n) * total
      let lo = 0
      let hi = count
      while (lo + 1 < hi) {
        const mid = (lo + hi) >> 1
        if (cum[mid] <= target) lo = mid
        else hi = mid
      }
      const span = cum[lo + 1] - cum[lo]
      const t = span > 1e-9 ? (target - cum[lo]) / span : 0
      const a = src[lo % count]
      const b = src[(lo + 1) % count]
      this.x[i] = lerp(a[0], b[0], t)
      this.y[i] = lerp(a[1], b[1], t)
      this.s[i] = (i / this.n) * rawLen
      const wa = world.half_width[lo % count]
      const wb = world.half_width[(lo + 1) % count]
      this.halfWidth[i] = lerp(wa, wb, t)
    }

    this.head = new Float64Array(this.n)
    this.nx = new Float64Array(this.n)
    this.ny = new Float64Array(this.n)
    this.k = new Float64Array(this.n)
    this._geometry()

    this.cornerAt = new Int32Array(this.n).fill(-1)
    this.toCorner = new Float64Array(this.n)
    this._corners()

    this.bounds = {
      minx: world.bounds[0], miny: world.bounds[1],
      maxx: world.bounds[2], maxy: world.bounds[3],
    }
    this.pitPath = world.pit_path ?? []
    this.bands = world.bands ?? []
    this.barriers = world.barriers ?? []
  }

  private _geometry(): void {
    const n = this.n
    for (let i = 0; i < n; i++) {
      const a = (i - 1 + n) % n
      const b = (i + 1) % n
      this.head[i] = Math.atan2(this.y[b] - this.y[a], this.x[b] - this.x[a])
      this.nx[i] = -Math.sin(this.head[i])
      this.ny[i] = Math.cos(this.head[i])
    }
    // Curvature over a stencil a couple of car lengths wide, and then
    // smoothed. Both matter. Narrower and the *survey's* own metre-to-metre
    // noise reads as a fifty-metre-radius corner in the middle of a straight,
    // which a driver planning from curvature would brake for; wider and a
    // chicane disappears into the straight either side of it.
    const span = Math.max(2, Math.round(CURVATURE_SPAN_M / this.ds))
    const raw = new Float64Array(n)
    for (let i = 0; i < n; i++) {
      const a = (i - span + n) % n
      const b = (i + span) % n
      raw[i] = curvatureOf(this.x[a], this.y[a], this.x[i], this.y[i], this.x[b], this.y[b])
    }
    this.k = smoothRing(raw, 6)
  }

  private _corners(): void {
    const n = this.n
    const k = this.k
    // A corner is road bending tighter than this. 600 m is about where a
    // modern car stops being flat and starts having to lift.
    const threshold = 1 / 600
    let start = 0
    while (start < n && Math.abs(k[start]) > threshold) start++
    const corners: Corner[] = []
    for (let c = 0; c < n; c++) {
      const i = (start + c) % n
      if (Math.abs(k[i]) <= threshold) continue
      let j = i
      let len = 1
      while (len < n && Math.abs(k[(j + 1) % n]) > threshold) {
        j = (j + 1) % n
        len++
      }
      if (len * this.ds > 15) {
        let apex = i
        let best = 0
        for (let q = 0; q < len; q++) {
          const idx = (i + q) % n
          if (Math.abs(k[idx]) > best) {
            best = Math.abs(k[idx])
            apex = idx
          }
        }
        corners.push({
          index: corners.length,
          from: i, apex, to: j,
          dir: Math.sign(k[apex]) || 1,
          radius: 1 / Math.max(best, 1e-6),
          length: len * this.ds,
          exitStraight: 0, entryStraight: 0,
          sIn: this.s[i], sApex: this.s[apex], sOut: this.s[j],
          name: '',
        })
      }
      c += len - 1
    }
    // Two bends the same way separated by less than a car length are one
    // corner with a kink in it, not two corners -- and planning them apart
    // gives a line that turns in twice.
    const merged: Corner[] = []
    for (const cn of corners) {
      const prev = merged[merged.length - 1]
      const gapM = prev ? (((cn.from - prev.to + this.n) % this.n) * this.ds) : Infinity
      if (prev && prev.dir === cn.dir && gapM < 12) {
        prev.to = cn.to
        prev.sOut = cn.sOut
        prev.length += gapM + cn.length
        if (cn.radius < prev.radius) {
          prev.radius = cn.radius
          prev.apex = cn.apex
          prev.sApex = cn.sApex
        }
      } else merged.push(cn)
    }
    merged.forEach((cn, i) => {
      cn.index = i
      cn.name = `Turn ${i + 1}`
      const next = merged[(i + 1) % merged.length]
      const prev = merged[(i - 1 + merged.length) % merged.length]
      cn.exitStraight = ((next.from - cn.to + this.n) % this.n) * this.ds
      cn.entryStraight = ((cn.from - prev.to + this.n) % this.n) * this.ds
      for (let q = 0; q < ((cn.to - cn.from + this.n) % this.n) + 1; q++) {
        this.cornerAt[(cn.from + q) % this.n] = i
      }
    })
    this.corners = merged

    // Distance to the next turn-in point, walked backwards round the lap so
    // every sample gets it in one pass.
    const big = 1e9
    this.toCorner.fill(big)
    for (const cn of merged) this.toCorner[cn.from] = 0
    for (let pass = 0; pass < 2; pass++) {
      for (let q = this.n - 1; q >= 0; q--) {
        const i = q
        const next = (i + 1) % this.n
        if (this.cornerAt[i] >= 0) { this.toCorner[i] = 0; continue }
        this.toCorner[i] = Math.min(this.toCorner[i], this.toCorner[next] + this.ds)
      }
    }
  }

  /** Which sample a lap distance falls on. */
  idxAt(s: number): number {
    const wrapped = ((s % this.length) + this.length) % this.length
    return Math.min(this.n - 1, Math.floor(wrapped / this.ds))
  }

  /** Sample index, wrapped. */
  wrap(i: number): number {
    return ((i % this.n) + this.n) % this.n
  }

  /** Where a lap distance and a lateral offset put a car on the plane. */
  place(s: number, off: number): { x: number; y: number; h: number } {
    const wrapped = ((s % this.length) + this.length) % this.length
    const exact = wrapped / this.ds
    const i = Math.floor(exact) % this.n
    const t = exact - Math.floor(exact)
    const j = (i + 1) % this.n
    const cx = lerp(this.x[i], this.x[j], t)
    const cy = lerp(this.y[i], this.y[j], t)
    const h = this.head[i] + wrapAngle(this.head[j] - this.head[i]) * t
    return { x: cx - Math.sin(h) * off, y: cy + Math.cos(h) * off, h }
  }

  /** How much road there is either side of the line, less the car. */
  limit(i: number): number {
    return Math.max(0.5, this.halfWidth[this.wrap(i)] - CAR_HALF_WIDTH - EDGE_MARGIN)
  }

  /**
   * Where a point on the plane is on the road: how far round the lap, and how
   * far across. Given a hint it is a local search, which is what makes it
   * affordable once per car per step.
   */
  locate(px: number, py: number, hint: number): { i: number; s: number; lat: number } {
    let bestI = -1
    let bestD = Infinity
    const span = 60
    for (let q = -span; q <= span; q++) {
      const i = this.wrap(hint + q)
      const dx = px - this.x[i]
      const dy = py - this.y[i]
      const d = dx * dx + dy * dy
      if (d < bestD) { bestD = d; bestI = i }
    }
    if (bestI < 0 || bestD > 250 * 250) {
      bestD = Infinity
      for (let i = 0; i < this.n; i += 4) {
        const dx = px - this.x[i]
        const dy = py - this.y[i]
        const d = dx * dx + dy * dy
        if (d < bestD) { bestD = d; bestI = i }
      }
    }
    const i = bestI
    const dx = px - this.x[i]
    const dy = py - this.y[i]
    const along = dx * Math.cos(this.head[i]) + dy * Math.sin(this.head[i])
    const lat = dx * this.nx[i] + dy * this.ny[i]
    return { i, s: this.s[i] + along, lat }
  }

  /** Turn a lateral-offset profile into a path with its geometry worked out. */
  makeLine(off: Float64Array, id: string): Line {
    const n = this.n
    const x = new Float64Array(n)
    const y = new Float64Array(n)
    for (let i = 0; i < n; i++) {
      x[i] = this.x[i] + this.nx[i] * off[i]
      y[i] = this.y[i] + this.ny[i] * off[i]
    }
    const k = new Float64Array(n)
    const head = new Float64Array(n)
    const seg = new Float64Array(n)
    const span = Math.max(2, Math.round(CURVATURE_SPAN_M / this.ds))
    for (let i = 0; i < n; i++) {
      const a = (i - span + n) % n
      const b = (i + span) % n
      k[i] = curvatureOf(x[a], y[a], x[i], y[i], x[b], y[b])
      const j = (i + 1) % n
      seg[i] = Math.hypot(x[j] - x[i], y[j] - y[i])
      const p = (i - 1 + n) % n
      head[i] = Math.atan2(y[j] - y[p], x[j] - x[p])
    }
    return { id, off, x, y, k: smoothRing(k, 6), head, seg }
  }
}
