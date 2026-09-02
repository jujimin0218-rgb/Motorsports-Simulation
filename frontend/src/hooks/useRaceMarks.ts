/**
 * What just happened, from watching what changed.
 *
 * The server sends the timing screen, not a commentary track. But a timing
 * screen that arrives twice says everything a commentary track would: a car
 * that was fourth and is now third has overtaken somebody, a car that was
 * running and is now retired has gone out, a car whose stop count went up has
 * been in the pits. So rather than adding an event stream to the server and
 * keeping the two in step, this reads the events back out of the frames.
 *
 * Marks are short-lived on purpose. The map is a live picture and a flash on
 * it means "this is happening"; one that stays is furniture, and after a few
 * of them the map is nothing else.
 */

import { useEffect, useRef, useState } from 'react'

import type { LiveRace, LiveRaceRow } from '../types/api'

/** How long a mark stays on the map, ms. */
const LIFETIME = 4200

export interface RaceMark {
  id: string
  kind: 'overtake' | 'pit' | 'out' | 'wide' | 'battle'
  /** The car it happened to, so the map can find where to draw it. */
  car: number
  label: string
  born: number
}

interface Seen {
  position: number | null
  stops: number
  retired: boolean
  offset: number
}

/** Everything worth flashing on the map, newest last. */
export function useRaceMarks(live: LiveRace | null): RaceMark[] {
  const [marks, setMarks] = useState<RaceMark[]>([])
  const before = useRef<Map<number, Seen>>(new Map())
  const counter = useRef(0)

  useEffect(() => {
    if (!live) return
    const now = Date.now()
    const fresh: RaceMark[] = []
    const next = new Map<number, Seen>()

    for (const row of live.order as LiveRaceRow[]) {
      const was = before.current.get(row.car_number)
      const seen: Seen = {
        position: row.position,
        stops: row.stops,
        retired: row.retired,
        offset: row.offset,
      }
      next.set(row.car_number, seen)
      if (!was) continue

      const add = (kind: RaceMark['kind'], label: string) => {
        counter.current += 1
        fresh.push({
          id: `${kind}-${row.car_number}-${counter.current}`,
          kind,
          car: row.car_number,
          label,
          born: now,
        })
      }

      if (!was.retired && seen.retired) add('out', 'OUT')
      else if (seen.stops > was.stops) add('pit', 'PIT')
      else if (
        was.position !== null &&
        seen.position !== null &&
        seen.position < was.position
      ) {
        add('overtake', `P${seen.position}`)
      } else if (Math.abs(seen.offset) > 2.6 && Math.abs(was.offset) <= 2.6) {
        // Far enough off the racing line that the driver is committed to
        // something rather than tidying up an exit.
        add('wide', 'OFF LINE')
      } else if (Math.abs(seen.offset) > 1.2) {
        add('battle', '')
      }
    }

    before.current = next
    if (fresh.length === 0) return
    setMarks((current) => [...current, ...fresh])
  }, [live])

  // Retire old marks on a timer rather than on the next frame: a race that
  // stops sending frames should not leave its last flash on screen for ever.
  useEffect(() => {
    if (marks.length === 0) return
    const timer = window.setInterval(() => {
      const cutoff = Date.now() - LIFETIME
      setMarks((current) => {
        const kept = current.filter((mark) => mark.born > cutoff)
        return kept.length === current.length ? current : kept
      })
    }, 700)
    return () => window.clearInterval(timer)
  }, [marks.length])

  return marks
}
