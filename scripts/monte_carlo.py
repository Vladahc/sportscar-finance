"""
Считаем много случайных историй на 24 месяца: сколько денег может получиться
из 100 000 рублей, если класть их в разные места.
Цифры на 1 сентября 2026. Это сравнение путей, а не совет «купи вот это».
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RNG = np.random.default_rng(20260901)
N_PATHS = 25_000
N_MONTHS = 24
W0 = 100_000.0

# Сколько рублей нужно через 24 месяца, чтобы хватило на машину.
# В сумму уже заложено 10% сверху на налоги и оформление.
# Базовая / средняя / самая мощная комплектация — см. разбор в docs.
HURDLE = {"T1": 5_720_000.0, "T2": 7_150_000.0, "T3": 12_100_000.0}


@dataclass
class Result:
    name: str
    start: float
    pmt: float  # сколько в среднем кладём сверху каждый месяц
    median: float
    mean: float
    p10: float
    p90: float
    p_ruin: float
    p_t1: float
    p_t2: float
    p_t3: float
    dd_typ: float
    dd_tail: float

    def as_row(self) -> dict:
        return {
            "name": self.name,
            "start": round(self.start),
            "pmt": round(self.pmt),
            "median": round(self.median),
            "mean": round(self.mean),
            "p10": round(self.p10),
            "p90": round(self.p90),
            "p_ruin": round(self.p_ruin, 4),
            "p_t1": round(self.p_t1, 4),
            "p_t2": round(self.p_t2, 4),
            "p_t3": round(self.p_t3, 4),
            "dd_typ": round(self.dd_typ, 3),
            "dd_tail": round(self.dd_tail, 3),
        }


def summarize(name: str, wealth: np.ndarray, start: float, pmt: float, dd: np.ndarray) -> Result:
    """Собирает простые цифры: середина, плохой и хороший случай, шанс купить машину."""
    ruin = wealth <= 1_000.0
    return Result(
        name=name,
        start=start,
        pmt=pmt,
        median=float(np.median(wealth)),
        mean=float(np.mean(wealth)),
        p10=float(np.percentile(wealth, 10)),
        p90=float(np.percentile(wealth, 90)),
        p_ruin=float(np.mean(ruin)),
        p_t1=float(np.mean(wealth >= HURDLE["T1"])),
        p_t2=float(np.mean(wealth >= HURDLE["T2"])),
        p_t3=float(np.mean(wealth >= HURDLE["T3"])),
        dd_typ=float(np.median(dd)),
        dd_tail=float(np.percentile(dd, 90)),
    )


def gbm_month(mu_ann: float, sig_ann: float, n: int) -> np.ndarray:
    """Случайный рост или падение за каждый месяц (как прыгает цена)."""
    dt = 1 / 12
    return RNG.normal((mu_ann - 0.5 * sig_ann**2) * dt, sig_ann * math.sqrt(dt), size=(N_PATHS, n))


def path_from_returns(r: np.ndarray, start: float, pmt: np.ndarray | float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """
    Идём месяц за месяцем: деньги растут или падают, потом сверху кладём пополнение.
    Запоминаем, насколько глубоко сумма проседала от своего максимума.
    """
    w = np.full(N_PATHS, start, dtype=float)
    peak = w.copy()
    max_dd = np.zeros(N_PATHS)
    if np.isscalar(pmt):
        pmt_arr = np.full((N_PATHS, r.shape[1]), float(pmt))
    else:
        pmt_arr = pmt
    for t in range(r.shape[1]):
        w = np.maximum(w, 0.0)
        w = w * np.exp(r[:, t]) + pmt_arr[:, t]
        w = np.where(np.isfinite(w), w, 0.0)
        peak = np.maximum(peak, w)
        dd = np.where(peak > 0, 1.0 - w / peak, 1.0)
        max_dd = np.maximum(max_dd, dd)
    return w, max_dd


def deposit_like(mu_ann: float, name: str, pmt: float = 0.0) -> Result:
    """Вклад: сейчас около 14% годовых, к концу двух лет ближе к 11% (прогноз Банка России)."""
    months = np.linspace(mu_ann, max(mu_ann - 0.03, 0.10), N_MONTHS)
    r = np.tile(np.log(1 + months / 12), (N_PATHS, 1))
    # Крошечный шум: налоги и то, что вклад не всегда продлевают идеально.
    r += RNG.normal(0, 0.001, r.shape)
    w, dd = path_from_returns(r, W0, pmt)
    return summarize(name, w, W0, pmt, dd)


def gbm_channel(name: str, mu: float, sig: float, pmt: float = 0.0, blowup_m: float = 0.0) -> Result:
    """Обычный рынок: цена гуляет. Иногда (blowup_m) за месяц можно потерять почти всё."""
    r = gbm_month(mu, sig, N_MONTHS)
    if blowup_m > 0:
        # В этом месяце случился обвал: заёмные деньги, обман или закрытие биржи.
        dead = RNG.random((N_PATHS, N_MONTHS)) < blowup_m
        r = np.where(dead, -10.0, r)
    w, dd = path_from_returns(r, W0, pmt)
    return summarize(name, w, W0, pmt, dd)


def hyip_channel() -> Result:
    """
    Сайт обещает около 3% в день. По исследованиям такие схемы живут недели,
    не годы: чаще всего около месяца, редко дольше года.
    Деньги делим: часть ещё на сайте, часть уже вывели. Каждый месяц с шансом 45%
    схема ломается. Пока жива — на экране +8% в месяц (не 3% в день: вывести всё сразу нельзя).
    """
    risk = np.full(N_PATHS, W0)
    cash = np.zeros(N_PATHS)
    alive = np.ones(N_PATHS, dtype=bool)
    peak = np.full(N_PATHS, W0)
    max_dd = np.zeros(N_PATHS)
    credited = 0.08
    for t in range(N_MONTHS):
        collapse = alive & (RNG.random(N_PATHS) < 0.45)
        risk = np.where(collapse, 0.0, risk)
        alive = alive & ~collapse
        risk = np.where(alive, risk * (1 + credited), risk)
        if (t + 1) % 3 == 0:
            take = alive & (RNG.random(N_PATHS) < 0.40)
            fail = take & (RNG.random(N_PATHS) < 0.25)
            risk = np.where(fail, 0.0, risk)
            cash = np.where(fail, 0.0, cash)  # иногда замораживают и уже выведенное
            alive = alive & ~fail
            moved = np.where(take & alive, risk * 0.40, 0.0)
            risk = np.where(take & alive, risk * 0.60, risk)
            cash = cash + moved
        w = risk + cash
        peak = np.maximum(peak, w)
        max_dd = np.maximum(max_dd, np.where(peak > 0, 1 - w / peak, 1))
    return summarize("Сайт с огромными процентами, деньги держать", risk + cash, W0, 0.0, max_dd)


def hyip_hit_and_run() -> Result:
    """Каждый месяц новая схема: успел вывести — хорошо, не успел — потерял остаток."""
    cash = np.zeros(N_PATHS)
    sleeve = np.full(N_PATHS, W0)
    peak = np.full(N_PATHS, W0)
    max_dd = np.zeros(N_PATHS)
    for t in range(N_MONTHS):
        stake = np.where(sleeve > 0, sleeve, np.minimum(cash, W0 * 0.5))
        cash = cash - np.where(sleeve > 0, 0.0, np.minimum(cash, W0 * 0.5))
        die = RNG.random(N_PATHS) < 0.55
        gain = RNG.uniform(0.05, 0.25, N_PATHS)
        extracted = np.where(die, 0.0, stake * (1 + gain))
        # Даже «успешный» месяц: в 20% случаев выплату не отдают.
        payout_fail = (~die) & (RNG.random(N_PATHS) < 0.20)
        extracted = np.where(payout_fail, 0.0, extracted)
        cash = cash + extracted
        sleeve = np.zeros(N_PATHS)  # на сайте ничего не оставляем
        w = cash + sleeve
        if t == 0:
            # Первый месяц умер — денег нет, дальше не из чего играть.
            pass
        peak = np.maximum(peak, w)
        max_dd = np.maximum(max_dd, np.where(peak > 0, 1 - w / peak, 1))
    return summarize("Сайт с процентами: зашёл и сразу вывел", cash, W0, 0.0, max_dd)


def forex_leverage() -> Result:
    """
    Валюта на заёмные деньги (в 30–50 раз больше, чем свои).
    У большинства частных счетов итог отрицательный. Иногда за месяц −80%.
    """
    r = gbm_month(-0.12, 0.55, N_MONTHS)
    shock = RNG.random((N_PATHS, N_MONTHS)) < 0.045
    r = np.where(shock, np.log(0.20), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Валюта на заёмные деньги (частные счета)", w, W0, 0.0, dd)


def moex_futures() -> Result:
    """Контракты на бирже с заёмными деньгами: можно быстро потерять залог."""
    r = gbm_month(0.08, 0.45, N_MONTHS)
    shock = RNG.random((N_PATHS, N_MONTHS)) < 0.03
    r = np.where(shock, np.log(0.15), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Срочные контракты Мосбиржи на заёмные деньги", w, W0, 0.0, dd)


def crypto_lev() -> Result:
    """Биткоин и монеты на заёмные деньги: часто обнуление счёта."""
    r = gbm_month(0.35, 1.10, N_MONTHS)
    shock = RNG.random((N_PATHS, N_MONTHS)) < 0.08
    r = np.where(shock, -8.0, r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Крипта на заёмные деньги (в 5–10 раз)", w, W0, 0.0, dd)


def memes() -> Result:
    """Шуточные монеты: часто исчезают вместе с деньгами."""
    r = gbm_month(-0.20, 1.60, N_MONTHS)
    rug = RNG.random((N_PATHS, N_MONTHS)) < 0.12
    r = np.where(rug, -8.0, r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Шуточные монеты и неликвидная крипта", w, W0, 0.0, dd)


def options_lottery() -> Result:
    """15% денег — как лотерейный билет, остальное лежит спокойнее."""
    w = np.full(N_PATHS, W0)
    peak = w.copy()
    max_dd = np.zeros(N_PATHS)
    for t in range(N_MONTHS):
        # В 8% месяцев ставка выигрывает в 4–12 раз. В 70% месяцев эти 15% сгорают.
        ticket = 0.15 * w
        core = 0.85 * w
        u = RNG.random(N_PATHS)
        payoff = np.where(u < 0.08, ticket * RNG.uniform(4, 12, N_PATHS), np.where(u < 0.78, 0.0, ticket * 0.4))
        w = core * np.exp(gbm_month(0.10, 0.22, 1)[:, 0]) + payoff
        peak = np.maximum(peak, w)
        max_dd = np.maximum(max_dd, np.where(peak > 0, 1 - w / peak, 1))
    return summarize("Опционы-лотерея: 15% денег на билет", w, W0, 0.0, max_dd)


def p2p() -> Result:
    """Займы через интернет-площадки: процент выше вклада, но кто-то не отдаёт."""
    r = gbm_month(0.16, 0.12, N_MONTHS)
    default = RNG.random((N_PATHS, N_MONTHS)) < 0.02
    r = np.where(default, np.log(0.70), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Займы людям и компаниям через площадки", w, W0, 0.0, dd)


def arb() -> Result:
    # Умелый обмен крипты на рубли: около 1,2% в месяц, на 100 тысячах много не разгонишь.
    r = RNG.normal(np.log(1.012), 0.008, size=(N_PATHS, N_MONTHS))
    freeze = RNG.random((N_PATHS, N_MONTHS)) < 0.01  # банк или биржа заморозили счёт
    r = np.where(freeze, np.log(0.5), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Разница цен на биржах (на 100 тысячах)", w, W0, 0.0, dd)


def prop_path() -> Result:
    """
    Четыре платных экзамена у торговой фирмы из 100 тысяч.
    Экзамен сдают примерно 10%. Потом ещё легко нарушить правило убытка и потерять счёт.
    """
    w = np.zeros(N_PATHS)
    fees = 28_000.0
    leftover = W0 - fees
    passed = RNG.random(N_PATHS) < 0.10
    # Что осталось после оплаты экзаменов — лежит спокойно.
    w = leftover * np.exp(np.sum(gbm_month(0.12, 0.05, N_MONTHS), axis=1))
    monthly_payout = RNG.lognormal(mean=math.log(180_000 + 1e-9), sigma=0.65, size=(N_PATHS, N_MONTHS))
    alive_funded = passed.copy()
    add = np.zeros(N_PATHS)
    for t in range(N_MONTHS):
        bust = alive_funded & (RNG.random(N_PATHS) < 0.12)
        alive_funded = alive_funded & ~bust
        # Фирма отдаёт 80% прибыли. Суммы уже в рублях.
        add += np.where(alive_funded, monthly_payout[:, t] * 0.80, 0.0)
    w = np.where(passed, w + add, leftover * (1.01 ** N_MONTHS))
    # Кто экзамен не сдал — остаток просто на вкладе.
    dd = np.where(passed, 0.45, 0.02)
    return summarize("Экзамен торговой фирмы, 4 попытки", w, W0, 0.0, dd)


def skill_ramp(p10: float, p50: float, p90: float) -> np.ndarray:
    """Заработок с работы: первые месяцы ноль, потом выход на обычный чек."""
    sigma = 0.55
    mu = math.log(max(p50, 1.0))
    level = RNG.lognormal(mu, sigma, N_PATHS)
    # Не даём чеку улететь в нереальные крайности.
    level = np.clip(level, p10 * 0.3, p90 * 1.8)
    pmt = np.zeros((N_PATHS, N_MONTHS))
    for t in range(N_MONTHS):
        scale = 0.0 if t < 2 else min(1.0, (t - 1) / 6.0)
        pmt[:, t] = level * scale
    return pmt


def combo(name: str, mu: float, sig: float, pmt: np.ndarray | float, blowup_m: float = 0.0) -> Result:
    """Работа плюс рынок: каждый месяц приходят новые деньги и они тоже гуляют."""
    r = gbm_month(mu, sig, N_MONTHS)
    if blowup_m:
        r = np.where(RNG.random(r.shape) < blowup_m, -6.0, r)
    avg_pmt = float(np.mean(pmt)) if not np.isscalar(pmt) else float(pmt)
    w, dd = path_from_returns(r, W0, pmt)
    start = W0
    return summarize(name, w, start, avg_pmt, dd)


def main() -> None:
    rows: list[Result] = []

    rows.append(deposit_like(0.140, "Вклад 14%, потом около 11%"))
    rows.append(deposit_like(0.135, "Облигации государства и фонды почти как вклад"))
    rows.append(gbm_channel("Российские акции", 0.12, 0.28))
    rows.append(gbm_channel("Налоговый счёт на 5 лет, закрыли через 2 года", 0.12, 0.28))
    rows.append(gbm_channel("Доллары и юани в рублях", 0.06, 0.18))
    rows.append(gbm_channel("Золото", 0.08, 0.16))
    rows.append(gbm_channel("Биткоин без займа", 0.30, 0.70))
    rows.append(gbm_channel("Эфир и крупные монеты", 0.18, 0.85))
    rows.append(memes())
    rows.append(crypto_lev())
    rows.append(forex_leverage())
    rows.append(moex_futures())
    rows.append(options_lottery())
    rows.append(p2p())
    rows.append(arb())
    rows.append(hyip_channel())
    rows.append(hyip_hit_and_run())
    rows.append(prop_path())
    rows.append(gbm_channel("Рискованные облигации компаний", 0.18, 0.15, blowup_m=0.008))

    # Три скорости заработка: высокий, средний и слабый чек.
    pmt_skill_high = skill_ramp(80_000, 220_000, 450_000)
    pmt_skill_med = skill_ramp(40_000, 120_000, 250_000)
    pmt_skill_low = skill_ramp(15_000, 50_000, 90_000)

    rows.append(combo("План А: работа 220 тыс. плюс крипта с займом", 0.25, 0.85, pmt_skill_high, blowup_m=0.025))
    rows.append(combo("План Б: работа 220 тыс. плюс вклад, акции, биткоин", 0.14, 0.22, pmt_skill_high))
    rows.append(combo("План В: работа 120 тыс. плюс акции и биткоин", 0.16, 0.35, pmt_skill_med))
    rows.append(combo("План Г: экзамен фирмы плюс работа 120 тыс.", 0.12, 0.25, pmt_skill_med))
    rows.append(combo("План Д: только работа 220 тыс., деньги на вклад", 0.12, 0.04, pmt_skill_high))
    rows.append(combo("План Е: слабая работа 50 тыс. плюс шуточные монеты", 0.05, 1.20, pmt_skill_low, blowup_m=0.06))
    rows.append(combo("План Ж: 20% в сайт с процентами плюс работа 120 тыс.", 0.10, 0.40, pmt_skill_med, blowup_m=0.04))
    rows.append(combo("Без работы, только биткоин с займом", 0.30, 1.05, 0.0, blowup_m=0.05))

    # Сначала у кого выше шанс купить базовую машину, потом у кого больше денег в середине.
    rows.sort(key=lambda x: (x.p_t1, x.median), reverse=True)

    payload = {
        "as_of": "2026-09-01",
        "n_paths": N_PATHS,
        "hurdle": HURDLE,
        "w0": W0,
        "rows": [r.as_row() for r in rows],
    }
    out = Path(__file__).resolve().parents[1] / "docs" / "monte_carlo_results.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Записано {out}")
    print(f"{'место':<4} {'шанс':>7} {'середина':>12} {'плохо':>12} {'хорошо':>14} {'ноль':>7}  название")
    for i, r in enumerate(rows, 1):
        print(
            f"{i:<4} {r.p_t1:7.2%} {r.median:12,.0f} {r.p10:12,.0f} {r.p90:14,.0f} {r.p_ruin:7.2%}  {r.name}"
        )


if __name__ == "__main__":
    main()
