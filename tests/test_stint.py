"""A stint: what the consumables do to a car over more than one lap.

The unit tests either side of this file check each system in isolation.  What
matters for a race is that they compose -- that a set of tyres comes in, goes
off and is finished, that the car gets lighter, and that the energy store
settles -- and that none of it is written down as a per-lap number anywhere.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.rng import RngHub
from f1_race_engine.simulation import LapSimulator
from f1_race_engine.tyres import TyreState
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.vehicle.ers import ErsState


@pytest.fixture(scope="module")
def slicks():
    compounds = load_builtin_compounds()
    return {code: compounds[code] for code in ("S", "M", "H")}


def _stint(simulator, laps, *, compound=None, fuel_mass=90.0):
    tyres = TyreState()
    if compound is not None:
        tyres.fit(compound)
    energy = ErsState(energy_remaining=simulator.vehicle.spec.ers.capacity)
    results = []
    fuel = fuel_mass
    for lap in range(1, laps + 1):
        result = simulator.simulate(
            lap=lap, fuel_mass=fuel, tyre_state=tyres, ers_state=energy,
            record_telemetry=False,
        )
        fuel -= result.fuel_used
        results.append(result)
    return results, tyres, energy


# -- warm-up -----------------------------------------------------------------


def test_a_set_out_of_the_blankets_comes_in(fast_track, car, perfect_driver, slicks):
    """The out-lap is slow because the tyres are cold, and the tyres stop being
    cold because the car has been driving on them.  Neither is scripted."""
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(11))
    results, tyres, _ = _stint(simulator, 4, compound=slicks["M"])
    assert results[1].lap_time < results[0].lap_time
    assert results[0].tyre_temperature > slicks["M"].optimal_temperature - slicks[
        "M"
    ].temperature_window
    assert tyres.in_working_window


def test_the_carcass_takes_longer_than_the_tread(
    fast_track, car, perfect_driver, slicks
):
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(11))
    _, tyres, _ = _stint(simulator, 1, compound=slicks["M"])
    assert tyres.carcass_temperature < tyres.surface_temperature


# -- degradation -------------------------------------------------------------


def test_a_stint_goes_off(fast_track, car, perfect_driver, slicks):
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(11))
    results, tyres, _ = _stint(simulator, 15, compound=slicks["M"])
    assert tyres.wear > 0.1
    assert results[-1].tyre_grip < results[2].tyre_grip
    assert results[-1].lap_time > results[2].lap_time


def test_wear_comes_from_work_not_laps(fast_track, car, perfect_driver, slicks):
    """Two stints of the same length on the same tyre, one driven harder.  If
    wear were a per-lap number they would come out identical."""
    from f1_race_engine.driver import Driver, DriverAttributes

    def attributes(**overrides):
        base = dict(
            pace=0.95, qualifying=0.95, racecraft=0.95, consistency=1.0,
            tyre_management=0.90, braking=0.95, cornering=0.95,
            throttle_control=0.95, wet_skill=0.90, risk_management=1.0,
        )
        base.update(overrides)
        return Driver(name="T", abbreviation="T", attributes=DriverAttributes(**base))

    hard = attributes()
    gentle = attributes(cornering=0.70, braking=0.70, throttle_control=0.70)
    _, pushed, _ = _stint(
        LapSimulator(fast_track, car, hard, rng=RngHub(11)), 6, compound=slicks["M"]
    )
    _, cruised, _ = _stint(
        LapSimulator(fast_track, car, gentle, rng=RngHub(11)), 6, compound=slicks["M"]
    )
    assert pushed.wear > cruised.wear


def test_tyre_management_lengthens_a_stint(fast_track, car, slicks):
    from f1_race_engine.driver import Driver, DriverAttributes

    def driver(management):
        return Driver(
            name="T", abbreviation="T",
            attributes=DriverAttributes(
                pace=0.90, qualifying=0.90, racecraft=0.90, consistency=1.0,
                tyre_management=management, braking=0.90, cornering=0.90,
                throttle_control=0.90, wet_skill=0.90, risk_management=1.0,
            ),
        )

    _, careful, _ = _stint(
        LapSimulator(fast_track, car, driver(0.98), rng=RngHub(11)), 8,
        compound=slicks["M"],
    )
    _, careless, _ = _stint(
        LapSimulator(fast_track, car, driver(0.40), rng=RngHub(11)), 8,
        compound=slicks["M"],
    )
    assert careful.wear < careless.wear


def test_a_harder_compound_lasts_longer(fast_track, car, perfect_driver, slicks):
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(11))
    _, soft, _ = _stint(simulator, 8, compound=slicks["S"])
    _, hard, _ = _stint(simulator, 8, compound=slicks["H"])
    assert hard.wear < soft.wear


def test_a_softer_compound_is_quicker_when_it_is_working(
    fast_track, car, perfect_driver, slicks
):
    """The trade rule 20 asks for, and the reason a strategist has a choice at
    all: grip now against grip later."""
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(11))
    soft, _, _ = _stint(simulator, 4, compound=slicks["S"])
    hard, _, _ = _stint(simulator, 4, compound=slicks["H"])
    assert min(lap.lap_time for lap in soft) < min(lap.lap_time for lap in hard)


# -- fuel --------------------------------------------------------------------


def test_the_car_gets_lighter_and_the_laps_get_quicker(fast_track, car, slicks):
    """Isolated from tyre degradation by fitting a set that barely wears."""
    from f1_race_engine.driver import Driver, DriverAttributes

    driver = Driver(
        name="T", abbreviation="T",
        attributes=DriverAttributes(
            pace=0.90, qualifying=0.90, racecraft=0.90, consistency=1.0,
            tyre_management=1.0, braking=0.90, cornering=0.90,
            throttle_control=0.90, wet_skill=0.90, risk_management=1.0,
        ),
    )
    simulator = LapSimulator(fast_track, car, driver, rng=RngHub(11))
    tyres = TyreState()
    energy = ErsState(energy_remaining=car.spec.ers.capacity)
    fuel = 100.0
    times = []
    for lap in range(1, 6):
        # A fresh set every lap: only the fuel load is allowed to change.
        tyres.fit(slicks["H"], temperature=slicks["H"].optimal_temperature)
        result = simulator.simulate(
            lap=lap, fuel_mass=fuel, tyre_state=tyres, ers_state=energy,
            record_telemetry=False,
        )
        fuel -= result.fuel_used
        times.append(result.lap_time)
    assert fuel < 100.0
    assert times[-1] < times[0]


def test_the_fuel_books_balance(fast_track, car, perfect_driver):
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(11))
    results, _, _ = _stint(simulator, 5)
    total = sum(result.fuel_used for result in results)
    assert results[-1].final_state.fuel_mass == pytest.approx(90.0 - total, rel=1e-9)


# -- determinism -------------------------------------------------------------


def test_a_stint_is_reproducible(fast_track, car, perfect_driver, slicks):
    """Rule 36: consumables carry state across laps, and that state must be a
    function of the seed and the inputs alone."""
    def run():
        simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(99))
        results, tyres, energy = _stint(simulator, 6, compound=slicks["M"])
        return (
            [result.lap_time for result in results],
            tyres.wear, tyres.surface_temperature, energy.energy_remaining,
        )

    assert run() == run()


def test_results_carry_the_consumables(fast_track, car, perfect_driver):
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(11))
    payload = simulator.simulate(record_telemetry=False).to_dict()
    for key in ("fuel_used", "energy_deployed", "energy_harvested",
                "tyre_wear", "tyre_temperature", "tyre_grip"):
        assert isinstance(payload[key], float)


# -- the stint has to settle -------------------------------------------------


def test_a_stint_settles_instead_of_oscillating(street_track, car, perfect_driver,
                                                slicks):
    """Lap times must drift, not alternate.

    A lap is planned before it is driven, so it is planned from some tyre
    temperature.  Taking that from the single reading at the timing line closes
    a feedback loop with a one-lap delay: a hot reading makes the whole next
    lap slow, the slow lap cools the tyre, and the lap after that is fast
    again.  On a circuit that works the tread hard the gain of that loop
    reaches one and the stint oscillates -- sixteen seconds a lap, alternating,
    which is not a tyre going off but a numerical artefact.

    The street circuit is the one that exposes it: slow, busy, and hardest on
    tread temperature.
    """
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator

    simulator = LapSimulator(street_track, car, perfect_driver, rng=RngHub(20260812))
    results, _, _ = _stint(simulator, 12, compound=slicks["S"], fuel_mass=45.0)
    times = [r.lap_time for r in results]

    # Past the opening laps, which are a set coming out of the blankets and
    # working up to temperature -- a real transient, and the thing an
    # oscillation is easy to mistake for.
    settled = times[4:]
    steps = [b - a for a, b in zip(settled, settled[1:])]
    assert max(abs(s) for s in steps) < 1.0, f"lap times jump around: {settled}"

    # And it degrades in one direction rather than sawtoothing.
    signs = [1 if s > 0 else -1 for s in steps if abs(s) > 0.01]
    alternations = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    assert alternations <= 1, f"lap times alternate: {settled}"
