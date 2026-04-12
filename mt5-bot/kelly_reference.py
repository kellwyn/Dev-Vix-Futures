"""
Kelly Criterion Reference Table — VIX Futures Strategy EA
Standalone script. No MT5 connection required.

Assumptions:
  - Stop Loss    : 20 points (STOP_LOSS_POINTS in .env)
  - $ per point  : adjust USD_PER_POINT for your broker's tick value
  - R:R varies   : 1.5:1 (strength 1) / 2.0:1 (strength 2) / 3.0:1 (strength 3)
  - TP is set by VIX Rule of 16 — these R:R values are illustrative baselines
"""

STOP_LOSS_PTS = 20
USD_PER_POINT = 10.0     # <-- adjust to your broker's contract spec
RISK_PCT_CAP  = 1.0      # EA's max RISK_PERCENT setting

SIGNALS = [
    {"label": "Strength 1 — Moderate", "prob": 0.55, "rr": 1.5},
    {"label": "Strength 2 — Strong",   "prob": 0.62, "rr": 2.0},
    {"label": "Strength 3 — V.Strong", "prob": 0.70, "rr": 3.0},
]

ACCOUNTS    = [10_000, 50_000, 100_000, 200_000]
RISK_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.50]   # % of account


def kelly(p, rr):
    q    = 1.0 - p
    full = (rr * p - q) / rr
    return round(full, 4), round(full / 2, 4)


def risk_per_lot():
    return STOP_LOSS_PTS * USD_PER_POINT


RPL = risk_per_lot()   # $ risked per 1.0 lot at default SL


# ── TABLE 1: Kelly fractions by signal strength ──────────────────────────────

W1 = 74
print()
print(f"  {'─'*W1}")
print(f"  TABLE 1  —  Kelly Criterion by Signal Strength")
print(f"  SL: {STOP_LOSS_PTS} pts  |  ${USD_PER_POINT}/pt  |  ${RPL:.0f} risk per lot  |  Cap: {RISK_PCT_CAP}%")
print(f"  {'─'*W1}")
print(f"  {'Signal Type':<26}  {'Win%':>5}  {'R:R':>5}  {'Full Kelly':>10}  {'Half-Kelly':>10}  {'EA Applies':>12}")
print(f"  {'─'*W1}")
for s in SIGNALS:
    fk, hk = kelly(s["prob"], s["rr"])
    hk_pct  = hk * 100
    ea_uses = f"≤{RISK_PCT_CAP:.1f}%  (capped)" if hk_pct > RISK_PCT_CAP else f"{hk_pct:.2f}%"
    print(f"  {s['label']:<26}  {s['prob']*100:>4.0f}%  "
          f"{s['rr']:>4.1f}:1  {fk*100:>9.1f}%  {hk_pct:>9.1f}%  {ea_uses:>12}")
print(f"  {'─'*W1}")
print(f"  Full Kelly is theoretical optimal. EA uses Half-Kelly, capped at {RISK_PCT_CAP}%.")
print()


# ── TABLE 2: Position sizing by account ──────────────────────────────────────

for s in SIGNALS:
    fk, hk = kelly(s["prob"], s["rr"])
    hk_pct  = hk * 100
    rr      = s["rr"]

    # Nearest lot sizes to Kelly target for each account
    def suited_lots(account):
        kelly_risk  = account * min(hk, RISK_PCT_CAP / 100)
        kelly_lot   = kelly_risk / RPL
        # Build 5 levels around Kelly target
        candidates  = sorted({
            round(max(0.01, kelly_lot * 0.25), 2),
            round(max(0.01, kelly_lot * 0.50), 2),
            round(max(0.01, kelly_lot * 0.75), 2),
            round(max(0.01, kelly_lot),        2),
            round(max(0.01, kelly_lot * 1.50), 2),
        })
        return candidates[:5]

    print(f"  {'─'*W1}")
    print(f"  TABLE 2  —  {s['label']}  |  Win {s['prob']*100:.0f}%  |  R:R 1:{rr}  "
          f"|  Half-Kelly {hk_pct:.1f}%  (EA cap {RISK_PCT_CAP}%)")
    print(f"  {'─'*W1}")

    # Header
    acct_headers = "".join(f"  {'$'+f'{a:,}':^40}" for a in ACCOUNTS)
    print(f"  {'':20}" + "".join(f"  {'$'+f'{a:,}':^40}" for a in ACCOUNTS))
    sub = "  {:6}  {:7}  {:9}  {:10}"
    print(f"  {'Lot':>20}" + (sub.format("Lot", "Risk %", "Risk $", "Reward $")) * len(ACCOUNTS))
    print(f"  {'─'*W1}")

    # Build rows — one risk level per row, one column per account
    for risk_pct in RISK_LEVELS:
        row = f"  {risk_pct:>18.2f}%"
        for account in ACCOUNTS:
            risk_usd   = account * risk_pct / 100
            lot        = round(risk_usd / RPL, 2)
            reward_usd = risk_usd * rr
            row += f"  {lot:>5.2f}  {risk_pct:>6.2f}%  ${risk_usd:>7,.0f}  ${reward_usd:>8,.0f}"
        print(row)

    print(f"  {'─'*W1}")
    print()


print(f"  NOTE: $10/pt is illustrative. Adjust USD_PER_POINT at the top of this file")
print(f"  to match your broker's actual tick value for the ES contract.")
print()
