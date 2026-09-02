/**
 * The pieces every screen is built from.
 *
 * Kept deliberately plain: this is a management game whose screens are almost
 * entirely tables of numbers, and the useful components are the ones that make
 * a number legible rather than the ones that decorate it.
 */

import type { ReactNode } from 'react'

import { ApiFailure } from '../services/api'
import { rating, titleCase } from './format'

export function Panel({
  title,
  action,
  children,
  note,
}: {
  title?: string
  action?: ReactNode
  note?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="panel">
      {(title || action) && (
        <div className="spread" style={{ marginBottom: title ? 12 : 0 }}>
          {title && <h2 style={{ margin: 0 }}>{title}</h2>}
          {action}
        </div>
      )}
      {note && <p className="subtitle" style={{ marginTop: -6 }}>{note}</p>}
      {children}
    </section>
  )
}

export function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: string
}) {
  return (
    <div className="panel">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ''}`}>{value}</div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  )
}

/** A 0–1 rating, as a bar and a number.  Used for cars, drivers and facilities. */
export function Meter({
  name,
  value,
  max = 1,
  tone,
  suffix,
}: {
  name: string
  value: number
  max?: number
  tone?: 'accent' | 'good' | 'warn'
  suffix?: string
}) {
  const share = Math.max(0, Math.min(1, value / max))
  return (
    <div className="meter-row">
      <span className="name">{titleCase(name)}</span>
      <span className={`bar ${tone ?? ''}`}>
        <span style={{ width: `${share * 100}%` }} />
      </span>
      <span className="value">{suffix ?? rating(value)}</span>
    </div>
  )
}

export function Notice({
  kind = 'info',
  children,
  code,
}: {
  kind?: 'info' | 'error' | 'ok'
  children: ReactNode
  code?: string
}) {
  return (
    <div className={`notice ${kind === 'info' ? '' : kind}`}>
      {children}
      {code && <span className="code">{code}</span>}
    </div>
  )
}

/** Whatever went wrong, said in the game's own words with its code kept. */
export function ErrorNotice({ error }: { error: ApiFailure | Error | null }) {
  if (!error) return null
  const failure = error instanceof ApiFailure ? error : null
  return (
    <Notice kind="error" code={failure?.code}>
      {error.message}
    </Notice>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <div className="empty">{what}…</div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Pill({
  children,
  tone,
}: {
  children: ReactNode
  tone?: 'on' | 'off' | 'hot' | 'warn'
}) {
  return <span className={`pill ${tone ?? ''}`}>{children}</span>
}

export function PageHead({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: ReactNode
  action?: ReactNode
}) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="subtitle">{subtitle}</div>}
      </div>
      {action}
    </header>
  )
}
