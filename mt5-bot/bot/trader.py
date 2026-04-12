"""
Trade execution with manual confirmation.
Displays full trade context including:
  - Rule & signal direction
  - Puts demand (VIX as proxy)
  - ATH confluence
  - VIX Rule of 16 realistic take-profit
  - Kelly Criterion position sizing
  - Risk/Reward in $, Sharpe ratio
"""

import os
import MetaTrader5 as mt5
from dotenv import load_dotenv

from bot.signals   import Signal, Direction
from bot.vix_rules import (
    realistic_tp_points,
    kelly_lot_size,
    single_trade_sharpe,
    kelly_criterion,
)

load_dotenv()

RISK_PERCENT  = float(os.getenv("RISK_PERCENT",     "1.0"))
STOP_LOSS_PTS = float(os.getenv("STOP_LOSS_POINTS", "20"))

_STRENGTH_LABEL = {1: "Moderate ★", 2: "Strong ★★", 3: "Very Strong ★★★"}

# Width of the confirmation panel
W = 68


def _row(label: str, value: str, indent: int = 2) -> None:
    dots = W - indent - len(label) - len(value) - 2
    print(f"  {' '*indent}{label}{'·'*max(1, dots)} {value}")


def _divider(char: str = "─") -> None:
    print(f"  {char * W}")


def _header(text: str) -> None:
    pad = max(0, (W - len(text) - 2) // 2)
    right = W - pad - len(text) - 2
    print(f"  {'═'*pad} {text} {'═'*right}")


def _wrap(text: str, width: int = 60, indent: int = 6) -> None:
    """Print long notes with word-wrap."""
    words  = text.split()
    line   = " " * indent
    for word in words:
        if len(line) + len(word) + 1 > width + indent:
            print(f"  {line}")
            line = " " * indent + word
        else:
            line = line + (" " if line.strip() else "") + word
    if line.strip():
        print(f"  {line}")


def _confirm(signal: Signal) -> bool:
    """Display full enriched trade context and ask for manual confirmation."""

    print()
    _divider("═")
    print(f"  SIGNAL ALERT  —  {_STRENGTH_LABEL.get(signal.strength, '')}")
    _divider()

    # ── SETUP ─────────────────────────────────────────────────────────
    _header("SETUP")
    _row("Rule",      signal.signal_type.value)
    _row("Direction", f"{signal.direction.value}  {signal.symbol}")
    _row("Time",      signal.timestamp.strftime("%Y-%m-%d  %H:%M:%S"))

    # ── CONFLUENCE ────────────────────────────────────────────────────
    _divider()
    _header("CONFLUENCE")
    for r in signal.reason:
        _wrap(f"▸ {r}")

    # ── ATH CONFLUENCE ────────────────────────────────────────────────
    _divider()
    if signal.at_ath_zone:
        _header("⚠  ATH CONFLUENCE  ⚠")
    else:
        _header("ATH CONFLUENCE")
    _row("2-Year ATH",  f"{signal.ath_price:.2f}" if signal.ath_price else "N/A")
    _row("Dist. to ATH", f"{signal.pct_from_ath:.1f}% below")
    for note in signal.ath_notes:
        _wrap(f"▸ {note}")

    # ── KEY LEVELS ────────────────────────────────────────────────────
    _divider()
    _header("KEY LEVELS")
    _row(f"{signal.symbol:<12} PDH", f"{signal.instrument_pdh:.2f}")
    _row(f"{signal.symbol:<12} PDL", f"{signal.instrument_pdl:.2f}")
    _row(f"{signal.correlated_symbol:<12} PDH", f"{signal.correlated_pdh:.2f}")
    _row(f"{signal.correlated_symbol:<12} PDL", f"{signal.correlated_pdl:.2f}")

    # ── Alert-only: no executable trade ───────────────────────────────
    if signal.direction == Direction.NONE:
        _divider()
        print("  ⚠  ALERT ONLY — no trade to execute for this signal type.")
        _divider("═")
        input("\n  Press Enter to continue scanning...")
        return False

    # ── VIX RULE OF 16 ────────────────────────────────────────────────
    _divider()
    _header("VIX RULE OF 16  —  REALISTIC TP")
    vix_tp_pts, actual_rr = realistic_tp_points(
        signal.vix_daily_pt_move, STOP_LOSS_PTS, signal.strength
    )
    _row("VIX / 16 formula",
         f"{signal.vix_price:.2f} / 16 = {signal.vix_daily_pct_move:.2f}%  "
         f"= ±{signal.vix_daily_pt_move:.1f} pts/day")
    _row("TP target fraction",
         {1: "50%", 2: "65%", 3: "80%"}.get(signal.strength, "65%") +
         " of daily expected move")
    _row("VIX-based TP",   f"{vix_tp_pts:.1f} pts")
    _row("Resulting R:R",  f"1 : {actual_rr:.2f}  (adjusted for achievability)")

    symbol_info = mt5.symbol_info(signal.symbol)
    account     = mt5.account_info()

    if symbol_info and account:
        pt = symbol_info.point

        if signal.direction == Direction.LONG:
            sl_price = signal.entry_price - STOP_LOSS_PTS * pt
            tp_price = signal.entry_price + vix_tp_pts    * pt
        else:
            sl_price = signal.entry_price + STOP_LOSS_PTS * pt
            tp_price = signal.entry_price - vix_tp_pts    * pt

        # ── KELLY POSITION SIZING ──────────────────────────────────────
        lot, eff_risk_pct, risk_amt, full_kelly_pct = kelly_lot_size(
            symbol       = signal.symbol,
            sl_points    = STOP_LOSS_PTS,
            probability  = signal.probability,
            rr_ratio     = actual_rr,
            max_risk_pct = RISK_PERCENT,
        )
        full_kelly, half_kelly = kelly_criterion(signal.probability, actual_rr)
        reward_amt = risk_amt * actual_rr if risk_amt else 0.0
        sharpe     = single_trade_sharpe(signal.probability, reward_amt, risk_amt)

        _divider()
        _header("TRADE PARAMETERS")
        _row("Entry Price", f"{signal.entry_price:.2f}")
        _row("Stop Loss",   f"{sl_price:.2f}  ({STOP_LOSS_PTS:.0f} pts)")
        _row("Take Profit", f"{tp_price:.2f}  ({vix_tp_pts:.0f} pts)  ← VIX Rule of 16")

        _divider()
        _header("KELLY POSITION SIZING")
        _row("Win Probability",    f"{signal.probability*100:.0f}%")
        _row("Full Kelly",         f"{full_kelly_pct:.2f}%  of balance")
        half_k_pct = half_kelly * 100
        _row("Half-Kelly (rec.)",  f"{half_k_pct:.2f}%  of balance")
        _row("Your RISK_PERCENT",  f"{RISK_PERCENT:.2f}%  cap")
        used = "Half-Kelly" if half_k_pct <= RISK_PERCENT else f"RISK_PERCENT cap ({RISK_PERCENT}%)"
        _row("Effective Risk",     f"{eff_risk_pct:.4f}%  [{used}]")
        _row("Lot Size",           f"{lot}")

        _divider()
        _header("RISK / REWARD")
        _row("Risk Amount",    f"${risk_amt:,.2f}")
        _row("Reward Amount",  f"${reward_amt:,.2f}")
        _row("Risk : Reward",  f"1 : {actual_rr:.2f}")
        _row("Sharpe Ratio",   f"{sharpe:.3f}  (single-trade estimate)")
        _row("Account Balance", f"${account.balance:,.2f}  {account.currency}")

    else:
        _divider()
        _header("TRADE PARAMETERS")
        _row("Entry",       f"{signal.entry_price:.2f}")
        _row("Stop Loss",   f"~{STOP_LOSS_PTS:.0f} pts from entry")
        _row("Take Profit", f"~{vix_tp_pts:.0f} pts  (VIX Rule of 16)")
        _row("R:R",         f"1 : {actual_rr:.2f}")
        _row("Probability", f"{signal.probability*100:.0f}%")
        lot = 0.0

    _divider("═")
    print()

    # ── CONFIRMATION PROMPT ───────────────────────────────────────────
    while True:
        choice = input("  Confirm trade? [y / n]: ").strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no", ""):
            print("  Trade skipped.\n")
            return False
        print("  Please enter y or n.")


def _build_request(signal: Signal, lot: float, vix_tp_pts: float) -> dict:
    symbol_info = mt5.symbol_info(signal.symbol)
    tick        = mt5.symbol_info_tick(signal.symbol)
    if symbol_info is None or tick is None:
        raise RuntimeError(f"Cannot get symbol info for {signal.symbol}")

    pt     = symbol_info.point
    digits = symbol_info.digits

    if signal.direction == Direction.LONG:
        order_type = mt5.ORDER_TYPE_BUY
        price      = tick.ask
        sl         = price - STOP_LOSS_PTS * pt
        tp         = price + vix_tp_pts    * pt
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price      = tick.bid
        sl         = price + STOP_LOSS_PTS * pt
        tp         = price - vix_tp_pts    * pt

    return {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       signal.symbol,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           round(sl, digits),
        "tp":           round(tp, digits),
        "deviation":    20,
        "magic":        202500,
        "comment":      f"VIX-EA: {signal.signal_type.name}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }


def execute(signal: Signal) -> bool:
    """
    Display enriched trade context, wait for manual confirmation, then execute.
    Returns True if the order was filled.
    """
    # Pre-calculate TP (needed for both display and order)
    vix_tp_pts, actual_rr = realistic_tp_points(
        signal.vix_daily_pt_move, STOP_LOSS_PTS, signal.strength
    )

    if not _confirm(signal):
        return False

    lot, *_ = kelly_lot_size(
        symbol       = signal.symbol,
        sl_points    = STOP_LOSS_PTS,
        probability  = signal.probability,
        rr_ratio     = actual_rr,
        max_risk_pct = RISK_PERCENT,
    )

    if lot <= 0:
        print("  ERROR: Kelly criterion returned 0 lot — trade has negative expected value. Skipped.")
        return False

    print(f"\n  Lot: {lot}  |  SL: {STOP_LOSS_PTS:.0f} pts  |  TP: {vix_tp_pts:.0f} pts  |  R:R 1:{actual_rr:.2f}")

    request = _build_request(signal, lot, vix_tp_pts)
    print(f"  Sending: {signal.direction.value} {lot} {signal.symbol} "
          f"@ {request['price']:.2f}  SL {request['sl']:.2f}  TP {request['tp']:.2f}")

    result = mt5.order_send(request)

    if result is None:
        print(f"  ERROR: order_send returned None — {mt5.last_error()}")
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  ORDER FILLED ✓  ticket=#{result.order}  price={result.price:.2f}  vol={result.volume}")
        return True

    print(f"  ORDER FAILED  retcode={result.retcode}  {result.comment}")
    return False
