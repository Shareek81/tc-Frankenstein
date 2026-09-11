from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address

from .ilog import ILog


@dataclass(frozen=True)
class LegacyLog(ILog):
    timestamp: datetime
    source: str
    event: str
    status: str

    def to_payload(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "event": self.event,
            "status": self.status,
        }

    @classmethod
    def from_json(cls, payload: object) -> "LegacyLog":
        if not isinstance(payload, dict):
            raise ValueError("A legacy log must be an object")
        for field in ("timestamp", "source", "event", "status"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid legacy log field: {field}")
        return cls(
            timestamp=datetime.fromisoformat(payload["timestamp"]),
            source=str(ip_address(payload["source"])),
            event=payload["event"],
            status=payload["status"],
        )