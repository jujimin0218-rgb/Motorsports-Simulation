"""Deterministic randomness (project rules 36 and 40, Test A)."""

from __future__ import annotations

import math
import statistics

import pytest

from f1_race_engine.core.errors import F1EngineError
from f1_race_engine.core.rng import RandomStream, RngHub, derive_seed


def test_same_seed_gives_the_same_sequence():
    """Test A: same input plus same seed reproduces the result exactly."""
    a = RngHub(20260812)
    b = RngHub(20260812)
    first = [a.stream("tyre.wear", car=44).normal(0.0, 1.0) for _ in range(20)]
    second = [b.stream("tyre.wear", car=44).normal(0.0, 1.0) for _ in range(20)]
    assert first == second


def test_different_seeds_diverge():
    hub_a, hub_b = RngHub(1), RngHub(2)
    a = [hub_a.stream("x").random() for _ in range(5)]
    b = [hub_b.stream("x").random() for _ in range(5)]
    assert a != b


def test_adding_a_new_subsystem_does_not_disturb_existing_streams():
    """The property that makes long-term development possible.

    A new subsystem drawing randomness must not shift the numbers every other
    subsystem sees, or adding a feature would silently invalidate every result
    recorded before it.
    """
    reference_hub = RngHub(7)
    reference = [reference_hub.stream("tyre.wear", car=1).normal() for _ in range(10)]

    hub = RngHub(7)
    for _ in range(500):  # a whole new subsystem, consuming heavily
        hub.stream("driver.mistakes", car=3, lap=9).random()
    after = [hub.stream("tyre.wear", car=1).normal() for _ in range(10)]

    assert after == reference


def test_streams_are_independent_across_qualifiers():
    hub = RngHub(99)
    car1 = [hub.stream("brakes", car=1).random() for _ in range(10)]
    car2 = [hub.stream("brakes", car=2).random() for _ in range(10)]
    assert car1 != car2


def test_qualifier_order_does_not_matter():
    hub = RngHub(5)
    assert hub.seed_for("x", car=1, lap=2) == hub.seed_for("x", lap=2, car=1)


def test_repeated_access_continues_the_same_stream():
    hub = RngHub(3)
    first = hub.stream("a").random()
    second = hub.stream("a").random()
    assert first != second
    assert hub.stream("a").draw_count == 2


def test_reset_rewinds_every_stream():
    hub = RngHub(11)
    first = [hub.stream("a").random() for _ in range(5)]
    hub.reset()
    assert [hub.stream("a").random() for _ in range(5)] == first


def test_forget_recreates_streams_from_the_seed():
    hub = RngHub(11)
    first = [hub.stream("a").random() for _ in range(5)]
    hub.forget()
    assert hub.active_paths == ()
    assert [hub.stream("a").random() for _ in range(5)] == first


def test_derive_seed_is_stable_across_processes():
    """Hashing must not depend on PYTHONHASHSEED."""
    assert derive_seed(20260812, "tyre.wear|car=44") == derive_seed(
        20260812, "tyre.wear|car=44"
    )
    assert derive_seed(1, "a") != derive_seed(1, "b")
    assert derive_seed(1, "a") != derive_seed(2, "a")


def test_child_streams_are_independent():
    parent = RandomStream(12345, "parent")
    child_a = parent.derive("a")
    child_b = parent.derive("b")
    assert child_a.seed != child_b.seed
    assert [child_a.random() for _ in range(5)] != [child_b.random() for _ in range(5)]


def test_normal_distribution_statistics():
    stream = RngHub(7).stream("normal")
    samples = [stream.normal(10.0, 2.0) for _ in range(40000)]
    assert statistics.fmean(samples) == pytest.approx(10.0, abs=0.05)
    assert statistics.pstdev(samples) == pytest.approx(2.0, abs=0.05)


def test_normal_consumes_a_fixed_number_of_draws():
    """Predictable draw counts make reproducibility failures bisectable."""
    stream = RngHub(7).stream("normal")
    for _ in range(100):
        stream.normal()
    assert stream.draw_count == 200


def test_zero_sigma_returns_the_mean_without_changing_draw_accounting():
    stream = RngHub(7).stream("normal")
    assert stream.normal(5.0, 0.0) == 5.0
    assert stream.draw_count == 2


def test_uniform_and_integer_ranges():
    stream = RngHub(13).stream("u")
    values = [stream.uniform(-3.0, 7.0) for _ in range(5000)]
    assert all(-3.0 <= v < 7.0 for v in values)
    integers = [stream.integer(2, 5) for _ in range(5000)]
    assert set(integers) == {2, 3, 4, 5}


def test_integer_rejects_an_empty_range():
    with pytest.raises(ValueError):
        RngHub(1).stream("x").integer(5, 2)


def test_chance_matches_its_probability():
    stream = RngHub(4).stream("c")
    hits = sum(stream.chance(0.25) for _ in range(40000))
    assert hits / 40000 == pytest.approx(0.25, abs=0.01)
    assert RngHub(4).stream("d").chance(0.0) is False
    assert RngHub(4).stream("d").chance(1.0) is True


def test_triangular_mean_matches_theory():
    stream = RngHub(5).stream("t")
    samples = [stream.triangular(0.0, 10.0, 3.0) for _ in range(40000)]
    assert statistics.fmean(samples) == pytest.approx((0.0 + 10.0 + 3.0) / 3.0, abs=0.06)
    assert all(0.0 <= s <= 10.0 for s in samples)


def test_truncated_normal_respects_its_bounds():
    stream = RngHub(6).stream("tn")
    samples = [stream.truncated_normal(0.0, 5.0, -1.0, 1.0) for _ in range(2000)]
    assert all(-1.0 <= s <= 1.0 for s in samples)


def test_weighted_choice_follows_its_weights():
    stream = RngHub(8).stream("w")
    counts = {"a": 0, "b": 0}
    for _ in range(20000):
        counts[stream.weighted_choice(["a", "b"], [3.0, 1.0])] += 1
    assert counts["a"] / 20000 == pytest.approx(0.75, abs=0.02)


def test_weighted_choice_validates_its_input():
    stream = RngHub(8).stream("w")
    with pytest.raises(ValueError):
        stream.weighted_choice(["a"], [1.0, 2.0])
    with pytest.raises(ValueError):
        stream.weighted_choice([], [])
    with pytest.raises(ValueError):
        stream.weighted_choice(["a", "b"], [0.0, 0.0])


def test_shuffled_is_a_permutation_and_is_reproducible():
    items = list(range(20))
    first = RngHub(21).stream("s").shuffled(items)
    second = RngHub(21).stream("s").shuffled(items)
    assert first == second
    assert sorted(first) == items
    assert items == list(range(20))  # input untouched


def test_choice_rejects_an_empty_sequence():
    with pytest.raises(ValueError):
        RngHub(1).stream("x").choice([])


def test_snapshot_records_stream_bookkeeping():
    hub = RngHub(31)
    hub.stream("a").random()
    hub.stream("b", car=2).normal()
    snapshot = hub.snapshot()
    assert snapshot.master_seed == 31
    assert {path for path, _, _ in snapshot.streams} == {"a", "b|car=2"}
    assert hub.total_draws() == 3
    assert snapshot.to_dict()["master_seed"] == 31


def test_spawned_hubs_are_independent():
    hub = RngHub(41)
    qualifying = hub.spawn("qualifying")
    race = hub.spawn("race")
    assert qualifying.master_seed != race.master_seed
    assert qualifying.stream("x").random() != race.stream("x").random()


def test_non_integer_seed_is_rejected():
    with pytest.raises(F1EngineError):
        RngHub("20260812")  # type: ignore[arg-type]
