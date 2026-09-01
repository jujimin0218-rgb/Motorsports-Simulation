/**
 * The race.
 *
 * There is no result in here.  There is a field of cars, each with its own
 * physics and its own driver, and a loop that advances all of them by a
 * hundredth of a second at a time.  Positions, overtakes, lap times, spins,
 * punctured races and the order at the flag are all read *off* that loop --
 * the process of driving is the simulation, and nothing else is allowed to
 * touch the outcome.
 *
 * What this layer owns is everything that is true of the circuit rather than
 * of one car: what is under each car and therefore how much grip it has, who
 * is in whose wake, where the flap may be opened, who has just run into whom,
 * where the pit lane is and what the flags are.  It hands each driver its view
 * of that, takes back three control inputs, and integrates.
 */

import {
  CAR_LENGTH, CAR_WIDTH, Circuit, WorldPayload, clamp, lerp, smoothstep, wrapDelta,
} from './geometry'
import { LineSet, buildLines } from './lines'
import { SURFACE_GRIP, Surface, TrackSurface } from './surface'
import { COMPOUNDS, Compound, callStrategy } from './strategy'
import { Driver, DriverTraits, Neighbour, RaceView, specFrom } from './ai'
import {
  CarSpec, CarState, Controls, StepReport, speedOf, step as stepCar,
} from './physics'

// -- surfaces ----------------------------------------------------------------
// The road, and what is beside it, come from `TrackSurface`: a continuous
// per-side profile derived from how fast a car arrives at each piece of road,
// rather than a "corner or not" flag with two fixed depths.

/** The pit lane speed limit, m/s. */
const PIT_SPEED = 80 / 3.6
/** How far outside the white line the pit lane runs, m. */
const PIT_LANE_GAP = 9.0
/** How far either side of the lane's centre is still tarmac, m. */
const PIT_LANE_WIDTH = 9.0
/** How far out of the lane a car sits while its crew works on it, m. */
const PIT_BOX_OFFSET = 3.6

/** What fraction of the circuit's own pace each of the flags allows. */
const VSC_PACE = 0.62
const SC_PACE = 0.5
/** And what a red flag allows, m/s: enough to reach the pit lane. */
const RED_PACE = 16

/** How long each state runs for, s, before race control looks again. */
const YELLOW_TIME = 9
const VSC_TIME = 35
const SC_TIME = 70
const RED_TIME = 55

export { CAR_LENGTH, CAR_WIDTH }
export type { Surface }

export type EventKind =
  | 'formation' | 'lights' | 'green' | 'overtake' | 'lockup' | 'spin' | 'off'
  | 'contact' | 'wall' | 'pit-in' | 'pit-stop' | 'pit-out' | 'fastest-lap'
  | 'retire' | 'yellow' | 'vsc' | 'safety-car' | 'red' | 'clear' | 'blue'
  | 'flag' | 'finish' | 'drs'

export interface RaceEvent {
  id: number
  /** Session time, s. */
  t: number
  lap: number
  kind: EventKind
  car: number | null
  other: number | null
  text: string
  /** Where it happened, for the renderer to put a marker on. */
  x?: number
  y?: number
  /** How big a deal it was, 0..1, so the renderer can scale the animation. */
  weight?: number
}

export interface Entry {
  car: number
  driver: string
  abbrev: string
  team: string
  colour: string
  isPlayer?: boolean
  /** Car performance, 0..1. Everything about the car is scaled from this. */
  performance: number
  powerBias?: number
  traits: DriverTraits
  /** Grid slot, 1 is pole. */
  grid: number
}

export type CarStatus = 'grid' | 'racing' | 'pit' | 'finished' | 'retired'

/**
 * What race control is showing.
 *
 * Not decoration. Each of these changes what every driver may do, and the
 * difference between them is what a driver is *allowed* to make up: under a
 * local yellow, nothing at that corner; under a virtual safety car, nothing
 * anywhere, but everyone keeps their gap; behind a safety car, the field
 * closes up and whatever anybody had is gone.
 */
export type FlagState = 'green' | 'yellow' | 'vsc' | 'safety-car' | 'red'

export interface RaceControl {
  state: FlagState
  /** Session time the current state runs until. */
  until: number
  /** Why, for the screen. */
  reason: string
  /** Sample index of the incident, for a local yellow. */
  at: number
  /** How long the field has been bunched behind the safety car, s. */
  bunchedFor: number
}

/** Something the renderer can animate: a puff of smoke, a shower of sparks. */
export interface Effect {
  kind: 'smoke' | 'dust' | 'spark' | 'gravel' | 'debris' | 'flash'
  x: number
  y: number
  vx: number
  vy: number
  life: number
  age: number
  size: number
  colour?: string
}

export class RaceCar {
  entry: Entry
  spec: CarSpec
  state: CarState
  driver: Driver
  status: CarStatus = 'grid'

  /** Where the car is on the road. */
  i = 0
  s = 0
  lat = 0
  lap = 0
  /** Metres covered since the start, which is what an order is built from. */
  covered = 0

  lapStarted = 0
  lastLap = 0
  bestLap = 0
  /** Which sector the car is in, 0..2. */
  sector = 0
  sectorStart = 0
  /** This lap's sector times so far, and the last complete set. */
  sectors: number[] = [0, 0, 0]
  lastSectors: number[] = [0, 0, 0]
  bestSectors: number[] = [0, 0, 0]
  /** Laps this set of tyres has done. */
  tyreAge = 0
  /** What the strategist last decided, for the screen. */
  strategyNote = 'on the opening stint'

  /** Where this car started across the road, and how far round it started. */
  gridOffset = 0
  gridDistance = 0
  /** Distance covered by which a car rejoining from the pits may take the line.
   *  Minus infinity until a car has actually been in the pits -- distance
   *  covered starts *negative* on the grid, so a zero here had the whole field
   *  aiming at the pit-exit blend line on the run to the first corner. */
  blendUntil = -Infinity

  position = 0
  gapToLeader = 0
  interval = 0
  stops = 0
  compound: Compound = 'medium'
  /** The compound the crew has ready for the next stop. */
  nextCompound: Compound = 'medium'

  surface: Surface = 'track'
  drsArmed = false
  drsOpen = false
  inWake = 0
  report: StepReport | null = null
  intent = 'clear'
  lineId = 'racing'
  commitment = 1
  /** What the driver is aiming for on the road just ahead, m/s. */
  targetSpeed = 0
  /** Metres to the next braking point. */
  toBraking = 0
  /** What the plan asked of the brakes, and how much grip the corner is using. */
  brakeDemand = 0
  lateralDemand = 0
  controls: Controls = { steer: 0, throttle: 0, brake: 0, drs: false }

  /** Purely for the picture: the wheels, the body, the flap. */
  wheelAngle = 0
  bodyRoll = 0
  bodyPitch = 0
  /** Seconds of visible drama left: shake after a hit, smoke after a lock-up. */
  shake = 0
  smoking = 0
  flames = 0
  damageSeen = 0

  /** Pit state. */
  wantsPit = false
  pitHold = 0
  pitBox = 0
  pitLap = -1
  penalties = 0
  trackLimits = 0

  offTrackFor = 0
  /** Seconds spent barely moving off the road, which is how a car gets beached. */
  stuckFor = 0
  /** Cooldown so one long scrape along a barrier is one incident. */
  wallFor = 0
  /** Seconds spent stationary, which is how a race ends without a crash. */
  stoppedFor = 0
  /** How long the fronts have been locked, and a cooldown on saying so. */
  lockedFor = 0
  lockNoted = 0
  spinning = false
  finishedAt = 0

  constructor(entry: Entry, spec: CarSpec, state: CarState, driver: Driver) {
    this.entry = entry
    this.spec = spec
    this.state = state
    this.driver = driver
  }

  get number(): number {
    return this.entry.car
  }
}

export interface RaceOptions {
  laps: number
  /** Seed for every random draw in the race -- the same seed replays it. */
  seed: number
  /** Simulated seconds per real second. */
  speed?: number
}

/** A stretch of road where the flap may be opened, and where that is decided. */
interface DrsZone {
  start: number
  end: number
  detect: number
}

export class Race {
  circuit: Circuit
  lines: LineSet
  cars: RaceCar[] = []
  events: RaceEvent[] = []
  effects: Effect[] = []
  laps: number
  time = 0
  /** Counts down from the formation lap to lights out. */
  countdown = 6
  started = false
  finished = false
  leaderLap = 0
  fastestLap: { car: number; time: number; lap: number } | null = null
  /** 0 = green. Rises where there has been an incident. */
  cautionUntil = 0
  cautionAt = -1
  /** What race control is showing, and why. */
  control: RaceControl = { state: 'green', until: 0, reason: '', at: -1, bunchedFor: 0 }
  /** Cars in the pit lane on their way to a box, which is a queue. */
  pitQueue = 0
  /** When cars have gone out lately, for spotting a multi-car accident. */
  private recentRetirements: number[] = []
  private eventId = 1
  /** The road and everything beside it. */
  surfaces: TrackSurface
  private drsZones: DrsZone[] = []
  private pitLine: ReturnType<Circuit['makeLine']> | null = null
  private pitEntryS = 0
  private pitExitS = 0
  private pitLimitS = 0
  private pitSide = -1
  /** The lane as drawn, and a box for every car, for the renderer. */
  pitPoints: { x: number; y: number }[] = []
  pitBoxes: { i: number; s: number; x: number; y: number; h: number }[] = []
  private rng: () => number
  /** Pairs that are already tangled, so one touch is one event. */
  private touching = new Map<string, number>()

  constructor(world: WorldPayload, entries: Entry[], options: RaceOptions) {
    this.circuit = new Circuit(world)
    this.surfaces = new TrackSurface(this.circuit)
    this.lines = buildLines(this.circuit)
    this.laps = options.laps
    let a = options.seed >>> 0
    this.rng = () => {
      a = (a + 0x6d2b79f5) | 0
      let t = Math.imul(a ^ (a >>> 15), 1 | a)
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    this.buildDrs()
    this.grid(entries)
    this.buildPitLane(world)
  }

  // -- setting up ------------------------------------------------------------

  /**
   * Where the flap may be opened.
   *
   * Every straight long enough to matter gets a zone, with the detection point
   * before the corner that leads onto it -- which is what makes DRS a thing a
   * driver has to earn on the previous corner rather than a button.
   */
  private buildDrs(): void {
    for (const cn of this.circuit.corners) {
      if (cn.exitStraight < 240) continue
      this.drsZones.push({
        start: (cn.sOut + 40) % this.circuit.length,
        end: (cn.sOut + cn.exitStraight - 25) % this.circuit.length,
        detect: (cn.sIn - 35 + this.circuit.length) % this.circuit.length,
      })
    }
  }

  /**
   * The pit lane, as a line the cars can actually be driven down.
   *
   * Generated here rather than taken from the server, which draws a lane for
   * the picture and nothing more: the drawn one is a hundred and fifty metres
   * long with its ends several metres *outside* the white line, which is not
   * long enough to hold twenty boxes and not a road a car could rejoin from.
   * Every stop turned into a queue of cars crawling on the racing line and
   * then into each other.
   *
   * So: a lane the length a pit lane is, on the side the drawn one was on,
   * described the same way as every other line -- a lateral offset per sample
   * that starts and ends on the racing line and swings out to the lane in
   * between. A car in the pits is then not in a special mode at all; it is a
   * car following a different line, with a speed limit, and the physics does
   * not know the difference.
   */
  private buildPitLane(world: WorldPayload): void {
    const circuit = this.circuit
    // Which side the pits are on: whatever the server drew, if it drew one.
    let side = -1
    const drawn = world.pit_path ?? []
    if (drawn.length >= 3) {
      const mid = drawn[Math.floor(drawn.length / 2)]
      side = Math.sign(circuit.locate(mid[0], mid[1], 0).lat) || -1
    }
    this.pitSide = side

    // On the main straight, which is the piece of road the start line is on.
    //
    // Not a cosmetic choice. Getting into a pit lane means crossing sixteen
    // metres of road; asked to do that in the middle of a corner, at speed, a
    // car runs out of grip and out of road, and every stop becomes an
    // accident. A real pit entry is on a straight for exactly this reason.
    let straightFrom = circuit.wrap(circuit.idxAt(circuit.length - 260))
    let straightLength = 260
    for (const cn of circuit.corners) {
      if (cn.exitStraight > straightLength) {
        straightLength = cn.exitStraight
        straightFrom = circuit.wrap(cn.to + Math.round(30 / circuit.ds))
      }
    }
    const lane = clamp(straightLength - 140, 320, 900)
    const entryIdx = straightFrom
    const exitIdx = circuit.wrap(entryIdx + Math.round(lane / circuit.ds))
    const span = ((exitIdx - entryIdx + circuit.n) % circuit.n) || circuit.n
    this.pitEntryS = circuit.s[entryIdx]
    this.pitExitS = circuit.s[exitIdx]

    const taperIn = Math.min(Math.round(span * 0.25), Math.round(150 / circuit.ds))
    const taperOut = Math.min(Math.round(span * 0.3), Math.round(190 / circuit.ds))
    const off = Float64Array.from(this.lines.racing.off)
    const points: { x: number; y: number }[] = []
    for (let q = 0; q <= span; q++) {
      const i = circuit.wrap(entryIdx + q)
      const weight = Math.min(
        smoothstep(clamp(q / taperIn, 0, 1)),
        smoothstep(clamp((span - q) / taperOut, 0, 1)),
      )
      const laneOff = side * (circuit.halfWidth[i] + PIT_LANE_GAP)
      off[i] = lerp(this.lines.racing.off[i], laneOff, weight)
      const place = circuit.place(circuit.s[i], off[i])
      points.push({ x: place.x, y: place.y })
    }
    this.pitLine = circuit.makeLine(off, 'pit')
    this.pitPoints = points
    // The limiter comes on once the car is actually in the lane, not the
    // moment it decides to pit. Braking to eighty km/h while still on the
    // racing line takes the two cars behind it along as well.
    this.pitLimitS = circuit.s[circuit.wrap(entryIdx + taperIn)]

    // One box per car, spread along the flat middle of the lane, in grid order
    // -- so the front row is at the near end and nobody has to drive the whole
    // lane to reach their crew.
    const first = taperIn + Math.round(25 / circuit.ds)
    const last = span - taperOut - Math.round(25 / circuit.ds)
    const usable = Math.max(1, last - first)
    const count = Math.max(1, this.cars.length)
    this.pitBoxes = []
    for (let b = 0; b < count; b++) {
      const at = first + Math.round((usable * b) / Math.max(1, count - 1))
      const i = circuit.wrap(entryIdx + at)
      const place = circuit.place(circuit.s[i], off[i] + side * PIT_BOX_OFFSET)
      this.pitBoxes.push({ i, s: circuit.s[i], x: place.x, y: place.y, h: place.h })
    }
  }

  /** Put the field on the grid, staggered the way a real one is. */
  private grid(entries: Entry[]): void {
    const circuit = this.circuit
    const ordered = [...entries].sort((a, b) => a.grid - b.grid)
    ordered.forEach((entry, index) => {
      const spec = specFrom(entry.performance, entry.powerBias ?? 0.5)
      // Rows of two, eight metres apart, on alternate sides of the road.
      // Rows of two, nine metres apart, well separated across the road: a
      // real grid gives a car more than its own width of clear air either side.
      const back = 14 + Math.floor(index / 2) * 9
      const side = (index % 2 === 0 ? 1 : -1) * Math.min(3.8, circuit.limit(0) * 0.78)
      const s = (circuit.length - back) % circuit.length
      const place = circuit.place(s, side)
      const state: CarState = {
        x: place.x, y: place.y, yaw: place.h,
        vx: 0, vy: 0, yawRate: 0,
        fuel: this.laps * 1.7 + 4, tyreWear: 0, tyreTemp: 92, damage: 0,
        tyreGripBonus: COMPOUNDS.medium.grip, tyreWearRate: COMPOUNDS.medium.wear,
        ers: spec.ersStore, deploying: false,
      }
      const driver = new Driver(circuit, this.lines, spec, entry.traits, entry.car, entry.car * 7919 + index)
      const car = new RaceCar(entry, spec, state, driver)
      car.s = s
      car.i = circuit.idxAt(s)
      car.lat = side
      car.covered = s - circuit.length
      car.gridOffset = side
      car.gridDistance = car.covered
      car.position = index + 1
      // A stop is planned before the race and then re-judged from the tyres,
      // which is how a real strategy works: a plan that reality edits.
      // Spread across the middle of the race rather than bunched at one lap.
      // Twenty cars stopping within two laps of each other is a queue the
      // length of the pit lane, and a queue in a pit lane is a pile-up.
      car.pitLap = clamp(
        Math.round(this.laps * (0.22 + this.rng() * 0.52)), 1, Math.max(1, this.laps - 1),
      )
      car.pitBox = index
      this.cars.push(car)
    })
    this.emit('formation', null, null, 'Formation lap complete — grid is set')
  }

  private emit(
    kind: EventKind, car: number | null, other: number | null, text: string,
    at?: { x: number; y: number }, weight = 0.5,
  ): void {
    this.events.push({
      id: this.eventId++, t: this.time, lap: this.leaderLap + 1,
      kind, car, other, text, x: at?.x, y: at?.y, weight,
    })
    if (this.events.length > 400) this.events.splice(0, this.events.length - 400)
  }

  private spawn(kind: Effect['kind'], x: number, y: number, count: number, spread: number, life: number, size: number, colour?: string): void {
    for (let q = 0; q < count; q++) {
      this.effects.push({
        kind, x, y,
        vx: (this.rng() - 0.5) * spread,
        vy: (this.rng() - 0.5) * spread,
        life, age: 0,
        size: size * (0.6 + this.rng() * 0.8),
        colour,
      })
    }
    if (this.effects.length > 900) this.effects.splice(0, this.effects.length - 900)
  }

  // -- what is under a car ---------------------------------------------------

  /** What is under a point on the road. */
  surfaceAt(i: number, lat: number): Surface {
    return this.surfaces.at(i, lat)
  }

  private drsAt(s: number): DrsZone | null {
    for (const zone of this.drsZones) {
      const along = (s - zone.start + this.circuit.length) % this.circuit.length
      const span = (zone.end - zone.start + this.circuit.length) % this.circuit.length
      if (along < span) return zone
    }
    return null
  }

  // -- the loop --------------------------------------------------------------

  /**
   * Advance the whole race by `dt` seconds.
   *
   * Sub-stepped: the tyre model is stiff, and a step long enough to be
   * comfortable for a browser is long enough for a car at 90 m/s to cross a
   * kerb without noticing. Five millisecond steps hold together at any speed a
   * car reaches here.
   */
  step(dt: number): void {
    const sub = Math.max(1, Math.ceil(dt / 0.006))
    const h = dt / sub
    for (let q = 0; q < sub; q++) this.tick(h)
    // Contact and classification are per *frame*, not per sub-step. Charging
    // a touch a hundred and sixty times a second turns a brush of wheels into
    // a fatal accident, and re-sorting the field that often costs more than
    // the physics does.
    this.pitQueue = this.cars.filter((c) => c.status === 'pit' && c.wantsPit).length
    this.contacts(dt)
    this.classify()
    this.advanceEffects(dt)
  }

  private tick(dt: number): void {
    this.time += dt
    if (!this.started) {
      this.countdown -= dt
      if (this.countdown <= 0) {
        this.started = true
        this.cars.forEach((c) => (c.status = 'racing'))
        this.emit('green', null, null, 'Lights out — and away we go')
      } else {
        // Held on the grid: the engines are running and nothing else is.
        return
      }
    }

    const order = this.roadOrder()
    for (let index = 0; index < order.length; index++) {
      this.driveCar(order[index], order, index, dt)
    }
    this.stepControl(dt)
  }

  /** Cars in the order they are lying on the road, wrapped. */
  private roadOrder(): RaceCar[] {
    return this.cars
      .filter((c) => c.status === 'racing' || c.status === 'pit')
      .sort((a, b) => a.s - b.s)
  }

  private driveCar(car: RaceCar, order: RaceCar[], index: number, dt: number): void {
    const circuit = this.circuit
    const state = car.state

    // -- who is where --------------------------------------------------------
    const aheadCar = order.length > 1 ? order[(index + 1) % order.length] : null
    const behindCar = order.length > 1 ? order[(index - 1 + order.length) % order.length] : null
    const neighbour = (other: RaceCar | null, sign: number): Neighbour | null => {
      if (!other || other === car) return null
      const gap = wrapDelta(other.s - car.s, circuit.length)
      if (sign > 0 && gap < 0) return null
      if (sign < 0 && gap > 0) return null
      if (Math.abs(gap) > 160) return null
      return {
        car: other.number, gap, offset: other.lat, speed: speedOf(other.state),
        lateral: other.lat - car.lat, inPit: other.status === 'pit',
      }
    }
    const ahead = neighbour(aheadCar, 1)
    const behind = neighbour(behindCar, -1)

    // The nearest car ahead that is genuinely in the way, which may be several
    // places up the road order when cars are running two abreast.
    // Deep enough to see past the other lane. During a pit window half the
    // field is in the lane and half is on the road at the same distance round
    // the lap, so the car actually in front can be a dozen places up the road
    // order -- and a driver who cannot see it drives into the back of it.
    let blocker: Neighbour | null = null
    const pitting = car.status === 'pit'
    for (let step = 1; step <= 14 && step < order.length; step++) {
      const other = order[(index + step) % order.length]
      const near = neighbour(other, 1)
      // Only cars in the same place. A car in the pit lane is not in front of
      // anybody on the circuit -- and, just as importantly, a car in the pit
      // lane *is* in front of the queue behind it. Skipping every pit car for
      // everybody left nobody in the pits able to see the stopped car in front
      // of them, and the whole lane drove into the back of it.
      if (!near || near.inPit !== pitting) continue
      if (Math.abs(near.lateral) > CAR_WIDTH * 1.6) continue
      if (!blocker || near.gap < blocker.gap) blocker = near
    }

    // Whoever is level with this car, which is the one it must not turn into.
    let alongside: Neighbour | null = null
    for (const step of [-2, -1, 1, 2]) {
      const other = order[(index + step + order.length * 2) % order.length]
      if (!other || other === car) continue
      const gap = wrapDelta(other.s - car.s, circuit.length)
      if (Math.abs(gap) > CAR_LENGTH * 1.05) continue
      const side = other.lat - car.lat
      if (Math.abs(side) > 4) continue
      if (!alongside || Math.abs(side) < Math.abs(alongside.lateral)) {
        alongside = {
          car: other.number, gap, offset: other.lat, speed: speedOf(other.state),
          lateral: side, inPit: other.status === 'pit',
        }
      }
    }

    // Two places a car holds a lane rather than taking the racing line: the
    // run to the first corner, where twenty cars want the same line from
    // twenty grid slots, and the exit of the pits, where a car doing eighty is
    // rejoining a road with cars on it doing three hundred. Both are the same
    // thing -- stay where you are predictable until you are up to speed.
    const sinceStart = car.covered - car.gridDistance
    let laneWeight = clamp(1 - sinceStart / 320, 0, 1)
    let laneOffset = car.gridOffset
    if (car.covered < car.blendUntil) {
      laneWeight = Math.max(laneWeight, clamp((car.blendUntil - car.covered) / 130, 0, 1))
      laneOffset = this.pitSide * circuit.limit(car.i) * 0.5
    }
    // Pulling into the box. A car that stops on the centreline of the pit lane
    // blocks every car behind it whose own box is further down; a real one
    // pulls out of the lane into its own bay and the rest go past.
    if (car.status === 'pit' && this.pitLine && (car.wantsPit || car.pitHold > 0)) {
      const box = this.pitBoxes[car.pitBox % this.pitBoxes.length]
      const toBox = wrapDelta(box.s - car.s, circuit.length)
      if (toBox < 55 && toBox > -30) {
        laneWeight = 1
        laneOffset = this.pitLine.off[car.i] + this.pitSide * PIT_BOX_OFFSET
      }
    }

    // -- the air -------------------------------------------------------------
    // Following costs downforce and gains a tow. Both come from the same gap,
    // which is why the car that can catch cannot pass.
    let wake = 1
    let tow = 1
    if (ahead && !ahead.inPit && ahead.gap < 55) {
      const closeness = clamp(1 - ahead.gap / 55, 0, 1)
      const aligned = clamp(1 - Math.abs(ahead.lateral) / 4.5, 0, 1)
      wake = 1 - 0.20 * closeness * aligned
      tow = 1 - 0.22 * closeness * aligned
      car.inWake = closeness * aligned
    } else {
      car.inWake = 0
    }

    // -- the flap ------------------------------------------------------------
    const detect = this.drsZones.find(
      (z) => Math.abs(wrapDelta(car.s - z.detect, circuit.length)) < 6,
    )
    if (detect) {
      car.drsArmed = ahead !== null && !ahead.inPit &&
        ahead.gap / Math.max(speedOf(state), 1) < 1.0
    }
    const zone = this.drsAt(car.s)
    const drsAllowed = car.status === 'racing' && car.drsArmed && zone !== null && this.cautionAt < 0
    if (!zone) car.drsOpen = false

    // -- what is under it ----------------------------------------------------
    // The pit lane is road too. Without this a car that has committed to the
    // pits is judged against the *circuit's* edges, finds itself twenty metres
    // beyond the barrier, and is written off on the way to a routine stop.
    const under = this.surfaceAt(car.i, car.lat)
    car.surface = under
    if (car.status === 'pit' && this.pitLine) {
      // Tarmac is the union of the circuit and the lane, which is what a pit
      // entry road actually is -- one continuous surface from the racing line
      // out to the boxes. Judged against the lane's centre alone, a car part
      // way across the entry is "off the road" and gets a track-limits
      // warning, a recovery, and eventually a retirement, every stop.
      const inLane = Math.abs(car.lat - this.pitLine.off[car.i]) < PIT_LANE_WIDTH
      car.surface = inLane || under === 'track' || under === 'kerb' ? 'track' : under
    }
    const grip = SURFACE_GRIP[car.surface]

    // -- yellow flags --------------------------------------------------------
    // A local yellow is a corner; the rest of the lap is green. A virtual
    // safety car is the whole lap at a fraction of the circuit's own pace. A
    // safety car is that, and the field closing up behind the leader.
    let caution = 0
    if (this.control.at >= 0 && this.control.state === 'yellow') {
      const along = wrapDelta(circuit.s[this.control.at] - car.s, circuit.length)
      const distance = Math.abs(along)
      if (distance < 240 && along > -60) caution = clamp(1 - distance / 240, 0, 1)
    }
    let controlCap: number | null = null
    let racing = true
    if (this.control.state === 'vsc') {
      controlCap = this.surfaces.reference[car.i] * VSC_PACE
      racing = false
    } else if (this.control.state === 'safety-car') {
      controlCap = this.surfaces.reference[car.i] * SC_PACE
      racing = false
    } else if (this.control.state === 'red') {
      controlCap = RED_PACE
      racing = false
    }

    // -- the pit lane --------------------------------------------------------
    const inPitWindow =
      car.status === 'pit' ||
      // Committed well before the entry. The pit line *is* the racing line
      // until the taper starts, so this costs nothing on the road -- and it
      // gives the driver the two hundred metres it needs to be at the limiter
      // when it reaches it, instead of arriving at three hundred km/h.
      (car.wantsPit && wrapDelta(car.s - this.pitEntryS, circuit.length) > -280 &&
        wrapDelta(car.s - this.pitEntryS, circuit.length) < 20)
    if (inPitWindow && car.status !== 'pit' && this.pitLine) {
      car.status = 'pit'
      car.driver.pitLine = this.pitLine
      this.emit('pit-in', car.number, null, `${car.entry.abbrev} pits from P${car.position}`,
        { x: state.x, y: state.y }, 0.6)
    }
    let speedLimit: number | null = null
    if (car.status === 'pit') {
      const intoLane = wrapDelta(car.s - this.pitLimitS, circuit.length)
      // Approaching the limit line, the driver slows for it the way they slow
      // for a corner -- early enough to be at the number when they cross it.
      speedLimit =
        intoLane >= 0
          ? PIT_SPEED
          : Math.max(PIT_SPEED, Math.sqrt(PIT_SPEED * PIT_SPEED + 2 * 11 * -intoLane))
      // Coming to a stop in the box is the same arithmetic as a braking zone,
      // aimed at zero: the crew is a corner the car has to be stationary for.
      if (car.wantsPit) {
        const box = this.pitBoxes[car.pitBox % this.pitBoxes.length]
        const toBox = wrapDelta(box.s - car.s, circuit.length)
        // Only on the approach. Behind the box the distance goes negative and
        // the square root of it is zero, which stops the car dead wherever it
        // happens to be -- including out on the racing line.
        if (toBox > 0 && toBox < 70) {
          speedLimit = Math.min(speedLimit, Math.sqrt(2 * 5 * toBox))
        }
      }
      const past = wrapDelta(car.s - this.pitExitS, circuit.length)
      if (past > 0 && past < 40 && car.pitHold <= 0) {
        car.status = 'racing'
        car.driver.pitLine = null
        car.wantsPit = false
        car.blendUntil = car.covered + 130
        this.emit('pit-out', car.number, null,
          `${car.entry.abbrev} rejoins on ${car.compound}s`, { x: state.x, y: state.y }, 0.4)
      }
    }

    if (controlCap !== null) {
      speedLimit = speedLimit === null ? controlCap : Math.min(speedLimit, controlCap)
    }

    const view: RaceView = {
      ahead, behind, now: this.time,
      alongside,
      blocker,
      racing,
      controlCap,
      laneHold: laneWeight > 0 ? laneOffset : null,
      laneWeight,
      drsAllowed, gripFactor: grip, wake, tow, caution, speedLimit,
    } as RaceView

    // -- drive ---------------------------------------------------------------
    const { controls, report } = car.driver.control(state, view, { i: car.i, s: car.s, lat: car.lat }, dt)
    car.intent = report.intent
    car.lineId = report.line
    car.commitment = report.commitment
    car.targetSpeed = report.target
    car.toBraking = report.toBraking
    car.brakeDemand = report.brakeDemand
    car.lateralDemand = report.lateralDemand

    // The pit crew holds the car; that is the one moment the driver is not the
    // one deciding whether it moves.
    if (car.pitHold > 0) {
      car.pitHold -= dt
      controls.throttle = 0
      controls.brake = 1
      // Held for traffic. A crew does not release a car into the path of one
      // coming down the road at three hundred, and neither does this: the stop
      // is extended until the exit is clear, which is a couple of tenths lost
      // rather than two cars out of the race.
      if (car.pitHold <= 0 && this.exitBusy(car)) car.pitHold = 0.25
      if (car.pitHold <= 0) {
        car.stops += 1
        car.tyreAge = 0
        car.compound = car.nextCompound
        car.state.tyreWear = 0
        car.state.tyreTemp = 70
        car.state.tyreGripBonus = COMPOUNDS[car.compound].grip
        car.state.tyreWearRate = COMPOUNDS[car.compound].wear
        this.emit('pit-stop', car.number, null,
          `${car.entry.abbrev} — stop ${car.stops}, fresh ${car.compound}s`,
          { x: state.x, y: state.y }, 0.5)
      }
    } else if (car.status === 'pit' && car.wantsPit) {
      const box = this.pitBoxes[car.pitBox % this.pitBoxes.length]
      const toBox = wrapDelta(box.s - car.s, circuit.length)
      // Close enough and slow enough is arrived. Generous on both, because a
      // car that creeps to a halt half a metre short of its own box and waits
      // there for the rest of the grand prix is not a pit stop.
      if (toBox < 6 && toBox > -10 && speedOf(state) < 5) {
        car.pitHold = 2.1 + this.rng() * 1.6
        car.wantsPit = false
      }
    }

    car.controls = controls
    car.drsOpen = controls.drs
    const physics = stepCar(state, car.spec, controls,
      { gripFactor: grip, wake, tow }, dt)
    car.report = physics

    // -- where that put it ---------------------------------------------------
    const located = circuit.locate(state.x, state.y, car.i)
    const advanced = wrapDelta(located.s - car.s, circuit.length)
    car.covered += advanced
    car.i = located.i
    car.lat = located.lat
    const wrapped = ((located.s % circuit.length) + circuit.length) % circuit.length
    const crossedLine = wrapped < car.s - circuit.length / 2
    car.s = wrapped

    this.reactToSurface(car, physics, dt)
    this.splitSectors(car)
    if (crossedLine) this.completeLap(car)
    this.animate(car, physics, dt)
  }

  /**
   * What the world does back.
   *
   * A car on the grass does not merely have a number reduced: it slides, it
   * throws up dust, it loses time, and if it is far enough off it has to wait
   * for a gap before it can come back. None of that is scripted -- the grip
   * multiplier goes into the tyre model and the rest is the same integrator.
   */
  private reactToSurface(car: RaceCar, physics: StepReport, dt: number): void {
    const state = car.state
    const speed = physics.speed

    car.wallFor = Math.max(0, car.wallFor - dt)

    // A car that has stopped is out of the race, wherever it stopped. Without
    // this a car resting against a barrier reports hitting it again every
    // step for the rest of the afternoon, which is both wrong and the only
    // thing left in the event feed.
    if (speed < 1.5 && car.status === 'racing' && this.started) {
      car.stoppedFor += dt
      const beached = car.surface !== 'track' && car.surface !== 'kerb'
      if (car.stoppedFor > (beached ? 7.0 : 12.0)) {
        // A car stopped *on* the road is a safety car; one in the run-off is
        // a virtual one. The difference is whether anybody has to drive round
        // it at three hundred km/h.
        this.report(car.i, beached ? 0.36 : 0.6,
          `${car.entry.abbrev} stopped ${beached ? 'in the run-off' : 'on track'}`)
        this.retire(car, beached ? 'stopped in the run-off' : 'stopped on track')
        return
      }
    } else {
      car.stoppedFor = 0
    }

    if (car.surface === 'wall' && car.status !== 'pit') {
      // The barrier. Stop the car going any further out, and charge for it.
      const limit = this.surfaces.wallFor(car.i, car.lat)
      const sign = Math.sign(car.lat) || 1
      const place = this.circuit.place(car.s, sign * (limit - 0.4))
      state.x = place.x
      state.y = place.y
      const hit = speed
      state.vx *= 0.25
      state.vy *= -0.2
      state.yawRate *= -0.3
      const harm = clamp(hit / 85, 0, 1)
      state.damage = Math.min(1, state.damage + harm * harm * 0.7)
      car.shake = Math.max(car.shake, 0.8)
      car.lat = sign * (limit - 0.4)
      // One scrape along a wall is one accident, however many steps the car
      // spends against it.
      if (car.wallFor <= 0) {
        car.wallFor = 4.0
        this.spawn('debris', state.x, state.y, 8, 14, 1.2, 0.5)
        this.spawn('smoke', state.x, state.y, 6, 5, 1.6, 1.6)
        this.emit('wall', car.number, null,
          `${car.entry.abbrev} into the barrier at ${(hit * 3.6).toFixed(0)} km/h`,
          { x: state.x, y: state.y }, clamp(harm + 0.3, 0, 1))
        car.driver.noteExcursion(2.5)
        // How big a shunt it was decides what comes out: a scrape is a yellow,
        // a real hit brings the marshals out.
        if (hit > 10) {
          this.report(car.i, clamp(0.12 + harm * 0.9, 0, 0.8),
            `${car.entry.abbrev} in the barrier at ${this.cornerName(car.i)}`)
        }
      }
      if (state.damage > 0.85 || hit > 34) this.retire(car, 'accident damage')
      return
    }

    const off = car.surface === 'gravel' || car.surface === 'grass' || car.surface === 'runoff'
    if (off) {
      car.offTrackFor += dt
      // Beached. A car crawling in a gravel trap does not dig itself out; it
      // waits for a crane, and its race is over.
      car.stuckFor = speed < 2.5 && car.surface === 'gravel' ? car.stuckFor + dt : 0
      if (car.stuckFor > 5.0) {
        this.report(car.i, 0.34, `${car.entry.abbrev} beached at ${this.cornerName(car.i)}`)
        this.retire(car, 'beached in the gravel')
        return
      }
      if (car.surface === 'gravel') {
        // Gravel does not just reduce grip, it drags the car down -- but a
        // modern trap is shallow enough that a car which keeps rolling can
        // usually get itself out, and only one that stops is beached.
        state.vx *= 1 - 0.8 * dt
        if (speed > 6) this.spawn('gravel', state.x, state.y, 2, 9, 0.9, 0.45)
      } else if (speed > 12) {
        this.spawn('dust', state.x, state.y, 1, 6, 1.1, 1.1)
      }
      if (car.offTrackFor > 0.16 && car.offTrackFor - dt <= 0.16 && speed > 20) {
        car.trackLimits += 1
        car.driver.noteExcursion(car.surface === 'gravel' ? 2.0 : 0.7)
        this.emit('off', car.number, null,
          car.surface === 'gravel'
            ? `${car.entry.abbrev} into the gravel at ${this.cornerName(car.i)}`
            : `${car.entry.abbrev} runs wide at ${this.cornerName(car.i)}` +
              (car.lineId === 'dive' ? ' — the lunge did not stick' : ''),
          { x: state.x, y: state.y }, car.surface === 'gravel' ? 0.8 : 0.4)
        if (car.surface === 'gravel' && speed > 45) {
          this.report(car.i, 0.16, `${car.entry.abbrev} in the gravel at ${this.cornerName(car.i)}`)
        }
      }
    } else {
      car.offTrackFor = 0
      car.stuckFor = 0
    }

    // A spin is a car whose slip angle has run away, not a state it is put in.
    //
    // Where the line is drawn matters more than it looks. Called at
    // thirty-five degrees, half the field is "spinning" every lap -- most of
    // those are big slides a driver gathers up, and treating each one as an
    // incident that costs three seconds of crawling turns a moment into a
    // retirement and the car behind's race as well.
    const spun = Math.abs(physics.slip) > 0.85 && speed > 6
    if (spun && !car.spinning) {
      car.spinning = true
      car.driver.noteExcursion(1.6)
      car.smoking = Math.max(car.smoking, 1.4)
      this.spawn('smoke', state.x, state.y, 10, 6, 1.8, 1.7)
      this.emit('spin', car.number, null,
        `${car.entry.abbrev} spins at ${this.cornerName(car.i)}!`,
        { x: state.x, y: state.y }, 0.85)
      // Only a spin that leaves a car where it should not be brings out flags.
      if (speed < 12 || car.surface === 'gravel') {
        this.report(car.i, 0.14, `${car.entry.abbrev} spun at ${this.cornerName(car.i)}`)
      }
    } else if (!spun && Math.abs(physics.slip) < 0.2) {
      car.spinning = false
    }

    car.lockedFor = physics.locked && speed > 18 ? car.lockedFor + dt : 0
    if (physics.locked && speed > 18) {
      car.smoking = Math.max(car.smoking, 0.5)
      if (this.rng() < 0.25) this.spawn('smoke', state.x, state.y, 2, 3, 0.7, 0.9)
      // A momentary lock is not news; a wheel that stays locked long enough to
      // flat-spot a tyre and miss an apex is.
      if (car.lockedFor > 0.35 && car.lockNoted <= 0) {
        car.lockNoted = 20
        this.emit('lockup', car.number, null,
          `${car.entry.abbrev} locks the fronts into ${this.cornerName(car.i)}`,
          { x: state.x, y: state.y }, 0.35)
      }
    }
    car.lockNoted = Math.max(0, car.lockNoted - dt)
    // Sparks: the plank on the ground at speed, which is a straight-line thing.
    if (speed > 62 && Math.abs(this.circuit.k[car.i]) < 1 / 700 && this.rng() < 0.18) {
      this.spawn('spark', state.x, state.y, 2, 4, 0.35, 0.28, '#ffcf6b')
    }
    if (state.damage > 0.55 && this.rng() < 0.05) {
      this.spawn('smoke', state.x, state.y, 1, 2, 1.4, 1.0)
    }
    if (state.damage >= 1) this.retire(car, 'terminal damage')
  }

  private cornerName(i: number): string {
    const index = this.circuit.cornerAt[this.circuit.wrap(i)]
    if (index >= 0) return this.circuit.corners[index].name
    let best = this.circuit.corners[0]
    let gap = Infinity
    for (const cn of this.circuit.corners) {
      const d = ((cn.from - i + this.circuit.n) % this.circuit.n) * this.circuit.ds
      if (d < gap) { gap = d; best = cn }
    }
    return best ? best.name : 'the corner'
  }

  /**
   * Something happened. Decide what race control does about it.
   *
   * Graded, because the grades are what a race actually looks like: most
   * incidents are a corner's worth of yellow and nothing else; a car stopped
   * somewhere awkward is a virtual safety car; a car in a barrier where the
   * marshals have to go and get it is a safety car and the field bunches up;
   * and once in a while the track is blocked and the race stops.
   *
   * It is also, deliberately, the thing that breaks a cascade. Half the
   * retirements in this simulation used to come from cars arriving at full
   * speed at somebody else's accident.
   */
  private report(i: number, severity: number, reason: string): void {
    const now = this.time
    // Never downgrade: a safety car does not become a yellow because somebody
    // spun a moment later.
    const rank: Record<FlagState, number> = {
      green: 0, yellow: 1, vsc: 2, 'safety-car': 3, red: 4,
    }
    let want: FlagState = 'yellow'
    let time = YELLOW_TIME
    if (severity >= 0.85) { want = 'red'; time = RED_TIME }
    else if (severity >= 0.55) { want = 'safety-car'; time = SC_TIME }
    else if (severity >= 0.3) { want = 'vsc'; time = VSC_TIME }

    if (rank[want] < rank[this.control.state] && now < this.control.until) {
      // Already under something bigger: extend it rather than replace it.
      this.control.until = Math.max(this.control.until, now + time * 0.5)
      this.control.at = i
      return
    }
    const changed = want !== this.control.state
    this.control = {
      state: want,
      until: now + time,
      reason,
      at: i,
      bunchedFor: want === 'safety-car' ? 0 : this.control.bunchedFor,
    }
    this.cautionAt = i
    this.cautionUntil = now + time
    if (!changed) return
    const text =
      want === 'red' ? `Red flag — ${reason}`
      : want === 'safety-car' ? `Safety car — ${reason}`
      : want === 'vsc' ? `Virtual safety car — ${reason}`
      : `Yellow flags — ${reason}`
    this.emit(want === 'yellow' ? 'yellow' : want, null, null, text, undefined,
      want === 'yellow' ? 0.45 : 0.95)
  }

  /**
   * Race control, one step at a time.
   *
   * The field has to be *let go* again, and that is not a timer: a safety car
   * comes in when the field is bunched and the track is clear, and a red flag
   * ends when everybody has been gathered up. Doing it on a stopwatch alone
   * releases twenty cars in a queue at different speeds, which is another
   * accident.
   */
  private stepControl(dt: number): void {
    const c = this.control
    if (c.state === 'green') return

    if (c.state === 'safety-car') {
      // Bunched when nobody on the lead lap is more than a couple of seconds
      // from the car in front.
      const train = this.cars.filter((x) => x.status === 'racing')
      const spread = train.every((x) => x.position === 1 || x.interval < 2.2)
      c.bunchedFor = spread ? c.bunchedFor + dt : 0
    }

    if (this.time < c.until) return
    if (c.state === 'safety-car' && c.bunchedFor < 6) {
      // Not ready: hold the field a little longer.
      c.until = this.time + 4
      return
    }
    const was = c.state
    this.control = { state: 'green', until: 0, reason: '', at: -1, bunchedFor: 0 }
    this.cautionAt = -1
    this.emit('clear', null, null,
      was === 'yellow' ? 'Track clear — green flag' : 'Green flag — racing resumes',
      undefined, was === 'yellow' ? 0.3 : 0.8)
  }

  private retire(car: RaceCar, why: string): void {
    if (car.status === 'retired' || car.status === 'finished') return
    car.status = 'retired'
    car.state.vx = 0
    car.state.vy = 0
    // Cars going out together is a different thing from cars going out one at
    // a time: an accident that takes three at once blocks the road, and the
    // race stops while it is cleared.
    this.recentRetirements = this.recentRetirements.filter((t) => this.time - t < 6)
    this.recentRetirements.push(this.time)
    if (this.recentRetirements.length >= 3) {
      this.recentRetirements = []
      this.report(car.i, 0.9, 'multiple cars involved, the track is blocked')
    }
    this.emit('retire', car.number, null, `${car.entry.driver} is out — ${why}`,
      { x: car.state.x, y: car.state.y }, 0.9)
  }

  /**
   * Sector splits, taken where the car crosses a third of the lap.
   *
   * Three of them, because three is what a timing screen shows and because a
   * lap time on its own does not say *where* somebody is quick.
   */
  private splitSectors(car: RaceCar): void {
    const third = this.circuit.length / 3
    const now = Math.min(2, Math.floor(car.s / third))
    if (now === car.sector) return
    const split = this.time - car.sectorStart
    if (split > 3 && car.lap > 0) {
      car.sectors[car.sector] = split
      if (car.bestSectors[car.sector] === 0 || split < car.bestSectors[car.sector]) {
        car.bestSectors[car.sector] = split
      }
    }
    car.sectorStart = this.time
    // Wrapping back to sector 0 is a new lap's worth of splits, so the set that
    // was being filled becomes the last complete one.
    if (now === 0) car.lastSectors = [...car.sectors]
    car.sector = now
  }

  /** The line. Lap times, sectors, strategy and the flag all hang off it. */
  private completeLap(car: RaceCar): void {
    if (car.status === 'retired') return
    const lapTime = this.time - car.lapStarted
    car.lapStarted = this.time
    if (car.lap > 0 && lapTime > 20 && car.status === 'racing') {
      car.lastLap = lapTime
      if (car.bestLap === 0 || lapTime < car.bestLap) car.bestLap = lapTime
      if (!this.fastestLap || lapTime < this.fastestLap.time) {
        this.fastestLap = { car: car.number, time: lapTime, lap: car.lap }
        this.emit('fastest-lap', car.number, null,
          `${car.entry.abbrev} — fastest lap, ${formatLap(lapTime)}`, undefined, 0.6)
      }
    }
    car.lap += 1
    car.driver.noteLap()
    this.leaderLap = Math.max(this.leaderLap, car.lap)

    car.tyreAge += 1

    // Strategy: not a lap number drawn before the start, but the question a
    // strategist actually answers each time the car goes past -- is the set on
    // it costing more than a stop would?
    if (car.status === 'racing' && !car.wantsPit) {
      const call = callStrategy(
        {
          lap: car.lap,
          laps: this.laps,
          wear: car.state.tyreWear,
          tyreAge: car.tyreAge,
          compound: car.compound,
          stops: car.stops,
          pitLoss: this.pitLoss(),
          // A stop under the flags is most of the way to free, because
          // everybody else is going slowly too.
          discount:
            this.control.state === 'safety-car' ? 0.72
            : this.control.state === 'vsc' ? 0.55
            : 0,
          queue: this.pitQueue,
          racing: this.control.state === 'green',
          behind: car.interval,
        },
        this.rng,
      )
      car.strategyNote = call.why
      if (call.pit) {
        car.wantsPit = true
        car.nextCompound = call.compound
      }
    }

    if (car.lap > this.laps) {
      car.status = 'finished'
      car.finishedAt = this.time
      this.emit('finish', car.number, null,
        `${car.entry.driver} takes the chequered flag in P${car.position}`,
        undefined, car.position === 1 ? 1 : 0.4)
      if (!this.finished) {
        this.finished = true
        this.emit('flag', car.number, null, `${car.entry.driver} wins at ${this.circuit.name}`, undefined, 1)
      }
    }
  }

  // -- cars touching ---------------------------------------------------------

  /**
   * Contact.
   *
   * Two cars are rectangles, and rectangles either overlap or they do not --
   * so the test is the separating axis theorem rather than a distance between
   * two dots, which would have a car being hit by another one in the next lane
   * and would never notice two cars nose to tail.
   *
   * What it costs is read off the closing speed along the contact normal.  A
   * wheel brushed alongside at a metre a second is a scuff; the same two cars
   * meeting at thirty is somebody's race over.  Nothing decides which -- the
   * lunge that was never going to fit arrives with the closing speed it
   * arrives with.
   */
  private contacts(dt: number): void {
    const live = this.cars.filter((c) => c.status === 'racing' || c.status === 'pit')
    live.sort((a, b) => a.s - b.s)
    for (const key of this.touching.keys()) {
      const left = (this.touching.get(key) ?? 0) - dt
      if (left <= 0) this.touching.delete(key)
      else this.touching.set(key, left)
    }
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const a = live[i]
        const b = live[j]
        const along = wrapDelta(b.s - a.s, this.circuit.length)
        if (Math.abs(along) > CAR_LENGTH * 1.4) break
        const hit = overlap(a.state, b.state)
        if (!hit) continue
        this.resolveContact(a, b, hit)
      }
    }
  }

  private resolveContact(
    a: RaceCar, b: RaceCar, hit: { nx: number; ny: number; depth: number },
  ): void {
    // Part them, half each, along the axis they are least overlapped on.
    const push = hit.depth * 0.5 + 0.01
    a.state.x -= hit.nx * push
    a.state.y -= hit.ny * push
    b.state.x += hit.nx * push
    b.state.y += hit.ny * push

    const key = a.number < b.number ? `${a.number}:${b.number}` : `${b.number}:${a.number}`
    const known = this.touching.has(key)
    // However long two cars stay tangled, it is one incident. Marked before
    // anything else, so a pair that is separating still counts as the same
    // touch rather than a fresh one on every frame.
    this.touching.set(key, 1.2)

    const va = worldVelocity(a.state)
    const vb = worldVelocity(b.state)
    const closing = (vb.x - va.x) * hit.nx + (vb.y - va.y) * hit.ny
    // Already moving apart: they have been dealt with, and hitting them again
    // would be the solver arguing with itself.
    if (closing > 0) return

    // Equal masses, and a very inelastic collision -- carbon fibre does not
    // bounce, it breaks.
    const impulse = -closing * 0.55
    applyWorldImpulse(a.state, -hit.nx * impulse, -hit.ny * impulse)
    applyWorldImpulse(b.state, hit.nx * impulse, hit.ny * impulse)

    // A hit off-centre spins the car, which is what a wheel-to-wheel touch
    // does and why it is worse than a square nose-to-tail one.
    const twist = clamp(-closing * 0.022, 0, 0.45)
    a.state.yawRate -= twist * Math.sign(hit.nx * Math.sin(a.state.yaw) - hit.ny * Math.cos(a.state.yaw) || 1)
    b.state.yawRate += twist * Math.sign(hit.nx * Math.sin(b.state.yaw) - hit.ny * Math.cos(b.state.yaw) || 1)

    // How bad a contact is scales with the energy in it, so a nudge between
    // two cars crawling down the pit lane is a nudge however sharply the
    // solver had to part them -- not the same event as two cars meeting at
    // two hundred km/h.
    const pace = Math.max(speedOf(a.state), speedOf(b.state))
    const severity = clamp(-closing / 26, 0, 1) * clamp(pace / 28, 0.12, 1)
    for (const car of [a, b]) {
      car.state.damage = Math.min(1, car.state.damage + severity * severity * 0.5)
      car.shake = Math.max(car.shake, 0.25 + severity * 0.6)
      if (car.state.damage >= 1) this.retire(car, 'contact damage')
    }
    if (severity > 0.06 && !known) {
      this.spawn('debris', (a.state.x + b.state.x) / 2, (a.state.y + b.state.y) / 2,
        Math.round(2 + severity * 9), 11, 1.0, 0.35)
      this.emit('contact', a.number, b.number,
        severity > 0.45
          ? `Big contact — ${a.entry.abbrev} and ${b.entry.abbrev} at ${this.cornerName(a.i)}`
          : `Wheel to wheel — ${a.entry.abbrev} and ${b.entry.abbrev} at ${this.cornerName(a.i)}`,
        { x: a.state.x, y: a.state.y }, severity)
      if (severity > 0.4) {
        this.report(a.i, clamp(severity * 0.8, 0, 0.75),
          `contact between ${a.entry.abbrev} and ${b.entry.abbrev}`)
      }
    }
  }

  // -- the order -------------------------------------------------------------

  /**
   * Who is where.
   *
   * Built from distance covered, which is a fact about the driving rather than
   * a judgement about it. An overtake is therefore not an event that gets
   * decided anywhere: it is the moment two rows of this list change places,
   * and it is *reported* here rather than caused here.
   */
  private classify(): void {
    const running = this.cars.filter((c) => c.status !== 'retired')
    const previous = new Map(running.map((c) => [c.number, c.position]))
    running.sort((a, b) => {
      if (a.status === 'finished' && b.status === 'finished') return a.finishedAt - b.finishedAt
      if (a.status === 'finished') return -1
      if (b.status === 'finished') return 1
      return b.covered - a.covered
    })
    const leader = running[0]
    running.forEach((car, index) => {
      car.position = index + 1
      car.gapToLeader = leader ? (leader.covered - car.covered) / Math.max(speedOf(car.state), 12) : 0
      const front = running[index - 1]
      car.interval = front ? (front.covered - car.covered) / Math.max(speedOf(car.state), 12) : 0
      const was = previous.get(car.number)
      if (was && was > car.position && this.started && !this.finished) {
        // Somebody was passed. Which one, and where, comes from the list.
        const lost = running.find((c) => c.position === was)
        if (lost && lost.number !== car.number && Math.abs(wrapDelta(lost.s - car.s, this.circuit.length)) < 60) {
          lost.driver.notePassed()
          const how = car.lineId === 'dive' ? 'down the inside'
            : car.lineId === 'outside' ? 'around the outside'
            : car.lineId === 'switchback' ? 'with the switchback'
            : car.drsOpen ? 'with DRS' : 'on the run'
          this.emit('overtake', car.number, lost.number,
            `${car.entry.abbrev} passes ${lost.entry.abbrev} ${how} for P${car.position}`,
            { x: car.state.x, y: car.state.y }, 0.7)
        }
      }
    })
    let retiredAt = running.length
    for (const car of this.cars) if (car.status === 'retired') car.position = ++retiredAt
  }

  // -- the picture -----------------------------------------------------------

  /** Everything that is only true of how the car looks, updated per step. */
  private animate(car: RaceCar, physics: StepReport, dt: number): void {
    // The front wheels lag the input a little, the way a real rack does.
    car.wheelAngle += (car.controls.steer - car.wheelAngle) * Math.min(1, dt * 16)
    // Roll and pitch are read straight off the accelerations, so the car
    // leans into a corner and dives under braking because it *is* doing that.
    const roll = clamp(-physics.ay / 45, -0.5, 0.5)
    const pitch = clamp(-physics.ax / 55, -0.5, 0.5)
    car.bodyRoll += (roll - car.bodyRoll) * Math.min(1, dt * 9)
    car.bodyPitch += (pitch - car.bodyPitch) * Math.min(1, dt * 9)
    car.shake = Math.max(0, car.shake - dt * 1.5)
    car.smoking = Math.max(0, car.smoking - dt * 1.1)
    car.damageSeen += (car.state.damage - car.damageSeen) * Math.min(1, dt * 2)
    car.flames = car.controls.throttle < 0.1 && physics.speed > 40 && this.rng() < 0.08 ? 0.14 : Math.max(0, car.flames - dt)
  }

  private advanceEffects(dt: number): void {
    for (let i = this.effects.length - 1; i >= 0; i--) {
      const e = this.effects[i]
      e.age += dt
      if (e.age >= e.life) { this.effects.splice(i, 1); continue }
      e.x += e.vx * dt
      e.y += e.vy * dt
      e.vx *= 1 - 1.6 * dt
      e.vy *= 1 - 1.6 * dt
      if (e.kind === 'smoke' || e.kind === 'dust') e.size += dt * 2.4
    }
  }

  /**
   * What a stop costs here, in seconds.
   *
   * The lane at its limit against the same road at racing speed, plus the time
   * the car is stationary. Computed rather than assumed, so a circuit with a
   * long pit lane genuinely discourages stopping.
   */
  pitLoss(): number {
    const geo = this.pitGeometry()
    if (!geo.line) return 22
    const span = ((geo.exitS - geo.entryS) + this.circuit.length) % this.circuit.length
    let onTrack = 0
    const from = this.circuit.idxAt(geo.entryS)
    const steps = Math.round(span / this.circuit.ds)
    for (let q = 0; q < steps; q++) {
      const i = this.circuit.wrap(from + q)
      onTrack += this.circuit.ds / Math.max(this.surfaces.reference[i], 5)
    }
    const inLane = span / geo.speedLimit
    return inLane - onTrack + 2.8
  }

  /**
   * Is somebody about to arrive at the pit exit?
   *
   * Answered in time rather than distance: a car two hundred metres away at
   * three hundred km/h is two seconds away, and two seconds is not enough.
   */
  private exitBusy(car: RaceCar): boolean {
    const geo = this.pitGeometry()
    const toExit = wrapDelta(geo.exitS - car.s, this.circuit.length)
    const need = clamp(toExit / geo.speedLimit, 2, 14)
    for (const other of this.cars) {
      if (other === car || other.status !== 'racing') continue
      const gap = wrapDelta(geo.exitS - other.s, this.circuit.length)
      if (gap < -20) continue
      const arrives = gap / Math.max(speedOf(other.state), 8)
      if (arrives < need + 1.4) return true
    }
    return false
  }

  /** The classification, for the tower. */
  standings(): RaceCar[] {
    return [...this.cars].sort((a, b) => a.position - b.position)
  }

  /** The pit lane, for the renderer to draw where the cars actually go. */
  pitGeometry() {
    return {
      line: this.pitLine,
      entryS: this.pitEntryS,
      exitS: this.pitExitS,
      side: this.pitSide,
      points: this.pitPoints,
      boxes: this.pitBoxes,
      speedLimit: PIT_SPEED,
    }
  }

  drsGeometry(): DrsZone[] {
    return this.drsZones
  }
}

export function formatLap(t: number): string {
  if (!isFinite(t) || t <= 0) return '—'
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return `${m}:${s < 10 ? '0' : ''}${s.toFixed(3)}`
}

export function formatGap(t: number): string {
  if (!isFinite(t) || t <= 0) return '—'
  return `+${t.toFixed(3)}`
}

// -- rectangles ---------------------------------------------------------------

/** A car's four corners, in world coordinates. */
export function corners(state: CarState): { x: number; y: number }[] {
  const c = Math.cos(state.yaw)
  const s = Math.sin(state.yaw)
  const hl = CAR_LENGTH / 2
  const hw = CAR_WIDTH / 2
  return [
    { x: state.x + c * hl - s * hw, y: state.y + s * hl + c * hw },
    { x: state.x + c * hl + s * hw, y: state.y + s * hl - c * hw },
    { x: state.x - c * hl + s * hw, y: state.y - s * hl - c * hw },
    { x: state.x - c * hl - s * hw, y: state.y - s * hl + c * hw },
  ]
}

/**
 * Do two cars overlap, and along which axis least?
 *
 * The separating axis theorem on two rectangles: if there is any axis on which
 * their shadows do not touch, they do not touch. Four axes are enough for two
 * rectangles, and the one with the least overlap is the direction to part them
 * along -- which is why a car nudged from behind goes forwards and one leaned
 * on goes sideways.
 */
function overlap(
  a: CarState, b: CarState,
): { nx: number; ny: number; depth: number } | null {
  const axes = [
    { x: Math.cos(a.yaw), y: Math.sin(a.yaw) },
    { x: -Math.sin(a.yaw), y: Math.cos(a.yaw) },
    { x: Math.cos(b.yaw), y: Math.sin(b.yaw) },
    { x: -Math.sin(b.yaw), y: Math.cos(b.yaw) },
  ]
  const hl = CAR_LENGTH / 2
  const hw = CAR_WIDTH / 2
  const reach = (state: CarState, ax: { x: number; y: number }) =>
    hl * Math.abs(Math.cos(state.yaw) * ax.x + Math.sin(state.yaw) * ax.y) +
    hw * Math.abs(-Math.sin(state.yaw) * ax.x + Math.cos(state.yaw) * ax.y)

  let best = Infinity
  let nx = 0
  let ny = 0
  for (const ax of axes) {
    const gap = (b.x - a.x) * ax.x + (b.y - a.y) * ax.y
    const depth = reach(a, ax) + reach(b, ax) - Math.abs(gap)
    if (depth <= 0) return null
    if (depth < best) {
      best = depth
      const sign = gap >= 0 ? 1 : -1
      nx = ax.x * sign
      ny = ax.y * sign
    }
  }
  return { nx, ny, depth: best }
}

/** Body-frame velocity, in the world. */
function worldVelocity(state: CarState): { x: number; y: number } {
  const c = Math.cos(state.yaw)
  const s = Math.sin(state.yaw)
  return { x: state.vx * c - state.vy * s, y: state.vx * s + state.vy * c }
}

/** Add a world-frame velocity change to a car. */
function applyWorldImpulse(state: CarState, dx: number, dy: number): void {
  const c = Math.cos(state.yaw)
  const s = Math.sin(state.yaw)
  state.vx += dx * c + dy * s
  state.vy += -dx * s + dy * c
}
