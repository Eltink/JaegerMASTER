from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from typing import Protocol
except ImportError:  # Python < 3.8
    class Protocol:  # type: ignore[no-redef]
        pass


class EventPublisher(Protocol):
    def record_event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        ...


class NullEventPublisher:
    def record_event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        return None


@dataclass
class RecordingEventPublisher:
    events: list[tuple[str, dict[str, Any]]] | None = None

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []

    def record_event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        assert self.events is not None
        self.events.append((name, payload or {}))
