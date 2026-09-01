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
    """Не слать одно и то же предупреждение слишком часто (по умолчанию раз в 2 часа)."""
    last = (state.get("last_alerts") or {}).get(kind)
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(last)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - prev >= timedelta(seconds=seconds)


def _mark_alert(state: dict, kind: str) -> None:
    """Запоминает, что такое предупреждение уже отправляли."""
    alerts = state.setdefault("last_alerts", {})
    alerts[kind] = datetime.now(timezone.utc).isoformat()


async def _send(bot: Bot, chat_id: str, text: str) -> None:
    """Пишет в Telegram. Длинный текст обрезает, чтобы сообщение прошло."""
    await bot.send_message(chat_id, text[:3900])


def _render(sig: Signal) -> str:
    """Собирает текст сообщения из заголовка и пояснения."""
    tag = {"info": "К сведению", "warn": "Осторожно", "kill": "Стоп"}[sig.severity]
    return f"[{tag}] {sig.title}\n{sig.body}"


async def run_macro_cycle(bot: Bot, settings: Settings) -> None:
    """Раз в час: курсы доллара и юаня."""
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
    """Каждые 15 минут: биткоин и просадка рыночных денег."""
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
        pause = 1800 if sig.severity != "kill" else 300
        if not _cooldown_ok(state, sig.kind, pause):
            continue
        if sig.severity == "kill":
            state["killed"] = True
            state["kill_reason"] = sig.title
        _mark_alert(state, sig.kind)
        save_state(state)
        await _send(bot, settings.telegram_chat_id, _render(sig))


async def run_digest(bot: Bot, settings: Settings) -> None:
    """Вечерняя сводка: сколько денег и что с курсами."""
    state = load_state()
    text = "Сводка на вечер (21:00 по Москве)\n\n" + format_status(settings, state)
    await _send(bot, settings.telegram_chat_id, text)


def build_dispatcher(bot: Bot, settings: Settings) -> Dispatcher:
    """Команды, которые человек может написать боту."""
    dp = Dispatcher()

    def _allowed(message: Message) -> bool:
        """Отвечаем только хозяину, чей номер чата записан в настройках."""
        return str(message.chat.id) == str(settings.telegram_chat_id)

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(
            "/status — сколько денег и какие курсы\n"
            "/digest — сводка прямо сейчас\n"
            "/kill — стоп: больше не наращивать риск на рынке\n"
            "/resume — снова разрешить рыночный риск\n"
            "/capital — как разложить стартовые 100 000 ₽\n"
            "/hurdle — сколько нужно на каждую комплектацию машины\n"
            "Бот сам сделки не открывает. Он только предупреждает."
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
        state["kill_reason"] = "человек нажал /kill"
        save_state(state)
        await message.answer(
            "Стоп включён. Рискованные покупки на рынке не наращивать. "
            "Работать и зарабатывать можно."
        )

    @dp.message(Command("resume"))
    async def resume_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        state = load_state()
        state["killed"] = False
        state["kill_reason"] = ""
        save_state(state)
        await message.answer(
            "Стоп снят. Снова действуют пороги: минус 15% — осторожно, минус 25% — стоп."
        )

    @dp.message(Command("capital"))
    async def capital_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(
            "Старт плана «работа плюс рынок»:\n"
            "40 000 ₽ — запуск работы,\n"
            "50 000 ₽ — спокойный вклад,\n"
            "10 000 ₽ — биткоин без заёмных денег.\n"
            "Не меньше 70% заработка в тот же день клади в копилку.\n"
            "Заёмные деньги (плечо) не повышают шанс купить базовую машину, "
            "если работа уже приносит доход. Подробности — в разборе."
        )

    @dp.message(Command("hurdle"))
    async def hurdle_cmd(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(
            f"Базовая комплектация: {settings.hurdle_t1:,.0f} ₽\n"
            f"Средняя и мощная: {settings.hurdle_t2:,.0f} ₽\n"
            f"Самая мощная: {settings.hurdle_t3:,.0f} ₽\n"
            "Это цена плюс запас 10% на налоги и оформление. "
            "Цифры от 1 сентября 2026. Смотри актуальную цену машины каждый день."
        )

    return dp


async def scheduler(bot: Bot, settings: Settings) -> None:
    """Бесконечный цикл: биткоин часто, курсы Банка России реже, сводка вечером."""
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
            log.exception("Сбой очередной проверки курсов")
        await asyncio.sleep(15)


async def amain() -> None:
    """Запускает бота и проверки курсов одновременно."""
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise SystemExit(
            "Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в файле .env"
        )
    bot = Bot(settings.telegram_bot_token)
    dp = build_dispatcher(bot, settings)
    await _send(
        bot,
        settings.telegram_chat_id,
        "Помощник по копилке на SU7 запущен. Напиши /help. Сделки сам не открываю.",
    )
    await asyncio.gather(dp.start_polling(bot), scheduler(bot, settings))


def main() -> None:
    """Обычный запуск из командной строки."""
    asyncio.run(amain())
