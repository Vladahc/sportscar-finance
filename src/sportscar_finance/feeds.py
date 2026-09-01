from __future__ import annotations

from dataclasses import dataclass

import aiohttp

# Официальные курсы Банка России на сегодня.
CBR_XML = "https://www.cbr.ru/scripts/XML_daily.asp"
# Цена биткоина в долларах и изменение за сутки.
COINGECKO_BTC = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
)
CBR_KEYRATE = "https://www.cbr.ru/hd_base/keyrate/"
# Страницы, которые бот должен открывать при проверке цены машины.
AUTO_USED = "https://auto.ru/cars/xiaomi/su7/23801820/used/"
BELARUS_SU7 = "https://evauto.pro/catalog/xiaomi-su7"
CBR_PRESS = "https://www.cbr.ru/rss/RssPress/"


@dataclass
class MacroSnapshot:
    """Курсы доллара, юаня и белорусского рубля к российскому рублю."""

    usd_rub: float | None
    cny_rub: float | None
    byn_rub: float | None
    source: str


@dataclass
class CryptoSnapshot:
    """Цена биткоина и насколько она изменилась за сутки."""

    btc_usd: float | None
    change_24h: float | None
    source: str


def _xml_value(xml: str, char_code: str) -> float | None:
    """Достаёт число курса из xml-ответа Банка России."""
    marker = f"<CharCode>{char_code}</CharCode>"
    i = xml.find(marker)
    if i < 0:
        return None
    v0 = xml.find("<Value>", i)
    v1 = xml.find("</Value>", v0)
    if v0 < 0 or v1 < 0:
        return None
    raw = xml[v0 + 7 : v1].replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


async def fetch_cbr_fx(session: aiohttp.ClientSession) -> MacroSnapshot:
    """Скачивает курсы доллара, юаня и белорусского рубля с сайта Банка России."""
    async with session.get(CBR_XML, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        xml = await resp.text()
    return MacroSnapshot(
        usd_rub=_xml_value(xml, "USD"),
        cny_rub=_xml_value(xml, "CNY"),
        byn_rub=_xml_value(xml, "BYN"),
        source="cbr_xml_daily",
    )


async def fetch_btc(session: aiohttp.ClientSession) -> CryptoSnapshot:
    """Скачивает цену биткоина."""
    async with session.get(COINGECKO_BTC, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        payload = await resp.json()
    row = payload.get("bitcoin") or {}
    return CryptoSnapshot(
        btc_usd=float(row["usd"]) if "usd" in row else None,
        change_24h=(float(row["usd_24h_change"]) / 100.0) if "usd_24h_change" in row else None,
        source="coingecko",
    )


async def fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    """Скачивает текст страницы. Пригодится для новостей и цены машины."""
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
        resp.raise_for_status()
        return await resp.text()
