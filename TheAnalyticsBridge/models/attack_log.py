from dataclasses import dataclass
from datetime import datetime, time
from ipaddress import ip_address

from .ilog import ILog


@dataclass(frozen=True)
class AttackLog(ILog):
    time: time
    type: str
    severity: int
    origin: str

    def to_payload(self) -> dict[str, object]:
        return {
            "time": self.time.isoformat(),
            "type": self.type,
            "severity": self.severity,
            "origin": self.origin,
        }

    @classmethod
    def from_json(cls, payload: object) -> "AttackLog":
        if not isinstance(payload, dict):
            raise ValueError("An attack log must be an object")
        for field in ("time", "type", "origin"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid attack log field: {field}")
        severity = payload.get("severity")
        if isinstance(severity, bool) or not isinstance(severity, int) or not 1 <= severity <= 9:
            raise ValueError("Attack severity must be an integer from 1 to 9")
        occurred_at = datetime.strptime(payload["time"], "%H:%M:%S").time()
        if occurred_at.strftime("%H:%M:%S") != payload["time"]:
            raise ValueError("Attack time must use HH:mm:ss")
        return cls(
            time=occurred_at,
            type=payload["type"],
            severity=severity,
            origin=str(ip_address(payload["origin"])),
        )