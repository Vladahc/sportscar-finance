"""
Пути купить Xiaomi SU7 и ездить по российским правилам.
Цифры на 1 сентября 2026. Это ориентиры, не счёт из салона.
"""

from __future__ import annotations

from dataclasses import dataclass

from sportscar_finance.config import Settings


@dataclass
class PurchasePath:
    """Один способ купить машину: цена, экономия, можно ли ездить в России по закону."""

    code: str
    title: str
    price_rub: float
    with_buffer: float
    legal_in_rf: str
    saving_vs_salon: float
    short_risk: str


def paths(settings: Settings) -> list[PurchasePath]:
    """Четыре рабочих ветки плюс опасная. Цены с запасом 10%."""
    salon = settings.hurdle_t1
    used = settings.hurdle_used
    by_rf = settings.hurdle_belarus_rf
    direct = settings.hurdle_direct_cn
    by_local = settings.hurdle_belarus_local

    salon_raw = salon / 1.10
    return [
        PurchasePath(
            "salon",
            "Салон или ввоз через российскую фирму, сразу российский электронный паспорт",
            salon_raw,
            salon,
            "да, это якорь",
            0,
            "Дорого. Запас сервиса и документов обычно лучше.",
        ),
        PurchasePath(
            "used",
            "Уже ездила в России, есть российский электронный паспорт",
            used / 1.10,
            used,
            "да, если паспорт и сбор за ввоз уже уплачены",
            salon - used,
            "Проверь VIN, что сбор не льготный «на год», батарею и софт.",
        ),
        PurchasePath(
            "direct_cn",
            "Купить в Китае и растаможить сразу в России, не через соседние страны",
            direct / 1.10,
            direct,
            "да, если брокер даёт российский электронный паспорт",
            salon - direct,
            "Сбор за ввоз на SU7 большой: мотор мощный, льгота 3 400 ₽ почти наверняка не действует.",
        ),
        PurchasePath(
            "belarus_rf",
            "Купить в Беларуси и поставить на учёт в России",
            by_rf / 1.10,
            by_rf,
            "спорно: с апреля 2024 электрокары, растаможенные в союзе стран, часто нельзя поставить на учёт в России",
            salon - by_rf,
            "Квота без пошлины в Беларуси кончается. Постановление правительства № 152. Не платить посреднику, пока юрист не подтвердит постановку на учёт.",
        ),
        PurchasePath(
            "belarus_plates",
            "Белорусские номера и ездить в России (не наш основной путь)",
            by_local / 1.10,
            by_local,
            "нет как постоянная официальная езда для гражданина России",
            salon - by_local,
            "Льготный электрокар нельзя просто передать россиянину. Штрафы, доначисление пошлины, отказ на границе.",
        ),
    ]


def format_paths(settings: Settings) -> str:
    """Текст для Telegram: сколько нужно по каждой ветке."""
    lines = [
        "Как купить SU7 дешевле салона и ездить в России",
        "",
    ]
    for i, p in enumerate(paths(settings), 1):
        save = f"экономия около {p.saving_vs_salon:,.0f} ₽" if p.saving_vs_salon > 0 else "это самый дорогой путь"
        lines.append(
            f"{i}. {p.title}\n"
            f"Нужно с запасом 10%: {p.with_buffer:,.0f} ₽ ({save}).\n"
            f"Официально в России: {p.legal_in_rf}.\n"
            f"Риск: {p.short_risk}\n"
        )
    lines.append(
        "Подробности: docs/vetka-pokupki.md. "
        "Перед договором сверка с юристом: правила меняются."
    )
    return "\n".join(lines).replace(",", " ")


def cheaper_hurdle(settings: Settings) -> tuple[str, float]:
    """Самая дешёвая ветка, на которой ещё можно легально ездить в России."""
    used = settings.hurdle_used
    direct = settings.hurdle_direct_cn
    if used <= direct:
        return "машина с пробегом и российским паспортом", used
    return "прямой ввоз из Китая в Россию", direct
