from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Здесь бот помнит последние курсы и включён ли «стоп».
STATE_PATH = Path("data/state.json")


def _default() -> dict[str, Any]:
    """Пустая память на самый первый запуск."""
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
    """Читает память с диска. Если файла ещё нет — возвращает пустую."""
    if not STATE_PATH.exists():
        return _default()
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    base = _default()
    base.update(data)
    return base


def save(state: dict[str, Any]) -> None:
    """Сохраняет память на диск и ставит время обновления."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
