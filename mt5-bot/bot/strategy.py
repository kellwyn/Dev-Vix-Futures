"""
Dylan O'Neill — VIX Futures Strategy
Monitors ES, NQ, and VIX relative to their previous day highs/lows
to identify confirmed breakdowns, fake breakdowns, and reversal setups.
Enriches every signal with ATH confluence, puts demand analysis, and
VIX Rule of 16 expected-move data.
"""

import os
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

from bot.signals  import Signal, SignalType, Direction, MarketSnapshot
from bot.vix_rules import (
    expected_daily_move,
    get_ath,
    ath_confluence,
)

load_dotenv()

ES_SYMBOL  = os.getenv("ES_SYMBOL",  "ES-Mini")
NQ_SYMBOL  = os.getenv("NQ_SYMBOL",  "NQ-Mini")
VIX_SYMBOL = os.getenv("VIX_SYMBOL", "VIX")

TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1,  "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,  "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}
TIMEFRAME = TIMEFRAME_MAP.get(os.getenv("TIMEFRAME", "M30"), mt5.TIMEFRAME_M30)

# Estimated win probability by signal type and strength
_PROBABILITIES: dict[SignalType, dict[int, float]] = {
    SignalType.CONFIRMED_BREAKDOWN:   {3: 0.70, 2: 0.62, 1: 0.55},
    SignalType.CONFIRMED_BREAKOUT:    {3: 0.70, 2: 0.62, 1: 0.55},
    SignalType.FAKE_BREAKDOWN:        {3: 0.68, 2: 0.65, 1: 0.58},
    SignalType.FAKE_BREAKOUT:         {3: 0.68, 2: 0.65, 1: 0.58},
    SignalType.VIX_LEADING_BEARISH:   {1: 0.55},
    SignalType.VIX_LEADING_BULLISH:   {1: 0.55},
    SignalType.ONE_PCT_DIVERGENCE_UP: {1: 0.50},
    SignalType.ONE_PCT_DIVERGENCE_DN: {1: 0.50},
}

# Correlated instrument: traded symbol → confirmation symbol
_CORRELATED: dict[str, str] = {
    ES_SYMBOL:  VIX_SYMBOL,
    NQ_SYMBOL:  VIX_SYMBOL,
    VIX_SYMBOL: ES_SYMBOL,
}


def _probability(signal_type: SignalType, strength: int) -> float:
    levels = _PROBABILITIES.get(signal_type, {})
    return levels.get(strength, levels.get(1, 0.50))


def _get_prev_day_levels(symbol: str) -> tuple[float, float, float]:
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 3)
    if rates is None or len(rates) < 2:
        raise RuntimeError(f"Cannot fetch daily data for {symbol}: {mt5.last_error()}")
    prev = pd.DataFrame(rates).iloc[-2]
    return float(prev["high"]), float(prev["low"]), float(prev["close"])


def _get_current_price(symbol: str) -> float:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"Cannot get tick for {symbol}: {mt5.last_error()}")
    return (tick.bid + tick.ask) / 2


def _pct_change(current: float, prev_close: float) -> float:
    return ((current - prev_close) / prev_close * 100) if prev_close else 0.0


def get_snapshot() -> MarketSnapshot:
    es_pdh,  es_pdl,  es_close  = _get_prev_day_levels(ES_SYMBOL)
    nq_pdh,  nq_pdl,  nq_close  = _get_prev_day_levels(NQ_SYMBOL)
    vix_pdh, vix_pdl, vix_close = _get_prev_day_levels(VIX_SYMBOL)
    es_price  = _get_current_price(ES_SYMBOL)
    nq_price  = _get_current_price(NQ_SYMBOL)
    vix_price = _get_current_price(VIX_SYMBOL)
    return MarketSnapshot(
        timestamp    = datetime.now(),
        es_price     = es_price,  es_pdh = es_pdh,  es_pdl = es_pdl,
        es_pct_chg   = _pct_change(es_price,  es_close),
        nq_price     = nq_price,  nq_pdh = nq_pdh,  nq_pdl = nq_pdl,
        nq_pct_chg   = _pct_change(nq_price,  nq_close),
        vix_price    = vix_price, vix_pdh = vix_pdh, vix_pdl = vix_pdl,
        vix_pct_chg  = _pct_change(vix_price, vix_close),
    )


def _make_signal(
    signal_type: SignalType,
    direction:   Direction,
    symbol:      str,
    entry_price: float,
    snap:        MarketSnapshot,
    reasons:     list[str],
    strength:    int,
) -> Signal:
    """
    Build a fully-enriched Signal:
    - PDH/PDL for traded and correlated instrument
    - VIX Rule of 16 daily expected move
    - ATH confluence
    - Puts demand interpretation
    - Win probability
    """
    # ── Traded instrument levels ───────────────────────────────────────
    if symbol == ES_SYMBOL:
        inst_pdh, inst_pdl = snap.es_pdh, snap.es_pdl
    elif symbol == NQ_SYMBOL:
        inst_pdh, inst_pdl = snap.nq_pdh, snap.nq_pdl
    else:
        inst_pdh, inst_pdl = snap.vix_pdh, snap.vix_pdl

    # ── Correlated instrument levels ──────────────────────────────────
    corr_sym = _CORRELATED.get(symbol, VIX_SYMBOL)
    if corr_sym == VIX_SYMBOL:
        corr_pdh, corr_pdl = snap.vix_pdh, snap.vix_pdl
    elif corr_sym == ES_SYMBOL:
        corr_pdh, corr_pdl = snap.es_pdh, snap.es_pdl
    else:
        corr_pdh, corr_pdl = snap.nq_pdh, snap.nq_pdl

    # ── VIX Rule of 16 ────────────────────────────────────────────────
    vix_pct_move, vix_pt_move = expected_daily_move(snap.vix_price, entry_price)

    # ── ATH confluence ────────────────────────────────────────────────
    ath            = get_ath(symbol)
    at_ath, pct_below_ath, ath_notes = ath_confluence(entry_price, ath)

    return Signal(
        signal_type        = signal_type,
        direction          = direction,
        symbol             = symbol,
        entry_price        = entry_price,
        instrument_pdh     = inst_pdh,
        instrument_pdl     = inst_pdl,
        correlated_symbol  = corr_sym,
        correlated_pdh     = corr_pdh,
        correlated_pdl     = corr_pdl,
        probability        = _probability(signal_type, strength),
        vix_price          = snap.vix_price,
        vix_daily_pct_move = vix_pct_move,
        vix_daily_pt_move  = vix_pt_move,
        ath_price          = ath,
        pct_from_ath       = pct_below_ath,
        at_ath_zone        = at_ath,
        ath_notes          = ath_notes,
        reason             = reasons,
        strength           = strength,
    )


# ─── VIX condition helpers ────────────────────────────────────────────────────

def _vix_strong(snap):     return snap.vix_price >= snap.vix_pdh
def _vix_weak(snap):       return snap.vix_price <= snap.vix_pdl
def _vix_lower_high(snap): return snap.vix_price <  snap.vix_pdh


def evaluate(snap: MarketSnapshot) -> Signal | None:
    """
    Evaluate market snapshot against all VIX strategy rules.
    Returns an enriched Signal when a setup is detected, else None.
    """
    reasons  = []
    strength = 1

    # ── RULE 1: CONFIRMED BREAKDOWN ───────────────────────────────────
    if snap.es_price < snap.es_pdl:
        if _vix_strong(snap):
            reasons.append(f"ES ({snap.es_price:.2f}) broke below PDL ({snap.es_pdl:.2f})")
            reasons.append(f"VIX ({snap.vix_price:.2f}) at/above PDH ({snap.vix_pdh:.2f}) — put demand confirmed")
            if snap.nq_price < snap.nq_pdl:
                reasons.append(f"NQ ({snap.nq_price:.2f}) also below PDL ({snap.nq_pdl:.2f}) — triple confirmation")
                strength = 3
            else:
                strength = 2
            return _make_signal(SignalType.CONFIRMED_BREAKDOWN, Direction.SHORT,
                                ES_SYMBOL, snap.es_price, snap, reasons, strength)

        # ── RULE 2: FAKE BREAKDOWN ────────────────────────────────────
        elif _vix_lower_high(snap) and snap.nq_price >= snap.nq_pdl:
            reasons.append(f"ES ({snap.es_price:.2f}) broke below PDL ({snap.es_pdl:.2f})")
            reasons.append(f"VIX ({snap.vix_price:.2f}) NOT at PDH ({snap.vix_pdh:.2f}) — put demand absent")
            reasons.append(f"NQ ({snap.nq_price:.2f}) holding above PDL ({snap.nq_pdl:.2f}) — relative strength")
            reasons.append("Bear trap likely — expect snap-back above PDL")
            return _make_signal(SignalType.FAKE_BREAKDOWN, Direction.LONG,
                                ES_SYMBOL, snap.es_price, snap, reasons, 2)

    # ── RULE 3: CONFIRMED BREAKOUT ────────────────────────────────────
    if snap.es_price > snap.es_pdh:
        if _vix_weak(snap):
            reasons.append(f"ES ({snap.es_price:.2f}) broke above PDH ({snap.es_pdh:.2f})")
            reasons.append(f"VIX ({snap.vix_price:.2f}) at/below PDL ({snap.vix_pdl:.2f}) — put demand removed")
            if snap.nq_price > snap.nq_pdh:
                reasons.append(f"NQ ({snap.nq_price:.2f}) also above PDH ({snap.nq_pdh:.2f}) — triple confirmation")
                strength = 3
            else:
                strength = 2
            return _make_signal(SignalType.CONFIRMED_BREAKOUT, Direction.LONG,
                                ES_SYMBOL, snap.es_price, snap, reasons, strength)

        # ── RULE 4: FAKE BREAKOUT ─────────────────────────────────────
        elif _vix_strong(snap) and snap.nq_price <= snap.nq_pdh:
            reasons.append(f"ES ({snap.es_price:.2f}) broke above PDH ({snap.es_pdh:.2f})")
            reasons.append(f"VIX ({snap.vix_price:.2f}) still at/above PDH ({snap.vix_pdh:.2f}) — put demand persists")
            reasons.append(f"NQ ({snap.nq_price:.2f}) not confirming above PDH ({snap.nq_pdh:.2f})")
            reasons.append("Bull trap likely — rally may fail under pressure")
            return _make_signal(SignalType.FAKE_BREAKOUT, Direction.SHORT,
                                ES_SYMBOL, snap.es_price, snap, reasons, 2)

    # ── RULE 5: VIX LEADING ───────────────────────────────────────────
    if _vix_strong(snap) and snap.es_price >= snap.es_pdl:
        reasons.append(f"VIX ({snap.vix_price:.2f}) at/above PDH ({snap.vix_pdh:.2f}) — put demand building")
        reasons.append(f"ES ({snap.es_price:.2f}) has NOT yet broken PDL ({snap.es_pdl:.2f})")
        reasons.append("VIX leading: downside pressure building — watch for ES breakdown")
        return _make_signal(SignalType.VIX_LEADING_BEARISH, Direction.NONE,
                            ES_SYMBOL, snap.es_price, snap, reasons, 1)

    if _vix_weak(snap) and snap.es_price <= snap.es_pdh:
        reasons.append(f"VIX ({snap.vix_price:.2f}) at/below PDL ({snap.vix_pdl:.2f}) — put demand unwinding")
        reasons.append(f"ES ({snap.es_price:.2f}) has NOT yet broken PDH ({snap.es_pdh:.2f})")
        reasons.append("VIX leading bullish: pressure easing — watch for ES breakout")
        return _make_signal(SignalType.VIX_LEADING_BULLISH, Direction.NONE,
                            ES_SYMBOL, snap.es_price, snap, reasons, 1)

    # ── RULE 6: 1% DIVERGENCE ─────────────────────────────────────────
    if snap.es_pct_chg >= 1.0 and snap.vix_pct_chg >= 1.0:
        reasons.append(f"ES +{snap.es_pct_chg:.2f}% AND VIX +{snap.vix_pct_chg:.2f}% — pressure rising with price")
        reasons.append("Rally is fragile — avoid chasing longs at resistance")
        return _make_signal(SignalType.ONE_PCT_DIVERGENCE_UP, Direction.NONE,
                            ES_SYMBOL, snap.es_price, snap, reasons, 1)

    if snap.es_pct_chg <= -1.0 and snap.vix_pct_chg <= -1.0:
        reasons.append(f"ES {snap.es_pct_chg:.2f}% AND VIX {snap.vix_pct_chg:.2f}% — pressure falling with price")
        reasons.append("Selloff is fragile — support more likely to hold")
        return _make_signal(SignalType.ONE_PCT_DIVERGENCE_DN, Direction.NONE,
                            ES_SYMBOL, snap.es_price, snap, reasons, 1)

    return None


def print_dashboard(snap: MarketSnapshot) -> None:
    def status(price, pdh, pdl):
        if price > pdh:   return "▲ ABOVE PDH"
        elif price < pdl: return "▼ BELOW PDL"
        else:             return "  in range  "

    vix_pct, vix_pts = expected_daily_move(snap.vix_price, snap.es_price)
    print(f"\n{'─'*68}")
    print(f"  VIX STRATEGY SCANNER  —  {snap.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  VIX Rule of 16: {snap.vix_price:.1f}/16 = {vix_pct:.2f}% daily expected move = ±{vix_pts:.1f} ES pts")
    print(f"{'─'*68}")
    print(f"  {'SYMBOL':<10} {'PRICE':>10}  {'%CHG':>7}  {'PDH':>10}  {'PDL':>10}  STATUS")
    print(f"  {'─'*64}")
    for sym, price, pct, pdh, pdl in [
        (ES_SYMBOL,  snap.es_price,  snap.es_pct_chg,  snap.es_pdh,  snap.es_pdl),
        (NQ_SYMBOL,  snap.nq_price,  snap.nq_pct_chg,  snap.nq_pdh,  snap.nq_pdl),
        (VIX_SYMBOL, snap.vix_price, snap.vix_pct_chg, snap.vix_pdh, snap.vix_pdl),
    ]:
        print(f"  {sym:<10} {price:>10.2f}  {pct:>+6.2f}%  {pdh:>10.2f}  {pdl:>10.2f}  {status(price,pdh,pdl)}")
    print(f"{'─'*68}")
