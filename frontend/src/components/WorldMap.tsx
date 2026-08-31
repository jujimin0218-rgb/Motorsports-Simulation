/**
 * The circuit as a place, drawn flat.
 *
 * The other map in here is a schematic: a stroke for the road and a dot per
 * car, which is the right picture for "where is everybody round the lap".
 * This one is the picture for "what is happening on this piece of road" -- the
 * asphalt at its real width with the kerb, run-off, grass, gravel and walls
 * beside it, and cars as the five-and-a-half by two metre rectangles the
 * physics actually collides.
 *
 * Everything arrives in metres and is drawn in metres; the viewBox does the
 * scaling. Nothing here works out where anything is -- the server laid the
 * circuit out, and this fills what it was given in the order it arrived.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { TrackWorld, WorldCar } from '../types/api'

const PAD = 30
const MAX_ZOOM = 40

/** Flat colours, one per surface. Deliberately not textures: a race is read at
 *  a glance and a glance wants an edge, not a material. */
const SURFACE: Record<string, string> = {
  grass: '#1d2a1f',
  gravel: '#3b3427',
  runoff: '#232a33',
  kerb: '#7a2b34',
  track: '#22272f',
  pit: '#2a2f38',
}

const toScreenY = (y: number, minY: number, maxY: number) => minY + maxY - y

function ring(points: [number, number][]): string {
  if (points.length < 3) return ''
  return (
    points
      .map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`)
      .join(' ') + ' Z'
  )
}

function line(points: [number, number][]): string {
  if (points.length < 2) return ''
  return points
    .map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(' ')
}

export default function WorldMap({
  world,
  cars = [],
  height = '100%',
  follow = null,
  debug = false,
}: {
  world: TrackWorld
  cars?: WorldCar[]
  height?: number | string
  /** Car number to keep centred. */
  follow?: number | null
  /** Draw the collision rectangles and contact points over the top. */
  debug?: boolean
}) {
  const [minX, minY, maxX, maxY] = world.bounds
  const full = { w: maxX - minX + PAD * 2, h: maxY - minY + PAD * 2 }

  const [zoom, setZoom] = useState(1)
  const [centre, setCentre] = useState({
    x: minX - PAD + full.w / 2,
    y: minY - PAD + full.h / 2,
  })
  const svgRef = useRef<SVGSVGElement | null>(null)
  const drag = useRef<{ cx: number; cy: number; px: number; py: number; fit: number } | null>(
    null,
  )

  const reset = useCallback(() => {
    setZoom(1)
    setCentre({ x: minX - PAD + full.w / 2, y: minY - PAD + full.h / 2 })
  }, [minX, minY, full.w, full.h])

  useEffect(() => reset(), [world.name, reset])

  const followed = follow === null ? undefined : cars.find((c) => c.car_number === follow)
  const view = {
    w: full.w / zoom,
    h: full.h / zoom,
    cx: followed ? followed.x : centre.x,
    cy: followed ? toScreenY(followed.y, minY, maxY) : centre.y,
  }
  const viewBox = `${view.cx - view.w / 2} ${view.cy - view.h / 2} ${view.w} ${view.h}`

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

  function at(event: { clientX: number; clientY: number }) {
    const box = svgRef.current?.getBoundingClientRect()
    if (!box) return null
    const fit = Math.min(box.width / view.w, box.height / view.h)
    return {
      x: view.cx + (event.clientX - box.left - box.width / 2) / fit,
      y: view.cy + (event.clientY - box.top - box.height / 2) / fit,
    }
  }

  function onWheel(event: React.WheelEvent<SVGSVGElement>) {
    const anchor = at(event)
    const next = Math.min(MAX_ZOOM, Math.max(1, zoom * (event.deltaY < 0 ? 1.2 : 1 / 1.2)))
    if (next === zoom) return
    setZoom(next)
    if (anchor && !followed) {
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
    if (zoom === 1 || followed) return
    const box = svgRef.current?.getBoundingClientRect()
    if (!box) return
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

  /**
   * Zoom without a pointer to zoom about.
   *
   * A circuit is a ring, so the middle of its bounding box is the hole in the
   * middle of it -- closing in on that shows an empty screen.  Closing in on
   * the race instead is both what the button is for and the only place there
   * is anything to see.
   */
  function zoomBy(factor: number) {
    const next = Math.min(MAX_ZOOM, Math.max(1, zoom * factor))
    setZoom(next)
    if (followed || next <= 1) return
    const onto = cars.find((car) => !car.retired) ?? cars[0]
    if (onto) {
      setCentre({ x: onto.x, y: toScreenY(onto.y, minY, maxY) })
    }
  }

  // Line weights are metres and hold their apparent size as the view closes in,
  // so zooming spreads the circuit out rather than fattening everything on it.
  const px = 1 / zoom
  const zoomed = zoom > 1.001

  return (
    <div className="trackmap" style={{ height }}>
      <div className="trackmap-zoom">
        <button type="button" onClick={() => zoomBy(1.6)} aria-label="Zoom in">
          +
        </button>
        <button type="button" onClick={() => zoomBy(1 / 1.6)} aria-label="Zoom out">
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
          cursor: followed ? 'default' : zoomed ? 'grab' : 'default',
        }}
        role="img"
        aria-label={`${world.name}, laid out`}
      >
        <g transform={`scale(1,-1) translate(0,${-(minY + maxY)})`}>
          {world.bands.map((band, index) => (
            <path
              key={index}
              d={ring(band.polygon)}
              fill={SURFACE[band.surface] ?? '#22272f'}
              stroke="none"
            />
          ))}

          {/* The pit lane, and then the walls over everything. */}
          <path
            d={line(world.pit_path)}
            fill="none"
            stroke={SURFACE.pit}
            strokeWidth={10}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {world.barriers.map((wall, index) => (
            <path
              key={index}
              d={line(wall)}
              fill="none"
              stroke="#6d7684"
              strokeWidth={Math.max(0.6, 1.4 * px)}
              strokeLinejoin="round"
            />
          ))}

          {cars.map((car) => (
            <g
              key={car.car_number}
              transform={`translate(${car.x} ${car.y}) rotate(${(car.heading * 180) / Math.PI})`}
              opacity={car.retired ? 0.4 : 1}
            >
              {car.in_wake && !car.retired && (
                <circle r={3.4} fill="#e3a33a" opacity={0.15} />
              )}
              {car.drs && !car.retired && (
                <circle r={2.9} fill="none" stroke="#35c07a" strokeWidth={0.5} opacity={0.9} />
              )}
              {/* The car itself, at the size the physics collides. */}
              <rect
                x={-2.8}
                y={-1.0}
                width={5.6}
                height={2.0}
                rx={0.6}
                fill={car.colour}
                stroke={car.is_player ? '#fff' : 'rgba(0,0,0,0.6)'}
                strokeWidth={car.is_player ? 0.4 : 0.2}
              />
              {/* Which way it is pointing, so a spin reads as a spin. */}
              <rect x={1.6} y={-0.45} width={1.2} height={0.9} fill="rgba(255,255,255,0.7)" />
            </g>
          ))}

          {debug &&
            cars.map((car) => (
              <g key={`d${car.car_number}`}>
                <path
                  d={ring(carCorners(car))}
                  fill="none"
                  stroke="#4d9be6"
                  strokeWidth={Math.max(0.3, 0.6 * px)}
                />
              </g>
            ))}
        </g>

        {cars.map((car) => (
          <text
            key={car.car_number}
            x={car.x}
            y={toScreenY(car.y, minY, maxY) - 3.4}
            fill="rgba(255,255,255,0.9)"
            fontSize={Math.max(3, 7 * px)}
            fontWeight={600}
            textAnchor="middle"
            style={{ pointerEvents: 'none' }}
          >
            {car.label}
          </text>
        ))}
      </svg>
    </div>
  )
}

/** The four corners of a car, for the debug outline. */
function carCorners(car: WorldCar): [number, number][] {
  const cos = Math.cos(car.heading)
  const sin = Math.sin(car.heading)
  const along: [number, number] = [cos * 2.8, sin * 2.8]
  const across: [number, number] = [-sin * 1.0, cos * 1.0]
  return [
    [car.x + along[0] + across[0], car.y + along[1] + across[1]],
    [car.x - along[0] + across[0], car.y - along[1] + across[1]],
    [car.x - along[0] - across[0], car.y - along[1] - across[1]],
    [car.x + along[0] - across[0], car.y + along[1] - across[1]],
  ]
}

/**
 * Where a car at a lap distance and a place across the road is, in metres.
 *
 * The same walk the server does when it lays the circuit out, done again here
 * because the race sends a distance and an offset and the picture needs a
 * point.  Kept next to the renderer that uses it rather than in a utility
 * drawer: if the server's own `place` ever changes, this is the other half of
 * that change.
 */
export function placeOnWorld(
  world: TrackWorld,
  distance: number,
  offset: number,
): { x: number; y: number; heading: number } {
  const count = world.centre.length
  const wrapped = ((distance % world.length) + world.length) % world.length
  const exact = wrapped / world.step
  const index = Math.floor(exact)
  const nudge = exact - index
  const [x0, y0] = world.centre[index % count]
  const [x1, y1] = world.centre[(index + 1) % count]
  const x = x0 + (x1 - x0) * nudge
  const y = y0 + (y1 - y0) * nudge
  const heading = Math.atan2(y1 - y0, x1 - x0)
  return {
    x: x - Math.sin(heading) * offset,
    y: y + Math.cos(heading) * offset,
    heading,
  }
}
