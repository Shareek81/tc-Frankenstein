from abc import ABC, abstractmethod


class ILog(ABC):
    @abstractmethod
    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable representation of this log."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_json(cls, payload: object) -> "ILog":
        raise NotImplementedError