/**
 * What the sky is doing, and what the road is like because of it.
 *
 * Every number here came from the race engine's own weather and track-evolution
 * models — the game does not decide any of it, it only carries the conditions
 * from one session of a weekend to the next.
 *
 * The two that change decisions are the last two. Standing water decides which
 * tyre the car starts on, and rubber decides how much grip there is: a track
 * that qualified at 0.78 and races at 0.07 has been rained on, and everybody's
 * strategy is now wrong.
 */

import { percent, titleCase } from './format'
import { Pill } from './ui'
import type { Weather } from '../types/api'

const mm = (metres: number) => `${(metres * 1000).toFixed(2)} mm`

export default function WeatherPanel({
  weather,
  forecast,
}: {
  weather: Weather
  forecast?: { rain_probability: number; air_temperature: number }
}) {
  const wet = weather.raining || weather.water_depth > 0
  return (
    <>
      <div className="inline" style={{ marginBottom: 12 }}>
        <Pill tone={weather.raining ? 'hot' : 'off'}>
          {weather.raining ? 'raining' : wet ? 'damp' : 'dry'}
        </Pill>
        <Pill tone="off">{titleCase(weather.session)}</Pill>
        {forecast && (
          <Pill tone={forecast.rain_probability > 0.35 ? 'warn' : 'off'}>
            {percent(forecast.rain_probability)} chance here
          </Pill>
        )}
      </div>

      <div className="grid four">
        <div>
          <div className="stat-label">Air</div>
          <div className="num" style={{ fontSize: 19, marginTop: 2 }}>
            {weather.air_temperature.toFixed(1)}°C
          </div>
        </div>
        <div>
          <div className="stat-label">Track</div>
          <div className="num" style={{ fontSize: 19, marginTop: 2 }}>
            {weather.track_temperature.toFixed(1)}°C
          </div>
        </div>
        <div>
          <div className="stat-label">Wind</div>
          <div className="num" style={{ fontSize: 19, marginTop: 2 }}>
            {weather.wind_speed.toFixed(1)} m/s
          </div>
        </div>
        <div>
          <div className="stat-label">Humidity</div>
          <div className="num" style={{ fontSize: 19, marginTop: 2 }}>
            {percent(weather.relative_humidity)}
          </div>
        </div>
      </div>

      <hr className="rule" />

      <div className="grid two">
        <div>
          <div className="spread">
            <span className="stat-label">Standing water</span>
            <span className="num" style={{ fontSize: 12 }}>
              {mm(weather.water_depth)}
            </span>
          </div>
          <div className={`bar ${wet ? 'warn' : ''}`} style={{ marginTop: 6 }}>
            <span style={{ width: `${Math.min(100, weather.water_depth * 1000 * 20)}%` }} />
          </div>
          <div className="stat-note">
            {weather.water_depth > 0
              ? `${percent(weather.wet_fraction)} of the lap is wet — it decides the tyre`
              : 'the road is dry'}
          </div>
        </div>
        <div>
          <div className="spread">
            <span className="stat-label">Rubber</span>
            <span className="num" style={{ fontSize: 12 }}>
              {weather.rubber.toFixed(3)}
            </span>
          </div>
          <div className="bar good" style={{ marginTop: 6 }}>
            <span style={{ width: `${weather.rubber * 100}%` }} />
          </div>
          <div className="stat-note">
            {weather.rubber > 0.5
              ? 'a track that has been run on'
              : weather.rubber > 0.1
                ? 'partly rubbered in'
                : 'green — or washed clean'}
          </div>
        </div>
      </div>
    </>
  )
}
