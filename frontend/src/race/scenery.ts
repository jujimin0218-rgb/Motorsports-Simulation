/**
 * What is beside the circuit.
 *
 * A circuit is not a ribbon of asphalt in a void: there are grandstands where
 * people watch, a pit building along the main straight, marshal posts every
 * few hundred metres, run-off with a wall behind it, and everything beyond
 * that. None of it touches the simulation -- the cars cannot hit a grandstand
 * and the trees do not slow anybody down -- but without it a race is a dot
 * moving along a line, and where the cars *are* on the circuit stops being
 * legible at a glance.
 *
 * All of it is generated from the circuit's own geometry and a fixed seed, so
 * a given track looks the same every time it is loaded, and no two tracks look
 * the same as each other.
 */

import { Circuit, clamp, lerp } from './geometry'

export interface Grandstand {
  /** The stand's footprint, as a closed ring in world metres. */
  ring: { x: number; y: number }[]
  /** The front edge, where the seating faces the track. */
  front: { x: number; y: number }[]
  /** Rows of seats, back to front, each a strip along the stand. */
  tiers: { x: number; y: number }[][]
  /** Roof outline, or null for an open stand. */
  roof: { x: number; y: number }[] | null
  name: string
  seed: number
}

export interface Building {
  ring: { x: number; y: number }[]
  height: number
  kind: 'garage' | 'tower' | 'block'
}

export interface Tree {
  x: number
  y: number
  r: number
  tone: number
}

export interface MarshalPost {
  x: number
  y: number
  heading: number
  /** Which side of the road, +1 left. */
  side: number
}

export interface Scenery {
  grandstands: Grandstand[]
  buildings: Building[]
  trees: Tree[]
  marshals: MarshalPost[]
  /** Start/finish line, as a stripe across the road. */
  startLine: { a: { x: number; y: number }; b: { x: number; y: number } }
  /** Braking markers at 100/50 m before each corner. */
  boards: { x: number; y: number; heading: number; label: string }[]
}

function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Build everything beside the road.
 *
 * `pit` is where the pit lane runs, so the grandstands know not to stand in
 * it and the pit building knows where to be.
 */
export function buildScenery(
  circuit: Circuit,
  pit: { side: number; entryS: number; exitS: number; offsets: Float64Array | null },
): Scenery {
  const r = rng(0x5eed ^ Math.round(circuit.length))
  const grandstands: Grandstand[] = []
  const buildings: Building[] = []
  const trees: Tree[] = []
  const marshals: MarshalPost[] = []
  const boards: Scenery['boards'] = []

  /** Where a point at (distance, offset) is. */
  const at = (s: number, off: number) => circuit.place(s, off)

  const pitSpan = (s: number) => {
    const from = pit.entryS
    const len = ((pit.exitS - from + circuit.length) % circuit.length) || circuit.length
    return ((s - from + circuit.length) % circuit.length) < len
  }

  // -- the pit building ------------------------------------------------------
  // A long shed of garages behind the pit lane, one bay per car, with the
  // paddock buildings behind it.
  if (pit.offsets) {
    const from = pit.entryS
    const len = ((pit.exitS - from + circuit.length) % circuit.length) || circuit.length
    const bays = 20
    const inset = 0.14
    for (let b = 0; b < bays; b++) {
      const s0 = from + len * (inset + ((1 - inset * 2) * b) / bays)
      const s1 = from + len * (inset + ((1 - inset * 2) * (b + 0.86)) / bays)
      const i0 = circuit.idxAt(s0)
      const near = pit.offsets[i0] + pit.side * 7
      const far = pit.offsets[i0] + pit.side * 20
      buildings.push({
        ring: [at(s0, near), at(s1, near), at(s1, far), at(s0, far)],
        height: 7,
        kind: 'garage',
      })
    }
    // The paddock behind, and a control tower over the start line.
    for (let q = 0; q < 6; q++) {
      const s0 = from + len * (0.12 + q * 0.13)
      const s1 = s0 + len * 0.1
      const i0 = circuit.idxAt(s0)
      const near = pit.offsets[i0] + pit.side * (24 + r() * 5)
      const far = near + pit.side * (18 + r() * 22)
      buildings.push({
        ring: [at(s0, near), at(s1, near), at(s1, far), at(s0, far)],
        height: 10 + r() * 14,
        kind: 'block',
      })
    }
    const towerS = from + len * 0.42
    const ti = circuit.idxAt(towerS)
    const tNear = pit.offsets[ti] + pit.side * 8
    buildings.push({
      ring: [
        at(towerS - 16, tNear),
        at(towerS + 16, tNear),
        at(towerS + 16, tNear + pit.side * 14),
        at(towerS - 16, tNear + pit.side * 14),
      ],
      height: 26,
      kind: 'tower',
    })
  }

  // -- grandstands -----------------------------------------------------------
  // Where people would actually sit: opposite the pits, and on the outside of
  // the corners with the best view of a braking zone.
  const stands: { s: number; side: number; len: number; name: string }[] = []
  const mainS = (pit.entryS + ((pit.exitS - pit.entryS + circuit.length) % circuit.length) * 0.45) %
    circuit.length
  stands.push({ s: mainS - 130, side: -pit.side, len: 300, name: 'Main Grandstand' })

  const byBraking = [...circuit.corners]
    .filter((c) => c.entryStraight > 180 && c.radius < 160)
    .sort((a, b) => b.entryStraight - a.entryStraight)
    .slice(0, 4)
  for (const cn of byBraking) {
    // Outside of the corner is the far side from the way it bends.
    stands.push({
      s: cn.sIn - 60,
      side: -cn.dir,
      len: clamp(cn.length + 80, 110, 240),
      name: `${cn.name} Grandstand`,
    })
  }

  for (const spec of stands) {
    const s0 = ((spec.s % circuit.length) + circuit.length) % circuit.length
    if (spec.name !== 'Main Grandstand' && pitSpan(s0)) continue
    const steps = Math.max(6, Math.round(spec.len / 12))
    const front: { x: number; y: number }[] = []
    const back: { x: number; y: number }[] = []
    const tierCount = 9 + Math.floor(r() * 5)
    const tiers: { x: number; y: number }[][] = Array.from({ length: tierCount }, () => [])
    const depth = 20 + r() * 14
    for (let q = 0; q <= steps; q++) {
      const s = s0 + (spec.len * q) / steps
      const i = circuit.idxAt(s)
      const gap = circuit.halfWidth[i] + 13
      front.push(at(s, spec.side * gap))
      back.push(at(s, spec.side * (gap + depth)))
      for (let t = 0; t < tierCount; t++) {
        tiers[t].push(at(s, spec.side * (gap + (depth * (t + 0.5)) / tierCount)))
      }
    }
    grandstands.push({
      ring: [...front, ...[...back].reverse()],
      front,
      tiers,
      roof: r() < 0.6 ? [...back, ...[...front].reverse()] : null,
      name: spec.name,
      seed: Math.floor(r() * 1e6),
    })
  }

  // -- marshal posts ---------------------------------------------------------
  for (let s = 30; s < circuit.length; s += 240) {
    const i = circuit.idxAt(s)
    const side = circuit.cornerAt[i] >= 0 ? -Math.sign(circuit.k[i] || 1) : 1
    const off = side * (circuit.halfWidth[i] + 9)
    const p = at(s, off)
    marshals.push({ x: p.x, y: p.y, heading: circuit.head[i], side })
  }

  // -- braking boards --------------------------------------------------------
  for (const cn of circuit.corners) {
    if (cn.entryStraight < 120) continue
    for (const back of [150, 100, 50]) {
      const s = ((cn.sIn - back) % circuit.length + circuit.length) % circuit.length
      const i = circuit.idxAt(s)
      const side = -cn.dir
      const p = at(s, side * (circuit.halfWidth[i] + 5))
      boards.push({ x: p.x, y: p.y, heading: circuit.head[i], label: String(back) })
    }
  }

  // -- trees and the rest of the world --------------------------------------
  const occupied = (x: number, y: number) => {
    const near = circuit.locate(x, y, 0)
    return Math.abs(near.lat) < circuit.halfWidth[near.i] + 34
  }
  for (let q = 0; q < 900; q++) {
    const s = r() * circuit.length
    const i = circuit.idxAt(s)
    const side = r() < 0.5 ? 1 : -1
    const off = side * (circuit.halfWidth[i] + 38 + r() * 120)
    const p = at(s, off)
    if (occupied(p.x, p.y)) continue
    trees.push({ x: p.x, y: p.y, r: 2.5 + r() * 4.5, tone: r() })
  }
  for (let q = 0; q < 22; q++) {
    const s = r() * circuit.length
    if (pitSpan(s)) continue
    const i = circuit.idxAt(s)
    const side = r() < 0.5 ? 1 : -1
    const off = side * (circuit.halfWidth[i] + 70 + r() * 90)
    const w = 14 + r() * 30
    const d = 12 + r() * 24
    const p0 = at(s, off)
    if (occupied(p0.x, p0.y)) continue
    const p1 = at(s + w, off)
    const p2 = at(s + w, off + side * d)
    const p3 = at(s, off + side * d)
    buildings.push({ ring: [p0, p1, p2, p3], height: 6 + r() * 12, kind: 'block' })
  }

  const line0 = at(0, -circuit.halfWidth[0])
  const line1 = at(0, circuit.halfWidth[0])

  return {
    grandstands,
    buildings,
    trees,
    marshals,
    boards,
    startLine: { a: line0, b: line1 },
  }
}

/** A crowd, as a stable field of dots that twinkle rather than move. */
export function crowdSeed(stand: Grandstand, tier: number, index: number): number {
  return (stand.seed ^ (tier * 2654435761) ^ (index * 40503)) >>> 0
}

export { lerp }
