import json
import os
from typing import Dict, Optional

class StrategyState:
    STATE_FILE = "data/strategy_state.json"

    def __init__(self):
        self._state = self._load()
        print(f"[StrategyState] Loaded: Active={self.is_active()}")

    def _load(self) -> dict:
        if os.path.exists(self.STATE_FILE):
            try:
                with open(self.STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[StrategyState] Failed to load state: {e}")
        return {
            "active": False,
            "frozen_ratio": None,
            "master_initial_margin": None
        }

    def _save(self):
        try:
            with open(self.STATE_FILE, "w") as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            print(f"[StrategyState] Failed to save state: {e}")

    def is_active(self) -> bool:
        return self._state.get("active", False)

    def activate(self):
        """Mark strategy as ACTIVE."""
        if not self.is_active():
            self._state["active"] = True
            print("[StrategyState] State set to ACTIVE.")
            self._save()

    def clear(self):
        """Reset strategy state (Full Exit)."""
        print("[StrategyState] Clearing state (Full Exit).")
        self._state = {
            "active": False,
            "frozen_ratio": None,
            "master_initial_margin": None
        }
        self._save()

    def get_frozen_ratio(self, child_id: str) -> float:
        """Get frozen ratio for a child. Returns 0.0 if not found."""
        ratios = self._state.get("frozen_ratio") or {}
        return ratios.get(child_id, 0.0)

    def set_frozen_ratio(self, child_id: str, ratio: float):
        """Set frozen ratio for a child."""
        if self._state.get("frozen_ratio") is None:
            self._state["frozen_ratio"] = {}
        self._state["frozen_ratio"][child_id] = ratio
        self._save()

    def get_master_initial_margin(self) -> Optional[float]:
        return self._state.get("master_initial_margin")

    def set_master_initial_margin(self, margin: float):
        self._state["master_initial_margin"] = margin
        self._save()

# Singleton Instance
state_manager = StrategyState()
