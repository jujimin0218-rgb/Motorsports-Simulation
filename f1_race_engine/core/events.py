"""A small, deterministic event bus.

Project rule 35 requires race events (safety car, VSC, red flag, failures,
collisions, driver mistakes) to reach the race state through an event layer
rather than being wired into the physics.  This module is that seam; it is
deliberately tiny, because the value is the *boundary*, not the machinery.

Two properties matter for a reproducible simulation:

* **Deterministic dispatch order.**  Handlers run by descending priority, and
  ties break by subscription order -- never by dict or set iteration order.
* **A replayable record.**  Every emitted event is kept (optionally capped), so
  a race result can be explained after the fact and a divergence between two
  runs can be traced to the first event that differed.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

TEvent = TypeVar("TEvent", bound="Event")


@dataclass(frozen=True)
class Event:
    """Base class for everything that flows through the bus.

    Subclasses add their own fields; ``time`` is the simulated time at which
    the event occurred, and ``data`` carries anything a consumer may want that
    does not deserve a dedicated field.
    """

    time: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return type(self).__name__

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        payload = asdict(self)
        payload["event"] = self.name
        return payload


@dataclass(frozen=True)
class Subscription:
    """A registered handler.  Cancel it by calling :meth:`unsubscribe`."""

    event_type: type[Event]
    handler: Callable[[Any], None]
    priority: int
    order: int
    bus: "EventBus" = field(repr=False)

    def unsubscribe(self) -> None:
        self.bus.unsubscribe(self)


class EventBus:
    """Publish/subscribe hub with deterministic ordering.

    Handlers registered for a base class also receive subclass events, so a
    listener can watch ``Event`` to log everything, or a specific subclass to
    react to one thing.
    """

    __slots__ = ("_subscriptions", "_counter", "_history", "_history_limit", "_recording")

    def __init__(self, *, record_history: bool = True, history_limit: int | None = None) -> None:
        self._subscriptions: list[Subscription] = []
        self._counter = itertools.count()
        self._history: list[Event] = []
        self._history_limit = history_limit
        self._recording = record_history

    # -- subscription --------------------------------------------------------

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], None],
        *,
        priority: int = 0,
    ) -> Subscription:
        """Register ``handler`` for ``event_type`` and its subclasses."""
        if not (isinstance(event_type, type) and issubclass(event_type, Event)):
            raise TypeError(f"{event_type!r} is not an Event subclass")
        subscription = Subscription(
            event_type=event_type,
            handler=handler,
            priority=priority,
            order=next(self._counter),
            bus=self,
        )
        self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        try:
            self._subscriptions.remove(subscription)
        except ValueError:
            pass

    def clear_subscriptions(self) -> None:
        self._subscriptions.clear()

    # -- emission ------------------------------------------------------------

    def emit(self, event: Event) -> Event:
        """Deliver ``event`` to every matching handler, in a stable order."""
        if self._recording:
            self._history.append(event)
            if self._history_limit is not None and len(self._history) > self._history_limit:
                del self._history[: len(self._history) - self._history_limit]
        for subscription in self._matching(type(event)):
            subscription.handler(event)
        return event

    def emit_all(self, events: Iterable[Event]) -> None:
        for event in events:
            self.emit(event)

    def _matching(self, event_type: type[Event]) -> list[Subscription]:
        matches = [s for s in self._subscriptions if issubclass(event_type, s.event_type)]
        matches.sort(key=lambda s: (-s.priority, s.order))
        return matches

    # -- history -------------------------------------------------------------

    @property
    def history(self) -> tuple[Event, ...]:
        return tuple(self._history)

    def history_of(self, event_type: type[TEvent]) -> tuple[TEvent, ...]:
        return tuple(e for e in self._history if isinstance(e, event_type))

    def clear_history(self) -> None:
        self._history.clear()

    def to_dict(self) -> dict[str, Any]:
        return {"events": [event.to_dict() for event in self._history]}

    def __len__(self) -> int:
        return len(self._history)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._history)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"EventBus(subscriptions={len(self._subscriptions)}, "
            f"history={len(self._history)})"
        )
