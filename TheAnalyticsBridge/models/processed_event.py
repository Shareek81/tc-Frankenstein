from dataclasses import dataclass
from datetime import datetime

from .ilog import ILog


@dataclass(frozen=True)
class ProcessedEvent:
    event_id: str
    log: ILog
    danger_score: int
    scoring_method: str
    processed_at: datetime

    def to_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "log": self.log.to_payload(),
            "danger_score": self.danger_score,
            "scoring_method": self.scoring_method,
            "processed_at": self.processed_at.isoformat(),
        }

    def __post_init__(self) -> None:
        if (
            isinstance(self.danger_score, bool)
            or not isinstance(self.danger_score, int)
            or not 1 <= self.danger_score <= 100
        ):
            raise ValueError("Danger score must be an integer from 1 to 100")