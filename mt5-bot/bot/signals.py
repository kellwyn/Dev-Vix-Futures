from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class SignalType(Enum):
    CONFIRMED_BREAKDOWN   = "CONFIRMED BREAKDOWN"        # ES + NQ break PDL, VIX at/above PDH
    FAKE_BREAKDOWN        = "FAKE BREAKDOWN"             # ES breaks PDL, NQ holds, VIX weak
    CONFIRMED_BREAKOUT    = "CONFIRMED BREAKOUT"         # ES + NQ break PDH, VIX at/below PDL
    FAKE_BREAKOUT         = "FAKE BREAKOUT"              # ES breaks PDH, NQ holds, VIX strong
    VIX_LEADING_BEARISH   = "VIX LEADING BEARISH"        # VIX hits PDH before ES breaks PDL
    VIX_LEADING_BULLISH   = "VIX LEADING BULLISH"        # VIX hits PDL before ES breaks PDH
    ONE_PCT_DIVERGENCE_UP = "1% RULE — FRAGILE RALLY"   # ES up 1%+ AND VIX up 1%+
    ONE_PCT_DIVERGENCE_DN = "1% RULE — FRAGILE SELLOFF" # ES down 1%+ AND VIX down 1%+
    NONE                  = "NO SIGNAL"


class Direction(Enum):
    LONG  = "BUY"
    SHORT = "SELL"
    NONE  = "NONE"


@dataclass
class MarketSnapshot:
    timestamp:   datetime

    es_price:    float
    es_pdh:      float
    es_pdl:      float
    es_pct_chg:  float

    nq_price:    float
    nq_pdh:      float
    nq_pdl:      float
    nq_pct_chg:  float

    vix_price:   float
    vix_pdh:     float
    vix_pdl:     float
    vix_pct_chg: float


@dataclass
class Signal:
    signal_type: SignalType
    direction:   Direction
    symbol:      str    # instrument being traded
    entry_price: float

    # ── Traded instrument PDH/PDL ─────────────────────────────────────
    instrument_pdh: float = 0.0
    instrument_pdl: float = 0.0

    # ── Correlated instrument (VIX ↔ ES) ─────────────────────────────
    correlated_symbol: str   = ""
    correlated_pdh:    float = 0.0
    correlated_pdl:    float = 0.0

    # ── Win probability ───────────────────────────────────────────────
    probability: float = 0.0

    # ── VIX Rule of 16 ───────────────────────────────────────────────
    vix_price:          float = 0.0
    vix_daily_pct_move: float = 0.0   # VIX / 16  (%)
    vix_daily_pt_move:  float = 0.0   # in instrument points

    # ── ATH confluence ────────────────────────────────────────────────
    ath_price:    float      = 0.0
    pct_from_ath: float      = 0.0
    at_ath_zone:  bool       = False
    ath_notes:    list[str]  = field(default_factory=list)

    # ── Confluence reasons ────────────────────────────────────────────
    reason:    list[str] = field(default_factory=list)
    timestamp: datetime  = field(default_factory=datetime.now)
    strength:  int       = 1   # 1 = moderate, 2 = strong, 3 = very strong
