"""
Торговый бот на срочном рынке: какая прибыль в месяц нужна,
если 20% прибыли сразу уходит в спокойный вклад, а остальное
остаётся на бирже и увеличивает объём торговли.

Цифры на 1 сентября 2026. Это целевой расчёт при ровной прибыли,
не обещание, что бот столько заработает.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

START = 100_000.0
MONTHS = 24
# Доля прибыли, которую снимаем с биржи каждый месяц.
TAKE_PROFIT = 0.20
# Спокойный приёмник: вклад / фонды почти как вклад.
# Первые 12 месяцев около 14% годовых, потом около 11%.
STABLE_YEAR_1 = 0.14
STABLE_YEAR_2 = 0.11

HURDLES = {
    "used": ("машина с пробегом и российским паспортом", 3_990_000.0),
    "direct": ("прямой ввоз Китай → Россия", 5_170_000.0),
    "salon": ("салон, новая базовая", 5_720_000.0),
}

# Сетка «если бот стабильно даёт столько в месяц».
GRID = [0.02, 0.03, 0.04, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20]


def month_rate(annual: float) -> float:
    """Сколько процентов за месяц, если за год получается annual."""
    return (1.0 + annual) ** (1.0 / 12.0) - 1.0


def stable_rate(month_index: int) -> float:
    """Ставка спокойного вклада в этот месяц (0 — первый месяц)."""
    annual = STABLE_YEAR_1 if month_index < 12 else STABLE_YEAR_2
    return month_rate(annual)


def run(r_month: float, take: float = TAKE_PROFIT) -> dict:
    """
    Один ровный сценарий: каждый месяц бот даёт r_month от суммы на бирже.
    Прибыль делим: take уходит во вклад, остальное остаётся и растит объём.
    Если месяц в минусе — с биржи ничего не снимаем, сумма на бирже падает.
    """
    futures = START
    stable = 0.0
    taken = 0.0
    path_total = [START / 1_000_000]
    path_futures = [START / 1_000_000]
    path_stable = [0.0]
    for t in range(MONTHS):
        stable *= 1.0 + stable_rate(t)
        profit = futures * r_month
        if profit > 0:
            withdraw = profit * take
            futures = futures + profit - withdraw
            stable += withdraw
            taken += withdraw
        else:
            futures = max(futures + profit, 0.0)
        if (t + 1) % 3 == 0:
            path_total.append(round((futures + stable) / 1_000_000, 3))
            path_futures.append(round(futures / 1_000_000, 3))
            path_stable.append(round(stable / 1_000_000, 3))
    return {
        "r_month": r_month,
        "futures": futures,
        "stable": stable,
        "total": futures + stable,
        "taken_raw": taken,
        "path_total": path_total,
        "path_futures": path_futures,
        "path_stable": path_stable,
    }


def needed_rate(target: float, take: float = TAKE_PROFIT) -> float:
    """Минимальная ровная прибыль бота в месяц, чтобы через 24 месяца хватило."""
    lo, hi = 0.0, 1.5
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if run(mid, take)["total"] >= target:
            hi = mid
        else:
            lo = mid
    return hi


def blowup_at(r_month: float, die_month: int) -> dict:
    """Бот жил die_month месяцев, потом счёт на бирже обнулили. Вклад уже не трогают."""
    futures = START
    stable = 0.0
    for t in range(MONTHS):
        stable *= 1.0 + stable_rate(t)
        if t >= die_month:
            futures = 0.0
            continue
        profit = futures * r_month
        if profit > 0:
            withdraw = profit * TAKE_PROFIT
            futures = futures + profit - withdraw
            stable += withdraw
        else:
            futures = max(futures + profit, 0.0)
    return {"futures": 0.0, "stable": stable, "total": stable}


def pct(x: float) -> str:
    return f"{x * 100:.2f}%".replace(".", ",")


def rub(x: float) -> str:
    return f"{x:,.0f} ₽".replace(",", " ")


def main() -> None:
    need = {key: needed_rate(price) for key, (_title, price) in HURDLES.items()}
    need_keep = {
        key: needed_rate(price, take=0.0) for key, (_title, price) in HURDLES.items()
    }
    grid_rows = [run(r) for r in GRID]
    # Пример «сильный бот, но не сказка»: 5% в месяц.
    example = run(0.05)
    example_keep = run(0.05, take=0.0)
    salon_path = run(need["salon"])
    used_path = run(need["used"])
    blow = {f"{int(r * 100)}pct": blowup_at(r, 12) for r in (0.05, 0.10, 0.18)}

    payload = {
        "as_of": "2026-09-01",
        "start": START,
        "months": MONTHS,
        "take_profit": TAKE_PROFIT,
        "stable": {
            "name": "спокойный рублёвый вклад и фонды почти как вклад",
            "year_1": STABLE_YEAR_1,
            "year_2": STABLE_YEAR_2,
            "why": (
                "Прибыльнее, чем подушка под матрасом. Спокойнее срочного рынка: "
                "нет залога, который биржа может списать за день."
            ),
        },
        "need_month": {k: round(v, 6) for k, v in need.items()},
        "need_year": {k: round((1 + v) ** 12 - 1, 4) for k, v in need.items()},
        "need_keep_all_month": {k: round(v, 6) for k, v in need_keep.items()},
        "grid": [
            {
                "r_month": r["r_month"],
                "futures": round(r["futures"]),
                "stable": round(r["stable"]),
                "total": round(r["total"]),
                "salon": r["total"] >= HURDLES["salon"][1],
                "used": r["total"] >= HURDLES["used"][1],
            }
            for r in grid_rows
        ],
        "example_5pct": {
            "futures": round(example["futures"]),
            "stable": round(example["stable"]),
            "total": round(example["total"]),
            "keep_all_total": round(example_keep["total"]),
        },
        "path_salon": {
            "r_month": round(need["salon"], 6),
            "total": salon_path["path_total"],
            "futures": salon_path["path_futures"],
            "stable": salon_path["path_stable"],
        },
        "path_used": {
            "r_month": round(need["used"], 6),
            "total": used_path["path_total"],
            "futures": used_path["path_futures"],
            "stable": used_path["path_stable"],
        },
        "path_5pct": {
            "total": example["path_total"],
            "futures": example["path_futures"],
            "stable": example["path_stable"],
        },
        "blowup_month_12": {
            k: {sk: round(sv) for sk, sv in v.items()} for k, v in blow.items()
        },
    }

    out = Path(__file__).resolve().parents[1] / "docs" / "futures_bot_results.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Записано", out)
    print()
    print("Нужная ровная прибыль бота в месяц (20% прибыли уходит во вклад):")
    for key, (title, price) in HURDLES.items():
        r = need[key]
        year = (1 + r) ** 12 - 1
        print(f"  {title} ({rub(price)}): {pct(r)} в месяц, это {pct(year)} за год")
        print(f"    если всю прибыль оставлять на бирже: {pct(need_keep[key])} в месяц")
    print()
    print("Сетка через 24 месяца:")
    print(f"{'бот/мес':>10} {'на бирже':>14} {'во вкладе':>14} {'всего':>14}  салон  вторичка")
    for r in grid_rows:
        mark_s = "да" if r["total"] >= HURDLES["salon"][1] else "нет"
        mark_u = "да" if r["total"] >= HURDLES["used"][1] else "нет"
        print(
            f"{pct(r['r_month']):>10} {rub(r['futures']):>14} {rub(r['stable']):>14} "
            f"{rub(r['total']):>14}  {mark_s:>5}  {mark_u:>8}"
        )
    print()
    print("Если бот ровно 5% в месяц:")
    print("  на бирже", rub(example["futures"]), "во вкладе", rub(example["stable"]), "всего", rub(example["total"]))
    print("  если не выводить 20%:", rub(example_keep["total"]))
    print()
    print("Если на 12-м месяце счёт бота обнулили, вклад уже не сгорает:")
    for k, v in blow.items():
        print(f"  при {k.replace('pct', '%')} до обнуления остаётся вклад {rub(v['stable'])}")


if __name__ == "__main__":
    main()
