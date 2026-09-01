# Beta — running it

    pip install -e ".[server]"
    python play.py

That is the whole thing.  It builds the page if it needs to, starts the server,
and opens a browser at it.  One process, one port.

Needs **Python 3.11+** and **Node 18+**.  The build output is not committed
(it is in `.gitignore`), so the first run installs the frontend packages and
builds the page — about a minute, once.  After that `play.py` reuses the build
and only rebuilds when the source is newer.

If you are handed a copy that already has `frontend/dist` in it, Node is not
needed at all.

    python play.py --rounds 1        one race (the default)
    python play.py --rounds 22       the full season
    python play.py --port 9000       somewhere else
    python play.py --no-browser      just serve it

## What to expect

Pick a team, pick a season length and a race distance, and start.  Then, per
round: **Start round → Practice → Qualifying → Race**, and between rounds,
development, contracts and finances.

Qualifying and the race are long enough to be run as jobs, because they are
real simulations rather than dice — so you watch them rather than wait for
them.  The race screen is a timing tower that moves a lap at a time: the order,
the gaps, who has stopped.  Qualifying builds its order up as the laps are set,
segment by segment.  The times below are how long that takes:

| | quarter distance | half | full |
|---|---|---|---|
| qualifying | ~1m 45s | ~1m 45s | ~1m 45s |
| race | ~2m 20s | ~5m 20s | ~10m |
| **a weekend** | **~4m** | **~7m** | **~12m** |

Qualifying costs the same at any race distance — it is three knockout segments
with every car running out-laps and flying laps on a track that rubbers in, and
the race length has nothing to do with it.

A shorter race is genuinely a shorter race: fewer stops, less tyre wear to
manage.  It is not a rougher guess at a longer one.  Every lap is simulated
either way.

## The circuit

The beta's one round is **Bahrain**, on measured geometry — the layout came out
of a surveyed centreline, lands on the published 5412 m exactly, and computes a
qualifying lap within 1.75 s of the real 2024 pole.  Eleven of the twenty-two
calendar circuits are like this; the rest are still synthetic.  See
`docs/CIRCUITS.md`.

## The live race

`Live race` in the sidebar is a different thing from the timing tower on the
weekend screen.  That one reads back a session the engine has already
simulated; this one *is* the simulation — twenty cars with their own physics and
their own drivers being driven round the circuit in front of you.

Click a car, or a row in the tower, to watch from it.  **Onboard** puts the
camera on the car and rotates the world round it; **Chase** sits behind it.

## What is worth poking at

- **The same car is quicker in different places.**  Take a power-biased team
  (Scuderia Lucente) and an aero-biased one (Apex GP), and the gap between them
  is roughly twice as large at the Hungaroring as at Monza.  That comes out of
  the geometry, not a per-circuit table.
- **Setup matters.**  Monza wants minimum wing and gets slower with more.
- **Seeds are honest.**  The same seed gives the same season, all the way down
  to which lap a failure happens on.  Enter one and you can replay anything.
- **The replay.**  After a race, `Replay` has where every car was every two
  seconds, from the same run that produced the result.

## Known rough edges

- Qualifying takes about a minute and three quarters and there is no way to
  skip it.
- Seven calendar circuits — Jeddah, Miami, Imola, Monaco, Baku, Singapore, Las
  Vegas — have no survey data, so they run on synthetic layouts.  Three more
  (Albert Park, Catalunya, Yas Marina) have real surveys of the *previous*
  layout and are deliberately held back.
- Spa is not shipped: its survey has no elevation and Raidillon climbs forty
  metres, so a flat Spa runs about five seconds a lap too fast.

## If something breaks

The server prints tracebacks to the terminal it was started from.  A save is
written automatically after each phase, so `Saves` should let you carry on from
just before whatever went wrong.
