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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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
const MAX_ZOOM = 16
/**
 * Plan-view metres to the coordinates the SVG draws in.
 *
 * The circuit's y runs up and the SVG's runs down, so the road is drawn inside
 * a flipped group.  Everything that has to sit *outside* that group -- the
 * labels, and the viewBox the zoom works in -- goes through here instead.
 */
const toScreenY = (y: number, minY: number, maxY: number) => minY + maxY - y

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
  follow = null,
}: {
  geometry: TrackGeometry
  cars?: CarOnTrack[]
  showCorners?: boolean
  height?: number
  /** Car number to keep centred, so a fight can be watched rather than found. */
  follow?: number | null
}) {
  const [minX, minY, maxX, maxY] = geometry.bounds
  const width = maxX - minX
  const depth = maxY - minY
  const full = { w: width + PAD * 2, h: depth + PAD * 2 }

  // Zoom is about a point on the circuit, held in the same coordinates the
  // viewBox uses, so panning and following are the same operation.
  const [zoom, setZoom] = useState(1)
  const [centre, setCentre] = useState({
    x: minX - PAD + full.w / 2,
    y: minY - PAD + full.h / 2,
  })
  const svgRef = useRef<SVGSVGElement | null>(null)
  const drag = useRef<
    { cx: number; cy: number; px: number; py: number; fit: number } | null
  >(null)

  const reset = useCallback(() => {
    setZoom(1)
    setCentre({ x: minX - PAD + full.w / 2, y: minY - PAD + full.h / 2 })
  }, [minX, minY, full.w, full.h])

  // A circuit change is a different map; keep nobody's old zoom on it.
  useEffect(() => reset(), [geometry.track, reset])

  const followed = follow === null ? undefined : cars.find((c) => c.carNumber === follow)
  const followAt = followed
    ? pointAt(geometry.points, geometry.length, followed.distance)
    : null

  const view = {
    w: full.w / zoom,
    h: full.h / zoom,
    cx: followAt ? followAt.x : centre.x,
    cy: followAt ? toScreenY(followAt.y, minY, maxY) : centre.y,
  }
  const viewBox = `${view.cx - view.w / 2} ${view.cy - view.h / 2} ${view.w} ${view.h}`

  /** Keep the circuit on screen: the view's centre stays over the map. */
  function clamp(point: { x: number; y: number }) {
    const halfW = Math.max(0, (full.w - view.w) / 2)
    const halfH = Math.max(0, (full.h - view.h) / 2)
    const midX = minX - PAD + full.w / 2
    const midY = minY - PAD + full.h / 2
    return {
      x: Math.min(midX + halfW, Math.max(midX - halfW, point.x)),
      y: Math.min(midY + halfH, Math.max(midY - halfH, point.y)),
    }
  }

  /** Where a pointer is, in the coordinates the viewBox is written in. */
  function at(event: { clientX: number; clientY: number }) {
    const box = svgRef.current?.getBoundingClientRect()
    if (!box) return null
    // preserveAspectRatio is the default "meet", so the shorter axis is padded.
    const fit = Math.min(box.width / view.w, box.height / view.h)
    return {
      x: view.cx + (event.clientX - box.left - box.width / 2) / fit,
      y: view.cy + (event.clientY - box.top - box.height / 2) / fit,
    }
  }

  function onWheel(event: React.WheelEvent<SVGSVGElement>) {
    const anchor = at(event)
    const next = Math.min(MAX_ZOOM, Math.max(1, zoom * (event.deltaY < 0 ? 1.18 : 1 / 1.18)))
    if (next === zoom) return
    setZoom(next)
    // Zoom about the pointer: the metre under it stays under it.
    if (anchor && !followAt) {
      const k = 1 - zoom / next
      setCentre(
        clamp({
          x: centre.x + (anchor.x - centre.x) * k,
          y: centre.y + (anchor.y - centre.y) * k,
        }),
      )
    }
  }

  function onPointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if (zoom === 1 || followAt) return
    const box = svgRef.current?.getBoundingClientRect()
    if (!box) return
    // Anchored in pixels rather than in metres: the metre under the pointer
    // moves as the map does, and dragging against it shakes.
    drag.current = {
      cx: centre.x,
      cy: centre.y,
      px: event.clientX,
      py: event.clientY,
      fit: Math.min(box.width / view.w, box.height / view.h),
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: React.PointerEvent<SVGSVGElement>) {
    const from = drag.current
    if (!from) return
    setCentre(
      clamp({
        x: from.cx - (event.clientX - from.px) / from.fit,
        y: from.cy - (event.clientY - from.py) / from.fit,
      }),
    )
  }

  const endDrag = () => {
    drag.current = null
  }

  // Line weights are in metres, because the viewBox is: a track that is two
  // kilometres across and one that is seven need the same *apparent* width, so
  // the stroke has to scale with the circuit rather than being a pixel count.
  // Dividing by the zoom holds that apparent width steady as the view closes
  // in, so zooming spreads the cars apart instead of fattening the road.
  const scale = Math.max(width, depth) / 1000
  const road = (13 * Math.max(1, scale * 0.9)) / zoom
  const marker = (9 * Math.max(1, scale * 0.9)) / zoom

  const sectors = useMemo(() => {
    const bounds = [0, ...geometry.sectors, geometry.length]
    return bounds.slice(0, -1).map((from, index) => ({
      from,
      to: bounds[index + 1],
      d: path(geometry.points, from, bounds[index + 1]),
    }))
  }, [geometry])

  const start = pointAt(geometry.points, geometry.length, 0)

  const zoomed = zoom > 1.001
  return (
    <div className="trackmap" style={{ height }}>
      <div className="trackmap-zoom">
        <button
          type="button"
          onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z * 1.6))}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => setZoom((z) => Math.max(1, z / 1.6))}
          aria-label="Zoom out"
        >
          −
        </button>
        <button type="button" onClick={reset} aria-label="Whole circuit" disabled={!zoomed}>
          ⌂
        </button>
        <span className="num">{zoom.toFixed(1)}×</span>
      </div>
    <svg
      ref={svgRef}
      viewBox={viewBox}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={reset}
      style={{
        width: '100%',
        height,
        display: 'block',
        touchAction: 'none',
        cursor: followAt ? 'default' : zoomed ? 'grab' : 'default',
      }}
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
            y={toScreenY(corner.y, minY, maxY)}
            fill="#5d6675"
            fontSize={Math.max(11, scale * 13) / zoom}
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
            y={toScreenY(at.y, minY, maxY)}
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
    </div>
  )
}
