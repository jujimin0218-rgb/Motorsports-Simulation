/**
 * The game, held once for the whole client.
 *
 * There is exactly one game on the server, so there is exactly one here.  Every
 * screen reads the same snapshot and every action refreshes it, which means no
 * screen can be looking at a season the server has moved on from -- the class
 * of bug where the dashboard says round four and the calendar says round five.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { ApiFailure, api } from '../services/api'
import type { GameSnapshot } from '../types/api'

interface GameContextValue {
  game: GameSnapshot | null
  loading: boolean
  /** Set when there is no game rather than when something went wrong. */
  missing: boolean
  error: ApiFailure | null
  refresh: () => Promise<void>
  /** Run something that changes the game, then re-read it. */
  act: <T>(work: () => Promise<T>) => Promise<T>
}

const GameContext = createContext<GameContextValue | null>(null)

export function GameProvider({ children }: { children: ReactNode }) {
  const [game, setGame] = useState<GameSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [missing, setMissing] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)

  const refresh = useCallback(async () => {
    try {
      const snapshot = await api.snapshot()
      setGame(snapshot)
      setMissing(false)
      setError(null)
    } catch (caught) {
      const failure = caught as ApiFailure
      if (failure.isMissingGame) {
        setGame(null)
        setMissing(true)
        setError(null)
      } else {
        setError(failure)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const act = useCallback(
    async <T,>(work: () => Promise<T>): Promise<T> => {
      const result = await work()
      await refresh()
      return result
    },
    [refresh],
  )

  const value = useMemo(
    () => ({ game, loading, missing, error, refresh, act }),
    [game, loading, missing, error, refresh, act],
  )
  return <GameContext.Provider value={value}>{children}</GameContext.Provider>
}

export function useGame(): GameContextValue {
  const value = useContext(GameContext)
  if (!value) throw new Error('useGame must be used inside a GameProvider')
  return value
}

/** The game, when a screen has already established that there is one. */
export function useLoadedGame(): GameSnapshot {
  const { game } = useGame()
  if (!game) throw new Error('this screen requires a loaded game')
  return game
}
