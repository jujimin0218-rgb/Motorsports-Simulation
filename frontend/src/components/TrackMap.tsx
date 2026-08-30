/**
 * A circuit, drawn, with cars on it.
 *
 * The separation project rule 11 asks for lives here.  The server sends a plan
 * view **in metres** — the projection of the engine's distance-based track
 * model, which is what the physics actually runs on — and this turns metres
 * into a viewBox.  A car's position arrives as a distance round the lap and is
 * placed by walking the same point list the road is drawn from, so a car is
 * always on the road by construction rather than by the two agreeing.
 */

import { useMemo } from 'react'

import type { TrackGeometry } from '../types/api'

export interface CarOnTrack {
  carNumber: number
  /** Distance round the lap, metres. */
  distance: number
  label: string
  colour: string
  isPlayer?: boolean
  retired?: boolean
}

const PAD = 40

/** Where a distance round the lap lands, in plan-view metres. */
export function pointAt(
  points: TrackGeometry['points'],
  lapLength: number,
  distance: number,
): { x: number; y: number; heading: number } {
  const wrapped = ((distance % lapLength) + lapLength) % lapLength

  // The points are in distance order, so a binary search finds the span.
  let low = 0
  let high = points.length - 1
  while (low < high - 1) {
    const mid = (low + high) >> 1
    if (points[mid][0] <= wrapped) low = mid
    else high = mid
  }

  const [d0, x0, y0] = points[low]
  const [d1, x1, y1] = points[Math.min(low + 1, points.length - 1)]
  const span = d1 - d0
  const t = span > 0 ? (wrapped - d0) / span : 0
  return {
    x: x0 + (x1 - x0) * t,
    y: y0 + (y1 - y0) * t,
    heading: Math.atan2(y1 - y0, x1 - x0),
  }
}

function path(points: TrackGeometry['points'], from = 0, to = Infinity): string {
  const within = points.filter(([d]) => d >= from && d <= to)
  if (within.length < 2) return ''
  return within
    .map(([, x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(' ')
}

export default function TrackMap({
  geometry,
  cars = [],
  showCorners = false,
  height = 420,
}: {
  geometry: TrackGeometry
  cars?: CarOnTrack[]
  showCorners?: boolean
  height?: number
}) {
  const [minX, minY, maxX, maxY] = geometry.bounds
  const width = maxX - minX
  const depth = maxY - minY
  const viewBox = `${minX - PAD} ${minY - PAD} ${width + PAD * 2} ${depth + PAD * 2}`

  // Line weights are in metres, because the viewBox is: a track that is two
  // kilometres across and one that is seven need the same *apparent* width, so
  // the stroke has to scale with the circuit rather than being a pixel count.
  const scale = Math.max(width, depth) / 1000
  const road = 13 * Math.max(1, scale * 0.9)
  const marker = 9 * Math.max(1, scale * 0.9)

  const sectors = useMemo(() => {
    const bounds = [0, ...geometry.sectors, geometry.length]
    return bounds.slice(0, -1).map((from, index) => ({
      from,
      to: bounds[index + 1],
      d: path(geometry.points, from, bounds[index + 1]),
    }))
  }, [geometry])

  const start = pointAt(geometry.points, geometry.length, 0)

  return (
    <svg
      viewBox={viewBox}
      style={{ width: '100%', height, display: 'block' }}
      role="img"
      aria-label={`${geometry.name} circuit map`}
    >
      <g transform={`scale(1,-1) translate(0,${-(minY + maxY)})`}>
        {/* The road itself, in one piece, under everything. */}
        <path
          d={path(geometry.points)}
          fill="none"
          stroke="#2a303a"
          strokeWidth={road}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Sectors, drawn over it — the three colours are colour-blind safe. */}
        {sectors.map((sector, index) => (
          <path
            key={index}
            d={sector.d}
            fill="none"
            stroke={['#0072B2', '#E69F00', '#009E73'][index % 3]}
            strokeWidth={road * 0.42}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.75}
          />
        ))}

        {/* DRS zones, as a dashed overlay. */}
        {geometry.drs_zones.map(([from, to], index) => (
          <path
            key={index}
            d={path(geometry.points, from, to)}
            fill="none"
            stroke="#CC79A7"
            strokeWidth={road * 0.28}
            strokeDasharray={`${road} ${road * 0.7}`}
            strokeLinecap="butt"
          />
        ))}

        {/* Start/finish. */}
        <g transform={`translate(${start.x} ${start.y}) rotate(${(start.heading * 180) / Math.PI})`}>
          <rect
            x={-road * 0.12}
            y={-road * 0.75}
            width={road * 0.24}
            height={road * 1.5}
            fill="#e6e9ee"
          />
        </g>

        {cars.map((car) => {
          const at = pointAt(geometry.points, geometry.length, car.distance)
          return (
            <g key={car.carNumber} transform={`translate(${at.x} ${at.y})`}>
              <circle
                r={marker * (car.isPlayer ? 0.78 : 0.6)}
                fill={car.colour}
                stroke={car.isPlayer ? '#fff' : 'rgba(0,0,0,0.55)'}
                strokeWidth={marker * (car.isPlayer ? 0.2 : 0.12)}
                opacity={car.retired ? 0.35 : 1}
              />
            </g>
          )
        })}
      </g>

      {/* Labels are drawn outside the flipped group so they read the right way up. */}
      {showCorners &&
        geometry.corners.map((corner) => (
          <text
            key={corner.id}
            x={corner.x}
            y={-(corner.y - (minY + maxY))}
            fill="#5d6675"
            fontSize={Math.max(11, scale * 13)}
            textAnchor="middle"
            dominantBaseline="middle"
          >
            {corner.id}
          </text>
        ))}

      {cars.map((car) => {
        const at = pointAt(geometry.points, geometry.length, car.distance)
        return (
          <text
            key={car.carNumber}
            x={at.x}
            y={-(at.y - (minY + maxY))}
            fill={car.isPlayer ? '#fff' : 'rgba(255,255,255,0.85)'}
            fontSize={marker * 0.62}
            fontWeight={600}
            textAnchor="middle"
            dominantBaseline="central"
            style={{ pointerEvents: 'none' }}
            opacity={car.retired ? 0.4 : 1}
          >
            {car.label}
          </text>
        )
      })}
    </svg>
  )
}
