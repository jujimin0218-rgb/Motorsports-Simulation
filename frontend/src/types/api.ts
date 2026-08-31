/**
 * The shapes the backend sends.
 *
 * Hand-written rather than generated, and deliberately narrow: these describe
 * what the client actually reads, not everything the server happens to
 * serialise.  Where a field is only ever displayed it is typed as what it is
 * -- a number of millions, a fraction between zero and one -- because the unit
 * is the part that goes wrong.
 */

export interface Circuit {
  id: string
  name: string
  country: string
  city: string
  length_km: number
  corner_count: number
  race_laps: number
  drs_zones: number
  physics_track: string
  characteristics: {
    power_sensitivity: number
    downforce_requirement: number
    tyre_stress: number
    brake_stress: number
    overtaking_ease: number
  }
  /** The venue's climate for the month this round is held in. */
  climate: {
    air_temperature: number
    rain_probability: number
    relative_humidity: number
    wind_speed: number
  }
}

export interface Weather {
  session: string
  air_temperature: number
  track_temperature: number
  rain_intensity: number
  raining: boolean
  cloud_cover: number
  wind_speed: number
  relative_humidity: number
  /** Metres of standing water. */
  water_depth: number
  wet_fraction: number
  rubber: number
}

export interface PenaltyRow {
  round: number
  driver: string
  team: string
  kind: 'time' | 'grid' | 'reprimand'
  reason: string
  seconds: number
  places: number
  lap: number | null
  served: boolean
}

export type RoundPhase =
  | 'not_started'
  | 'practice'
  | 'qualifying'
  | 'strategy'
  | 'race'
  | 'result'
  | 'development'
  | 'complete'

export interface RoundSummary {
  number: number
  circuit: string
  name: string
  laps: number
  phase: RoundPhase
  race_id: string | null
  grid: string[]
}

export interface CalendarEntry extends RoundSummary {
  circuit: string
  race_laps: number
}

/** A calendar row carries the circuit object alongside its id. */
export interface CalendarRow extends Omit<CalendarEntry, 'circuit'> {
  circuit: Circuit
}

export interface CarPerformance {
  aero: number
  chassis: number
  power_unit: number
  mechanical_grip: number
  tyre_management: number
  reliability: number
}

export interface Facilities {
  aerodynamics: number
  power_unit: number
  chassis: number
  reliability: number
  simulator: number
  driver_development: number
}

export interface EngineSupplier {
  id: string
  name: string
  nationality: string
  ice_output: number
  kers_output: number
  fuel_efficiency: number
  cooling: number
  reliability: number
  cost_per_season: number
  works_team: string | null
}

export interface Team {
  id: string
  name: string
  nationality: string
  engine: string
  /** Millions. */
  budget: number
  reputation: number
  car: CarPerformance
  facilities: Facilities
  rd_points: number
  drivers: string[]
  staff: number
  prize_position: number
  season_spending: number
}

export interface TeamRow extends Team {
  engine_name: string
  car_overall: number
  championship_position: number | null
  driver_names: string[]
}

export interface Contract {
  /** Millions per season. */
  salary: number
  seasons_remaining: number
  signing_bonus: number
  performance_bonus: number
  release_clause: number
}

export interface Driver {
  id: string
  name: string
  abbreviation: string
  nationality: string
  age: number
  skills: Record<string, number>
  potential: number
  experience: number
  reputation: number
  form: number
  team: string | null
  contract: Contract | null
  retired: boolean
}

export interface DriverRow extends Driver {
  market_value: number
  overall: number
  championship_position?: number | null
}

export interface DriverStanding {
  position: number
  driver: string
  team: string
  driver_name: string
  team_name: string
  points: number
  wins: number
  podiums: number
  poles: number
  fastest_laps: number
  dnfs: number
  starts: number
  best_finish: number
}

export interface TeamStanding
  extends Omit<DriverStanding, 'driver' | 'driver_name'> {
  team: string
  team_name: string
}

export interface Standings {
  drivers: DriverStanding[]
  teams: TeamStanding[]
}

export interface GameSettings {
  race_distance: number
  difficulty: 'easy' | 'normal' | 'hard'
  hazards: boolean
}

export interface GameSnapshot {
  name: string
  season: number
  seed: number
  settings: GameSettings
  /** Race ids that can be played back.  Only the most recent few are kept. */
  replays: string[]
  autosave_error: string | null
  player_team: string
  /** Rounds in this season's calendar, which a short season cuts down. */
  rounds: number
  season_complete: boolean
  current_round: (RoundSummary & { circuit: Circuit; race_laps: number }) | null
  team: TeamRow & { engine: EngineSupplier }
  drivers: DriverRow[]
  standings: Standings
}

export interface SelectableTeam {
  id: string
  name: string
  nationality: string
  engine: string
  budget: number
  reputation: number
  car_rating: number
  facility_average: number
  drivers: string[]
}

export interface SaveSummary {
  id: string
  slot: string | null
  name: string
  season: number
  round: number
  player_team: string
  created_at: number
  updated_at: number
}

export type JobStatus = 'pending' | 'running' | 'done' | 'failed'

export interface Job<T = unknown> {
  id: string
  kind: string
  status: JobStatus
  progress: number
  detail: string
  started_at: number
  finished_at: number | null
  /** The session as it stands, while it is still running. */
  live?: LiveRace | LiveQualifying
  result?: T
  error?: string
  code?: string
}

/** One row of a session being watched rather than read back afterwards. */
export interface LiveRow {
  position: number | null
  car_number: number
  driver: string
  team: string
  is_player: boolean
}

export interface LiveRaceRow extends LiveRow {
  laps_completed: number
  gap: string
  interval: string
  retired: boolean
  /** Metres round the lap, for the map. Interpolated, unlike the order. */
  distance: number
  /** Metres across the road from the racing line, left positive. */
  offset: number
  /** Within a second of the car ahead, so in its dirty air. */
  in_wake: boolean
  /** In the wake *and* in a zone, so the wing is open. */
  drs: boolean
  /** Came into the pits on this lap. */
  pitted: boolean
  last_lap: number
  compound: string | null
  tyre_age: number
  stops: number
  started: number | null
  /** Places made up on the grid slot, or null for a car that is out. */
  gained: number | null
  fastest_lap: boolean
}

export interface LiveRace {
  lap: number
  laps: number
  order: LiveRaceRow[]
  retired: number
  leader_elapsed?: number
  fastest_lap: {
    car_number: number
    driver: string
    lap_time: number
    lap: number
  } | null
}

export interface LiveQualifyingRow extends LiveRow {
  /** Seconds, or null for a car that has not set a time yet. */
  best: number | null
  gap: number | null
  segment: string | null
}

export interface LiveQualifying {
  segment: string
  done: number
  total: number
  /** False while the segment is still running, true once it is a result. */
  complete: boolean
  order: LiveQualifyingRow[]
}

export const isLiveRace = (live: Job['live']): live is LiveRace =>
  live !== undefined && 'lap' in live

export interface QualifyingRow {
  position: number
  driver: string
  team: string
  best: number | null
  eliminated_in: string | null
}

export interface QualifyingReport {
  round: number
  phase: RoundPhase
  pole: string | null
  grid: string[]
  qualifying: QualifyingRow[]
  weather: Weather
}

export interface RaceClassificationRow {
  round: number
  driver: string
  team: string
  position: number
  started: number
  laps_completed: number
  retired: boolean
  fastest_lap: boolean
  pole: boolean
}

export interface RaceReport {
  round: number
  phase: RoundPhase
  race_id: string
  winner: string | null
  classification: RaceClassificationRow[]
  retirements: number
  weather: Weather
  penalties: PenaltyRow[]
  flags: { lap: number; flag: string; reason: string }[]
}

export interface PracticeReport {
  round: number
  phase: RoundPhase
  circuit: string
  tyre_stress: number
  overtaking_ease: number
  weather: Weather
  forecast: {
    air_temperature: number
    rain_probability: number
    relative_humidity: number
    wind_speed: number
  }
}

export interface DevelopmentArea {
  area: string
  current: number
  gain_at_current_points: number
  /** What a fixed hundred points would buy, so the table means something to a
   *  team with nothing banked. */
  gain_per_100: number
  remaining_demand: number
  efficiency: number
}

export interface Upgrade {
  id: string
  team: string
  area: string
  points: number
  cost: number
  arrives_at_round: number
  commissioned_at_round: number
  expected_gain: number
  failure_chance: number
  status: 'in_development' | 'fitted' | 'failed'
  actual_gain: number
}

export interface DevelopmentOptions {
  rd_points: number
  budget: number
  cap_headroom: number
  cost_per_point: number
  areas: DevelopmentArea[]
  in_development: Upgrade[]
}

export interface LedgerLine {
  label: string
  amount: number
}

export interface Finances {
  budget: number
  season_spending: number
  cap: number
  cap_headroom: number
  bankruptcy_limit: number
  per_round: {
    team: string
    lines: LedgerLine[]
    income: number
    spending: number
    total: number
  }
  projected_to_season_end: number
  rounds_remaining: number
  sponsors: { sponsor: string; team: string; seasons_remaining: number }[]
}

export interface SponsorRow {
  id: string
  name: string
  sector: string
  base_payment: number
  reputation_required: number
  target: { kind: string; value: number }
  target_description: string
  bonus: number
  penalty: number
  seasons: number
  available: boolean
  signed: boolean
  reputation_shortfall: number
}

export interface NegotiationAnswer {
  accepted: boolean
  score: number
  asking_price: number
  reason: string
  breakdown: Record<string, number>
  offer: {
    team: string
    driver: string
    salary: number
    seasons: number
    signing_bonus: number
    performance_bonus: number
  }
}

/** Every refusal arrives in this shape, so a client branches on the code. */
export interface ApiError {
  code: string
  message: string
}


// -- the circuit, drawn ------------------------------------------------------

export interface TrackGeometry {
  track: string
  name: string
  length: number
  /** `[distance, x, y, width]` in metres, start line first. */
  points: [number, number, number, number][]
  /** `[minX, minY, maxX, maxY]` in metres. */
  bounds: [number, number, number, number]
  sectors: number[]
  drs_zones: [number, number][]
  corners: { id: number; name: string; distance: number; x: number; y: number; radius: number | null }[]
  pit_entry: number
  pit_exit: number
  circuit: Circuit
}

export interface ReplayCar {
  car_number: number
  driver: string
  team: string
  driver_name: string
  team_name: string
  /** Distance covered in total, one entry every `interval` seconds. */
  distances: number[]
  /** Metres across the road at each of those samples, left positive. */
  offsets: number[]
  stopped_at: number | null
  retired: boolean
}

export interface ReplayEvent {
  kind: 'incident' | 'flag' | 'overtake'
  lap: number | null
  car_number?: number
  passed?: number
  flag?: string
  detail?: string
}

/** One lap of one car: [distance m, speed kph, throttle, brake, DRS]. */
export type TelemetryLap = number[][]

export interface Replay {
  race_id: string
  track: string
  lap_length: number
  laps: number
  duration: number
  interval: number
  cars: ReplayCar[]
  events: ReplayEvent[]
  /** By car number, then by lap. Laps run behind a safety car are absent. */
  telemetry: Record<string, Record<string, TelemetryLap>>
}


// -- the end of a season -----------------------------------------------------

export interface SeasonRecord {
  season: number
  driver_champion: string
  constructor_champion: string
  player_team: string
  player_team_position: number
  standings: Standings
  race_winners: string[]
  pole_sitters: string[]
}

export interface SeasonSummary {
  season: number
  driver_champion: string
  constructor_champion: string
  player_position: number
  settlements: Record<
    string,
    { team: string; lines: LedgerLine[]; income: number; spending: number; total: number }
  >
  retirements: string[]
  record: SeasonRecord
}

export interface WinterReport {
  season: number
  rounds: number
  rebased: Record<string, number>
  reputations: Record<string, number>
  drivers_aged: Record<string, number>
  retired: string[]
  contracts_expired: string[]
  snapshot: GameSnapshot
}
