/**
 * Fetch something, once, and know which of the three states you are in.
 *
 * Small on purpose.  The alternative is every page repeating the same
 * loading/error/data triple and getting the error case subtly wrong in a
 * different way each time -- which for this client matters, because a refusal
 * from the backend is information the player needs rather than a crash.
 */

import { useCallback, useEffect, useState } from 'react'

import { ApiFailure } from '../services/api'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: ApiFailure | null
  reload: () => void
}

export function useAsync<T>(
  load: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let live = true
    setLoading(true)
    load()
      .then((value) => {
        if (!live) return
        setData(value)
        setError(null)
      })
      .catch((caught) => {
        if (!live) return
        setError(caught as ApiFailure)
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, loading, error, reload }
}
