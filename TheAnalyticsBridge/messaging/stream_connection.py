from dataclasses import dataclass

from models import ProcessedEvent

from .contracts import EventSubscription


@dataclass(frozen=True)
class StreamConnection:
    history: tuple[ProcessedEvent, ...]
    subscription: EventSubscription