//+------------------------------------------------------------------+
//|  VixFuturesEA.mq5                                                |
//|  Dylan O'Neill — VIX Futures Strategy                            |
//|  Backtest symbols: US500M / NDAQ / VIXM                         |
//|                                                                  |
//|  Rules implemented:                                              |
//|    1. Confirmed Breakdown  — ES+NQ break PDL, VIX above PDH     |
//|    2. Fake Breakdown       — ES breaks PDL, VIX weak, NQ holds  |
//|    3. Confirmed Breakout   — ES+NQ break PDH, VIX below PDL     |
//|    4. Fake Breakout        — ES breaks PDH, VIX elevated, NQ lag|
//|    5. VIX Leading Bearish  — VIX at PDH before ES breaks PDL    |
//|    6. VIX Leading Bullish  — VIX at PDL before ES breaks PDH    |
//|    7. 1% Divergence Rule   — ES and VIX move same direction ≥1% |
//|                                                                  |
//|  Sizing  : Half-Kelly, capped at MaxRiskPct                      |
//|  TP      : VIX Rule of 16  (VIX/16 = daily expected move %)     |
//|  Confirm : MessageBox prompt — disable for clean backtesting     |
//+------------------------------------------------------------------+
#property copyright "Dylan O'Neill VIX Strategy EA"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//── Input Parameters ──────────────────────────────────────────────────────────
input string   ES_Symbol        = "US500M";   // ES equivalent
input string   NQ_Symbol        = "NDAQ";     // NQ equivalent
input string   VIX_Symbol       = "VIXM";     // VIX equivalent

input ENUM_TIMEFRAMES Timeframe = PERIOD_M30; // Analysis timeframe

input double   StopLossPts      = 20.0;       // Stop loss in points
input double   MaxRiskPct       = 1.0;        // Max risk % of balance (Kelly cap)
input int      MagicNumber      = 202500;     // EA magic number
input bool     ManualConfirm    = false;      // Show confirm dialog (live only)
input bool     AllowLongs       = true;       // Allow long trades
input bool     AllowShorts      = true;       // Allow short trades

//── Signal strength → TP fraction of VIX daily move ──────────────────────────
//   Strength 1 = 50%, Strength 2 = 65%, Strength 3 = 80%
//   R:R caps:   1.5:1            2.0:1             3.0:1
//   Realistic TP = min(VIX-based, R:R-based) for achievability

//── Globals ───────────────────────────────────────────────────────────────────
CTrade         Trade;
datetime       g_lastBarTime  = 0;    // Prevent multi-fire per bar
string         g_lastSignal   = "";   // Prevent re-alerting same signal

//+------------------------------------------------------------------+
//| Expert initialisation                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   Trade.SetExpertMagicNumber(MagicNumber);
   Trade.SetDeviationInPoints(20);

   // Verify symbols are available
   string syms[3] = {ES_Symbol, NQ_Symbol, VIX_Symbol};
   for(int i = 0; i < 3; i++)
   {
      if(!SymbolSelect(syms[i], true))
      {
         PrintFormat("WARNING: Symbol %s not found in Market Watch — add it and restart.", syms[i]);
      }
   }
   Print("VIX Futures EA initialised. Symbols: ", ES_Symbol, " / ", NQ_Symbol, " / ", VIX_Symbol);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Utility: previous day high / low / close for any symbol          |
//+------------------------------------------------------------------+
bool GetPrevDayLevels(string sym, double &pdh, double &pdl, double &pdc)
{
   MqlRates rates[];
   if(CopyRates(sym, PERIOD_D1, 0, 3, rates) < 2) return false;
   pdh = rates[1].high;
   pdl = rates[1].low;
   pdc = rates[1].close;
   return true;
}

//+------------------------------------------------------------------+
//| Utility: % change from prior close                               |
//+------------------------------------------------------------------+
double PctChange(double current, double prevClose)
{
   if(prevClose == 0) return 0;
   return (current - prevClose) / prevClose * 100.0;
}

//+------------------------------------------------------------------+
//| VIX Rule of 16 — daily expected point move on ES                 |
//+------------------------------------------------------------------+
double VixDailyPoints(double vixPrice, double esPrice)
{
   return esPrice * (vixPrice / 16.0) / 100.0;
}

//+------------------------------------------------------------------+
//| Realistic TP: min(VIX-fraction, R:R target), returns points      |
//+------------------------------------------------------------------+
double RealisticTP(double vixDailyPts, double slPts, int strength)
{
   double fractions[4] = {0, 0.50, 0.65, 0.80};   // index 1-3
   double rrTargets[4] = {0, 1.5,  2.0,  3.0};

   int    s          = MathMax(1, MathMin(3, strength));
   double vixTP      = vixDailyPts * fractions[s];
   double rrTP       = slPts       * rrTargets[s];
   return MathMin(vixTP, rrTP);   // more conservative = more achievable
}

//+------------------------------------------------------------------+
//| Kelly Criterion — returns half-kelly fraction (0–1)              |
//+------------------------------------------------------------------+
double HalfKelly(double prob, double rr)
{
   if(rr <= 0 || prob <= 0 || prob >= 1) return 0;
   double full = (rr * prob - (1.0 - prob)) / rr;
   return MathMax(0, full / 2.0);
}

//+------------------------------------------------------------------+
//| Lot size via Half-Kelly, capped at MaxRiskPct                    |
//+------------------------------------------------------------------+
double CalcLot(string sym, double slPts, double prob, double rr)
{
   double hk          = HalfKelly(prob, rr);
   if(hk <= 0) return 0;                          // negative EV — skip

   double effRisk     = MathMin(hk, MaxRiskPct / 100.0);
   double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount  = balance * effRisk;

   double tickValue   = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize == 0 || tickValue == 0) return 0;

   double riskPerLot  = (slPts / tickSize) * tickValue;
   if(riskPerLot == 0) return 0;

   double lot         = riskAmount / riskPerLot;
   double minLot      = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double maxLot      = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step        = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);

   lot = MathFloor(lot / step) * step;
   lot = MathMax(minLot, MathMin(maxLot, lot));
   return lot;
}

//+------------------------------------------------------------------+
//| 2-year ATH for ATH confluence check                              |
//+------------------------------------------------------------------+
double GetATH(string sym, int lookback = 504)
{
   MqlRates rates[];
   int copied = CopyRates(sym, PERIOD_D1, 0, lookback, rates);
   if(copied <= 0) return 0;
   double ath = 0;
   for(int i = 0; i < copied; i++)
      ath = MathMax(ath, rates[i].high);
   return ath;
}

//+------------------------------------------------------------------+
//| Single-trade Sharpe estimate                                      |
//+------------------------------------------------------------------+
double SingleSharpe(double prob, double reward, double risk)
{
   if(prob <= 0 || prob >= 1 || risk <= 0 || reward <= 0) return 0;
   double eR   = prob * reward - (1 - prob) * risk;
   double stdR = MathSqrt(prob * (1 - prob)) * (reward + risk);
   return stdR > 0 ? eR / stdR : 0;
}

//+------------------------------------------------------------------+
//| Build and log a detailed signal card to Experts log              |
//+------------------------------------------------------------------+
void LogSignalCard(
   string signalType, string direction, string sym,
   double entry,      double sl,        double tp,
   double esPDH,      double esPDL,
   double vixPDH,     double vixPDL,
   double vixPrice,   double vixDailyPct, double vixDailyPts,
   double ath,        double pctFromATH,
   double prob,       double lot,
   double riskAmt,    double rewardAmt,
   double rr,         double sharpe,
   int    strength,   string reasons
)
{
   string stars = "";
   for(int i = 0; i < strength; i++) stars += "*";

   string atkWarn = (pctFromATH <= 2.0 && ath > 0)
                    ? "  *** AT/NEAR ATH ZONE — VIX signals less reliable here ***"
                    : StringFormat("  %.1f%% below 2yr ATH (%.2f)", pctFromATH, ath);

   PrintFormat("╔══════════════════════════════════════════════════════════╗");
   PrintFormat("  SIGNAL  %s  [%s]  Strength %s", signalType, direction, stars);
   PrintFormat("──────────────────────────────────────────────────────────");
   PrintFormat("  CONFLUENCE");
   PrintFormat("%s", reasons);
   PrintFormat("──────────────────────────────────────────────────────────");
   PrintFormat("  KEY LEVELS");
   PrintFormat("  %-14s  PDH %.2f   PDL %.2f", sym, esPDH, esPDL);
   PrintFormat("  %-14s  PDH %.2f   PDL %.2f", VIX_Symbol, vixPDH, vixPDL);
   PrintFormat("──────────────────────────────────────────────────────────");
   PrintFormat("  ATH CONFLUENCE:  %s", atkWarn);
   PrintFormat("──────────────────────────────────────────────────────────");
   PrintFormat("  VIX RULE OF 16:  %.2f / 16 = %.2f%%  = +/-%.1f pts/day", vixPrice, vixDailyPct, vixDailyPts);
   PrintFormat("──────────────────────────────────────────────────────────");
   PrintFormat("  TRADE PARAMETERS");
   PrintFormat("  Entry       %.2f", entry);
   PrintFormat("  Stop Loss   %.2f  (%g pts)", sl, StopLossPts);
   PrintFormat("  Take Profit %.2f  (VIX Rule of 16)", tp);
   PrintFormat("──────────────────────────────────────────────────────────");
   PrintFormat("  KELLY POSITION SIZING");
   PrintFormat("  Win Prob    %.0f%%", prob * 100);
   PrintFormat("  R:R         1:%.2f", rr);
   PrintFormat("  Lot         %.2f", lot);
   PrintFormat("  Risk $      $%.2f  (%.4f%% of balance)", riskAmt, riskAmt / AccountInfoDouble(ACCOUNT_BALANCE) * 100);
   PrintFormat("  Reward $    $%.2f", rewardAmt);
   PrintFormat("  Sharpe      %.3f  (single-trade)", sharpe);
   PrintFormat("╚══════════════════════════════════════════════════════════╝");
}

//+------------------------------------------------------------------+
//| Place trade after optional manual confirm                         |
//+------------------------------------------------------------------+
bool PlaceTrade(
   string sym, ENUM_ORDER_TYPE orderType,
   double lot, double sl, double tp,
   string comment
)
{
   if(lot <= 0)
   {
      Print("Kelly returned 0 lot — negative EV, trade skipped.");
      return false;
   }

   if(ManualConfirm && !MQLInfoInteger(MQL_TESTER))
   {
      string msg = StringFormat(
         "Confirm %s  %s\nLot: %.2f  SL: %.2f  TP: %.2f\n\nProceed?",
         (orderType == ORDER_TYPE_BUY ? "BUY" : "SELL"), sym, lot, sl, tp
      );
      int choice = MessageBox(msg, "VIX EA — Trade Confirmation", MB_YESNO | MB_ICONQUESTION);
      if(choice != IDYES)
      {
         Print("Trade declined by trader.");
         return false;
      }
   }

   bool result;
   if(orderType == ORDER_TYPE_BUY)
      result = Trade.Buy(lot, sym, 0, sl, tp, comment);
   else
      result = Trade.Sell(lot, sym, 0, sl, tp, comment);

   if(!result)
      PrintFormat("Order failed: %d  %s", Trade.ResultRetcode(), Trade.ResultRetcodeDescription());

   return result;
}

//+------------------------------------------------------------------+
//| Check if a position already open for this EA on this symbol      |
//+------------------------------------------------------------------+
bool HasOpenPosition(string sym)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) == sym && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Main EA tick logic                                                |
//+------------------------------------------------------------------+
void OnTick()
{
   // Only evaluate once per completed bar on the analysis timeframe
   datetime barTime = iTime(ES_Symbol, Timeframe, 0);
   if(barTime == g_lastBarTime) return;
   g_lastBarTime = barTime;

   // Skip if already in a position
   if(HasOpenPosition(ES_Symbol)) return;

   // ── Fetch previous day levels ────────────────────────────────────
   double esPDH, esPDL, esPDC;
   double nqPDH, nqPDL, nqPDC;
   double vixPDH, vixPDL, vixPDC;

   if(!GetPrevDayLevels(ES_Symbol,  esPDH,  esPDL,  esPDC))  return;
   if(!GetPrevDayLevels(NQ_Symbol,  nqPDH,  nqPDL,  nqPDC))  return;
   if(!GetPrevDayLevels(VIX_Symbol, vixPDH, vixPDL, vixPDC)) return;

   // ── Current prices ───────────────────────────────────────────────
   double esPrice  = (SymbolInfoDouble(ES_Symbol,  SYMBOL_BID) + SymbolInfoDouble(ES_Symbol,  SYMBOL_ASK)) / 2;
   double nqPrice  = (SymbolInfoDouble(NQ_Symbol,  SYMBOL_BID) + SymbolInfoDouble(NQ_Symbol,  SYMBOL_ASK)) / 2;
   double vixPrice = (SymbolInfoDouble(VIX_Symbol, SYMBOL_BID) + SymbolInfoDouble(VIX_Symbol, SYMBOL_ASK)) / 2;

   double esPct    = PctChange(esPrice,  esPDC);
   double vixPct   = PctChange(vixPrice, vixPDC);

   // ── VIX conditions ───────────────────────────────────────────────
   bool vixStrong    = vixPrice >= vixPDH;   // VIX at/above PDH → pressure confirmed
   bool vixWeak      = vixPrice <= vixPDL;   // VIX at/below PDL → pressure removed
   bool vixLowerHigh = vixPrice <  vixPDH;   // VIX below PDH → no confirmation

   // ── VIX Rule of 16 ───────────────────────────────────────────────
   double vixDailyPct = vixPrice / 16.0;
   double vixDailyPts = VixDailyPoints(vixPrice, esPrice);

   // ── ATH confluence ───────────────────────────────────────────────
   double ath        = GetATH(ES_Symbol);
   double pctFromATH = (ath > 0) ? MathMax(0, (ath - esPrice) / ath * 100.0) : 0;
   bool   atATH      = (pctFromATH <= 2.0 && ath > 0);

   // ── Signal evaluation ────────────────────────────────────────────
   string signalType = "";
   string direction  = "";
   string reasons    = "";
   int    strength   = 0;
   double prob       = 0;
   bool   goLong     = false;
   bool   goShort    = false;

   // RULE 1: CONFIRMED BREAKDOWN
   if(esPrice < esPDL && vixStrong)
   {
      signalType = "CONFIRMED BREAKDOWN";
      direction  = "SHORT " + ES_Symbol;
      reasons    = StringFormat("  > %s (%.2f) broke below PDL (%.2f)\n", ES_Symbol, esPrice, esPDL);
      reasons   += StringFormat("  > %s (%.2f) at/above PDH (%.2f) — put demand confirmed\n", VIX_Symbol, vixPrice, vixPDH);
      if(nqPrice < nqPDL)
      {
         reasons  += StringFormat("  > %s (%.2f) also below PDL (%.2f) — triple confirmation\n", NQ_Symbol, nqPrice, nqPDL);
         strength  = 3; prob = 0.70;
      }
      else
      {
         reasons  += StringFormat("  > %s (%.2f) holding above PDL (%.2f)\n", NQ_Symbol, nqPrice, nqPDL);
         strength  = 2; prob = 0.62;
      }
      if(atATH)
      {
         reasons += StringFormat("  *** ATH ZONE (%.1f%% from ATH) — VIX breakdown may reflect routine hedging\n", pctFromATH);
         prob    -= 0.08;   // reduce confidence at ATH
      }
      goShort = true;
   }

   // RULE 2: FAKE BREAKDOWN
   else if(esPrice < esPDL && vixLowerHigh && nqPrice >= nqPDL)
   {
      signalType = "FAKE BREAKDOWN (Bear Trap)";
      direction  = "LONG " + ES_Symbol;
      reasons    = StringFormat("  > %s (%.2f) broke below PDL (%.2f)\n", ES_Symbol, esPrice, esPDL);
      reasons   += StringFormat("  > %s (%.2f) NOT at PDH (%.2f) — no put demand confirmation\n", VIX_Symbol, vixPrice, vixPDH);
      reasons   += StringFormat("  > %s (%.2f) holding above PDL (%.2f) — relative strength\n", NQ_Symbol, nqPrice, nqPDL);
      reasons   += "  > Bear trap likely — expect snap-back above PDL\n";
      strength   = 2; prob = 0.65;
      goLong     = true;
   }

   // RULE 3: CONFIRMED BREAKOUT
   else if(esPrice > esPDH && vixWeak)
   {
      signalType = "CONFIRMED BREAKOUT";
      direction  = "LONG " + ES_Symbol;
      reasons    = StringFormat("  > %s (%.2f) broke above PDH (%.2f)\n", ES_Symbol, esPrice, esPDH);
      reasons   += StringFormat("  > %s (%.2f) at/below PDL (%.2f) — put demand removed\n", VIX_Symbol, vixPrice, vixPDL);
      if(nqPrice > nqPDH)
      {
         reasons  += StringFormat("  > %s (%.2f) also above PDH (%.2f) — triple confirmation\n", NQ_Symbol, nqPrice, nqPDH);
         strength  = 3; prob = 0.70;
      }
      else
      {
         reasons  += StringFormat("  > %s (%.2f) not yet above PDH (%.2f)\n", NQ_Symbol, nqPrice, nqPDH);
         strength  = 2; prob = 0.62;
      }
      goLong = true;
   }

   // RULE 4: FAKE BREAKOUT
   else if(esPrice > esPDH && vixStrong && nqPrice <= nqPDH)
   {
      signalType = "FAKE BREAKOUT (Bull Trap)";
      direction  = "SHORT " + ES_Symbol;
      reasons    = StringFormat("  > %s (%.2f) broke above PDH (%.2f)\n", ES_Symbol, esPrice, esPDH);
      reasons   += StringFormat("  > %s (%.2f) still at/above PDH (%.2f) — put demand persists\n", VIX_Symbol, vixPrice, vixPDH);
      reasons   += StringFormat("  > %s (%.2f) not confirming above PDH (%.2f)\n", NQ_Symbol, nqPrice, nqPDH);
      reasons   += "  > Bull trap likely — rally may fail under pressure\n";
      strength   = 2; prob = 0.65;
      goShort    = true;
   }

   // RULE 5: VIX LEADING BEARISH (alert only)
   else if(vixStrong && esPrice >= esPDL)
   {
      signalType = "VIX LEADING BEARISH (Alert)";
      direction  = "WATCH — no trade yet";
      reasons    = StringFormat("  > %s (%.2f) at/above PDH (%.2f) — pressure building\n", VIX_Symbol, vixPrice, vixPDH);
      reasons   += StringFormat("  > %s (%.2f) has NOT yet broken PDL (%.2f)\n", ES_Symbol, esPrice, esPDL);
      reasons   += "  > VIX leading: watch for ES breakdown entry\n";
      strength   = 1; prob = 0.55;
   }

   // RULE 6: VIX LEADING BULLISH (alert only)
   else if(vixWeak && esPrice <= esPDH)
   {
      signalType = "VIX LEADING BULLISH (Alert)";
      direction  = "WATCH — no trade yet";
      reasons    = StringFormat("  > %s (%.2f) at/below PDL (%.2f) — pressure easing\n", VIX_Symbol, vixPrice, vixPDL);
      reasons   += StringFormat("  > %s (%.2f) has NOT yet broken PDH (%.2f)\n", ES_Symbol, esPrice, esPDH);
      reasons   += "  > VIX leading bullish: watch for ES breakout entry\n";
      strength   = 1; prob = 0.55;
   }

   // RULE 7: 1% DIVERGENCE RULE (alert only)
   else if(esPct >= 1.0 && vixPct >= 1.0)
   {
      signalType = "1% RULE — FRAGILE RALLY";
      direction  = "CAUTION — avoid chasing longs";
      reasons    = StringFormat("  > %s +%.2f%% AND %s +%.2f%% — pressure rising with price\n", ES_Symbol, esPct, VIX_Symbol, vixPct);
      reasons   += "  > Rally is fragile — resistance more likely to hold\n";
      strength   = 1; prob = 0.50;
   }
   else if(esPct <= -1.0 && vixPct <= -1.0)
   {
      signalType = "1% RULE — FRAGILE SELLOFF";
      direction  = "CAUTION — avoid chasing shorts";
      reasons    = StringFormat("  > %s %.2f%% AND %s %.2f%% — pressure falling with price\n", ES_Symbol, esPct, VIX_Symbol, vixPct);
      reasons   += "  > Selloff is fragile — support more likely to hold\n";
      strength   = 1; prob = 0.50;
   }

   // No signal
   if(signalType == "") return;

   // Prevent re-logging the same signal bar after bar
   string signalKey = signalType + TimeToString(barTime);
   if(signalKey == g_lastSignal) return;
   g_lastSignal = signalKey;

   // ── Calculate trade levels ────────────────────────────────────────
   double pt      = SymbolInfoDouble(ES_Symbol, SYMBOL_POINT);
   double rr      = (strength == 3) ? 3.0 : (strength == 2) ? 2.0 : 1.5;
   double tpPts   = RealisticTP(vixDailyPts, StopLossPts, strength);
   double actualRR = (StopLossPts > 0) ? tpPts / StopLossPts : rr;

   double lot     = CalcLot(ES_Symbol, StopLossPts, prob, actualRR);
   double slPrice, tpPrice;

   if(goLong)
   {
      slPrice = esPrice - StopLossPts * pt;
      tpPrice = esPrice + tpPts       * pt;
   }
   else
   {
      slPrice = esPrice + StopLossPts * pt;
      tpPrice = esPrice - tpPts       * pt;
   }

   double tickValue  = SymbolInfoDouble(ES_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize   = SymbolInfoDouble(ES_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double riskAmt    = (tickSize > 0) ? lot * (StopLossPts / tickSize) * tickValue : 0;
   double rewardAmt  = riskAmt * actualRR;
   double sharpe     = SingleSharpe(prob, rewardAmt, riskAmt);

   // ── Log signal card ───────────────────────────────────────────────
   LogSignalCard(
      signalType, direction, ES_Symbol,
      esPrice, slPrice, tpPrice,
      esPDH, esPDL, vixPDH, vixPDL,
      vixPrice, vixDailyPct, vixDailyPts,
      ath, pctFromATH,
      prob, lot, riskAmt, rewardAmt,
      actualRR, sharpe, strength, reasons
   );

   // ── Execute trade ─────────────────────────────────────────────────
   string comment = StringFormat("VIX-EA|%s|S%d", signalType, strength);

   if(goLong && AllowLongs)
      PlaceTrade(ES_Symbol, ORDER_TYPE_BUY,  lot, slPrice, tpPrice, comment);
   else if(goShort && AllowShorts)
      PlaceTrade(ES_Symbol, ORDER_TYPE_SELL, lot, slPrice, tpPrice, comment);
}

//+------------------------------------------------------------------+
//| Chart comment — live dashboard                                    |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam,
                  const double &dparam, const string &sparam)
{
   // Reserved for future dashboard overlay
}

void OnDeinit(const int reason)
{
   Comment("");
   Print("VIX Futures EA removed. Reason: ", reason);
}
//+------------------------------------------------------------------+
