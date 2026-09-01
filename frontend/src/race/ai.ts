/**
 * The driver.
 *
 * One of these sits in every car and gets three things out: a steering angle,
 * a throttle and a brake.  That is the whole interface to the world.  It
 * cannot move its car, cannot decide it has overtaken anybody, and cannot be
 * told where it finishes -- it can only drive, and the race is whatever comes
 * of twenty of them driving at once.
 *
 * **Speed is not looked up.**  Each driver scans the line it is on, computes
 * from *its own car's* mass, downforce and tyre state how fast that piece of
 * road can be taken, and works backwards to find where it has to brake.  Two
 * cars in the same corner brake in different places because their numbers are
 * different, which is the only reason anything here is ever quicker than
 * anything else.
 *
 * **Overtaking is a choice of line.**  A driver who has caught somebody does
 * not gain a probability of passing.  It picks a different path -- the inside
 * for a lunge, the outside if the inside is shut, a sacrificed entry for a
 * switchback -- and then drives it.  Whether the move comes off is settled by
 * the physics: whether the car actually stops in time, whether it is far
 * enough alongside at the apex, whether it comes out of the corner with more
 * speed than the car it is fighting.
 *
 * **And it can get it wrong.**  Commitment is a real number.  Above one, the
 * driver brakes later than its own car can survive, and the resulting
 * understeer, the wide exit and sometimes the trip through the gravel are not
 * outcomes selected from a list -- they are what happens to a car that arrives
 * at a corner too fast.
 */

import { CAR_LENGTH, CAR_WIDTH, Circuit, clamp, lerp, wrapAngle } from './geometry'
import { Line, LineId, LineSet } from './lines'
import {
  BASE_CAR, CarSpec, CarState, Controls, brakingLimit, corneringSpeed, lateralLimit,
  speedOf, tractionThrottle, tyreGrip,
} from './physics'

/** Everything about a driver that does not change during a race. */
export interface DriverTraits {
  /** How close to the car's limit they habitually run, 0..1. */
  pace: number
  /** Willingness to commit to a move that might not come off. */
  aggression: number
  /** How hard they will defend, and how early they move to do it. */
  defence: number
  /** Low means the inputs wander: mistakes, and worse ones under pressure. */
  consistency: number
  /** Judgement: how well their commitment matches what the car can do. */
  racecraft: number
  /** How much they lift to look after the tyres. */
  tyreCare: number
  /** Seconds before they act on something new. */
  reaction: number
}

export const AVERAGE_DRIVER: DriverTraits = {
  pace: 0.80, aggression: 0.55, consistency: 0.80,
  racecraft: 0.70, defence: 0.60, tyreCare: 0.55, reaction: 0.24,
}

/** What a driver can see of everybody else. Filled in by the race. */
export interface Neighbour {
  car: number
  /** Metres of road between the two cars: positive is ahead. */
  gap: number
  /** Where they are across the road, m left of the centreline. */
  offset: number
  speed: number
  /** Their lateral position relative to this car's, m. */
  lateral: number
  inPit: boolean
}

export interface RaceView {
  ahead: Neighbour | null
  behind: Neighbour | null
  /** The nearest car level with this one, which is a wall you cannot cross. */
  alongside: Neighbour | null
  /**
   * The nearest car ahead that is actually in the way.
   *
   * Not the same as `ahead`: on a grid, and any time two cars run side by
   * side, the closest car by distance round the lap is in the *other* lane and
   * is not blocking anybody, while the one that is blocking is further away.
   * Following the wrong one means either brake-checking for a car that is not
   * there, or -- much worse -- driving into the one that is.
   */
  blocker: Neighbour | null
  /**
   * A place across the road to hold rather than the line, and how strongly.
   *
   * Used for the run to the first corner: twenty cars all want the same line
   * from twenty different grid slots, and if they all take it at once they
   * take it through each other. Real drivers hold their column and converge.
   */
  laneHold: number | null
  laneWeight: number
  /** Session time, s. */
  now: number
  /** Whether the flap may be opened here. */
  drsAllowed: boolean
  /** Grip of whatever is under the car right now, as a fraction of asphalt. */
  gripFactor: number
  /** Downforce multiplier from the car in front's wake. */
  wake: number
  /** Yellow flags: no overtaking, and slow down. */
  caution: number
  /** Metres of pit lane speed limit, or null on the circuit. */
  speedLimit: number | null
}

/** What the driver is trying to do, which is worth showing on screen. */
export type Intent =
  | 'clear' | 'closing' | 'attacking' | 'defending'
  | 'switchback' | 'recovering' | 'pitting' | 'cruising'

export interface DriverReport {
  intent: Intent
  line: LineId
  /** Above one means braking later than the car can take. */
  commitment: number
  /** Target speed for the road just ahead, m/s. */
  target: number
  /** Metres to the next braking point; negative once past it. */
  toBraking: number
  /** How much brake the plan asked for, before the friction circle took its cut. */
  brakeDemand: number
  /** Fraction of the grip circle the corner is already using. */
  lateralDemand: number
  /** Set on the step a mistake is made, for the race to turn into an event. */
  mistake: null | 'lockup' | 'snap' | 'wide' | 'missed-apex'
}

/** A small deterministic noise source, one per driver. */
function makeRng(seed: number) {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** How far ahead the driver looks for a corner, s. */
const PLAN_HORIZON = 6.5
/** Below this gap, a driver is racing rather than following. */
const FIGHT_GAP = 26
/** A move is only worth trying where there is room to complete it. */
const MIN_PASSING_RADIUS = 55

/** The least of its braking a car is ever assumed to be able to use. */
const MIN_BRAKE_EFFICIENCY = 0.12

/** How fast a driver will let the car go while rejoining, m/s. */
const REJOIN_SPEED = 26

export class Driver {
  circuit: Circuit
  lines: LineSet
  spec: CarSpec
  traits: DriverTraits
  car: number

  /** Which line the driver wants to be on, and how far across to it it is. */
  line: LineId = 'racing'
  private blend = 1
  private blendFrom: LineId = 'racing'

  /** How much beyond the ideal braking point this driver is going, this corner. */
  commitment = 1
  intent: Intent = 'clear'
  /** Car number being raced, if any. */
  target: number | null = null

  /** Set while the driver is recovering from a spin or an excursion. */
  recovering = 0
  /** Corner index the current plan was made for. */
  private plannedCorner = -1
  private nextDecision = 0
  private rng: () => number
  private steerNoise = 0
  private noiseTimer = 0
  /** This corner's helping of bravery with the throttle, re-drawn per corner. */
  private throttleNerve = 0
  private lastMistake: DriverReport['mistake'] = null
  /** Laps since this driver was passed, which is what sets up a switchback. */
  private passedRecently = 0

  constructor(
    circuit: Circuit, lines: LineSet, spec: CarSpec, traits: DriverTraits,
    car: number, seed: number,
  ) {
    this.circuit = circuit
    this.lines = lines
    this.spec = spec
    this.traits = traits
    this.car = car
    this.rng = makeRng(seed * 2654435761 + 12345)
  }

  /** Set while the car is in the pit lane: it overrides every other line. */
  pitLine: Line | null = null

  private path(id: LineId): Line {
    return this.pitLine ?? this.lines[id]
  }

  /** The offset the driver is aiming for at a sample, mid line-change. */
  private aimOffset(i: number): number {
    const to = this.path(this.line).off[this.circuit.wrap(i)]
    if (this.blend >= 1) return to
    const from = this.path(this.blendFrom).off[this.circuit.wrap(i)]
    return lerp(from, to, this.blend)
  }

  /**
   * Where across the road the driver is actually trying to be, all in.
   *
   * The line, plus where the fight wants the car, plus the grid column on the
   * run to the first corner -- and then clamped by whoever is alongside,
   * because a car level with yours is a wall. That clamp is not politeness:
   * without it every start is twenty cars converging on one line through each
   * other, and every fight ends in the barriers.
   */
  private targetOffset(i: number, view: RaceView, here: number): number {
    let aim = this.aimOffset(i) + this.lateralBias(view)
    if (view.laneHold !== null && view.laneWeight > 0) {
      aim = lerp(aim, view.laneHold, view.laneWeight)
    }
    // Rejoining, the driver aims only a little way back toward the line each
    // time, which is a shallow angle back onto the road rather than a dive
    // across it.
    if (this.recovering > 0) aim = lerp(here, aim, 0.3)

    const beside = view.alongside
    if (beside && Math.abs(beside.lateral) < CAR_WIDTH * 1.6) {
      const theirs = here + beside.lateral
      const room = CAR_WIDTH * 1.05
      if (beside.lateral > 0) aim = Math.min(aim, theirs - room)
      else aim = Math.max(aim, theirs + room)
    }
    // But never off the road to avoid somebody. A driver being leaned on runs
    // out of room and lifts; they do not drive into the gravel to make space,
    // and a model that lets them puts half the field in the run-off on lap one.
    //
    // "The road" includes the pit lane when the car is committed to it. Left
    // out, this clamp pinned every pitting car to the white line, none of them
    // ever reached the lane, and the whole field queued at the edge of the
    // circuit and drove into each other -- which was, in the end, every
    // incident in the race.
    const edge = this.circuit.limit(i)
    if (this.pitLine) {
      const lane = this.pitLine.off[this.circuit.wrap(i)]
      return clamp(aim, Math.min(-edge, lane - 3), Math.max(edge, lane + 3))
    }
    return clamp(aim, -edge, edge)
  }

  /** Curvature of the path the driver is actually taking, mid line-change. */
  private aimCurvature(i: number): number {
    const to = this.path(this.line).k[this.circuit.wrap(i)]
    if (this.blend >= 1) return to
    const from = this.path(this.blendFrom).k[this.circuit.wrap(i)]
    return lerp(from, to, this.blend)
  }

  private switchTo(id: LineId): void {
    if (id === this.line) return
    // Where the car is now becomes the start of the move across, so a line
    // change is a manoeuvre with a beginning rather than a jump.
    this.blendFrom = this.line
    this.line = id
    this.blend = 0
  }

  /**
   * Decide what to do, then do it.
   *
   * Called every physics step. The *decisions* are re-taken a few times a
   * second -- a driver does not re-plan a corner at 120 Hz -- but the control
   * outputs are computed every step, because a steering correction that only
   * arrives every tenth of a second is a driver asleep at the wheel.
   */
  control(
    state: CarState, view: RaceView, at: { i: number; s: number; lat: number }, dt: number,
  ): { controls: Controls; report: DriverReport } {
    const v = speedOf(state)
    const mass = this.spec.mass + state.fuel
    const mu = this.spec.grip * view.gripFactor * tyreGrip(state)
    this.lastIndex = at.i
    // Plan on the air the driver expects to have, not the air it has this
    // instant. A car that will still be in somebody's wake at the apex has to
    // brake for the downforce it will have *there*, and one that plans on the
    // clean air it happens to be in at the braking point arrives at the apex
    // with a third less of it than it counted on -- which is a corner exit in
    // the run-off, and it is the single most common way this field used to
    // lose cars.
    const planWake =
      view.ahead && !view.ahead.inPit && view.ahead.gap < 90
        ? Math.min(view.wake, 0.82)
        : view.wake
    view = view.wake === planWake ? view : { ...view, wake: planWake }

    this.lastMistake = null
    if (view.now >= this.nextDecision) {
      this.nextDecision = view.now + 0.12 + this.traits.reaction * 0.4
      this.decide(state, view, at, v)
    }

    // Crossing to a new line takes road: about a car's width every hundred
    // metres, which is what a real move across looks like from above.
    if (this.blend < 1) this.blend = Math.min(1, this.blend + (v * dt) / 90)

    // -- where to point the car ---------------------------------------------
    //
    // Three terms, and each of them is doing a different job.
    //
    // **Feed-forward.** The steering angle a car of this wheelbase needs to
    // follow a path of this curvature, which is a geometric fact and not a
    // gain: `atan(L * kappa)`. On its own it drives the corner correctly and
    // drifts, because nothing corrects the error it accumulates.
    //
    // **Heading.** How far the car is pointing away from where the line is
    // going. This is what turns the car in and what stops it turning in.
    //
    // **Cross-track.** How far the car is from the line, divided by the speed
    // -- so a metre out at forty is a large correction and at ninety a small
    // one. Without it a car through an esse lags the line by a third of a
    // second, arrives at each direction change already on the wrong side, and
    // has to use more grip than the corner needs just to get back.
    //
    // Together they are a standard path follower. Pure pursuit alone was not:
    // it cut every entry and ran wide at every exit, and at the exit the line
    // is already at the edge of the road.
    const previewM = clamp(v * 0.30, 6, 26)
    const i0 = at.i + Math.round(previewM / this.circuit.ds)
    const i1 = i0 + Math.max(2, Math.round(6 / this.circuit.ds))
    const o0 = this.targetOffset(i0, view, at.lat)
    const o1 = this.targetOffset(i1, view, at.lat)
    const p0 = this.circuit.place(this.circuit.s[this.circuit.wrap(i0)], o0)
    const p1 = this.circuit.place(this.circuit.s[this.circuit.wrap(i1)], o1)
    const pathHeading = Math.atan2(p1.y - p0.y, p1.x - p0.x)
    const headingError = wrapAngle(pathHeading - state.yaw)
    const crossError = at.lat - this.targetOffset(at.i, view, at.lat)

    const wheelbase = this.spec.frontAxle + this.spec.rearAxle
    const curvature = this.aimCurvature(i0)
    const feedForward = Math.atan(wheelbase * curvature)

    // Steering noise: the hands are not perfect, and they are worse when the
    // driver is being pressured or is over the limit.
    this.noiseTimer -= dt
    if (this.noiseTimer <= 0) {
      this.noiseTimer = 0.18 + this.rng() * 0.3
      const jitter = (1 - this.traits.consistency) * 0.022 + Math.max(0, this.commitment - 1) * 0.035
      this.steerNoise = (this.rng() - 0.5) * 2 * jitter
    }

    let steer = clamp(
      feedForward +
        headingError * 0.60 +
        Math.atan2(-crossError * 2.2, Math.max(v, 12)) +
        this.steerNoise,
      -0.35, 0.35,
    )

    // -- how fast to be going -----------------------------------------------
    const plan = this.speedPlan(state, view, at, v, mass, mu)
    let throttle = 0
    let brake = 0
    const error = plan.target - v

    if (plan.brakeDemand > 0) {
      brake = clamp(plan.brakeDemand, 0, 1)
      // Trail braking, done the way the tyre requires: one grip budget, spent
      // on stopping and turning together. Whatever fraction of it the corner
      // is already using laterally is not available to brake with, so the
      // pedal comes off as the car turns in -- and a driver who does not do
      // this arrives at the apex having asked the rear axle for more than it
      // has, which is a spin, every corner, all race.
      const lateralUse = clamp(plan.lateralDemand, 0, 1)
      const room = Math.sqrt(Math.max(0, 1 - lateralUse * lateralUse))
      // How near the edge of that circle a driver dares run is car control.
      brake *= lerp(room * 0.86, room, this.traits.racecraft)
    } else if (error > 0) {
      throttle = clamp(error * 0.5, 0, 1)
      // Coming out of a corner the driver feeds it in rather than switching it
      // on. How near the traction limit they dare sit is car control -- and a
      // driver who oversteps it gets wheelspin and then the back end, because
      // that is what the tyre model does with more torque than it has grip.
      // The same one grip budget as the brakes, spent the other way. Getting
      // on the power at the apex means asking the rear for drive while it is
      // still making most of the cornering force, and the room left is
      // whatever the friction circle has not already sold.
      // Only once the car is actually going. At walking pace the yaw rate this
      // is read from is huge and meaningless -- a car turning in its own
      // length reads as being at the limit -- and a car that will not open the
      // throttle at walking pace is a car that never gets going again.
      const lateralUse = v > 10 ? clamp(plan.lateralDemand, 0, 1) : 0
      const room = Math.sqrt(Math.max(0, 1 - lateralUse * lateralUse))
      const grip = tractionThrottle(this.spec, mass, v, mu, view.wake)
      // How near the edge a driver dares run, and how well they judge it. A
      // number above one is a driver who has asked for more than the tyre has
      // and is about to find out -- which some of them do, some laps.
      const nerve = 0.90 + this.traits.racecraft * 0.13 + this.throttleNerve
      throttle = Math.min(throttle, Math.max(0.06, grip * room * nerve))
    } else {
      brake = clamp(-error * 0.06, 0, 0.35)
    }

    // The pit limiter is a hard ceiling on speed, not a replacement for
    // driving: it takes the throttle away above the limit and nothing else.
    // Handled as an override it also overrode the car in front, and the whole
    // field drove into the back of whoever was stopped in their box.
    if (view.speedLimit !== null && v > view.speedLimit) throttle = 0


    // -- what the car is telling the driver ---------------------------------
    // The car is sliding when its velocity no longer points where its nose
    // does, and the answer to that is always the same: put the front wheels
    // where the car is actually going. In understeer that unwinds the lock,
    // which is what lets the front tyre come back under its peak; in oversteer
    // it is opposite lock. One correction, two names.
    //
    // The sign here is not cosmetic. Applied the other way round it adds lock
    // to a front tyre that is already past its peak, and every car in the
    // field understeers off at the first corner -- which is exactly what it
    // did until this was fixed.
    const slide = Math.atan2(state.vy, Math.max(state.vx, 1))
    const tolerated = 0.07
    const excess = slide - clamp(slide, -tolerated, tolerated)
    if (excess !== 0 && v > 8) {
      const skill = 0.55 + this.traits.racecraft * 0.75
      steer = clamp(steer + excess * skill, -0.42, 0.42)
      if (Math.abs(slide) > 0.28) {
        this.lastMistake = 'snap'
        throttle *= 0.25
      }
    }

    // And the other half of it: never ask the front for more than it has.
    //
    // A tyre's lateral force peaks at a slip angle and *falls away* past it,
    // so a driver who answers understeer with more lock gets less grip, runs
    // wider, adds more lock, and is in the run-off -- a stable spiral the car
    // cannot recover from because every step of it feels like the right thing
    // to do. What a real driver does is unwind to the angle the tyre is
    // actually happiest at, and wait for the front to bite.
    //
    // How completely they do it is skill. Overdriving the front is the most
    // common thing a slower driver does, and here it costs exactly what it
    // costs in reality: corner exit speed.
    if (v > 10) {
      const slipAngle = Math.atan2(
        state.vy + this.spec.frontAxle * state.yawRate, Math.max(state.vx, 3),
      )
      const peak = Math.atan(Math.tan(Math.PI / (2 * this.spec.tyreC)) / this.spec.tyreB)
      const allowance = peak * (1 + (1 - this.traits.racecraft) * 0.55)
      const demanded = slipAngle - steer
      if (Math.abs(demanded) > allowance) {
        const ideal = slipAngle - Math.sign(demanded) * allowance
        steer = lerp(steer, ideal, 0.4 + this.traits.racecraft * 0.5)
        this.lastMistake = this.lastMistake ?? 'missed-apex'
      }
    }

    // -- rejoining ----------------------------------------------------------
    // A car that has been off does not simply resume. It slows right down,
    // waits until it is pointing the right way, and comes back on at a shallow
    // angle. Skipping any of that is how one excursion becomes four: a car
    // that drives off the grass at ninety km/h and forty degrees of slip finds
    // grip all at once and spins, off it goes again, and the incident feeds on
    // itself for the rest of the race.
    if (this.recovering > 0) {
      this.recovering -= dt
      // Sliding fast: hands off everything and let it settle. Otherwise crawl
      // back on -- and *always* crawl, because a driver who will not touch the
      // throttle until the car is perfectly straight never moves again on
      // grass, and a car that never moves again is a retirement.
      const sliding = Math.abs(slide) > 0.30 && v > 12
      throttle = sliding ? 0 : Math.max(Math.min(throttle, 0.45), v < 11 ? 0.25 : 0)
      if (v > REJOIN_SPEED) brake = Math.max(brake, 0.3)
      else brake = 0
    }

    const drs = view.drsAllowed && brake === 0 && Math.abs(this.circuit.k[at.i]) < 1 / 900

    return {
      controls: { steer, throttle, brake, drs },
      report: {
        intent: this.intent,
        line: this.line,
        commitment: this.commitment,
        target: plan.target,
        toBraking: plan.toBraking,
        brakeDemand: plan.brakeDemand,
        lateralDemand: plan.lateralDemand,
        mistake: this.lastMistake ?? plan.mistake,
      },
    }
  }

  /**
   * How fast to be going, and whether to be on the brakes yet.
   *
   * The backward pass, done forwards and on the fly.  For every piece of road
   * within the planning horizon the driver works out, from *its own car's*
   * mass, downforce and tyre state, how fast that piece can be taken -- and
   * then how fast it could be going *here* and still get down to that:
   *
   *     allowed = sqrt(v_corner^2 + 2 a_brake d)
   *
   * The smallest of those is the speed for right now.  It falls smoothly as
   * the corner comes, which is what a braking zone is; the sample that
   * produced it is the braking point, and how far away it is is what the
   * driver is actually looking at.
   *
   * Nothing is precomputed, so a car on worn tyres genuinely brakes earlier
   * than the same car did ten laps ago, and a car in another's wake brakes
   * earlier than one in clean air -- because the downforce term in
   * `corneringSpeed` is smaller and the driver can feel it.
   */
  private speedPlan(
    state: CarState, view: RaceView, at: { i: number; s: number },
    v: number, mass: number, mu: number,
  ): {
    target: number
    brakeDemand: number
    /** Fraction of the tyres' grip the corner here is already using. */
    lateralDemand: number
    toBraking: number
    mistake: DriverReport['mistake']
  } {
    const circuit = this.circuit
    const horizon = Math.max(70, v * PLAN_HORIZON)
    const steps = Math.min(circuit.n - 1, Math.round(horizon / circuit.ds))
    // Every fifth metre or so: finer than that is planning detail the car
    // cannot act on, and this runs for every car several times a second.
    const stride = Math.max(1, Math.round(5 / circuit.ds))
    const available = brakingLimit(this.spec, mass, v, mu, view.wake)

    const hereRadius = 1 / Math.max(Math.abs(this.aimCurvature(at.i)), 1e-6)
    let target = corneringSpeed(this.spec, mass, hereRadius, mu, view.wake)
    let bindLimit = target
    let bindDistance = 0
    let bindBrake = available

    // Running mean of how bent the road is between here and wherever the scan
    // has got to, which is what says how much of the braking is done straight.
    let bendSum = 0
    let bendCount = 0

    for (let q = 2; q <= steps; q += stride) {
      const i = circuit.wrap(at.i + q)
      const bend = Math.abs(this.aimCurvature(i))
      bendSum += bend
      bendCount++
      const radius = 1 / Math.max(bend, 1e-6)
      if (radius > 2500) continue
      const limit = corneringSpeed(this.spec, mass, radius, mu, view.wake)
      if (limit >= this.spec.vMax) continue
      const distance = q * circuit.ds

      // How hard the car can brake over the *whole* zone, not at the speed it
      // happens to be doing now, and not as though the zone were straight.
      //
      // Two things make the entry figure a lie. Braking is a downforce effect
      // and downforce goes as the square of speed, so a car that pulls five g
      // from three hundred pulls barely two by the time it is down to a
      // hundred -- hence the mean speed. And a braking zone that is itself
      // curved has already sold part of the tyre to the corner, so there is
      // less of it left to stop with; into a fast corner that follows a bend,
      // almost none. Planning either of those as though it were not true is
      // how a car arrives at a corner a hundred km/h too fast with no grip
      // left to do anything about it.
      const meanSpeed = (v + limit) * 0.5
      const meanBend = bendSum / bendCount
      const latMax = Math.max(1, lateralLimit(this.spec, mass, meanSpeed, mu, view.wake))
      const latUse = clamp((meanBend * meanSpeed * meanSpeed) / latMax, 0, 0.985)
      const efficiency = Math.max(MIN_BRAKE_EFFICIENCY, Math.sqrt(1 - latUse * latUse))
      const brake = brakingLimit(this.spec, mass, meanSpeed, mu, view.wake) * efficiency

      // Commitment is the whole risk model in one number. At one the driver
      // brakes where the car can stop; above one they brake where they *wish*
      // it could, and the corner arrives before the speed does.
      const believed = brake * this.commitment
      const allowed = Math.sqrt(limit * limit + 2 * believed * distance)
      if (allowed < target) {
        target = allowed
        bindLimit = limit
        bindDistance = distance
        bindBrake = brake
      }
    }

    // And the car in front, which is a corner that moves.
    //
    // Exactly the same backward pass: how fast could this car be going here
    // and still be down to *their* speed by the time it reaches them. It is
    // what makes traffic cost time, and it is the reason nobody drives through
    // anybody -- not a rule saying they may not, but a driver who can see a
    // car in front and does the arithmetic.
    const inFront = view.blocker
    if (inFront && !inFront.inPit && inFront.gap > 0 && inFront.gap < 140) {
      {
        const attacking = this.intent === 'attacking' || this.intent === 'switchback'
        // The gap a driver actually holds is a time, not a distance -- half a
        // second at any speed. An attacker holds less of it, which is how it
        // gets close enough to have a look and why it is in the dirty air.
        const timeGap = attacking ? 0.14 : 0.30 + (1 - this.traits.aggression) * 0.40
        const desired = CAR_LENGTH * (attacking ? 1.05 : 1.3) + v * timeGap
        // Settle onto that gap smoothly: match their speed, plus a bit for
        // however far off the gap is. Braking hard every time somebody is a
        // metre closer than ideal is what locks a front wheel.
        const settle = Math.max(0, inFront.speed + (inFront.gap - desired) * 0.9)
        // And underneath it, the same backward pass as for a corner, for when
        // the gap really has gone: how fast could this car be going and still
        // be down to theirs before it reaches them.
        const room = Math.max(0.3, inFront.gap - CAR_LENGTH * 1.15)
        const closing = brakingLimit(
          this.spec, mass, (v + inFront.speed) * 0.5, mu, view.wake,
        ) * 0.85
        const emergency = Math.sqrt(inFront.speed * inFront.speed + 2 * closing * room)
        const held = Math.min(settle, emergency)
        if (held < target) {
          target = held
          bindLimit = inFront.speed
          bindDistance = room
          bindBrake = closing
        }
      }
    }

    // Rejoining after an excursion: slowly, and looking over your shoulder.
    if (this.recovering > 0 && target > REJOIN_SPEED) {
      target = REJOIN_SPEED
      bindLimit = REJOIN_SPEED
      bindDistance = Math.max(bindDistance, 1)
    }

    // The pit lane's own limit is just another thing that caps the speed here.
    if (view.speedLimit !== null && view.speedLimit < target) {
      target = view.speedLimit
      bindLimit = view.speedLimit
      bindDistance = Math.max(bindDistance, 1)
    }

    // The driver's own pace: not everybody runs the car to its limit, and
    // nobody does it while nursing a set of tyres to the end of a stint.
    const nursing = Math.max(0, state.tyreWear - 0.6) * 0.12 * (1 - this.traits.tyreCare)
    // Racing somebody wheel to wheel costs speed, and it costs it here rather
    // than in a penalty applied afterwards: a driver who cannot use all of the
    // road -- because there is a car in the rest of it -- cannot carry the
    // speed the road would allow, and one who tries is the driver who runs
    // wide at the exit with somebody alongside.
    // Racing costs speed, and it costs it here rather than in a penalty applied
    // afterwards. A driver who cannot use all of the road -- because there is a
    // car in the rest of it -- cannot carry the speed the road would allow, and
    // one who tries is the driver who runs wide at the exit with somebody
    // alongside. Traffic anywhere near also makes the limit less knowable, and
    // a driver who cannot be sure of the limit leaves more of it alone.
    const near = view.ahead && !view.ahead.inPit && view.ahead.gap < 70
    const crowded = (view.alongside ? 0.09 : 0) + (near ? 0.06 : 0)
    // Nobody drives at a hundred per cent of a computed limit. The limit is not
    // known exactly -- the tyre is a little different every lap, the air is
    // never quite clean, the road is never quite the same -- so a driver runs
    // at a margin inside it and spends the margin when they choose to. Without
    // one, a long constant-radius corner is five seconds at the absolute edge
    // and the first perturbation of any kind puts the car in the run-off.
    const pace =
      (0.925 + this.traits.pace * 0.048) * (1 - nursing) * (1 - view.caution * 0.20) *
      (1 - crowded)
    target *= pace

    // What it would take to be at the binding speed by the time we reach it.
    let demand = 0
    let toBraking = 9999
    if (bindDistance > 0 && v > bindLimit) {
      const required = (v * v - bindLimit * bindLimit) / (2 * Math.max(bindDistance, 1))
      // Pedal, not deceleration: a driver pushes with a force, and the force
      // that gives the deceleration they want is mass times it. Mapping it
      // this way is what lets a driver brake hard without locking a wheel --
      // and what makes the pedal saturate, and the wheel lock, exactly when
      // they have asked for more than the car has.
      // Not all of the pedal. A driver brakes as hard as they trust themselves
      // to, and trusting yourself to stand on it right up to the point the
      // front tyre lets go is a skill -- so the ceiling is one. Without it
      // every car in the field flat-spots a tyre at the heaviest stop on the
      // lap, every lap, because the plan asks for the whole pedal there.
      const ceiling = 0.88 + this.traits.racecraft * 0.14
      demand = clamp((required * mass) / this.spec.brakeForce, 0, ceiling)
      const stopping = (v * v - bindLimit * bindLimit) / (2 * Math.max(bindBrake * this.commitment, 1))
      toBraking = bindDistance - stopping
    }
    // Off the profile entirely -- too fast for the road that is here, not just
    // for the road that is coming. Stand on it.
    if (v > target + 0.5) {
      demand = Math.max(demand, clamp(((v - target) * 9 * mass) / this.spec.brakeForce, 0, 1))
    }

    // Arriving needing more than the car has is what over-committed means. It
    // is reported, not corrected: what happens next is the physics running
    // wide, and that is the point of letting a driver be wrong.
    const mistake: DriverReport['mistake'] =
      bindDistance > 0 && bindDistance < 110 &&
      (v * v - bindLimit * bindLimit) / (2 * Math.max(bindDistance, 1)) > bindBrake * 1.05
        ? 'wide'
        : null

    // How much of the grip circle the car is *actually* spending on turning
    // right now -- read off its own yaw rate rather than off the line it is
    // supposed to be on, because a driver feels the corner they are in and not
    // the one they meant to take.
    const lateralNow = Math.abs(v * state.yawRate)
    const lateralMax = Math.max(1, lateralLimit(this.spec, mass, v, mu, view.wake))
    return {
      target,
      brakeDemand: demand,
      lateralDemand: lateralNow / lateralMax,
      toBraking,
      mistake,
    }
  }

  /**
   * Where to sit across the road relative to whoever is being raced.
   *
   * The line says where the road wants the car; this says where the *fight*
   * wants it. Sitting a little offset in traffic is not decoration -- it is
   * how a driver gets air over the front wing and how they show a wheel.
   */
  private lateralBias(view: RaceView): number {
    const ahead = view.ahead
    if (!ahead || ahead.gap > FIGHT_GAP || ahead.inPit) return 0
    if (this.intent === 'attacking' || this.intent === 'switchback') return 0
    // Ease out of the dirty air, toward whichever side has more room -- and
    // only a little, and much less in a corner. The driver plans its speed
    // from the *line's* curvature, so the further it sits from the line the
    // less that plan is about the path it is actually on.
    const side = ahead.lateral >= 0 ? -1 : 1
    const closeness = clamp(1 - ahead.gap / FIGHT_GAP, 0, 1)
    const bending = Math.abs(this.circuit.k[this.circuit.wrap(this.lastIndex)]) > 1 / 400
    return side * closeness * 0.9 * (bending ? 0.3 : 1)
  }

  /** Where the car was last located, for the bits that need it out of band. */
  private lastIndex = 0

  /**
   * The decision: which line to be on, and how hard to commit to it.
   *
   * Everything here is about a *corner*, because that is where positions
   * change. The driver looks at the next braking zone, at who is where, and
   * picks the path that gets it the place -- or keeps it.
   */
  private decide(
    _state: CarState, view: RaceView, at: { i: number; s: number; lat: number }, v: number,
  ): void {
    const circuit = this.circuit
    const t = this.traits
    const cornerAhead = this.nextCorner(at.i)
    const distanceToCorner = cornerAhead
      ? ((cornerAhead.from - at.i + circuit.n) % circuit.n) * circuit.ds
      : Infinity

    // A plan is made once per corner, on the approach, and then lived with --
    // which is why a lunge that goes wrong stays gone wrong.
    const planning = cornerAhead !== null && distanceToCorner < Math.max(90, v * 3.2)
    const isNewCorner = cornerAhead !== null && cornerAhead.index !== this.plannedCorner

    if (this.recovering > 0) {
      this.intent = 'recovering'
      this.switchTo('racing')
      this.commitment = 0.9
      return
    }

    const ahead = view.ahead
    const behind = view.behind

    // -- am I being raced? ---------------------------------------------------
    const threatened =
      behind !== null && !behind.inPit && -behind.gap < FIGHT_GAP * 1.4 &&
      behind.speed > v - 3 && view.caution < 0.5

    // -- am I racing anybody? ------------------------------------------------
    const chasing = ahead !== null && !ahead.inPit && ahead.gap < FIGHT_GAP * 2.2

    if (!planning || cornerAhead === null) {
      // On a straight: line up behind, take the tow, and get to whichever side
      // the corner is going to be entered from.
      this.commitment = 1
      if (chasing && ahead && ahead.gap < FIGHT_GAP) {
        this.intent = 'closing'
        this.target = ahead.car
      } else {
        this.intent = ahead && ahead.gap < FIGHT_GAP * 3 ? 'closing' : 'clear'
        this.target = null
      }
      if (this.line !== 'racing' && !threatened) this.switchTo('racing')
      if (threatened && this.line !== 'defend' && t.defence > 0.35 && view.caution < 0.5) {
        // Covering the inside on the straight before the braking zone.
        this.switchTo('defend')
        this.intent = 'defending'
      }
      return
    }

    if (isNewCorner) this.plannedCorner = cornerAhead.index

    const passable = cornerAhead.radius > MIN_PASSING_RADIUS || cornerAhead.entryStraight > 200
    const room = circuit.limit(cornerAhead.apex) * 2

    // -- defending -----------------------------------------------------------
    if (threatened && view.caution < 0.5) {
      // The defender takes the inside if it thinks it is genuinely under
      // threat. It costs exit speed -- and that cost is charged by the
      // defensive line's own smaller exit radius, not by a penalty.
      const pressure = clamp(1 + (behind!.gap + FIGHT_GAP) / FIGHT_GAP, 0, 1)
      if (t.defence > 0.3 && pressure > 0.25) {
        this.switchTo('defend')
        this.intent = 'defending'
        this.commitment = 1 + (t.aggression - 0.5) * 0.05
        // Pressure makes mistakes: the driver in front is looking in a mirror.
        if (this.rng() < (1 - t.consistency) * 0.05 * pressure) {
          this.commitment += 0.10 + this.rng() * 0.10
        }
        return
      }
    }

    // -- attacking -----------------------------------------------------------
    if (chasing && ahead && view.caution < 0.5) {
      this.target = ahead.car
      const closing = v - ahead.speed
      // Where the gap will be by the time both cars are at the braking point.
      const timeToCorner = distanceToCorner / Math.max(v, 1)
      const projected = ahead.gap - closing * timeToCorner
      const roomToPass = room > 9 && passable

      // Is there a hole? A move is on when the attacker will be close enough
      // at turn-in that it can be alongside by the apex, and there is road to
      // be alongside on.
      const canReach = projected < 14 && projected > -2
      const worthTrying = closing > -1.5 || view.drsAllowed || ahead.gap < 8

      if (canReach && roomToPass && worthTrying) {
        // Which side is free? The defender has usually taken the inside.
        const insideOffset = cornerAhead.dir * circuit.limit(cornerAhead.apex)
        const defenderInside = Math.sign(ahead.offset) === Math.sign(insideOffset) &&
          Math.abs(ahead.offset) > circuit.limit(cornerAhead.apex) * 0.45

        if (!defenderInside) {
          this.switchTo('dive')
          this.intent = 'attacking'
        } else if (t.aggression > 0.62 && cornerAhead.radius > 90) {
          // The inside is shut. Around the outside is a real option in a fast
          // corner and a bad idea in a slow one, and the driver knows which.
          this.switchTo('outside')
          this.intent = 'attacking'
        } else {
          // Take the exit instead: give up the entry, be on the power first.
          this.switchTo('switchback')
          this.intent = 'switchback'
        }

        // How much is this worth? A driver who has been stuck for laps, or who
        // is simply brave, brakes later than the car can really take.
        const desperation = clamp((this.passedRecently > 0 ? 0.3 : 0) + (ahead.gap < 6 ? 0.3 : 0), 0, 0.6)
        const brave = t.aggression * 0.9 + desperation
        const judgement = t.racecraft
        // Commitment above one is a car that will not stop in time. How far
        // above is how brave the driver is, less how good their judgement is,
        // plus the day they are having.
        this.commitment = 1 + (brave - judgement * 0.85) * 0.16 + (this.rng() - 0.45) * 0.09 * (1 - t.consistency)
        this.commitment = clamp(this.commitment, 0.94, 1.18)
        return
      }

      // Close, but nothing on: follow, keep out of the worst of the air, and
      // be ready. Following costs downforce and it costs certainty, so the
      // plan is a little slower and the braking a little earlier.
      this.intent = 'closing'
      this.switchTo('racing')
      this.commitment = clamp(0.965 + t.aggression * 0.03, 0.94, 1.02)
      return
    }

    // -- clear air -----------------------------------------------------------
    this.intent = view.caution > 0.5 ? 'cruising' : 'clear'
    this.target = null
    this.switchTo('racing')
    // Even alone, nobody hits the same braking point twice. This is the whole
    // of the consistency model on a clear lap, and it is why lap times differ.
    if (isNewCorner) {
      const wobble = (1 - t.consistency) * 0.055
      this.commitment = clamp(1 + (this.rng() - 0.5) * 2 * wobble, 0.9, 1.14)
    }
    this.throttleNerve = (this.rng() - 0.5) * (1 - t.consistency) * 0.14
  }

  /** The next corner the car will reach, or null if it is already in one. */
  private nextCorner(i: number) {
    const circuit = this.circuit
    const here = circuit.cornerAt[i]
    if (here >= 0) return circuit.corners[here]
    let best = null
    let bestGap = Infinity
    for (const cn of circuit.corners) {
      const gap = ((cn.from - i + circuit.n) % circuit.n) * circuit.ds
      if (gap < bestGap) { bestGap = gap; best = cn }
    }
    return best
  }

  /** Told by the race when this driver loses a place, which sets up a reply. */
  notePassed(): void {
    this.passedRecently = 2
  }

  noteLap(): void {
    if (this.passedRecently > 0) this.passedRecently--
  }

  /** Told by the race when the car has left the circuit or spun. */
  noteExcursion(seconds: number): void {
    this.recovering = Math.max(this.recovering, seconds)
    this.commitment = 0.92
  }
}

/**
 * Turn a game driver's ratings into the traits the model uses.
 *
 * The game stores skills as fractions, but the same shape of data turns up
 * scaled to a hundred elsewhere, so the scale is detected rather than assumed:
 * a driver silently rated at 0.009 instead of 0.9 is a driver who cannot drive,
 * and it would look like a bug in the physics.
 */
export function traitsFrom(skills: Record<string, number>, form = 0): DriverTraits {
  const values = Object.values(skills).filter((v) => typeof v === 'number')
  const scale = values.some((v) => v > 1.5) ? 1 / 100 : 1
  const get = (key: string, fallback: number) => {
    const raw = skills[key]
    return typeof raw === 'number' ? clamp(raw * scale, 0, 1) : fallback
  }
  const racecraft = get('racecraft', 0.7)
  return {
    pace: clamp(get('pace', 0.8) + form * 0.05, 0.35, 1),
    aggression: get('overtaking', 0.55),
    consistency: get('consistency', 0.8),
    racecraft,
    defence: get('defending', 0.6),
    tyreCare: get('tyre_management', 0.55),
    reaction: clamp(0.34 - racecraft * 0.16, 0.12, 0.36),
  }
}

/** A car spec scaled by a team's performance, 0..1. */
export function specFrom(performance: number, powerBias = 0.5): CarSpec {
  const p = clamp(performance, 0, 1)
  return {
    ...BASE_CAR,
    power: BASE_CAR.power * (0.90 + p * 0.12 + (powerBias - 0.5) * 0.06),
    liftArea: BASE_CAR.liftArea * (0.86 + p * 0.20 - (powerBias - 0.5) * 0.10),
    dragArea: BASE_CAR.dragArea * (1.03 - p * 0.05 - (powerBias - 0.5) * 0.05),
    grip: BASE_CAR.grip * (0.94 + p * 0.09),
    brakeForce: BASE_CAR.brakeForce * (0.95 + p * 0.08),
  }
}
