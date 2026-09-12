from dataclasses import dataclass


@dataclass(frozen=True)
class EventAssessment:
    danger_score: int
    insight: tuple[str, str]
    respondsuggested: tuple[str, str]