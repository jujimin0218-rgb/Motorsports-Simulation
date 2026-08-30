/**
 * How numbers are shown.
 *
 * Every one of these exists because the unit is the part that goes wrong.  A
 * budget is millions, a rating is a fraction, a lap time is minutes and
 * thousandths, and a gap is signed.  Formatting them in one place is what stops
 * a screen from quietly showing 0.94 where it means 94%.
 */

export const money = (millions: number, digits = 1): string =>
  `${millions < 0 ? '-' : ''}€${Math.abs(millions).toFixed(digits)}M`

export const signedMoney = (millions: number, digits = 1): string =>
  `${millions >= 0 ? '+' : '-'}€${Math.abs(millions).toFixed(digits)}M`

export const rating = (value: number, digits = 3): string => value.toFixed(digits)

export const percent = (fraction: number, digits = 0): string =>
  `${(fraction * 100).toFixed(digits)}%`

export const signedPercent = (fraction: number, digits = 1): string =>
  `${fraction >= 0 ? '+' : ''}${(fraction * 100).toFixed(digits)}%`

/** Seconds as a lap time: 1:28.227. */
export function lapTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const minutes = Math.floor(seconds / 60)
  const rest = seconds - minutes * 60
  return `${minutes}:${rest.toFixed(3).padStart(6, '0')}`
}

export const ordinal = (position: number): string => {
  const tens = position % 100
  if (tens >= 11 && tens <= 13) return `${position}th`
  return `${position}${['th', 'st', 'nd', 'rd'][position % 10] ?? 'th'}`
}

/** A skill or rating name as a person would read it. */
export const titleCase = (key: string): string =>
  key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export const when = (epochSeconds: number): string =>
  new Date(epochSeconds * 1000).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

/** Positive is good for some things and bad for others, so say which. */
export const toneFor = (value: number, higherIsBetter = true): string => {
  if (value === 0) return ''
  const good = higherIsBetter ? value > 0 : value < 0
  return good ? 'good' : 'bad'
}
