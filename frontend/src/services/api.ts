/**
 * The only place the client talks to the server.
 *
 * Two things this file is careful about.
 *
 * **Errors keep their code.**  Every refusal from the backend arrives as
 * `{code, message}` -- the phase machine says `InvalidGamePhase`, the economy
 * says `InsufficientBudget` -- and a screen that only had the English string
 * could not tell them apart.  So the code is carried through on the thrown
 * error.
 *
 * **Long sessions are polled, not awaited.**  Qualifying is minutes of
 * simulation and a race is longer.  The server hands back a job; `runJob`
 * follows it and reports progress, so a screen can show something moving
 * rather than a spinner and a promise that may not settle for ten minutes.
 */

import type {
  CalendarRow,
  DevelopmentOptions,
  DriverRow,
  Finances,
  GameSnapshot,
  Job,
  NegotiationAnswer,
  PracticeReport,
  QualifyingReport,
  RaceReport,
  Replay,
  SaveSummary,
  SelectableTeam,
  SponsorRow,
  SeasonRecord,
  SeasonSummary,
  Standings,
  TeamRow,
  TrackGeometry,
  Upgrade,
  WinterReport,
} from '../types/api'

export class ApiFailure extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiFailure'
    this.code = code
    this.status = status
  }

  /** True when the game refused because of where the round is, not what was asked. */
  get isPhaseError(): boolean {
    return this.code === 'InvalidGamePhase'
  }

  get isMissingGame(): boolean {
    return this.code === 'SaveNotFound'
  }
}

interface Request extends Omit<RequestInit, 'body'> {
  body?: unknown
}

async function request<T>(path: string, init?: Request): Promise<T> {
  const { body, headers, ...rest } = init ?? {}
  const options: RequestInit = { ...rest }
  if (body !== undefined) {
    options.body = JSON.stringify(body)
    options.headers = { 'Content-Type': 'application/json', ...(headers ?? {}) }
  } else if (headers) {
    options.headers = headers
  }

  let response: Response
  try {
    response = await fetch(path, options)
  } catch (cause) {
    throw new ApiFailure(
      'NetworkError',
      'The server is not answering.  Is the backend running?',
      0,
    )
  }

  if (!response.ok) {
    let code = `Http${response.status}`
    let message = response.statusText
    try {
      const payload = await response.json()
      if (payload && typeof payload === 'object') {
        code = payload.code ?? code
        message = payload.message ?? payload.detail ?? message
      }
    } catch {
      /* a body that is not JSON leaves the status as the whole story */
    }
    throw new ApiFailure(code, message, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const get = <T>(path: string) => request<T>(path)
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ?? {} })
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' })

export const api = {
  // -- the game ------------------------------------------------------------
  health: () => get<{ status: string }>('/health'),
  snapshot: () => get<GameSnapshot>('/api/game'),
  selectableTeams: () => get<SelectableTeam[]>('/api/game/teams'),
  newGame: (body: {
    player_team: string
    seed?: number | null
    name?: string
    rounds?: number | null
    race_distance?: number | null
  }) =>
    post<GameSnapshot>('/api/game/new', body),
  save: (body: { save_id?: string | null; slot?: string | null; name?: string | null }) =>
    post<SaveSummary>('/api/game/save', body),
  load: (body: { save_id?: string | null; slot?: string | null }) =>
    post<GameSnapshot>('/api/game/load', body),
  saves: () => get<SaveSummary[]>('/api/game/saves'),
  deleteSave: (id: string) => del<{ deleted: string }>(`/api/game/saves/${id}`),

  // -- reading it ----------------------------------------------------------
  season: () =>
    get<{
      season: number
      rounds: number
      current_round: number | null
      phase: string | null
      complete: boolean
      settings: GameSnapshot['settings']
    }>('/api/season'),
  updateSettings: (body: {
    race_distance?: number
    difficulty?: string
    hazards?: boolean
  }) =>
    request<GameSnapshot['settings']>('/api/season/settings', {
      method: 'PATCH',
      body,
    }),
  calendar: () => get<CalendarRow[]>('/api/calendar'),
  teams: () => get<TeamRow[]>('/api/teams'),
  drivers: (freeAgents = false) =>
    get<DriverRow[]>(`/api/drivers${freeAgents ? '?free_agents=true' : ''}`),
  standings: () => get<Standings>('/api/standings'),
  history: () => get<SeasonRecord[]>('/api/history'),
  closeSeason: () => post<SeasonSummary>('/api/season/close'),
  startNextSeason: () => post<WinterReport>('/api/season/next'),
  race: (raceId: string) => get<Record<string, unknown>>(`/api/race/${raceId}`),
  replay: (raceId: string) => get<Replay>(`/api/race/${raceId}/replay`),
  track: (round?: number) =>
    get<TrackGeometry>(`/api/track${round ? `?round=${round}` : ''}`),

  // -- running a weekend ---------------------------------------------------
  startRound: () => post<Record<string, unknown>>('/api/round/start'),
  runPractice: () => post<PracticeReport>('/api/round/practice'),
  startQualifying: () => post<Job<QualifyingReport>>('/api/qualifying/run'),
  startRace: () => post<Job<RaceReport>>('/api/race/run'),
  runDevelopment: () => post<Record<string, unknown>>('/api/round/development'),
  nextRound: () => get<Record<string, unknown>>('/api/round/next'),
  job: <T>(id: string) => get<Job<T>>(`/api/jobs/${id}`),

  // -- between the races ---------------------------------------------------
  development: (team?: string) =>
    get<DevelopmentOptions>(`/api/rd${team ? `?team=${team}` : ''}`),
  invest: (body: { area: string; points: number; rushed?: number }) =>
    post<Upgrade>('/api/rd/invest', body),
  upgrades: (team?: string) =>
    get<Upgrade[]>(`/api/upgrades${team ? `?team=${team}` : ''}`),
  upgradeFacility: (facility: string) =>
    post<{ facility: string; level: number; cost: number; budget: number }>(
      '/api/facilities/upgrade',
      { facility },
    ),
  finances: (team?: string) =>
    get<Finances>(`/api/finances${team ? `?team=${team}` : ''}`),
  sponsors: (team?: string) =>
    get<SponsorRow[]>(`/api/sponsors${team ? `?team=${team}` : ''}`),
  signSponsor: (sponsorId: string) =>
    post<Record<string, unknown>>('/api/sponsors/sign', { sponsor_id: sponsorId }),
  negotiate: (body: {
    driver_id: string
    salary: number
    seasons?: number
    signing_bonus?: number
  }) => post<NegotiationAnswer>('/api/contracts/negotiate', body),
  signDriver: (body: {
    driver_id: string
    salary: number
    seasons?: number
    signing_bonus?: number
    seat?: number | null
  }) => post<Record<string, unknown>>('/api/contracts/sign', body),
}

/**
 * Start a long session and follow it to the end.
 *
 * `onProgress` is called as the server reports it, which for a race is once a
 * lap -- so the screen can show a race happening rather than a spinner.
 */
export async function runJob<T>(
  start: () => Promise<Job<T>>,
  onProgress?: (job: Job<T>) => void,
  { intervalMs = 700 }: { intervalMs?: number } = {},
): Promise<T> {
  let job = await start()
  onProgress?.(job)
  while (job.status === 'pending' || job.status === 'running') {
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    job = await api.job<T>(job.id)
    onProgress?.(job)
  }
  if (job.status === 'failed') {
    throw new ApiFailure(job.code ?? 'JobFailed', job.error ?? 'the session failed', 500)
  }
  return job.result as T
}
