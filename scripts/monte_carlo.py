"""
Scenario / Monte Carlo engine for 24-month Xiaomi SU7 capital paths.
Date of assumptions: 2026-09-01. Not investment advice — a ranking model.
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

# Purchase hurdles at month 24, RUB, including 10% buffer (tax/fees/registration).
# Base car prices: T1 5.20m, T2 6.50m, T3 11.00m (see docs).
HURDLE = {"T1": 5_720_000.0, "T2": 7_150_000.0, "T3": 12_100_000.0}


@dataclass
class Result:
    name: str
    start: float
    pmt: float  # monthly contribution (can vary; this is average planned)
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
    dt = 1 / 12
    return RNG.normal((mu_ann - 0.5 * sig_ann**2) * dt, sig_ann * math.sqrt(dt), size=(N_PATHS, n))


def path_from_returns(r: np.ndarray, start: float, pmt: np.ndarray | float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """r: (paths, months). pmt applied at start of each month after return, except month 0 start."""
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
    # Key-rate path: 14% now, drifting to ~11% by month 24 (CBR 2027 forecast 10.5–12.5).
    months = np.linspace(mu_ann, max(mu_ann - 0.03, 0.10), N_MONTHS)
    r = np.tile(np.log(1 + months / 12), (N_PATHS, 1))
    # Tiny noise for reinvestment / tax drag
    r += RNG.normal(0, 0.001, r.shape)
    w, dd = path_from_returns(r, W0, pmt)
    return summarize(name, w, W0, pmt, dd)


def gbm_channel(name: str, mu: float, sig: float, pmt: float = 0.0, blowup_m: float = 0.0) -> Result:
    r = gbm_month(mu, sig, N_MONTHS)
    if blowup_m > 0:
        # Independent monthly blow-up (leverage / margin call / rug).
        dead = RNG.random((N_PATHS, N_MONTHS)) < blowup_m
        r = np.where(dead, -10.0, r)  # ~0 wealth
    w, dd = path_from_returns(r, W0, pmt)
    return summarize(name, w, W0, pmt, dd)


def hyip_channel() -> Result:
    """
    Advertised 3%/day vs empirical survival.
    Moore/Han/Clayton 2012: median life 28d; ~25% > 3m; ~10% > 10m.
    WACCO 2022: median 43d; 9.5% survive > 1 year.
    Split book: HYIP risk sleeve vs realized cash. Monthly collapse p=0.45
    on the sleeve. Credited 8%/month while alive (lock haircut vs 3%/day ads).
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
            cash = np.where(fail, 0.0, cash)  # freeze cabinet can hit prior withdrawals too
            alive = alive & ~fail
            moved = np.where(take & alive, risk * 0.40, 0.0)
            risk = np.where(take & alive, risk * 0.60, risk)
            cash = cash + moved
        w = risk + cash
        peak = np.maximum(peak, w)
        max_dd = np.maximum(max_dd, np.where(peak > 0, 1 - w / peak, 1))
    return summarize("HYIP advertised 3%/day (empirical survival)", risk + cash, W0, 0.0, max_dd)


def hyip_hit_and_run() -> Result:
    """New scheme each month; extract if it lives the month, else lose residual sleeve."""
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
        # 20% of 'success' months still fail on payout
        payout_fail = (~die) & (RNG.random(N_PATHS) < 0.20)
        extracted = np.where(payout_fail, 0.0, extracted)
        cash = cash + extracted
        sleeve = np.zeros(N_PATHS)  # never leave money parked
        w = cash + sleeve
        if t == 0:
            # if first month dies with all capital, cash stays 0
            pass
        peak = np.maximum(peak, w)
        max_dd = np.maximum(max_dd, np.where(peak > 0, 1 - w / peak, 1))
    return summarize("HYIP hit-and-run rotation", cash, W0, 0.0, max_dd)


def forex_leverage() -> Result:
    """
    Retail FX 1:30–1:50. ESMA/NFA: majority of retail accounts lose.
    Model: monthly edge -1.5% + 18% vol, plus 4.5% monthly chance of -80% (gap/margin).
    """
    r = gbm_month(-0.12, 0.55, N_MONTHS)
    shock = RNG.random((N_PATHS, N_MONTHS)) < 0.045
    r = np.where(shock, np.log(0.20), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Forex/CFD 1:30–1:50 retail", w, W0, 0.0, dd)


def moex_futures() -> Result:
    r = gbm_month(0.08, 0.45, N_MONTHS)
    shock = RNG.random((N_PATHS, N_MONTHS)) < 0.03
    r = np.where(shock, np.log(0.15), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("MOEX futures SI/RTS ~5–10x", w, W0, 0.0, dd)


def crypto_lev() -> Result:
    r = gbm_month(0.35, 1.10, N_MONTHS)
    shock = RNG.random((N_PATHS, N_MONTHS)) < 0.08
    r = np.where(shock, -8.0, r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Crypto perps 5–10x", w, W0, 0.0, dd)


def memes() -> Result:
    r = gbm_month(-0.20, 1.60, N_MONTHS)
    rug = RNG.random((N_PATHS, N_MONTHS)) < 0.12
    r = np.where(rug, -8.0, r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("Memecoins / illiquid alts", w, W0, 0.0, dd)


def options_lottery() -> Result:
    w = np.full(N_PATHS, W0)
    peak = w.copy()
    max_dd = np.zeros(N_PATHS)
    for t in range(N_MONTHS):
        # 8% of months: 4–12x on the slice; 70%: -100% of the 15% ticket; rest ~0
        ticket = 0.15 * w
        core = 0.85 * w
        u = RNG.random(N_PATHS)
        payoff = np.where(u < 0.08, ticket * RNG.uniform(4, 12, N_PATHS), np.where(u < 0.78, 0.0, ticket * 0.4))
        w = core * np.exp(gbm_month(0.10, 0.22, 1)[:, 0]) + payoff
        peak = np.maximum(peak, w)
        max_dd = np.maximum(max_dd, np.where(peak > 0, 1 - w / peak, 1))
    return summarize("Options lottery 15% of book", w, W0, 0.0, max_dd)


def p2p() -> Result:
    r = gbm_month(0.16, 0.12, N_MONTHS)
    default = RNG.random((N_PATHS, N_MONTHS)) < 0.02
    r = np.where(default, np.log(0.70), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("P2P / crowdlending RF", w, W0, 0.0, dd)


def arb() -> Result:
    # Skilled P2P crypto-fiat / funding: 1.2% month median, capacity limited at 100k
    r = RNG.normal(np.log(1.012), 0.008, size=(N_PATHS, N_MONTHS))
    freeze = RNG.random((N_PATHS, N_MONTHS)) < 0.01  # account lock / AML
    r = np.where(freeze, np.log(0.5), r)
    w, dd = path_from_returns(r, W0, 0.0)
    return summarize("CEX/DEX/P2P arb (100k capacity)", w, W0, 0.0, dd)


def prop_path() -> Result:
    """
    4 challenge attempts from 100k (~25k fee budget + living). Combined pass ~10%.
    If funded: 24 months, 15% monthly chance of rule-break wipe; payout lognormal.
    """
    w = np.zeros(N_PATHS)
    fees = 28_000.0
    leftover = W0 - fees
    # attempts
    passed = RNG.random(N_PATHS) < 0.10
    # residual cash
    w = leftover * np.exp(np.sum(gbm_month(0.12, 0.05, N_MONTHS), axis=1))
    monthly_payout = RNG.lognormal(mean=math.log(180_000 + 1e-9), sigma=0.65, size=(N_PATHS, N_MONTHS))
    alive_funded = passed.copy()
    add = np.zeros(N_PATHS)
    for t in range(N_MONTHS):
        bust = alive_funded & (RNG.random(N_PATHS) < 0.12)
        alive_funded = alive_funded & ~bust
        add += np.where(alive_funded, monthly_payout[:, t] * 0.80, 0.0)  # 80% split, already RUB-ish
    w = np.where(passed, w + add, leftover * (1.01 ** N_MONTHS))
    # paths that never pass: leftover on deposit
    dd = np.where(passed, 0.45, 0.02)
    return summarize("Prop/FTMO-like 4 attempts + funded tail", w, W0, 0.0, dd)


def skill_ramp(p10: float, p50: float, p90: float) -> np.ndarray:
    """Monthly net cashflow ramp: 3 months to first invoice, then plateau."""
    # lognormal around p50
    sigma = 0.55
    mu = math.log(max(p50, 1.0))
    level = RNG.lognormal(mu, sigma, N_PATHS)
    # clip to a wide range
    level = np.clip(level, p10 * 0.3, p90 * 1.8)
    pmt = np.zeros((N_PATHS, N_MONTHS))
    for t in range(N_MONTHS):
        scale = 0.0 if t < 2 else min(1.0, (t - 1) / 6.0)
        pmt[:, t] = level * scale
    return pmt


def combo(name: str, mu: float, sig: float, pmt: np.ndarray | float, blowup_m: float = 0.0) -> Result:
    r = gbm_month(mu, sig, N_MONTHS)
    if blowup_m:
        r = np.where(RNG.random(r.shape) < blowup_m, -6.0, r)
    avg_pmt = float(np.mean(pmt)) if not np.isscalar(pmt) else float(pmt)
    w, dd = path_from_returns(r, W0, pmt)
    start = W0
    return summarize(name, w, start, avg_pmt, dd)


def main() -> None:
    rows: list[Result] = []

    rows.append(deposit_like(0.140, "Вклад 14% -> ~11% (ключ ЦБ)"))
    rows.append(deposit_like(0.135, "ОФЗ-флоатер / ДПИФ ден. рынка"))
    rows.append(gbm_channel("Акции РФ IMOEX / БПИФ", 0.12, 0.28))
    rows.append(gbm_channel("ИИС-3 + IMOEX (закрытие на 24м, вычет сгорел)", 0.12, 0.28))
    rows.append(gbm_channel("USD/CNY кэш в RUB", 0.06, 0.18))
    rows.append(gbm_channel("Золото (GLDRUB)", 0.08, 0.16))
    rows.append(gbm_channel("BTC spot", 0.30, 0.70))
    rows.append(gbm_channel("ETH + large alts", 0.18, 0.85))
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
    rows.append(gbm_channel("HYDO / корп. бонды 20%+", 0.18, 0.15, blowup_m=0.008))

    # Income ramps
    pmt_skill_high = skill_ramp(80_000, 220_000, 450_000)
    pmt_skill_med = skill_ramp(40_000, 120_000, 250_000)
    pmt_skill_low = skill_ramp(15_000, 50_000, 90_000)

    rows.append(combo("T-A Aggressive: skill P50~220k + crypto 3x book", 0.25, 0.85, pmt_skill_high, blowup_m=0.025))
    rows.append(combo("T-B Income+market: skill P50~220k + 50/30/20 MM/IMOEX/BTC", 0.14, 0.22, pmt_skill_high))
    rows.append(combo("T-C Mixed: skill P50~120k + BTC+IMOEX", 0.16, 0.35, pmt_skill_med))
    rows.append(combo("T-D Prop+skill: P50~120k cashflow + leftover market", 0.12, 0.25, pmt_skill_med))
    rows.append(combo("T-E Only skill P50~220k, кэш на вклад", 0.12, 0.04, pmt_skill_high))
    rows.append(combo("T-F Weak income P50~50k + memes/lev", 0.05, 1.20, pmt_skill_low, blowup_m=0.06))
    rows.append(combo("T-G HYIP 20% book + skill P50~120k", 0.10, 0.40, pmt_skill_med, blowup_m=0.04))
    rows.append(combo("Пополнение 0, только BTC 3x", 0.30, 1.05, 0.0, blowup_m=0.05))

    # Sort: P(T1) desc, median desc
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

    print(f"Wrote {out}")
    print(f"{'rank':<4} {'P(T1)':>7} {'median':>12} {'p10':>12} {'p90':>14} {'ruin':>7}  name")
    for i, r in enumerate(rows, 1):
        print(
            f"{i:<4} {r.p_t1:7.2%} {r.median:12,.0f} {r.p10:12,.0f} {r.p90:14,.0f} {r.p_ruin:7.2%}  {r.name}"
        )


if __name__ == "__main__":
    main()
