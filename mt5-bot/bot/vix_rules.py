"""
VIX utility functions:
  - VIX Rule of 16 (realistic daily expected move → TP sizing)
  - Kelly Criterion (optimal position sizing)
  - ATH detection and confluence notes
  - Puts demand interpretation from VIX behavior
"""

import os
import math
import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

VIX_SYMBOL = os.getenv("VIX_SYMBOL", "VIX")

# ─────────────────────────────────────────────────────────────────────────────
# VIX RULE OF 16
# ─────────────────────────────────────────────────────────────────────────────

def expected_daily_move(vix_price: float, instrument_price: float) -> tuple[float, float]:
    """
    VIX Rule of 16:
      daily expected move (%) = VIX / 16
      daily expected move (pts) = instrument_price * (VIX/16) / 100

    This is the 1-standard-deviation daily move implied by VIX for the next 30 days.
    Returns (pct_move, point_move).
    """
    pct = vix_price / 16.0
    pts = instrument_price * pct / 100.0
    return round(pct, 4), round(pts, 2)


def realistic_tp_points(
    vix_daily_pts: float,
    sl_points: float,
    strength: int,
) -> tuple[float, float]:
    """
    Calculate a realistic take-profit in points based on the VIX Rule of 16.

    Target fraction of the daily expected move by signal strength:
      Strength 1 → 50% of daily move (conservative)
      Strength 2 → 65% of daily move
      Strength 3 → 80% of daily move

    Also compare against a pure R:R target and use whichever is LOWER
    (more conservative / more achievable within the day).

    Returns (tp_points, actual_rr_ratio).
    """
    _TARGET_FRACTION = {1: 0.50, 2: 0.65, 3: 0.80}
    _RR_TARGET       = {1: 1.5,  2: 2.0,  3: 3.0}

    vix_tp  = vix_daily_pts * _TARGET_FRACTION.get(strength, 0.65)
    rr_tp   = sl_points     * _RR_TARGET.get(strength, 2.0)

    # Use the more conservative (lower) of the two to ensure achievability
    tp_pts  = min(vix_tp, rr_tp)
    rr      = tp_pts / sl_points if sl_points > 0 else 0.0
    return round(tp_pts, 2), round(rr, 2)


# ─────────────────────────────────────────────────────────────────────────────
# KELLY CRITERION
# ─────────────────────────────────────────────────────────────────────────────

def kelly_criterion(probability: float, rr_ratio: float) -> tuple[float, float]:
    """
    Kelly Criterion: optimal fraction of bankroll to risk per trade.

      f* = (b·p − q) / b     where b = rr_ratio, p = win prob, q = 1 − p

    A negative result means negative expected value — do not trade.
    Half-Kelly is used in practice to reduce variance and drawdown risk.

    Returns (full_kelly_fraction, half_kelly_fraction) as decimals (e.g. 0.05 = 5%).
    """
    p, q, b = probability, 1.0 - probability, rr_ratio
    if b <= 0 or p <= 0 or p >= 1:
        return 0.0, 0.0
    full_kelly = (b * p - q) / b
    half_kelly = full_kelly / 2.0
    return round(full_kelly, 4), round(half_kelly, 4)


def kelly_lot_size(
    symbol: str,
    sl_points: float,
    probability: float,
    rr_ratio: float,
    max_risk_pct: float,
) -> tuple[float, float, float, float]:
    """
    Calculate lot size using Half-Kelly, capped at max_risk_pct of balance.

    Returns (lot, effective_risk_pct, risk_amount_usd, full_kelly_pct).
    """
    full_kelly, half_kelly = kelly_criterion(probability, rr_ratio)
    account     = mt5.account_info()
    symbol_info = mt5.symbol_info(symbol)

    if account is None or symbol_info is None or half_kelly <= 0:
        return 0.0, 0.0, 0.0, full_kelly * 100

    # Cap Half-Kelly at the user's max risk setting
    effective_risk_pct = min(half_kelly, max_risk_pct / 100.0)
    risk_amount        = account.balance * effective_risk_pct

    tick_value   = symbol_info.trade_tick_value
    tick_size    = symbol_info.trade_tick_size
    if tick_size == 0 or tick_value == 0:
        return 0.0, effective_risk_pct * 100, risk_amount, full_kelly * 100

    risk_per_lot = (sl_points / tick_size) * tick_value
    if risk_per_lot == 0:
        return 0.0, effective_risk_pct * 100, risk_amount, full_kelly * 100

    lot = risk_amount / risk_per_lot
    lot = max(symbol_info.volume_min,
              round(lot / symbol_info.volume_step) * symbol_info.volume_step)
    lot = min(lot, symbol_info.volume_max)

    return lot, round(effective_risk_pct * 100, 4), round(risk_amount, 2), round(full_kelly * 100, 2)


# ─────────────────────────────────────────────────────────────────────────────
# ATH CONFLUENCE
# ─────────────────────────────────────────────────────────────────────────────

def get_ath(symbol: str, lookback_bars: int = 504) -> float:
    """
    Get the 2-year high for a symbol (proxy for ATH in recent market context).
    Returns 0.0 on failure.
    """
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, lookback_bars)
    if rates is None or len(rates) == 0:
        return 0.0
    return float(pd.DataFrame(rates)["high"].max())


def ath_confluence(current_price: float, ath: float) -> tuple[bool, float, list[str]]:
    """
    Assess proximity to ATH and generate confluence notes.
    Returns (at_ath_zone: bool, pct_below_ath: float, notes: list[str]).
    """
    notes = []
    if ath <= 0:
        return False, 0.0, ["ATH data unavailable"]

    pct_below = max(0.0, (ath - current_price) / ath * 100)

    if pct_below <= 0.5:
        notes.append(f"Price AT all-time high zone ({ath:.2f})")
        notes.append("VIX finds natural floor here — put options cheapest at ATH, fund managers buy puts aggressively")
        notes.append("Rising VIX at ATH does NOT always confirm breakdown — extra context required")
        return True, round(pct_below, 2), notes

    if pct_below <= 2.0:
        notes.append(f"Price NEAR ATH ({ath:.2f}, {pct_below:.1f}% below)")
        notes.append("ATH proximity — elevated VIX here may reflect routine hedging, not true breakdown pressure")
        return True, round(pct_below, 2), notes

    notes.append(f"Price is {pct_below:.1f}% below 2-year ATH ({ath:.2f}) — ATH not a factor")
    return False, round(pct_below, 2), notes


# ─────────────────────────────────────────────────────────────────────────────
# SHARPE (single-trade estimate)
# ─────────────────────────────────────────────────────────────────────────────

def single_trade_sharpe(probability: float, reward: float, risk: float) -> float:
    """
    Single-trade Sharpe ratio estimate.
      E[R]   = p · reward − (1−p) · risk
      Std[R] = √(p·(1−p)) · (reward + risk)
      Sharpe = E[R] / Std[R]
    """
    p = probability
    if p <= 0 or p >= 1 or risk <= 0 or reward <= 0:
        return 0.0
    e_r   = p * reward - (1 - p) * risk
    std_r = math.sqrt(p * (1 - p)) * (reward + risk)
    return round(e_r / std_r, 3) if std_r > 0 else 0.0
