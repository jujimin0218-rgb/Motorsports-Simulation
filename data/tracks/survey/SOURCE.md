# Surveyed centrelines

Fifteen of the twenty-two circuits on the calendar, as **centrelines** in
metres with the track width either side:

```
x_m, y_m, w_tr_right_m, w_tr_left_m
```

From the [TUM racetrack database](https://github.com/TUMFTM/racetrack-database),
which is published under an open licence by the Institute of Automotive
Technology at TU München.

A centreline rather than a racing line, which is the reason to prefer it: a
racing line has already cut every corner, and its radii are the driver's rather
than the circuit's.

`tools/extract_circuits.py` recovers corner radii, turn angles and straight
lengths from these and hands them to the engine's builder. Run it to see what
each circuit comes back as, and `docs/CIRCUITS.md` for what still stands
between these and shipping.

## What is here

Sakhir · Melbourne · Suzuka · Catalunya · Montreal · Spielberg · Silverstone ·
Spa · Budapest · Zandvoort · Monza · Austin · Mexico City · São Paulo ·
Yas Marina

## What is not

Jeddah, Miami, Imola, Monaco, Baku, Singapore and Las Vegas are not in this
database. They need another source.

Yas Marina is the **pre-2021 layout** — 5547 m against the current 5281 m. It
is real data, of a circuit that has since been modified.
