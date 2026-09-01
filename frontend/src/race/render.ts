/**
 * Drawing the race.
 *
 * Everything here is a consequence of the simulation and never a cause of it:
 * the renderer reads car positions, headings, control inputs and the effects
 * the race spawned, and paints them. It cannot move a car.
 *
 * Two things it does own. The **camera**, which is what makes a race legible --
 * a whole circuit from above tells you the order, and a camera bolted to one
 * car tells you what that driver is dealing with, and they are different
 * questions. And the **static geometry**, which is built into `Path2D`s once
 * per circuit: at sixty frames a second with twenty cars, rebuilding a few
 * thousand-point polygon every frame is the difference between a race that
 * runs and one that stutters.
 */

import { Circuit, TAU, clamp, lerp, wrapAngle } from './geometry'
import { CAR_LENGTH, CAR_WIDTH, Race, RaceCar } from './race'
import { Scenery, buildScenery } from './scenery'
import { speedOf } from './physics'

export type CameraMode = 'tv' | 'chase' | 'onboard'

export interface Camera {
  mode: CameraMode
  /** Car being followed, or null for the whole circuit. */
  follow: number | null
  /** Metres across the shorter screen axis. Smaller is closer in. */
  span: number
  /** Smoothed state, updated per frame. */
  x: number
  y: number
  rotation: number
  zoomSpan: number
}

const PALETTE = {
  grass: '#1b2a1d',
  grassAlt: '#203121',
  gravel: '#4a3f2c',
  runoff: '#2b313a',
  kerbA: '#b8353c',
  kerbB: '#e8e8ea',
  track: '#242830',
  trackEdge: '#e6e8ec',
  pit: '#2c3038',
  wall: '#585f6b',
  wallTop: '#7b838f',
  garage: '#2a2f3a',
  garageRoof: '#333a47',
  stand: '#3a4150',
  standRoof: '#4b5468',
  tree: '#22361f',
  treeAlt: '#2c4426',
  marshal: '#d8dce4',
  board: '#f0f2f6',
  line: 'rgba(255,255,255,0.18)',
}

/** Draw a closed ring of world points. */
function ring(ctx: CanvasRenderingContext2D, pts: { x: number; y: number }[]): void {
  if (pts.length < 3) return
  ctx.moveTo(pts[0].x, pts[0].y)
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
  ctx.closePath()
}

/** A band between two lateral offsets, as a closed ring round the whole lap. */
function band(
  circuit: Circuit,
  inner: (i: number) => number,
  outer: (i: number) => number,
  step = 2,
): Path2D {
  const path = new Path2D()
  const n = circuit.n
  let started = false
  for (let i = 0; i < n; i += step) {
    const o = inner(i)
    const x = circuit.x[i] + circuit.nx[i] * o
    const y = circuit.y[i] + circuit.ny[i] * o
    if (!started) { path.moveTo(x, y); started = true } else path.lineTo(x, y)
  }
  for (let i = n - 1; i >= 0; i -= step) {
    const o = outer(i)
    path.lineTo(circuit.x[i] + circuit.nx[i] * o, circuit.y[i] + circuit.ny[i] * o)
  }
  path.closePath()
  return path
}

/** A stroked line down the middle of a lateral-offset profile. */
function trace(circuit: Circuit, off: (i: number) => number, step = 2): Path2D {
  const path = new Path2D()
  for (let i = 0; i <= circuit.n; i += step) {
    const j = i % circuit.n
    const o = off(j)
    const x = circuit.x[j] + circuit.nx[j] * o
    const y = circuit.y[j] + circuit.ny[j] * o
    if (i === 0) path.moveTo(x, y)
    else path.lineTo(x, y)
  }
  path.closePath()
  return path
}

interface Static {
  grass: Path2D
  gravel: Path2D[]
  runoff: Path2D[]
  track: Path2D
  kerbs: { path: Path2D; alt: boolean }[]
  edges: Path2D
  pit: Path2D | null
  pitEdge: Path2D | null
  walls: Path2D[]
  bounds: { minx: number; miny: number; maxx: number; maxy: number }
}

export class Renderer {
  private race: Race
  private circuit: Circuit
  private scenery: Scenery
  private statics: Static
  /** Rubber laid down where cars have locked up or slid, drawn under them. */
  private marks: { x: number; y: number; h: number; w: number; age: number }[] = []
  camera: Camera = { mode: 'tv', follow: null, span: 900, x: 0, y: 0, rotation: 0, zoomSpan: 900 }
  /** Banner currently on screen, and how long it has left. */
  private banner: { text: string; kind: string; life: number } | null = null
  private lastEvent = 0

  constructor(race: Race) {
    this.race = race
    this.circuit = race.circuit
    const pit = race.pitGeometry()
    this.scenery = buildScenery(this.circuit, {
      side: pit.side,
      entryS: pit.entryS,
      exitS: pit.exitS,
      offsets: pit.line ? pit.line.off : null,
    })
    this.statics = this.buildStatics()
    const b = this.statics.bounds
    this.camera.x = (b.minx + b.maxx) / 2
    this.camera.y = (b.miny + b.maxy) / 2
    this.camera.span = Math.max(b.maxx - b.minx, b.maxy - b.miny) * 1.05
    this.camera.zoomSpan = this.camera.span
  }

  /** Build every piece of circuit geometry that never changes. */
  private buildStatics(): Static {
    const c = this.circuit
    const prof = this.race.surfaceProfile()
    const half = (i: number) => c.halfWidth[i]
    const kerbOut = (i: number) => half(i) + prof.kerb[i]
    const wallAt = (i: number) => kerbOut(i) + prof.runoff[i]
    const gravelIn = (i: number) => kerbOut(i) + prof.runoff[i] * prof.gravelFrom[i]

    const grass = new Path2D()
    const outer = band(c, (i) => -(wallAt(i) + 260), (i) => wallAt(i) + 260, 3)
    grass.addPath(outer)

    const gravel: Path2D[] = []
    const runoff: Path2D[] = []
    for (const side of [1, -1]) {
      runoff.push(band(c, (i) => side * kerbOut(i), (i) => side * gravelIn(i), 2))
      gravel.push(band(c, (i) => side * gravelIn(i), (i) => side * wallAt(i), 2))
    }

    const track = band(c, (i) => -half(i), (i) => half(i), 2)

    // Kerbs, in alternating red and white blocks a couple of metres long, and
    // only where there is a kerb at all -- which is at the corners.
    const kerbs: { path: Path2D; alt: boolean }[] = []
    const blockLen = Math.max(2, Math.round(2.6 / c.ds))
    for (const side of [1, -1]) {
      let i = 0
      let alt = false
      while (i < c.n) {
        if (prof.kerb[i] <= 0) { i++; continue }
        const from = i
        let to = i
        while (to + 1 < c.n && prof.kerb[to + 1] > 0 && to - from < blockLen) to++
        const path = new Path2D()
        for (let q = from; q <= to; q++) {
          const o = side * half(q)
          const x = c.x[q] + c.nx[q] * o
          const y = c.y[q] + c.ny[q] * o
          if (q === from) path.moveTo(x, y)
          else path.lineTo(x, y)
        }
        for (let q = to; q >= from; q--) {
          const o = side * kerbOut(q)
          path.lineTo(c.x[q] + c.nx[q] * o, c.y[q] + c.ny[q] * o)
        }
        path.closePath()
        kerbs.push({ path, alt })
        alt = !alt
        i = to + 1
      }
    }

    const edges = new Path2D()
    edges.addPath(trace(c, (i) => -half(i) + 0.12, 2))
    edges.addPath(trace(c, (i) => half(i) - 0.12, 2))

    const walls: Path2D[] = []
    for (const side of [1, -1]) {
      walls.push(band(c, (i) => side * wallAt(i), (i) => side * (wallAt(i) + 1.1), 2))
    }

    const pitGeo = this.race.pitGeometry()
    let pit: Path2D | null = null
    let pitEdge: Path2D | null = null
    if (pitGeo.line) {
      const off = pitGeo.line.off
      const from = c.idxAt(pitGeo.entryS)
      const span = ((c.idxAt(pitGeo.exitS) - from + c.n) % c.n) || c.n
      const p = new Path2D()
      const e = new Path2D()
      for (let q = 0; q <= span; q += 2) {
        const i = c.wrap(from + q)
        const o = off[i] + pitGeo.side * 5.5
        const x = c.x[i] + c.nx[i] * o
        const y = c.y[i] + c.ny[i] * o
        if (q === 0) { p.moveTo(x, y); e.moveTo(x, y) } else { p.lineTo(x, y); e.lineTo(x, y) }
      }
      for (let q = span; q >= 0; q -= 2) {
        const i = c.wrap(from + q)
        const o = off[i] - pitGeo.side * 5.5
        p.lineTo(c.x[i] + c.nx[i] * o, c.y[i] + c.ny[i] * o)
      }
      p.closePath()
      pit = p
      pitEdge = e
    }

    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity
    for (let i = 0; i < c.n; i++) {
      const reach = wallAt(i) + 16
      minx = Math.min(minx, c.x[i] - reach)
      maxx = Math.max(maxx, c.x[i] + reach)
      miny = Math.min(miny, c.y[i] - reach)
      maxy = Math.max(maxy, c.y[i] + reach)
    }
    return { grass, gravel, runoff, track, kerbs, edges, pit, pitEdge, walls, bounds: { minx, miny, maxx, maxy } }
  }

  /** Fit the whole circuit in view. */
  resetCamera(): void {
    const b = this.statics.bounds
    this.camera.follow = null
    this.camera.mode = 'tv'
    this.camera.span = Math.max(b.maxx - b.minx, b.maxy - b.miny) * 1.05
    this.camera.x = (b.minx + b.maxx) / 2
    this.camera.y = (b.miny + b.maxy) / 2
    this.camera.rotation = 0
  }

  /** Point the camera at a car, in whichever mode is set. */
  watch(car: number | null, mode: CameraMode = 'chase'): void {
    this.camera.follow = car
    this.camera.mode = car === null ? 'tv' : mode
    if (car === null) this.resetCamera()
    else this.camera.span = mode === 'onboard' ? 60 : 150
  }

  private followed(): RaceCar | null {
    if (this.camera.follow === null) return null
    return this.race.cars.find((c) => c.number === this.camera.follow) ?? null
  }

  /** Move the camera toward where it should be. Called once per frame. */
  update(dt: number): void {
    const cam = this.camera
    const car = this.followed()
    let wantX = cam.x
    let wantY = cam.y
    let wantRot = cam.rotation
    if (car) {
      const v = speedOf(car.state)
      if (cam.mode === 'onboard') {
        // Just behind the roll hoop, looking where the car is pointing. Lead
        // the camera with speed so the driver sees far enough ahead to matter.
        const lead = 6 + v * 0.34
        wantX = car.state.x + Math.cos(car.state.yaw) * lead
        wantY = car.state.y + Math.sin(car.state.yaw) * lead
        wantRot = -car.state.yaw - Math.PI / 2
        cam.span = 46 + v * 0.62
      } else {
        wantX = car.state.x + Math.cos(car.state.yaw) * (v * 0.5)
        wantY = car.state.y + Math.sin(car.state.yaw) * (v * 0.5)
        wantRot = -car.state.yaw - Math.PI / 2
        cam.span = 108 + v * 1.05
      }
    }
    // A camera that snaps is unwatchable and one that lags is worse; this is
    // fast enough to keep the car centred and slow enough not to jitter.
    const k = 1 - Math.exp(-dt * (cam.mode === 'onboard' ? 14 : 7))
    cam.x = lerp(cam.x, wantX, k)
    cam.y = lerp(cam.y, wantY, k)
    cam.rotation += wrapAngle(wantRot - cam.rotation) * (1 - Math.exp(-dt * 6))
    cam.zoomSpan = lerp(cam.zoomSpan, cam.span, 1 - Math.exp(-dt * 4))

    // Rubber on the road: laid where a car is sliding or locked, and it fades.
    for (const c of this.race.cars) {
      if (c.status === 'retired') continue
      const r = c.report
      if (!r) continue
      const sliding = Math.abs(r.slip) > 0.13 || r.locked || r.spinning
      if (sliding && r.speed > 8 && this.marks.length < 1400) {
        this.marks.push({ x: c.state.x, y: c.state.y, h: c.state.yaw, w: CAR_WIDTH, age: 0 })
      }
    }
    for (let i = this.marks.length - 1; i >= 0; i--) {
      this.marks[i].age += dt
      if (this.marks[i].age > 26) this.marks.splice(i, 1)
    }

    // The newest event worth putting on screen.
    const events = this.race.events
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e.id <= this.lastEvent) break
      if ((e.weight ?? 0) < 0.4) continue
      this.lastEvent = e.id
      this.banner = { text: e.text, kind: e.kind, life: 3.4 }
      break
    }
    if (events.length) this.lastEvent = Math.max(this.lastEvent, events[events.length - 1].id)
    if (this.banner) {
      this.banner.life -= dt
      if (this.banner.life <= 0) this.banner = null
    }
  }

  /** Paint one frame. */
  draw(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    const cam = this.camera
    const scale = Math.min(width, height) / cam.zoomSpan
    ctx.save()
    ctx.fillStyle = '#141a16'
    ctx.fillRect(0, 0, width, height)
    ctx.translate(width / 2, height / 2)
    ctx.rotate(cam.rotation)
    ctx.scale(scale, -scale)
    ctx.translate(-cam.x, -cam.y)
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    const detail = scale > 0.55

    this.drawGround(ctx, scale)
    if (detail) this.drawFarScenery(ctx, scale)
    this.drawSurfaces(ctx, scale)
    this.drawMarkings(ctx, scale, detail)
    this.drawPit(ctx, scale, detail)
    if (detail) this.drawNearScenery(ctx, scale)
    this.drawWalls(ctx)
    this.drawMarks(ctx)
    this.drawEffects(ctx, false)
    this.drawCars(ctx, scale, detail)
    this.drawEffects(ctx, true)
    ctx.restore()

    this.drawLabels(ctx, width, height)
    this.drawOverlay(ctx, width, height)
  }

  private drawGround(ctx: CanvasRenderingContext2D, scale: number): void {
    const b = this.statics.bounds
    ctx.fillStyle = PALETTE.grass
    ctx.fillRect(b.minx - 400, b.miny - 400, b.maxx - b.minx + 800, b.maxy - b.miny + 800)
    if (scale > 0.3) {
      // A faint mown pattern, so the ground reads as ground rather than as a
      // flat colour when the camera is low.
      ctx.save()
      ctx.fillStyle = PALETTE.grassAlt
      const step = 34
      for (let x = b.minx - 400; x < b.maxx + 400; x += step * 2) {
        ctx.fillRect(x, b.miny - 400, step, b.maxy - b.miny + 800)
      }
      ctx.restore()
    }
  }

  private drawSurfaces(ctx: CanvasRenderingContext2D, scale: number): void {
    const s = this.statics
    ctx.fillStyle = PALETTE.gravel
    for (const p of s.gravel) ctx.fill(p, 'evenodd')
    ctx.fillStyle = PALETTE.runoff
    for (const p of s.runoff) ctx.fill(p, 'evenodd')
    for (const k of s.kerbs) {
      ctx.fillStyle = k.alt ? PALETTE.kerbA : PALETTE.kerbB
      ctx.fill(k.path)
    }
    ctx.fillStyle = PALETTE.track
    ctx.fill(s.track, 'evenodd')
    ctx.strokeStyle = PALETTE.trackEdge
    ctx.lineWidth = Math.max(0.12, 0.9 / Math.max(scale, 0.05))
    ctx.globalAlpha = 0.75
    ctx.stroke(s.edges)
    ctx.globalAlpha = 1
  }

  private drawMarkings(ctx: CanvasRenderingContext2D, scale: number, detail: boolean): void {
    const c = this.circuit
    // Start/finish: a chequered band across the road.
    const line = this.scenery.startLine
    const dx = line.b.x - line.a.x
    const dy = line.b.y - line.a.y
    const len = Math.hypot(dx, dy)
    const ux = dx / len
    const uy = dy / len
    const px = -uy
    const py = ux
    const cells = 14
    for (let q = 0; q < cells; q++) {
      for (let r = 0; r < 2; r++) {
        ctx.fillStyle = (q + r) % 2 ? '#f2f4f8' : '#181c22'
        const x0 = line.a.x + ux * (len * q) / cells + px * (r * 1.1 - 1.1)
        const y0 = line.a.y + uy * (len * q) / cells + py * (r * 1.1 - 1.1)
        ctx.beginPath()
        ctx.moveTo(x0, y0)
        ctx.lineTo(x0 + (ux * len) / cells, y0 + (uy * len) / cells)
        ctx.lineTo(x0 + (ux * len) / cells + px * 1.1, y0 + (uy * len) / cells + py * 1.1)
        ctx.lineTo(x0 + px * 1.1, y0 + py * 1.1)
        ctx.closePath()
        ctx.fill()
      }
    }
    if (!detail) return
    // DRS zones, as a dashed stripe near the inside edge.
    ctx.save()
    ctx.strokeStyle = 'rgba(90,190,255,0.5)'
    ctx.lineWidth = Math.max(0.2, 0.5 / Math.max(scale, 0.05))
    ctx.setLineDash([6, 8])
    for (const z of this.race.drsGeometry()) {
      const from = c.idxAt(z.start)
      const span = ((c.idxAt(z.end) - from + c.n) % c.n)
      ctx.beginPath()
      for (let q = 0; q <= span; q += 2) {
        const i = c.wrap(from + q)
        const o = c.halfWidth[i] - 0.9
        const x = c.x[i] + c.nx[i] * o
        const y = c.y[i] + c.ny[i] * o
        if (q === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
    }
    ctx.restore()
  }

  private drawPit(ctx: CanvasRenderingContext2D, scale: number, detail: boolean): void {
    const s = this.statics
    if (!s.pit) return
    ctx.fillStyle = PALETTE.pit
    ctx.fill(s.pit)
    if (s.pitEdge) {
      ctx.strokeStyle = 'rgba(255,255,255,0.35)'
      ctx.lineWidth = Math.max(0.1, 0.5 / Math.max(scale, 0.05))
      ctx.stroke(s.pitEdge)
    }
    if (!detail) return
    // The boxes, and a number for each.
    const geo = this.race.pitGeometry()
    ctx.save()
    for (let b = 0; b < geo.boxes.length; b++) {
      const box = geo.boxes[b]
      ctx.save()
      ctx.translate(box.x, box.y)
      ctx.rotate(box.h)
      ctx.fillStyle = 'rgba(255,255,255,0.10)'
      ctx.fillRect(-3.4, -1.9, 6.8, 3.8)
      ctx.strokeStyle = 'rgba(255,255,255,0.30)'
      ctx.lineWidth = 0.18
      ctx.strokeRect(-3.4, -1.9, 6.8, 3.8)
      ctx.restore()
    }
    ctx.restore()
  }

  private drawFarScenery(ctx: CanvasRenderingContext2D, scale: number): void {
    for (const t of this.scenery.trees) {
      ctx.fillStyle = t.tone > 0.5 ? PALETTE.tree : PALETTE.treeAlt
      ctx.beginPath()
      ctx.arc(t.x, t.y, t.r, 0, TAU)
      ctx.fill()
    }
    for (const b of this.scenery.buildings) {
      if (b.kind === 'garage') continue
      ctx.fillStyle = b.kind === 'tower' ? '#39414f' : '#2c323c'
      ctx.beginPath()
      ring(ctx, b.ring)
      ctx.fill()
      ctx.strokeStyle = 'rgba(0,0,0,0.35)'
      ctx.lineWidth = 0.4
      ctx.stroke()
    }
    void scale
  }

  private drawNearScenery(ctx: CanvasRenderingContext2D, scale: number): void {
    // Garages along the pit lane.
    for (const b of this.scenery.buildings) {
      if (b.kind !== 'garage') continue
      ctx.fillStyle = PALETTE.garage
      ctx.beginPath()
      ring(ctx, b.ring)
      ctx.fill()
      ctx.strokeStyle = PALETTE.garageRoof
      ctx.lineWidth = 0.5
      ctx.stroke()
    }

    // Grandstands, with a crowd in them.
    for (const stand of this.scenery.grandstands) {
      ctx.fillStyle = PALETTE.stand
      ctx.beginPath()
      ring(ctx, stand.ring)
      ctx.fill()
      if (stand.roof) {
        ctx.fillStyle = PALETTE.standRoof
        ctx.beginPath()
        ring(ctx, stand.roof.slice(0, Math.max(2, Math.floor(stand.roof.length / 2))))
        ctx.closePath()
        ctx.fill()
      }
      if (scale > 1.1) {
        // Close enough to see people. A stable pattern that shimmers, rather
        // than dots that jump about: a crowd moves, it does not teleport.
        const t = this.race.time
        for (let tier = 0; tier < stand.tiers.length; tier += 1) {
          const row = stand.tiers[tier]
          for (let q = 0; q < row.length; q++) {
            const seed = (stand.seed ^ (tier * 9176) ^ (q * 40503)) >>> 0
            const hue = (seed % 360)
            const flick = 0.55 + 0.45 * Math.sin(t * 2 + (seed % 100))
            ctx.fillStyle = `hsla(${hue}, 45%, ${52 + flick * 12}%, 0.85)`
            ctx.beginPath()
            ctx.arc(row[q].x, row[q].y, 0.55, 0, TAU)
            ctx.fill()
          }
        }
      }
      ctx.strokeStyle = 'rgba(255,255,255,0.18)'
      ctx.lineWidth = 0.4
      ctx.beginPath()
      ring(ctx, stand.front)
      ctx.stroke()
    }

    // Marshal posts and braking boards.
    for (const m of this.scenery.marshals) {
      ctx.save()
      ctx.translate(m.x, m.y)
      ctx.rotate(m.heading)
      ctx.fillStyle = PALETTE.marshal
      ctx.fillRect(-1.4, -0.7, 2.8, 1.4)
      ctx.fillStyle = this.race.cautionAt >= 0 ? '#f5d13b' : '#7f8794'
      ctx.fillRect(-0.5, -0.45, 1, 0.9)
      ctx.restore()
    }
    if (scale > 1.4) {
      for (const b of this.scenery.boards) {
        ctx.save()
        ctx.translate(b.x, b.y)
        ctx.rotate(b.heading)
        ctx.fillStyle = PALETTE.board
        ctx.fillRect(-1.2, -0.9, 2.4, 1.8)
        ctx.restore()
      }
    }
  }

  private drawWalls(ctx: CanvasRenderingContext2D): void {
    ctx.fillStyle = PALETTE.wall
    for (const w of this.statics.walls) ctx.fill(w, 'evenodd')
  }

  private drawMarks(ctx: CanvasRenderingContext2D): void {
    ctx.save()
    for (const m of this.marks) {
      const a = clamp(1 - m.age / 26, 0, 1) * 0.35
      ctx.globalAlpha = a
      ctx.fillStyle = '#0d0f12'
      ctx.save()
      ctx.translate(m.x, m.y)
      ctx.rotate(m.h)
      ctx.fillRect(-1.6, -m.w / 2, 3.2, 0.45)
      ctx.fillRect(-1.6, m.w / 2 - 0.45, 3.2, 0.45)
      ctx.restore()
    }
    ctx.restore()
  }

  private drawEffects(ctx: CanvasRenderingContext2D, above: boolean): void {
    ctx.save()
    for (const e of this.race.effects) {
      const high = e.kind === 'spark' || e.kind === 'flash'
      if (high !== above) continue
      const life = clamp(1 - e.age / e.life, 0, 1)
      switch (e.kind) {
        case 'smoke':
          ctx.globalAlpha = life * 0.5
          ctx.fillStyle = '#d8dbe0'
          ctx.beginPath()
          ctx.arc(e.x, e.y, e.size * (1 + (1 - life) * 2.5), 0, TAU)
          ctx.fill()
          break
        case 'dust':
          ctx.globalAlpha = life * 0.45
          ctx.fillStyle = '#8b7a5c'
          ctx.beginPath()
          ctx.arc(e.x, e.y, e.size * (1 + (1 - life) * 2), 0, TAU)
          ctx.fill()
          break
        case 'gravel':
          ctx.globalAlpha = life
          ctx.fillStyle = '#6b5c3e'
          ctx.beginPath()
          ctx.arc(e.x, e.y, e.size, 0, TAU)
          ctx.fill()
          break
        case 'debris':
          ctx.globalAlpha = life
          ctx.fillStyle = '#c9ccd2'
          ctx.fillRect(e.x - e.size / 2, e.y - e.size / 2, e.size, e.size)
          break
        case 'spark':
          ctx.globalAlpha = life
          ctx.fillStyle = e.colour ?? '#ffcf6b'
          ctx.beginPath()
          ctx.arc(e.x, e.y, e.size * life, 0, TAU)
          ctx.fill()
          break
        case 'flash':
          ctx.globalAlpha = life * 0.8
          ctx.fillStyle = e.colour ?? '#fff'
          ctx.beginPath()
          ctx.arc(e.x, e.y, e.size * (1 + (1 - life) * 6), 0, TAU)
          ctx.fill()
          break
      }
    }
    ctx.restore()
  }

  private drawCars(ctx: CanvasRenderingContext2D, scale: number, detail: boolean): void {
    for (const car of this.race.cars) {
      if (car.status === 'grid' && !this.race.started) {
        // still on the grid, but drawn -- the grid is part of the picture
      }
      const st = car.state
      const shake = car.shake > 0 ? (Math.random() - 0.5) * car.shake * 0.5 : 0
      ctx.save()
      ctx.translate(st.x + shake, st.y + shake)
      ctx.rotate(st.yaw)

      const retired = car.status === 'retired'
      ctx.globalAlpha = retired ? 0.45 : 1

      // Shadow, offset by the body's roll so the car looks like it is leaning.
      ctx.fillStyle = 'rgba(0,0,0,0.45)'
      ctx.fillRect(-CAR_LENGTH / 2 + 0.2, -CAR_WIDTH / 2 + 0.2 + car.bodyRoll * 1.2, CAR_LENGTH, CAR_WIDTH)

      // Wheels. The fronts turn, and all four are drawn because a car whose
      // wheels are straight while it is cornering does not read as a car.
      ctx.fillStyle = '#101317'
      const wb = CAR_LENGTH * 0.31
      const tw = CAR_WIDTH * 0.52
      for (const [ax, front] of [[wb, true], [-wb, false]] as const) {
        for (const sy of [1, -1]) {
          ctx.save()
          ctx.translate(ax, sy * tw)
          if (front) ctx.rotate(car.wheelAngle)
          ctx.fillRect(-0.62, -0.32, 1.24, 0.64)
          ctx.restore()
        }
      }

      // Body: a nose, a tub and a rear, in the team's colour.
      const colour = car.entry.colour || '#9aa3b2'
      ctx.beginPath()
      ctx.moveTo(CAR_LENGTH / 2, 0)
      ctx.lineTo(CAR_LENGTH * 0.18, CAR_WIDTH * 0.3)
      ctx.lineTo(-CAR_LENGTH * 0.2, CAR_WIDTH * 0.38)
      ctx.lineTo(-CAR_LENGTH / 2, CAR_WIDTH * 0.34)
      ctx.lineTo(-CAR_LENGTH / 2, -CAR_WIDTH * 0.34)
      ctx.lineTo(-CAR_LENGTH * 0.2, -CAR_WIDTH * 0.38)
      ctx.lineTo(CAR_LENGTH * 0.18, -CAR_WIDTH * 0.3)
      ctx.closePath()
      ctx.fillStyle = colour
      ctx.fill()
      // Damage darkens the car, which is the cheapest honest way to show it.
      if (car.damageSeen > 0.05) {
        ctx.fillStyle = `rgba(20,16,14,${clamp(car.damageSeen * 0.7, 0, 0.7)})`
        ctx.fill()
      }

      // Front and rear wings, and the DRS flap, which is open or it is not.
      ctx.fillStyle = 'rgba(0,0,0,0.55)'
      ctx.fillRect(CAR_LENGTH * 0.42, -CAR_WIDTH * 0.5, 0.35, CAR_WIDTH)
      if (car.drsOpen) {
        ctx.fillStyle = '#5abeff'
        ctx.fillRect(-CAR_LENGTH * 0.5, -CAR_WIDTH * 0.42, 0.5, CAR_WIDTH * 0.84)
      } else {
        ctx.fillRect(-CAR_LENGTH * 0.52, -CAR_WIDTH * 0.44, 0.4, CAR_WIDTH * 0.88)
      }

      // Brake glow, which is what a car under braking actually looks like.
      if (car.controls.brake > 0.25 && !retired) {
        ctx.globalAlpha = clamp(car.controls.brake, 0, 1) * 0.9
        ctx.fillStyle = '#ff4d3d'
        ctx.fillRect(-CAR_LENGTH * 0.5, -CAR_WIDTH * 0.22, 0.3, CAR_WIDTH * 0.44)
        ctx.globalAlpha = retired ? 0.45 : 1
      }
      if (car.flames > 0) {
        ctx.globalAlpha = 0.8
        ctx.fillStyle = '#ffae52'
        ctx.beginPath()
        ctx.arc(-CAR_LENGTH * 0.55, 0, 0.5, 0, TAU)
        ctx.fill()
        ctx.globalAlpha = retired ? 0.45 : 1
      }

      // Halo, so the car has a cockpit at close range.
      if (detail && scale > 2) {
        ctx.strokeStyle = 'rgba(15,18,22,0.85)'
        ctx.lineWidth = 0.16
        ctx.beginPath()
        ctx.arc(CAR_LENGTH * 0.04, 0, CAR_WIDTH * 0.33, 0, TAU)
        ctx.stroke()
      }
      ctx.restore()
    }
  }

  /**
   * Where a world point lands on the screen.
   *
   * The world transform includes a vertical flip (metres go up, pixels go
   * down), and a flip does not commute with a rotation -- so text drawn inside
   * it comes out mirrored however carefully the rotation is undone. Labels are
   * therefore drawn in screen space, from this.
   */
  private toScreen(x: number, y: number, width: number, height: number): { x: number; y: number } {
    const cam = this.camera
    const scale = Math.min(width, height) / cam.zoomSpan
    const dx = (x - cam.x) * scale
    const dy = -(y - cam.y) * scale
    const cos = Math.cos(cam.rotation)
    const sin = Math.sin(cam.rotation)
    return { x: width / 2 + dx * cos - dy * sin, y: height / 2 + dx * sin + dy * cos }
  }

  /**
   * Car names, in screen space.
   *
   * Hidden when the field is far enough away that twenty of them would be one
   * illegible smear -- which, on a grid, is exactly what they were.
   */
  private drawLabels(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    const scale = Math.min(width, height) / this.camera.zoomSpan
    if (scale < 0.75) return
    ctx.save()
    ctx.font = '600 11px ui-sans-serif, system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    const placed: { x: number; y: number }[] = []
    for (const car of this.race.cars) {
      const p = this.toScreen(car.state.x, car.state.y, width, height)
      if (p.x < -60 || p.y < -40 || p.x > width + 60 || p.y > height + 40) continue
      const label = car.entry.abbrev || String(car.number)
      const w = ctx.measureText(label).width + 10
      let y = p.y - Math.max(14, CAR_LENGTH * scale * 0.6 + 10)
      // Nudge a label that would sit on top of one already drawn, so a pack of
      // cars reads as a pack rather than as one word.
      for (let attempt = 0; attempt < 6; attempt++) {
        const clash = placed.some((q) => Math.abs(q.x - p.x) < w * 0.9 && Math.abs(q.y - y) < 15)
        if (!clash) break
        y -= 15
      }
      placed.push({ x: p.x, y })
      const retired = car.status === 'retired'
      ctx.globalAlpha = retired ? 0.4 : 1
      ctx.fillStyle = 'rgba(10,13,17,0.8)'
      ctx.beginPath()
      ctx.roundRect(p.x - w / 2, y - 8, w, 15, 3)
      ctx.fill()
      ctx.fillStyle = car.entry.colour
      ctx.fillRect(p.x - w / 2, y - 8, 2.5, 15)
      ctx.fillStyle = car.entry.isPlayer ? '#ffd166' : '#e8ecf3'
      ctx.fillText(label, p.x + 1, y)
      if (car.inWake > 0.35 && !retired) {
        ctx.fillStyle = 'rgba(120,190,255,0.85)'
        ctx.fillRect(p.x - w / 2, y + 7, w * clamp(car.inWake, 0, 1), 2)
      }
    }
    ctx.restore()
  }

  /** Screen-space furniture: the banner, the flag state, the lights. */
  private drawOverlay(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    const race = this.race
    ctx.save()
    ctx.textBaseline = 'middle'

    // The start lights, counted down before the race.
    if (!race.started) {
      const lit = Math.max(0, Math.min(5, Math.ceil(5 - race.countdown + 1)))
      const r = Math.max(9, Math.min(18, width / 60))
      const gap = r * 2.7
      const x0 = width / 2 - gap * 2
      const y = height * 0.16
      ctx.fillStyle = 'rgba(8,10,14,0.75)'
      ctx.beginPath()
      ctx.roundRect(x0 - r * 2, y - r * 2, gap * 4 + r * 4, r * 4, r)
      ctx.fill()
      for (let i = 0; i < 5; i++) {
        ctx.beginPath()
        ctx.arc(x0 + gap * i, y, r, 0, TAU)
        ctx.fillStyle = i < lit ? '#ff3b30' : 'rgba(255,255,255,0.14)'
        ctx.fill()
      }
      ctx.fillStyle = '#e8ecf3'
      ctx.font = '600 14px ui-sans-serif, system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('Lights out in ' + race.countdown.toFixed(1) + 's', width / 2, y + r * 3)
    }

    // Flags.
    if (race.cautionAt >= 0) {
      ctx.fillStyle = 'rgba(245,209,59,0.16)'
      ctx.fillRect(0, 0, width, height)
      ctx.fillStyle = '#f5d13b'
      ctx.font = '700 13px ui-sans-serif, system-ui, sans-serif'
      ctx.textAlign = 'left'
      ctx.fillText('YELLOW FLAG', 16, 22)
    }
    if (race.finished) {
      ctx.fillStyle = '#e8ecf3'
      ctx.font = '700 13px ui-sans-serif, system-ui, sans-serif'
      ctx.textAlign = 'left'
      ctx.fillText('CHEQUERED FLAG', 16, 22)
    }

    // The banner: the last thing worth telling you about.
    if (this.banner) {
      const b = this.banner
      const t = clamp(b.life / 0.4, 0, 1) * clamp((3.4 - b.life) / 0.25, 0, 1)
      ctx.globalAlpha = t
      const pad = 14
      ctx.font = '600 14px ui-sans-serif, system-ui, sans-serif'
      const w = ctx.measureText(b.text).width + pad * 2
      const x = width / 2 - w / 2
      const y = height - 54
      const accent =
        b.kind === 'overtake' ? '#4ade80'
        : b.kind === 'spin' || b.kind === 'contact' || b.kind === 'wall' ? '#f87171'
        : b.kind === 'fastest-lap' ? '#c084fc'
        : b.kind === 'flag' || b.kind === 'finish' ? '#fbbf24'
        : '#93c5fd'
      ctx.fillStyle = 'rgba(10,13,17,0.86)'
      ctx.beginPath()
      ctx.roundRect(x, y, w, 30, 6)
      ctx.fill()
      ctx.fillStyle = accent
      ctx.fillRect(x, y, 3, 30)
      ctx.fillStyle = '#e8ecf3'
      ctx.textAlign = 'left'
      ctx.fillText(b.text, x + pad, y + 15)
      ctx.globalAlpha = 1
    }
    ctx.restore()
  }

  /** Which car is nearest a screen point, for click-to-follow on the map. */
  pick(sx: number, sy: number, width: number, height: number): number | null {
    const cam = this.camera
    const scale = Math.min(width, height) / cam.zoomSpan
    const dx = sx - width / 2
    const dy = sy - height / 2
    const cos = Math.cos(-cam.rotation)
    const sin = Math.sin(-cam.rotation)
    const rx = dx * cos - dy * sin
    const ry = dx * sin + dy * cos
    const wx = cam.x + rx / scale
    const wy = cam.y - ry / scale
    let best: number | null = null
    let bestD = 14 / scale
    for (const car of this.race.cars) {
      const d = Math.hypot(car.state.x - wx, car.state.y - wy)
      if (d < bestD) { bestD = d; best = car.number }
    }
    return best
  }
}

export { PALETTE }
