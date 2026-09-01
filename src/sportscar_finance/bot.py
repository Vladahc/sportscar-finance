from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from sportscar_finance.config import Settings, load_settings
from sportscar_finance.feeds import fetch_btc, fetch_cbr_fx
from sportscar_finance.signals import Signal, evaluate, format_status
from sportscar_finance.store import load as load_state
from sportscar_finance.store import save as save_state

log = logging.getLogger("sportscar_finance")
MSK = ZoneInfo("Europe/Moscow")


def _cooldown_ok(state: dict, kind: str, seconds: int = 7200) -> bool:
    last = (state.get("last_alerts") or {}).get(kind)
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(last)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - prev >= timedelta(seconds=seconds)


def _mark_alert(state: dict, kind: str) -> None:
    alerts = state.setdefault("last_alerts", {})
    alerts[kind] = datetime.now(timezone.utc).isoformat()


async def _send(bot: Bot, chat_id: str, text: str) -> None:
    await bot.send_message(chat_id, text[:3900])


def _render(sig: Signal) -> str:
    tag = {"info": "INFO", "warn": "WARN", "kill": "KILL"}[sig.severity]
    return f"[{tag}] {sig.title}\n{sig.body}"


async def run_macro_cycle(bot: Bot, settings: Settings) -> None:
    state = load_state()
    async with aiohttp.ClientSession() as session:
        fx = await fetch_cbr_fx(session)
    signals = evaluate(settings, state, usd_rub=fx.usd_rub, cny_rub=fx.cny_rub)
    save_state(state)
    for sig in signals:
        if sig.kind in {"FX_USD", "FX_CNY"} and not _cooldown_ok(state, sig.kind):
            continue
        _mark_alert(state, sig.kind)
        save_state(state)
        await _send(bot, settings.telegram_chat_id, _render(sig))


async def run_crypto_cycle(bot: Bot, settings: Settings) -> None:
    state = load_state()
    if state.get("killed"):
        return
    async with aiohttp.ClientSession() as session:
        crypto = await fetch_btc(session)
    market = state.get("market_rub") or settings.btc_sleeve_rub
    if crypto.btc_usd and state.get("last_btc_usd"):
        market = market * (crypto.btc_usd / state["last_btc_usd"])
    elif crypto.btc_usd and state.get("market_rub") is None:
        market = settings.btc_sleeve_rub
    signals = evaluate(
        settings,
        state,
        btc_usd=crypto.btc_usd,
        btc_change_24h=crypto.change_24h,
        market_rub=market,
    )
    save_state(state)
    for sig in signals:
        if not _cooldown_ok(state, sig.kind, 1800 if sig.severity != "kill" else 300):
            continue
        if sig.severity == "kill":
            state["killed"] = True
            state["kill_reason"] = sig.title
        _mark_alert(state, sig.kind)
        save_state(state)
        await _send(bot, settings.telegram_chat_id, _render(sig))


async def run_digest(bot: Bot, settings: Settings) -> None:
    state = load_state()
    text = "Дайджест 21:00 МСК\n\n" + format_status(settings, state)
    await _send(bot, settings.telegram_chat_id, text)


def build_dispatcher(bot: Bot, settings: Settings) -> Dispatcher:
    dp = Dispatcher()

    def _allowed(message: Message) -> bool:
        return str(message.chat.id) == str(settings.telegram_chat_id)

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(
            "/status — капитал и котировки\n"
            "/digest — сводка сейчас\n"
            "/kill — запрет наращивать рыночный риск\n"
            "/resume — снять kill\n"
            "/capital — напомнить правило 40/50/10\n"
            "/hurdle — барьеры T1–T3\n"
            "Агент не торгует сам. Он сигналит."
        )

    @dp.message(Command("status"))
    async def status_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(format_status(settings, load_state()))

    @dp.message(Command("digest"))
    async def digest_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await run_digest(bot, settings)

    @dp.message(Command("kill"))
    async def kill_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        state = load_state()
        state["killed"] = True
        state["kill_reason"] = "ручной /kill"
        save_state(state)
        await message.answer("Kill-switch включён. Рыночный рукав не наращивать. Навык продолжать.")

    @dp.message(Command("resume"))
    async def resume_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        state = load_state()
        state["killed"] = False
        state["kill_reason"] = ""
        save_state(state)
        await message.answer("Kill-switch снят. Правила DD 15/25% снова в силе.")

    @dp.message(Command("capital"))
    async def capital_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(
            "Старт T-B: 40к навык / 50к ликвидность / 10к BTC spot.\n"
            "Реинвест ≥70% чека в день поступления.\n"
            "Плечо не увеличивает P(T1) при живом кэшфлоу — см. анализ."
        )

    @dp.message(Command("hurdle"))
    async def hurdle_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(
            f"T1 {settings.hurdle_t1:,.0f} ₽\n"
            f"T2 {settings.hurdle_t2:,.0f} ₽\n"
            f"T3 {settings.hurdle_t3:,.0f} ₽\n"
            "База+10% запас, срез 2026-09-01. Обновлять ежедневно по цене SU7."
        )

    return dp


async def scheduler(bot: Bot, settings: Settings) -> None:
    last_digest_date = None
    last_crypto = datetime.fromtimestamp(0, tz=timezone.utc)
    last_macro = datetime.fromtimestamp(0, tz=timezone.utc)
    while True:
        now_msk = datetime.now(MSK)
        now_utc = datetime.now(timezone.utc)
        try:
            if (now_utc - last_crypto).total_seconds() >= settings.poll_crypto_sec:
                await run_crypto_cycle(bot, settings)
                last_crypto = now_utc
            if (now_utc - last_macro).total_seconds() >= settings.poll_macro_sec:
                await run_macro_cycle(bot, settings)
                last_macro = now_utc
            if now_msk.hour == settings.digest_hour_msk and last_digest_date != now_msk.date():
                await run_digest(bot, settings)
                last_digest_date = now_msk.date()
        except Exception:
            log.exception("cycle failed")
        await asyncio.sleep(15)


async def amain() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise SystemExit("Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env")
    bot = Bot(settings.telegram_bot_token)
    dp = build_dispatcher(bot, settings)
    await _send(
        bot,
        settings.telegram_chat_id,
        "Агент SU7 запущен. Команды: /help. Торговлю сам не открываю.",
    )
    await asyncio.gather(dp.start_polling(bot), scheduler(bot, settings))


def main() -> None:
    asyncio.run(amain())
