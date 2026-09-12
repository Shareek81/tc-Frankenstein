from dataclasses import dataclass
from datetime import datetime

from .ilog import ILog


@dataclass(frozen=True)
class ProcessedEvent:
    event_id: str
    log: ILog
    danger_score: int | None
    scoring_method: str
    processed_at: datetime
    insight: tuple[str, ...] = ()
    respondsuggested: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "log": self.log.to_payload(),
            "danger_score": self.danger_score,
            "scoring_method": self.scoring_method,
            "processed_at": self.processed_at.isoformat(),
            "insight": list(self.insight),
            "respondsuggested": list(self.respondsuggested),
        }

    def __post_init__(self) -> None:
        if self.danger_score is None:
            if self.insight or self.respondsuggested:
                raise ValueError("Unscored events cannot contain AI insights or responses")
            return
        if (
            isinstance(self.danger_score, bool)
            or not isinstance(self.danger_score, int)
            or not 1 <= self.danger_score <= 100
        ):
            raise ValueError("Danger score must be an integer from 1 to 100")
        if not self.insight and not self.respondsuggested:
            return
        for points in (self.insight, self.respondsuggested):
            if not isinstance(points, tuple) or len(points) != 2 or any(
                not isinstance(point, str) or not point.strip() or len(point) > 400
                for point in points
            ):
                raise ValueError("AI insight and response must each contain exactly two nonblank points")