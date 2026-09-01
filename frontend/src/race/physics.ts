/**
 * A car, as a thing that obeys forces.
 *
 * Nothing in here knows what a race is.  It is handed a steering angle, a
 * throttle and a brake, and it works out where the car ends up -- which means
 * every lap time, every overtake and every excursion in the simulation is the
 * consequence of what a driver did with the controls, and not of anything
 * written down about how a race is supposed to turn out.  That is the point of
 * doing it this way: there is no drawer marked "result" for anything to reach
 * into.
 *
 * The model is a single-track (bicycle) car with load transfer:
 *
 * - **Aerodynamics.**  Downforce and drag both go as the square of speed, so
 *   the same car has half again the grip at the end of a straight that it has
 *   in a hairpin.  That single fact is most of why a racing line looks the way
 *   it does.
 * - **Load transfer.**  Braking moves weight onto the front axle and
 *   accelerating moves it back, so the axle that is being asked for grip is
 *   usually the one that has least of it.
 * - **Tyres.**  A simplified Pacejka curve: lateral force rises with slip
 *   angle, peaks, and falls away.  Past the peak the car does not simply stop
 *   turning -- it gets worse, which is what makes a mistake a mistake rather
 *   than a plateau.
 * - **The friction ellipse.**  A tyre has one budget for grip and spends it on
 *   turning and stopping together.  Trail-braking into an apex is spending it
 *   in both directions at once, and overspending it is a lock-up or a spin.
 *
 * Understeer, oversteer, lock-ups and spins are therefore not states the code
 * switches into.  They are what this integrator does when it is asked for more
 * than the tyres have.
 */

import { clamp, wrapAngle } from './geometry'

/** Air density at sea level, kg/m^3. */
const RHO = 1.225
const G = 9.81

/** Everything about a car that does not change while it is being driven. */
export interface CarSpec {
  /** Dry mass without fuel, kg. */
  mass: number
  /** Distance from the centre of mass to the front and rear axles, m. */
  frontAxle: number
  rearAxle: number
  /** Height of the centre of mass, m. Sets how much weight moves about. */
  cgHeight: number
  /** Yaw inertia, kg m^2. */
  inertia: number
  /** Drag area, Cd*A. */
  dragArea: number
  /** Downforce area, Cl*A. */
  liftArea: number
  /** Fraction of downforce carried by the front axle. */
  aeroBalance: number
  /** How much drag the open rear wing gives back, as a fraction. */
  drsDragCut: number
  /** Crank power, W. */
  power: number
  /** What the electrical side adds when it is deployed, W. */
  ersPower: number
  /** How much it can hold, J. */
  ersStore: number
  /** How fast it recovers under braking, W. */
  ersHarvest: number
  /** Peak brake force at the tyres, N, before grip is considered. */
  brakeForce: number
  /** Fraction of braking done by the front axle. */
  brakeBalance: number
  /** Peak tyre friction coefficient on a fresh tyre. */
  grip: number
  /** How much the tyre loses as vertical load rises -- the reason a heavier
   *  car is not simply proportionally slower. Per newton. */
  loadSensitivity: number
  /** Pacejka-ish stiffness and shape for the lateral curve. */
  tyreB: number
  tyreC: number
  /** Top speed limiter, m/s -- gearing, not drag. */
  vMax: number
}

/**
 * A modern grand prix car, which every entry is a variation on.
 *
 * The numbers are chosen so the *behaviour* matches a real one where a real
 * one has been measured, rather than to look plausible in a table:
 *
 * | what | here | a 2024 car |
 * |---|---|---|
 * | lateral at 110 km/h | 2.5 g | 2.5–3 g |
 * | lateral at 320 km/h | 5.3 g | 5.5–6 g |
 * | braking from 300 km/h | 4.8 g | 5–6 g |
 * | top speed | 346 km/h | ~340 km/h |
 * | a lap of Bahrain, alone | 1:28.4 | 1:29.2 pole |
 *
 * The two ends of the lateral figure are what `loadSensitivity` is for, and
 * getting *both* right is the point. A tyre's coefficient falls as it is
 * pressed harder, so a car with enough grip for a hairpin has far too much
 * with three tonnes of downforce on it, and one tuned for the fast corners
 * cannot get out of a slow one. Setting the peak and the load sensitivity
 * together is what makes one set of numbers do both.
 */
export const BASE_CAR: CarSpec = {
  mass: 798,
  frontAxle: 1.72,
  rearAxle: 1.88,
  cgHeight: 0.30,
  inertia: 1100,
  dragArea: 1.30,
  liftArea: 4.60,
  aeroBalance: 0.45,
  drsDragCut: 0.22,
  power: 735000,
  ersPower: 120000,
  ersStore: 4.0e6,
  ersHarvest: 220000,
  // Sized so a driver standing on the pedal is just at the front tyres' limit
  // in a normal stop: locking a wheel takes overdoing it, rather than being
  // what happens at every corner.
  brakeForce: 40000,
  brakeBalance: 0.62,
  grip: 2.18,
  loadSensitivity: 2.4e-5,
  tyreB: 9.5,
  tyreC: 1.65,
  vMax: 96,
}

/** The car's state, integrated. */
export interface CarState {
  x: number
  y: number
  /** Which way the car is pointing, rad. Not which way it is going. */
  yaw: number
  /** Body-frame velocity: along the car, and across it. */
  vx: number
  vy: number
  /** Yaw rate, rad/s. */
  yawRate: number
  /** Fuel still on board, kg. */
  fuel: number
  /** 0 fresh, 1 gone. */
  tyreWear: number
  /** The compound's peak grip, as a multiplier on the car's own. */
  tyreGripBonus: number
  /** And how fast it wears, relative to a medium. */
  tyreWearRate: number
  /** Working temperature, degC. Grip is best in a window. */
  tyreTemp: number
  /** Accumulated damage, 0..1. Costs downforce and power. */
  damage: number
  /** Energy in the battery, J. */
  ers: number
  /** Whether it is being deployed right now, for the picture. */
  deploying: boolean
}

/** What the driver is doing with the controls, this step. */
export interface Controls {
  /** Front wheel angle, rad. */
  steer: number
  throttle: number
  brake: number
  drs: boolean
}

/** What the world underneath is doing to the car. */
export interface Footing {
  /** Grip multiplier of whatever the car is on: road, kerb, gravel, grass. */
  gripFactor: number
  /** Downforce multiplier, below one in another car's wake. */
  wake: number
  /** Drag multiplier, below one in the tow. */
  tow: number
}

/** Anything worth knowing that came out of one step. */
export interface StepReport {
  /** Body slip angle, rad. Big means the car is sideways. */
  slip: number
  /** Front and rear slip angles, rad. */
  slipFront: number
  slipRear: number
  /** How much of each axle's grip is being used, 0..1+. */
  useFront: number
  useRear: number
  /** Longitudinal and lateral acceleration, m/s^2. */
  ax: number
  ay: number
  /** The front tyres are past their peak: the car is not turning as asked. */
  understeer: boolean
  /** The rears are past theirs. */
  oversteer: boolean
  /** Brakes locked: asking for more retardation than the tyre can give. */
  locked: boolean
  /** Wheelspin. */
  spinning: boolean
  speed: number
}

/** Speed, m/s -- the thing everything else is measured against. */
export function speedOf(s: CarState): number {
  return Math.hypot(s.vx, s.vy)
}

/**
 * How much grip the tyre has right now, as a multiplier on the car's peak.
 *
 * Wear takes it away steadily; temperature takes it away outside a window,
 * which is why a car on cold tyres out of the pits is genuinely slower for a
 * lap rather than nominally so.
 */
export function tyreGrip(state: CarState): number {
  const wear =
    (state.tyreGripBonus ?? 1) *
    (1 - 0.22 * state.tyreWear * state.tyreWear - 0.06 * state.tyreWear)
  const dt = (state.tyreTemp - 95) / 45
  const thermal = 1 - 0.30 * dt * dt
  return Math.max(0.35, wear * Math.min(1, thermal))
}

/** Peak lateral force one axle can make at a given vertical load. */
function axleGrip(spec: CarState & { spec: CarSpec }, load: number, mu: number): number {
  // Load sensitivity: doubling the load does not double the grip.
  return Math.max(0, mu * load * (1 - spec.spec.loadSensitivity * load))
}

/** The lateral force a tyre makes at a slip angle, normalised to its peak. */
function pacejka(slip: number, B: number, C: number): number {
  return Math.sin(C * Math.atan(B * slip))
}

/**
 * Advance one car by `dt` seconds.
 *
 * Returns what the step told us about the car, which is what the driver model
 * reads back on the next step -- the same information a driver gets through
 * the seat rather than from a table.
 */
export function step(
  state: CarState,
  spec: CarSpec,
  controls: Controls,
  footing: Footing,
  dt: number,
): StepReport {
  const mass = spec.mass + state.fuel
  const wheelbase = spec.frontAxle + spec.rearAxle
  const v = Math.hypot(state.vx, state.vy)
  const damageLoss = 1 - 0.55 * state.damage

  // -- aerodynamics ---------------------------------------------------------
  const q = 0.5 * RHO * v * v
  const downforce = q * spec.liftArea * footing.wake * damageLoss
  const drsCut = controls.drs ? 1 - spec.drsDragCut : 1
  const drag = q * spec.dragArea * drsCut * footing.tow

  // -- what the tyres can do ------------------------------------------------
  const mu = spec.grip * footing.gripFactor * tyreGrip(state)
  const staticFront = mass * G * (spec.rearAxle / wheelbase)
  const staticRear = mass * G * (spec.frontAxle / wheelbase)
  // Load transfer uses last step's longitudinal acceleration, which is what
  // makes braking and turning interact the way they do: the front is loaded
  // by the very thing that is asking it for grip.
  const lastAx = (state as CarState & { lastAx?: number }).lastAx ?? 0
  const shift = (mass * lastAx * spec.cgHeight) / wheelbase
  const loadFront = Math.max(50, staticFront + downforce * spec.aeroBalance - shift)
  const loadRear = Math.max(50, staticRear + downforce * (1 - spec.aeroBalance) + shift)
  const capFront = axleGrip({ ...state, spec }, loadFront, mu)
  const capRear = axleGrip({ ...state, spec }, loadRear, mu)

  // -- longitudinal demand --------------------------------------------------
  // The electrical side. Deployed where it is worth having -- on the throttle,
  // above the speed at which the engine alone starts running out of torque --
  // and recovered under braking. It is what makes a modern car pull away down
  // a straight the way it does, and what runs out if a driver uses it all
  // defending in the first sector.
  const wantsErs = controls.throttle > 0.75 && v > 32 && state.ers > 0
  const deploy = wantsErs ? spec.ersPower : 0
  state.deploying = wantsErs
  const totalPower = (spec.power + deploy) * damageLoss

  const engine = v > 1 ? Math.min(totalPower / Math.max(v, 8), 26000) : 16000
  const limiter = v >= spec.vMax ? 0 : 1
  let driveForce = controls.throttle * engine * limiter
  const brakeDemand = controls.brake * spec.brakeForce
  let brakeFront = brakeDemand * spec.brakeBalance
  let brakeRear = brakeDemand * (1 - spec.brakeBalance)

  // -- slip angles ----------------------------------------------------------
  // Below walking pace the slip angle is meaningless and its derivative is
  // enormous, so the guard is not a fudge: it is where the model stops being
  // the right one.
  const vref = Math.max(Math.abs(state.vx), 3)
  const slipFront = Math.atan2(state.vy + spec.frontAxle * state.yawRate, vref) - controls.steer
  const slipRear = Math.atan2(state.vy - spec.rearAxle * state.yawRate, vref)

  // -- what the axles can actually do ---------------------------------------
  // A tyre asked for more than it has does not give more: it slides. Sliding
  // friction is a little below the peak, so the car keeps *some* grip -- which
  // is the difference between power oversteer, which a driver can catch, and
  // an instant spin, which nobody could.
  const SLIDING = 0.90

  // Braking. A wheel asked for more retardation than its tyre has locks, and
  // a locked wheel is a skidding one: it slows the car slightly less and does
  // nothing at all sideways. Both axles: a rear that locks under braking is
  // how a car ends up facing the way it came from, and leaving it out is the
  // difference between a driver who can brake and one who cannot.
  const locked = brakeFront > capFront
  if (locked) brakeFront = capFront * SLIDING
  const rearLocked = brakeRear > capRear
  if (rearLocked) brakeRear = capRear * SLIDING
  // Traction. What the engine asks for beyond what the rear can hold is
  // wheelspin, not acceleration.
  const spinning = driveForce - brakeRear > capRear
  if (spinning) driveForce = capRear * SLIDING + brakeRear

  // The friction ellipse: one budget per axle, spent on stopping and turning
  // together. Whatever the longitudinal demand leaves is what is available to
  // turn with, which is why trail-braking works and why overdoing it does not.
  const longFront = -brakeFront
  const longRear = driveForce - brakeRear
  const usedFront = Math.min(SLIDING, Math.abs(longFront) / Math.max(capFront, 1))
  const usedRear = Math.min(SLIDING, Math.abs(longRear) / Math.max(capRear, 1))
  const latCapFront = capFront * Math.sqrt(Math.max(0, 1 - usedFront * usedFront))
  const latCapRear = capRear * Math.sqrt(Math.max(0, 1 - usedRear * usedRear))

  const forceFront = -latCapFront * pacejka(slipFront, spec.tyreB, spec.tyreC)
  const forceRear = -latCapRear * pacejka(slipRear, spec.tyreB, spec.tyreC)

  const longitudinal =
    driveForce - brakeRear - brakeFront * Math.cos(controls.steer) -
    forceFront * Math.sin(controls.steer) - drag - Math.sign(state.vx) * 12
  const lateral = forceRear + forceFront * Math.cos(controls.steer)
  const moment =
    spec.frontAxle * (forceFront * Math.cos(controls.steer)) - spec.rearAxle * forceRear

  // -- integrate ------------------------------------------------------------
  const ax = longitudinal / mass
  const ay = lateral / mass
  state.vx += (ax + state.vy * state.yawRate) * dt
  state.vy += (ay - state.vx * state.yawRate) * dt
  state.yawRate += (moment / spec.inertia) * dt

  // A locked front wheel does not steer, so the car goes where it was already
  // going: straight on, into the run-off.
  if (locked) state.yawRate *= Math.max(0, 1 - 3.5 * dt)

  if (state.vx < 0) state.vx = 0
  state.yaw = wrapAngle(state.yaw + state.yawRate * dt)
  const cos = Math.cos(state.yaw)
  const sin = Math.sin(state.yaw)
  state.x += (state.vx * cos - state.vy * sin) * dt
  state.y += (state.vx * sin + state.vy * cos) * dt
  ;(state as CarState & { lastAx?: number }).lastAx = ax

  // -- consumables ----------------------------------------------------------
  const newSpeed = Math.hypot(state.vx, state.vy)
  // How hard the tyres are being worked, in g. Both wear and temperature come
  // from this one number, because it is the one thing physically happening to
  // them -- and it is the *resultant* acceleration, not the sum of the four
  // force components. Summing them double-counts (a car at two g reads as four),
  // and a temperature model fed a doubled number equilibrates far too hot.
  const work = Math.hypot(ax, ay) / G

  // About a kilo and a half a lap, which is what a modern car uses.
  state.fuel = Math.max(0, state.fuel - (0.016 * controls.throttle + 0.004) * dt)

  // The battery: spent on the throttle, refilled on the brakes. A lap of a
  // circuit with long braking zones gives most of it back; one without does
  // not, which is why the same car deploys differently at different tracks.
  if (deploy > 0) state.ers = Math.max(0, state.ers - deploy * dt)
  if (controls.brake > 0.1 && v > 12) {
    state.ers = Math.min(spec.ersStore, state.ers + spec.ersHarvest * controls.brake * dt)
  }

  // Wear is the energy going through the contact patch, not the number of laps
  // that have been counted -- so a driver who looks after them genuinely has
  // more left at the end, and one who slides the car does not.
  state.tyreWear = Math.min(1.4, state.tyreWear + work * work * 0.00024 * (state.tyreWearRate ?? 1) * dt)

  // Temperature relaxes toward what this much work sustains, rather than being
  // integrated from a heating rate: a rate model with a cooling term has an
  // equilibrium nobody chose, and this one's was a hundred and seventy-seven
  // degrees, at which grip had collapsed to its floor and every car spent the
  // race sliding. Stated as a target it is a number that can be checked.
  const AMBIENT = 28
  const target = AMBIENT + 26 + work * 22
  state.tyreTemp += (target - state.tyreTemp) * Math.min(1, (0.16 + newSpeed * 0.002) * dt)

  const slip = Math.abs(Math.atan2(state.vy, Math.max(state.vx, 0.5)))
  // Past the peak of the curve, an axle is giving less than it was asked for.
  const peakSlip = Math.atan(Math.tan(Math.PI / (2 * spec.tyreC)) / spec.tyreB)
  return {
    slip,
    slipFront,
    slipRear,
    useFront: latCapFront > 1 ? Math.abs(forceFront) / latCapFront : 1,
    useRear: latCapRear > 1 ? Math.abs(forceRear) / latCapRear : 1,
    ax,
    ay,
    understeer: Math.abs(slipFront) > peakSlip && Math.abs(controls.steer) > 0.02,
    oversteer: Math.abs(slipRear) > peakSlip,
    locked,
    spinning,
    speed: newSpeed,
  }
}

/**
 * What one axle can make laterally at a vertical load, N.
 *
 * The same expression the integrator uses, exported so the driver model's
 * estimate of its own car and the car's actual behaviour cannot drift apart.
 * They did drift, once: the planner ignored load sensitivity, believed it
 * could brake thirty per cent harder than it could, and put every car in the
 * gravel at the first corner. A driver who is wrong about their own car is a
 * driver who crashes, which is realistic and useless.
 */
function axleCap(load: number, mu: number, loadSensitivity: number): number {
  return Math.max(0, mu * load * (1 - loadSensitivity * load))
}

/** Static and aerodynamic load on each axle at a given speed, N. */
function axleLoads(
  spec: CarSpec, mass: number, v: number, wake: number,
): { front: number; rear: number } {
  const wheelbase = spec.frontAxle + spec.rearAxle
  const down = 0.5 * RHO * spec.liftArea * wake * v * v
  return {
    front: mass * G * (spec.rearAxle / wheelbase) + down * spec.aeroBalance,
    rear: mass * G * (spec.frontAxle / wheelbase) + down * (1 - spec.aeroBalance),
  }
}

/** The most lateral acceleration the tyres can make at this speed, m/s^2. */
export function lateralLimit(
  spec: CarSpec, mass: number, v: number, mu: number, wake: number,
): number {
  const load = axleLoads(spec, mass, v, wake)
  return (
    axleCap(load.front, mu, spec.loadSensitivity) +
    axleCap(load.rear, mu, spec.loadSensitivity)
  ) / mass
}

/**
 * The fastest a car can go through a corner of radius `radius`.
 *
 * Solved rather than looked up, because downforce depends on the very speed
 * being solved for: more speed is more grip is more speed.  Three fixed-point
 * passes settle it to well inside a tenth of a metre per second, which is far
 * finer than the difference it makes to a braking point.
 */
export function corneringSpeed(
  spec: CarSpec, mass: number, radius: number, mu: number, wake: number,
): number {
  const r = Math.abs(radius)
  if (!isFinite(r) || r > 4000) return spec.vMax
  let v = Math.sqrt(mu * G * r)
  for (let pass = 0; pass < 3; pass++) {
    const guess = Math.min(v, spec.vMax)
    const load = axleLoads(spec, mass, guess, wake)
    const lateral =
      (axleCap(load.front, mu, spec.loadSensitivity) +
        axleCap(load.rear, mu, spec.loadSensitivity)) / mass
    v = Math.sqrt(Math.max(0, lateral * r))
  }
  return Math.min(spec.vMax, v)
}

/**
 * How hard the car can actually brake at a given speed, m/s^2.
 *
 * Not the sum of both axles' grip: the brake balance is fixed, so whichever
 * axle runs out first is the one that decides. It is nearly always the front,
 * which is why locking a front wheel is the mistake a driver makes and locking
 * a rear is the mistake a car makes.
 */
export function brakingLimit(
  spec: CarSpec, mass: number, v: number, mu: number, wake: number,
): number {
  const wheelbase = spec.frontAxle + spec.rearAxle
  const load = axleLoads(spec, mass, v, wake)
  const drag = (0.5 * RHO * spec.dragArea * v * v) / mass
  let decel = (mu * (load.front + load.rear)) / mass
  // Load transfer depends on the deceleration it is being computed for, so
  // take one pass at it and then believe the answer.
  for (let pass = 0; pass < 2; pass++) {
    const shift = (mass * decel * spec.cgHeight) / wheelbase
    const front = axleCap(load.front + shift, mu, spec.loadSensitivity)
    const rear = axleCap(Math.max(50, load.rear - shift), mu, spec.loadSensitivity)
    decel = Math.min(
      front / (mass * spec.brakeBalance),
      rear / (mass * (1 - spec.brakeBalance)),
      spec.brakeForce / mass,
    )
  }
  return decel + drag
}

/**
 * The most throttle the rear tyres will take at this speed.
 *
 * A driver does not hold the pedal down and hope: they feed in what the car
 * will accept. How close they get to this number is car control, and going
 * past it is wheelspin and then oversteer -- which is exactly what the
 * integrator does with it.
 */
export function tractionThrottle(
  spec: CarSpec, mass: number, v: number, mu: number, wake: number,
): number {
  const load = axleLoads(spec, mass, v, wake)
  const cap = axleCap(load.rear, mu, spec.loadSensitivity)
  const engine = Math.min(spec.power / Math.max(v, 8), 26000)
  return clamp(cap / Math.max(engine, 1), 0.06, 1)
}

/** How hard it can accelerate at a given speed, m/s^2. */
export function tractionLimit(
  spec: CarSpec, mass: number, v: number, mu: number, wake: number,
): number {
  const load = axleLoads(spec, mass, v, wake)
  const grip = axleCap(load.rear, mu, spec.loadSensitivity) / mass
  const engine = Math.min(spec.power / Math.max(v, 8), 26000) / mass
  const drag = (0.5 * RHO * spec.dragArea * v * v) / mass
  return Math.max(0, Math.min(grip, engine) - drag)
}
