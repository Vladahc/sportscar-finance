from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_PATH = Path("data/state.json")


def _default() -> dict[str, Any]:
    return {
        "killed": False,
        "kill_reason": "",
        "last_alerts": {},
        "last_usd_rub": None,
        "last_cny_rub": None,
        "last_btc_usd": None,
        "btc_hour_ref": None,
        "peak_market_rub": None,
        "market_rub": None,
        "hurdle_t1": 5_720_000,
        "updated_at": None,
    }


def load() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _default()
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    base = _default()
    base.update(data)
    return base


def save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
