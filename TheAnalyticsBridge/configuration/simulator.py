import os
from pathlib import Path

from . import load_environment


def load_simulator_stop_path() -> Path:
    bridge_path = load_environment()
    value = os.environ["ATTACK_SIM_STOP_PATH"].strip()
    if not value:
        raise ValueError("ATTACK_SIM_STOP_PATH must not be empty")
    stop_path = Path(value)
    if not stop_path.is_absolute():
        stop_path = bridge_path / stop_path
    return stop_path.resolve()


if __name__ == "__main__":
    print(load_simulator_stop_path())