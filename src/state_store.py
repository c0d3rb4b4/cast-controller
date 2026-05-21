from __future__ import annotations

import threading
from pathlib import Path

from models import ControllerState, utc_now


class StateStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> ControllerState:
        with self._lock:
            if not self.path.exists():
                return ControllerState()

            raw_state = self.path.read_text(encoding="utf-8").strip()
            if not raw_state:
                return ControllerState()

            return ControllerState.model_validate_json(raw_state)

    def save(self, state: ControllerState) -> ControllerState:
        with self._lock:
            state.updated_at = utc_now()
            self.path.parent.mkdir(parents=True, exist_ok=True)

            tmp_path = self.path.with_name(f"{self.path.name}.tmp")
            tmp_path.write_text(
                state.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(self.path)
            return state

