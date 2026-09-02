"""The event bus: the seam race events will arrive through (project rule 35)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from f1_race_engine.core.events import Event, EventBus


@dataclass(frozen=True)
class SafetyCar(Event):
    reason: str = ""


@dataclass(frozen=True)
class VirtualSafetyCar(SafetyCar):
    pass


def test_handlers_receive_their_event():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(SafetyCar, seen.append)
    event = bus.emit(SafetyCar(time=12.0, reason="debris"))
    assert seen == [event]


def test_base_class_subscription_receives_subclasses():
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(Event, lambda e: seen.append(e.name))
    bus.emit(VirtualSafetyCar(time=1.0))
    bus.emit(Event(time=2.0))
    assert seen == ["VirtualSafetyCar", "Event"]


def test_subclass_subscription_ignores_the_base_class():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(VirtualSafetyCar, seen.append)
    bus.emit(SafetyCar(time=1.0))
    assert seen == []


def test_dispatch_order_is_deterministic():
    """Reproducibility requires a stable order, never dict iteration order."""
    bus = EventBus()
    order: list[str] = []
    bus.subscribe(Event, lambda e: order.append("low"), priority=-5)
    bus.subscribe(Event, lambda e: order.append("high"), priority=10)
    bus.subscribe(Event, lambda e: order.append("mid-a"), priority=0)
    bus.subscribe(Event, lambda e: order.append("mid-b"), priority=0)
    bus.emit(Event())
    assert order == ["high", "mid-a", "mid-b", "low"]


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    seen: list[Event] = []
    subscription = bus.subscribe(Event, seen.append)
    bus.emit(Event())
    subscription.unsubscribe()
    bus.emit(Event())
    assert len(seen) == 1
    subscription.unsubscribe()  # idempotent


def test_history_is_recorded_and_filterable():
    bus = EventBus()
    bus.emit(SafetyCar(time=1.0, reason="a"))
    bus.emit(Event(time=2.0))
    assert len(bus) == 2
    assert len(bus.history_of(SafetyCar)) == 1
    assert [e.name for e in bus] == ["SafetyCar", "Event"]
    bus.clear_history()
    assert len(bus) == 0


def test_history_can_be_disabled_or_capped():
    quiet = EventBus(record_history=False)
    quiet.emit(Event())
    assert len(quiet) == 0

    capped = EventBus(history_limit=3)
    for i in range(10):
        capped.emit(Event(time=float(i)))
    assert len(capped) == 3
    assert [e.time for e in capped] == [7.0, 8.0, 9.0]


def test_emit_all():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(Event, seen.append)
    bus.emit_all([Event(time=1.0), Event(time=2.0)])
    assert len(seen) == 2


def test_export_is_plain_data():
    bus = EventBus()
    bus.emit(SafetyCar(time=3.0, reason="rain"))
    payload = bus.to_dict()
    assert payload["events"][0]["event"] == "SafetyCar"
    assert payload["events"][0]["reason"] == "rain"


def test_only_event_subclasses_can_be_subscribed():
    with pytest.raises(TypeError):
        EventBus().subscribe(str, lambda e: None)  # type: ignore[arg-type]


def test_clear_subscriptions():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(Event, seen.append)
    bus.clear_subscriptions()
    bus.emit(Event())
    assert seen == []
