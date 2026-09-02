/**
 * What the cars were doing, against distance round the lap.
 *
 * The engine's own lap simulation, kept as the race ran rather than recomputed
 * afterwards: these are the numbers that produced the lap time beside them.
 *
 * Speed and the pedals are two charts sharing one x-axis rather than one chart
 * with two y-scales.  Kilometres an hour and a fraction of a pedal have nothing
 * to do with each other, and putting them on the same frame invents crossings
 * that mean nothing.
 *
 * A trace is coloured by which car was picked, not by its team.  Everywhere
 * else a colour means a team, and it should -- but two team mates compared here
 * would then be one colour and two indistinguishable lines, which is the whole
 * of what this panel is for.  The swatch in the legend says which is which.
 */

import { useState } from 'react'

import type { TelemetryLap } from '../types/api'

/** Channel positions in a stored sample: distance, speed, throttle, brake, DRS. */
const D = 0
const SPEED = 1
const THROTTLE = 2
const BRAKE = 3
const DRS = 4

/** The first two categorical slots, which pass the palette checks as a pair. */
const TRACE_COLOURS = ['#3987e5', '#d95926']

export interface TelemetryCar {
  carNumber: number
  driver: string
  samples: TelemetryLap
}

const PAD = { left: 46, right: 12, top: 10, bottom: 18 }

function Plot({
  cars,
  channel,
  height,
  lapLength,
  max,
  label,
  format,
  hover,
  onHover,
}: {
  cars: TelemetryCar[]
  channel: number
  height: number
  lapLength: number
  max: number
  label: string
  format: (value: number) => string
  hover: number | null
  onHover: (distance: number | null) => void
}) {
  const w = 1000
  const inner = { w: w - PAD.left - PAD.right, h: height - PAD.top - PAD.bottom }
  const x = (d: number) => PAD.left + (d / lapLength) * inner.w
  const y = (v: number) => PAD.top + inner.h - (v / max) * inner.h

  const ticks = [0, max / 2, max]

  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      style={{ width: '100%', height, display: 'block' }}
      onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect()
        const at = ((event.clientX - box.left) / box.width) * w
        const d = ((at - PAD.left) / inner.w) * lapLength
        onHover(d >= 0 && d <= lapLength ? d : null)
      }}
      onPointerLeave={() => onHover(null)}
      role="img"
      aria-label={`${label} against distance round the lap`}
    >
      {/* Recessive grid: there to read a value off, not to be looked at. */}
      {ticks.map((value) => (
        <g key={value}>
          <line
            x1={PAD.left}
            x2={w - PAD.right}
            y1={y(value)}
            y2={y(value)}
            stroke="#262b33"
            strokeWidth={1}
          />
          <text x={PAD.left - 6} y={y(value)} fill="#5d6675" fontSize={10} textAnchor="end" dominantBaseline="central">
            {format(value)}
          </text>
        </g>
      ))}
      <text x={PAD.left} y={PAD.top - 1} fill="#8b94a3" fontSize={10}>
        {label}
      </text>

      {cars.map((car, index) => (
        <path
          key={car.carNumber}
          d={car.samples
            .map((s, i) => `${i === 0 ? 'M' : 'L'} ${x(s[D]).toFixed(1)} ${y(s[channel]).toFixed(1)}`)
            .join(' ')}
          fill="none"
          stroke={TRACE_COLOURS[index % TRACE_COLOURS.length]}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ))}

      {hover !== null && (
        <line
          x1={x(hover)}
          x2={x(hover)}
          y1={PAD.top}
          y2={PAD.top + inner.h}
          stroke="#8b94a3"
          strokeWidth={1}
          strokeDasharray="3 3"
        />
      )}
    </svg>
  )
}

/** The sample nearest a distance, for the read-out under the crosshair. */
function nearest(samples: TelemetryLap, distance: number): number[] | null {
  if (!samples.length) return null
  let best = samples[0]
  let gap = Math.abs(best[D] - distance)
  for (const sample of samples) {
    const now = Math.abs(sample[D] - distance)
    if (now < gap) {
      gap = now
      best = sample
    }
  }
  return best
}

export default function TelemetryTrace({
  cars,
  lapLength,
}: {
  cars: TelemetryCar[]
  lapLength: number
}) {
  const [hover, setHover] = useState<number | null>(null)

  if (!cars.length) return null

  return (
    <div>
      {/* A legend for two or more, and every trace is labelled either way. */}
      <div className="inline" style={{ marginBottom: 6 }}>
        {cars.map((car, index) => {
          const sample = hover === null ? null : nearest(car.samples, hover)
          return (
            <span key={car.carNumber} className="trace-key">
              <span className="trace-swatch" style={{ background: TRACE_COLOURS[index % TRACE_COLOURS.length] }} />
              {car.driver}
              {sample && (
                <span className="num dim" style={{ marginLeft: 6 }}>
                  {sample[SPEED].toFixed(0)} kph · {(sample[THROTTLE] * 100).toFixed(0)}% ·{' '}
                  {(sample[BRAKE] * 100).toFixed(0)}% brake{sample[DRS] ? ' · DRS' : ''}
                </span>
              )}
            </span>
          )
        })}
      </div>

      <Plot
        cars={cars}
        channel={SPEED}
        height={140}
        lapLength={lapLength}
        max={360}
        label="Speed, kph"
        format={(v) => v.toFixed(0)}
        hover={hover}
        onHover={setHover}
      />
      <Plot
        cars={cars}
        channel={THROTTLE}
        height={78}
        lapLength={lapLength}
        max={1}
        label="Throttle"
        format={(v) => `${(v * 100).toFixed(0)}%`}
        hover={hover}
        onHover={setHover}
      />
      <Plot
        cars={cars}
        channel={BRAKE}
        height={78}
        lapLength={lapLength}
        max={1}
        label="Brake"
        format={(v) => `${(v * 100).toFixed(0)}%`}
        hover={hover}
        onHover={setHover}
      />
      <p className="subtitle" style={{ marginBottom: 0 }}>
        Distance round the lap, 0 to {(lapLength / 1000).toFixed(3)} km. The engine
        does not model a gearbox, so there is no gear trace to draw.
      </p>
    </div>
  )
}
