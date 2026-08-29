/**
 * The shell.
 *
 * One rule shapes it: **a screen that needs a game does not render without
 * one.**  Rather than every page checking, the shell resolves that once -- no
 * game means the new-game screen, whatever the URL says -- so no page has to
 * carry a null check for a case it cannot handle anyway.
 */

import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { ErrorNotice, Loading } from './components/ui'
import { money } from './components/format'
import { useGame } from './hooks/useGame'
import Calendar from './pages/Calendar'
import Contracts from './pages/Contracts'
import Dashboard from './pages/Dashboard'
import Development from './pages/Development'
import Drivers from './pages/Drivers'
import Finances from './pages/Finances'
import NewGame from './pages/NewGame'
import RaceWeekend from './pages/RaceWeekend'
import Saves from './pages/Saves'
import Standings from './pages/Standings'
import Team from './pages/Team'

interface NavEntry {
  to: string
  label: string
  badge?: string
}

export default function App() {
  const { game, loading, missing, error, refresh } = useGame()

  if (loading) {
    return (
      <div className="main">
        <Loading what="Reaching the server" />
      </div>
    )
  }

  if (error && !game) {
    return (
      <div className="main" style={{ maxWidth: 620 }}>
        <h1>Cannot reach the game</h1>
        <ErrorNotice error={error} />
        <p className="subtitle">
          The backend runs with{' '}
          <code className="num">uvicorn app.main:app --app-dir backend</code>.
        </p>
        <button onClick={() => void refresh()}>Try again</button>
      </div>
    )
  }

  if (missing || !game) {
    return (
      <div className="main">
        <NewGame />
      </div>
    )
  }

  const round = game.current_round
  const groups: { name: string; entries: NavEntry[] }[] = [
    {
      name: 'Season',
      entries: [
        { to: '/', label: 'Dashboard' },
        {
          to: '/weekend',
          label: 'Race weekend',
          badge: round ? `R${round.number}` : 'done',
        },
        { to: '/calendar', label: 'Calendar' },
        { to: '/standings', label: 'Standings' },
      ],
    },
    {
      name: 'Team',
      entries: [
        { to: '/team', label: 'Team' },
        {
          to: '/development',
          label: 'Development',
          badge: game.team.rd_points.toFixed(0),
        },
        {
          to: '/finances',
          label: 'Finances',
          badge: money(game.team.budget, 0),
        },
        { to: '/contracts', label: 'Contracts' },
        { to: '/drivers', label: 'Drivers' },
      ],
    },
    { name: 'Game', entries: [{ to: '/saves', label: 'Saves & settings' }] },
  ]

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">
          <span className="brand-mark" />
          <div className="stack">
            <span className="brand-name">{game.team.name}</span>
            <span className="brand-sub">
              {game.season} season · seed {game.seed}
            </span>
          </div>
        </div>

        {groups.map((group) => (
          <div key={group.name}>
            <div className="nav-group">{group.name}</div>
            {group.entries.map((entry) => (
              <NavLink
                key={entry.to}
                to={entry.to}
                end={entry.to === '/'}
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
              >
                <span>{entry.label}</span>
                {entry.badge && <span className="nav-badge">{entry.badge}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/weekend" element={<RaceWeekend />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/standings" element={<Standings />} />
          <Route path="/team" element={<Team />} />
          <Route path="/development" element={<Development />} />
          <Route path="/finances" element={<Finances />} />
          <Route path="/contracts" element={<Contracts />} />
          <Route path="/drivers" element={<Drivers />} />
          <Route path="/saves" element={<Saves />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
