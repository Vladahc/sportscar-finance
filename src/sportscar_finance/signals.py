from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sportscar_finance.config import Settings


@dataclass
class Signal:
    """Одно сообщение человеку: что случилось и насколько это серьёзно."""

    kind: str
    # info — просто знать; warn — осторожно; kill — стоп, больше не рисковать
    severity: str
    title: str
    body: str


def _move(prev: float | None, cur: float | None) -> float | None:
    """На сколько цена изменилась по сравнению с прошлым разом (доля, не рубли)."""
    if prev is None or cur is None or prev == 0:
        return None
    return (cur - prev) / prev


def evaluate(
    settings: Settings,
    state: dict[str, Any],
    *,
    usd_rub: float | None = None,
    cny_rub: float | None = None,
    btc_usd: float | None = None,
    btc_change_24h: float | None = None,
    market_rub: float | None = None,
) -> list[Signal]:
    """Смотрит новые курсы и решает, о чём предупредить."""
    signals: list[Signal] = []
    now = datetime.now(timezone.utc).isoformat()

    usd_move = _move(state.get("last_usd_rub"), usd_rub)
    if usd_move is not None and abs(usd_move) >= settings.usd_rub_day_move:
        signals.append(
            Signal(
                "FX_USD",
                "warn",
                f"Доллар к рублю {usd_move:+.2%}",
                f"Было {state['last_usd_rub']:.4f}, стало {usd_rub:.4f}. "
                "Подумай, оставлять ли деньги в рублях или часть в валюте.",
            )
        )

    cny_move = _move(state.get("last_cny_rub"), cny_rub)
    if cny_move is not None and abs(cny_move) >= settings.usd_rub_day_move:
        signals.append(
            Signal(
                "FX_CNY",
                "warn",
                f"Юань к рублю {cny_move:+.2%}",
                f"Цена машины из Китая едет вместе с юанем. "
                f"Было {state['last_cny_rub']:.4f}, стало {cny_rub:.4f}.",
            )
        )

    if btc_change_24h is not None and abs(btc_change_24h) >= settings.btc_day_move:
        signals.append(
            Signal(
                "BTC_DAY",
                "warn",
                f"Биткоин за сутки {btc_change_24h:+.2%}",
                "Не докупать на заёмные деньги. Проверь, не просели ли слишком сильно "
                "деньги, которые лежат в биткоине.",
            )
        )

    hour_ref = state.get("btc_hour_ref")
    hour_move = _move(hour_ref[1] if hour_ref else None, btc_usd)
    if hour_ref and hour_move is not None and abs(hour_move) >= settings.btc_hour_move:
        signals.append(
            Signal(
                "BTC_HOUR",
                "warn",
                f"Биткоин за час {hour_move:+.2%}",
                f"{hour_ref[1]} → {btc_usd}. Сейчас не увеличивать риск.",
            )
        )

    if market_rub is not None:
        peak = state.get("peak_market_rub") or market_rub
        peak = max(peak, market_rub)
        # Насколько текущая сумма ниже самой высокой точки.
        dd = 1.0 - market_rub / peak if peak else 0.0
        if dd >= settings.market_dd_kill:
            signals.append(
                Signal(
                    "DD_KILL",
                    "kill",
                    f"Рыночные деньги просели на {dd:.0%}",
                    "Стоп: переложи рискованные деньги в спокойный вклад. "
                    "Работу и заработок не останавливай.",
                )
            )
        elif dd >= settings.market_dd_warn:
            signals.append(
                Signal(
                    "DD_WARN",
                    "warn",
                    f"Рыночные деньги просели на {dd:.0%}",
                    "Это предупреждение. Пока не добавляй риск.",
                )
            )
        state["peak_market_rub"] = peak
        state["market_rub"] = market_rub

    if usd_rub is not None:
        state["last_usd_rub"] = usd_rub
    if cny_rub is not None:
        state["last_cny_rub"] = cny_rub
    if btc_usd is not None:
        state["last_btc_usd"] = btc_usd
        state["btc_hour_ref"] = [now, btc_usd]

    return signals


def format_status(settings: Settings, state: dict[str, Any]) -> str:
    """Короткая сводка: сколько денег, сколько ещё нужно, включён ли стоп."""
    capital = settings.cash_rub + settings.btc_sleeve_rub + settings.skill_reserve_rub
    hurdle = state.get("hurdle_t1") or settings.hurdle_t1
    gap = max(hurdle - capital, 0)
    killed = "включён" if state.get("killed") else "выключен"
    return (
        f"План «работа плюс спокойный рынок»\n"
        f"Деньги на старте (как записали): {capital:,.0f} ₽\n"
        f"Нужно на базовую машину: {hurdle:,.0f} ₽\n"
        f"Ещё не хватает: {gap:,.0f} ₽\n"
        f"Доллар к рублю: {state.get('last_usd_rub')}\n"
        f"Юань к рублю: {state.get('last_cny_rub')}\n"
        f"Биткоин, $: {state.get('last_btc_usd')}\n"
        f"Стоп риска: {killed}\n"
        f"Обновлено: {state.get('updated_at') or 'проверки ещё не было'}\n"
        f"Напоминание: машину покупает заработок, а не игра на заёмные деньги."
    ).replace(",", " ")
