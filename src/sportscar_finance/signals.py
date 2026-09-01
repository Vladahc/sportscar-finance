from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sportscar_finance.config import Settings


@dataclass
class Signal:
    kind: str
    severity: str  # info | warn | kill
    title: str
    body: str


def _move(prev: float | None, cur: float | None) -> float | None:
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
    signals: list[Signal] = []
    now = datetime.now(timezone.utc).isoformat()

    usd_move = _move(state.get("last_usd_rub"), usd_rub)
    if usd_move is not None and abs(usd_move) >= settings.usd_rub_day_move:
        signals.append(
            Signal(
                "FX_USD",
                "warn",
                f"USD/RUB {usd_move:+.2%}",
                f"Было {state['last_usd_rub']:.4f}, стало {usd_rub:.4f}. Пересмотреть MM vs валютный кэш.",
            )
        )

    cny_move = _move(state.get("last_cny_rub"), cny_rub)
    if cny_move is not None and abs(cny_move) >= settings.usd_rub_day_move:
        signals.append(
            Signal(
                "FX_CNY",
                "warn",
                f"CNY/RUB {cny_move:+.2%}",
                f"Барьер SU7 двигается с юанем. Было {state['last_cny_rub']:.4f}, стало {cny_rub:.4f}.",
            )
        )

    if btc_change_24h is not None and abs(btc_change_24h) >= settings.btc_day_move:
        signals.append(
            Signal(
                "BTC_DAY",
                "warn",
                f"BTC за сутки {btc_change_24h:+.2%}",
                "Не усреднять плечом. Сверить правило DD по крипто-рукаву.",
            )
        )

    hour_ref = state.get("btc_hour_ref")
    hour_move = _move(hour_ref[1] if hour_ref else None, btc_usd)
    if hour_ref and hour_move is not None and abs(hour_move) >= settings.btc_hour_move:
        signals.append(
            Signal(
                "BTC_HOUR",
                "warn",
                f"BTC за час {hour_move:+.2%}",
                f"{hour_ref[1]} → {btc_usd}. Часовой контур: не увеличивать плечо.",
            )
        )

    if market_rub is not None:
        peak = state.get("peak_market_rub") or market_rub
        peak = max(peak, market_rub)
        dd = 1.0 - market_rub / peak if peak else 0.0
        if dd >= settings.market_dd_kill:
            signals.append(
                Signal(
                    "DD_KILL",
                    "kill",
                    f"DD рыночного рукава {dd:.0%}",
                    "Сигнал KILL_MARKET_SLEEVE: перевести риск в денежный рынок. Навык не останавливать.",
                )
            )
        elif dd >= settings.market_dd_warn:
            signals.append(
                Signal(
                    "DD_WARN",
                    "warn",
                    f"DD рыночного рукава {dd:.0%}",
                    "Порог предупреждения. Не добавлять риск до восстановления.",
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
    capital = settings.cash_rub + settings.btc_sleeve_rub + settings.skill_reserve_rub
    hurdle = state.get("hurdle_t1") or settings.hurdle_t1
    gap = max(hurdle - capital, 0)
    killed = "ВКЛ" if state.get("killed") else "выкл"
    return (
        f"Контур SU7 / T-B\n"
        f"Капитал (журнал старта): {capital:,.0f} ₽\n"
        f"Барьер T1: {hurdle:,.0f} ₽\n"
        f"Гэп: {gap:,.0f} ₽\n"
        f"USD/RUB: {state.get('last_usd_rub')}\n"
        f"CNY/RUB: {state.get('last_cny_rub')}\n"
        f"BTC: {state.get('last_btc_usd')}\n"
        f"Kill-switch: {killed}\n"
        f"Обновлено: {state.get('updated_at') or 'ещё не было цикла'}\n"
        f"Напоминание: P(T1) двигает чек навыка, не плечо."
    ).replace(",", " ")
