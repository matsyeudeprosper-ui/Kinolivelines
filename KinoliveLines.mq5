//+------------------------------------------------------------------+
//|                                                 KinoliveLines.mq5 |
//|   The S/R "hlines" engine, extracted standalone from              |
//|   KinoliveTrader and turned into a measuring instrument.          |
//|                                                                   |
//|   WHAT IT DOES                                                    |
//|   1. Rebuilds KinoliveTrader's level detector verbatim in         |
//|      behaviour: previous-candle high/low on three timeframes ->   |
//|      ATR-based merge -> same-type minimum spacing -> up to six    |
//|      horizontal lines drawn on the chart.                         |
//|   2. Journals every touch of those lines, then measures what      |
//|      price ACTUALLY did for N bars afterwards - MFE and MAE in    |
//|      price, in ATR, and in spread multiples.                      |
//|   3. Journals YOUR manual trades with the level context at the    |
//|      moment of each fill, so a discretionary decision can be      |
//|      matched against the line that (maybe) motivated it.          |
//|                                                                   |
//|   WHAT IT DELIBERATELY DOES NOT DO                                |
//|   It never sends an order. There is no entry logic, no TP, no     |
//|   basket, no risk engine. KinoliveTrader's ExtremeTracker /       |
//|   ExtremeEntry layer is intentionally left behind: the point is   |
//|   to find out whether these lines carry an edge at all before     |
//|   any strategy is built on top of them.                           |
//|                                                                   |
//|   Both CSVs are written to the terminal's COMMON files folder:    |
//|     ...\MetaQuotes\Terminal\Common\Files\                         |
//+------------------------------------------------------------------+
#property copyright "Kinolive"
#property version   "1.00"
#property description "Standalone S/R hline engine + touch/trade journal. Never trades."

//==================== INPUTS ====================
input group "--- Level detection (mirrors KinoliveTrader) ---"
input ENUM_TIMEFRAMES InpTF_High           = PERIOD_H4;   // High TF (thick line, top priority)
input ENUM_TIMEFRAMES InpTF_Mid            = PERIOD_H1;   // Mid TF (also drives the merge ATR)
input ENUM_TIMEFRAMES InpTF_Low            = PERIOD_M15;  // Low TF (thin line, lowest priority)
input ENUM_TIMEFRAMES InpSignalTF          = PERIOD_M1;   // Timeframe touches are evaluated on
input double          InpATRMergeMult      = 0.12;        // Merge tolerance = max(3*spread, this * ATR)
input double          InpMinSpacingPercent = 0.10;        // Min gap between SAME-type levels, % of price
input double          InpMaxLevelDistPct   = 10.0;        // Ignore levels further than this % from price
input int             InpMaxLevels         = 6;           // Max levels kept (hard ceiling 6)

input group "--- Touch journal ---"
input bool            InpLogTouches        = true;        // Record every level touch to CSV
input int             InpOutcomeBars       = 60;          // Bars of InpSignalTF to measure after a touch
input bool            InpStableTouchesOnly = false;       // Only journal touches of levels that persisted a bar

input group "--- Your-trade journal ---"
input bool            InpLogMyTrades       = true;        // Record every fill on this symbol, any magic

input group "--- Display ---"
input bool            InpShowPanel         = true;        // Draw the status panel
input bool            InpGreyTouched       = true;        // Grey a level out once touched
input color           InpColorSupport      = clrLimeGreen;
input color           InpColorResist       = clrRed;
input color           InpColorTouched      = clrDimGray;
input int             InpPanelX            = 12;
input int             InpPanelY            = 22;

input group "--- Diagnostics ---"
input bool            InpDebug             = false;       // Verbose Print() of detector decisions

//==================== CONSTANTS ====================
#define KL_MAX_LEVELS   6
#define KL_MAX_OBS      64
#define KL_PREFIX       "KL_"
#define KL_LINE_PREFIX  "KL_LVL_"
#define KL_PANEL_PREFIX "KL_PANEL_"

//==================== TYPES ====================
// firstSeenBarTime: the M1 bar at which this price (within tolerance, same
// type) was FIRST produced by CollectLevels() in the current unbroken streak.
// A level built from a candle that only just closed is trivially "touched" by
// that same candle's own extreme, so anything reading a touch as meaningful
// needs to know the line existed before the touch. That is IsLevelStable().
struct KLLevel
{
   double   price;
   bool     isHigh;          // true = resistance, false = support
   string   tf;              // "H4" / "H1" / "M15" (label of the source TF)
   int      priority;        // higher TF wins a merge
   datetime firstSeenBarTime;
   bool     touched;         // has been touched at least once since it appeared
   bool     prevBarTouched;  // was inside the previous signal bar's range
   datetime firedBarTime;    // last signal bar on which a touch EVENT was emitted
};

// One pending measurement per touch: opened when a touch fires, closed and
// written to CSV once InpOutcomeBars bars of InpSignalTF have elapsed.
struct KLTouchObs
{
   bool     active;
   datetime touchTime;
   double   level;
   bool     isHigh;
   string   tf;
   bool     stable;
   double   midAtTouch;
   double   atrSignal;
   double   atrMerge;
   double   spreadAvg;
   int      barsElapsed;
   int      barsToMFE;
   double   mfe;             // best excursion in the BOUNCE direction
   double   mae;             // worst excursion THROUGH the level
   double   closeAtHorizon;
};

//==================== STATE ====================
KLLevel     g_lv[KL_MAX_LEVELS];
int         g_lvCount = 0;

KLTouchObs  g_obs[KL_MAX_OBS];

int         g_atrMergeHandle  = INVALID_HANDLE;
int         g_atrSignalHandle = INVALID_HANDLE;

double      g_spreadEMA       = 0.0;
datetime    g_lastLevelBar    = 0;   // M1 bar of the last detector run
datetime    g_lastSignalBar   = 0;   // last signal-TF bar seen

string      g_touchCsv;
string      g_tradeCsv;

int         g_touchesLogged   = 0;
int         g_tradesLogged    = 0;

//==================== HELPERS ====================
int KLMaxLevels()
{
   int n = InpMaxLevels;
   if(n < 1)             n = 1;
   if(n > KL_MAX_LEVELS) n = KL_MAX_LEVELS;
   return n;
}

double KLPoint() { return SymbolInfoDouble(_Symbol, SYMBOL_POINT); }

double KLMid()
{
   return (SymbolInfoDouble(_Symbol, SYMBOL_BID) + SymbolInfoDouble(_Symbol, SYMBOL_ASK)) / 2.0;
}

double KLSpreadNow()
{
   double s = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(s <= 0) s = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) * KLPoint();
   return s;
}

double KLATR(int handle, int shift = 1)
{
   if(handle == INVALID_HANDLE) return 0.0;
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, shift, 1, buf) <= 0) return 0.0;
   return buf[0];
}

string KLTFName(ENUM_TIMEFRAMES tf) { return StringSubstr(EnumToString(tf), 7); }

// Divide only when the denominator is a real, positive scale.
double KLSafeDiv(double num, double den) { return (den > 0.0) ? num / den : 0.0; }

//==================== LEVEL DETECTOR ====================
// Faithful port of GridLevels.mqh::CollectGridLevels(). Same six raw
// candidates, same merge rule, same same-type-only spacing filter, same
// persistence carry-over - only the TFs and constants are inputs now.
void CollectLevels()
{
   // Snapshot the outgoing set BEFORE it is overwritten, so a level that
   // survives this recompute keeps its age and its touched flag instead of
   // the clock resetting every bar.
   KLLevel prev[KL_MAX_LEVELS];
   int prevCount = g_lvCount;
   for(int i = 0; i < prevCount && i < KL_MAX_LEVELS; i++) prev[i] = g_lv[i];

   // --- Step 1: raw candidates - previous closed candle's high and low ---
   struct RawLevel { double price; bool isHigh; int priority; string tfName; };
   RawLevel raw[KL_MAX_LEVELS];
   int rawCount = 0;

   ENUM_TIMEFRAMES tfs[3];
   tfs[0] = InpTF_High;  tfs[1] = InpTF_Mid;  tfs[2] = InpTF_Low;
   int prios[3];
   prios[0] = 3;         prios[1] = 2;        prios[2] = 1;

   for(int t = 0; t < 3; t++)
   {
      double hi = iHigh(_Symbol, tfs[t], 1);
      double lo = iLow (_Symbol, tfs[t], 1);
      string nm = KLTFName(tfs[t]);

      if(hi > 0 && rawCount < KL_MAX_LEVELS)
      {
         raw[rawCount].price    = hi;
         raw[rawCount].isHigh   = true;
         raw[rawCount].priority = prios[t];
         raw[rawCount].tfName   = nm;
         rawCount++;
      }
      if(lo > 0 && rawCount < KL_MAX_LEVELS)
      {
         raw[rawCount].price    = lo;
         raw[rawCount].isHigh   = false;
         raw[rawCount].priority = prios[t];
         raw[rawCount].tfName   = nm;
         rawCount++;
      }
   }

   if(rawCount == 0) { g_lvCount = 0; return; }

   // --- Step 2: sort ascending by price ---
   for(int i = 0; i < rawCount - 1; i++)
      for(int j = i + 1; j < rawCount; j++)
         if(raw[i].price > raw[j].price)
         {
            RawLevel tmp = raw[i]; raw[i] = raw[j]; raw[j] = tmp;
         }

   // --- Step 3: merge tolerance ---
   double spread = KLSpreadNow();
   double atrMid = KLATR(g_atrMergeHandle, 1);
   if(atrMid <= 0) atrMid = spread * 10.0;
   double mergeTol = MathMax(spread * 3.0, atrMid * InpATRMergeMult);
   if(mergeTol < spread * 0.5) mergeTol = spread * 0.5;

   // --- Step 4: merge close levels, higher timeframe wins ---
   bool keep[KL_MAX_LEVELS];
   for(int i = 0; i < KL_MAX_LEVELS; i++) keep[i] = true;
   for(int i = 0; i < rawCount; i++)
   {
      if(!keep[i]) continue;
      for(int j = i + 1; j < rawCount; j++)
      {
         if(!keep[j]) continue;
         if(MathAbs(raw[i].price - raw[j].price) <= mergeTol)
         {
            if(raw[j].priority > raw[i].priority) raw[i] = raw[j];
            keep[j] = false;
         }
      }
   }

   RawLevel merged[KL_MAX_LEVELS];
   int mergedCount = 0;
   for(int i = 0; i < rawCount; i++)
      if(keep[i]) merged[mergedCount++] = raw[i];

   // --- Step 5: minimum spacing, SAME TYPE ONLY ---
   // Support and resistance are allowed to sit on top of each other; two
   // supports crammed together are the same level counted twice.
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double minDistance = bid * (InpMinSpacingPercent / 100.0);
   if(minDistance <= 0) minDistance = 10 * KLPoint();

   RawLevel filtered[KL_MAX_LEVELS];
   int filteredCount = 0;
   int cap = KLMaxLevels();
   for(int i = 0; i < mergedCount; i++)
   {
      if(filteredCount == 0)
      {
         filtered[filteredCount++] = merged[i];
         continue;
      }
      double dist  = MathAbs(merged[i].price - filtered[filteredCount - 1].price);
      bool sameType = (merged[i].isHigh == filtered[filteredCount - 1].isHigh);

      if(!sameType || dist >= minDistance)
         filtered[filteredCount++] = merged[i];
      else if(InpDebug)
         Print("KL: skipping ", DoubleToString(merged[i].price, _Digits),
               " (same-type level too close, gap ", DoubleToString(dist, _Digits),
               " < ", DoubleToString(minDistance, _Digits), ")");

      if(filteredCount >= cap) break;
   }

   // --- Step 6: store, carrying persistence and touched state forward ---
   double   persistTol = 2 * KLPoint();
   datetime curM1Bar   = iTime(_Symbol, PERIOD_M1, 0);

   g_lvCount = filteredCount;
   for(int i = 0; i < filteredCount; i++)
   {
      g_lv[i].price    = filtered[i].price;
      g_lv[i].isHigh   = filtered[i].isHigh;
      g_lv[i].tf       = filtered[i].tfName;
      g_lv[i].priority = filtered[i].priority;

      datetime seenTime       = curM1Bar;
      bool     carriedTouched = false;
      bool     carriedPrev    = false;
      datetime carriedFired   = 0;

      for(int p = 0; p < prevCount && p < KL_MAX_LEVELS; p++)
      {
         if(prev[p].isHigh == filtered[i].isHigh &&
            MathAbs(prev[p].price - filtered[i].price) <= persistTol)
         {
            seenTime       = (prev[p].firstSeenBarTime > 0) ? prev[p].firstSeenBarTime : curM1Bar;
            carriedTouched = prev[p].touched;
            carriedPrev    = prev[p].prevBarTouched;
            carriedFired   = prev[p].firedBarTime;
            break;
         }
      }

      g_lv[i].firstSeenBarTime = seenTime;
      g_lv[i].touched          = carriedTouched;
      g_lv[i].prevBarTouched   = carriedPrev;
      g_lv[i].firedBarTime     = carriedFired;
   }
}

bool IsLevelStable(int idx)
{
   if(idx < 0 || idx >= g_lvCount) return false;
   datetime firstSeen = g_lv[idx].firstSeenBarTime;
   if(firstSeen <= 0) return false;
   return (firstSeen < iTime(_Symbol, PERIOD_M1, 0));
}

bool IsLevelTooFar(double level)
{
   double mid = KLMid();
   if(mid <= 0) return true;
   return (MathAbs(level - mid) / mid * 100.0 > InpMaxLevelDistPct);
}

//==================== VISUALS ====================
void DrawHLine(string name, double price, color clr, int style, int width, string tooltip)
{
   if(ObjectFind(0, name) >= 0)
   {
      ObjectSetDouble (0, name, OBJPROP_PRICE, price);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_STYLE, style);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   }
   else
   {
      ObjectCreate    (0, name, OBJ_HLINE, 0, 0, price);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_STYLE, style);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   if(tooltip != "") ObjectSetString(0, name, OBJPROP_TOOLTIP, tooltip);
}

int LineWidthForTF(string tf)
{
   if(tf == KLTFName(InpTF_High)) return 4;
   if(tf == KLTFName(InpTF_Mid))  return 2;
   return 1;
}

void DrawLevels()
{
   for(int i = 0; i < g_lvCount; i++)
   {
      string name = KL_LINE_PREFIX + IntegerToString(i);
      bool   grey = (InpGreyTouched && g_lv[i].touched);
      color  clr  = grey ? InpColorTouched : (g_lv[i].isHigh ? InpColorResist : InpColorSupport);
      int    w    = grey ? 1 : LineWidthForTF(g_lv[i].tf);

      string tip = StringFormat("%s %s | %s | age %s | %s",
                                g_lv[i].tf,
                                g_lv[i].isHigh ? "Resistance" : "Support",
                                DoubleToString(g_lv[i].price, _Digits),
                                IsLevelStable(i) ? "stable" : "NEW this bar",
                                g_lv[i].touched ? "touched" : "untouched");

      DrawHLine(name, g_lv[i].price, clr, STYLE_SOLID, w, tip);
   }

   // Drop lines for slots the detector no longer fills.
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
      string n = ObjectName(0, i);
      if(StringFind(n, KL_LINE_PREFIX) != 0) continue;
      int idx = (int)StringToInteger(StringSubstr(n, StringLen(KL_LINE_PREFIX)));
      if(idx >= g_lvCount) ObjectDelete(0, n);
   }
}

void PanelLabel(int row, string text, color clr)
{
   string name = KL_PANEL_PREFIX + IntegerToString(row);
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate    (0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, InpPanelX);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, InpPanelY + row * 14);
      ObjectSetString (0, name, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   ObjectSetString (0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
}

void DrawPanel()
{
   if(!InpShowPanel) return;

   double mid    = KLMid();
   double atrSig = KLATR(g_atrSignalHandle, 1);
   int    row    = 0;

   PanelLabel(row++, "KinoliveLines  " + _Symbol + "  (observation only - never trades)", clrWhite);
   PanelLabel(row++, StringFormat("spread avg %.*f  |  ATR(%s) %.*f  |  levels %d",
                                  _Digits, g_spreadEMA, KLTFName(InpSignalTF), _Digits, atrSig, g_lvCount),
              clrSilver);

   for(int i = 0; i < g_lvCount; i++)
   {
      double distPrice = g_lv[i].price - mid;
      double distSpr   = KLSafeDiv(MathAbs(distPrice), g_spreadEMA);
      color  clr       = g_lv[i].touched ? InpColorTouched
                                         : (g_lv[i].isHigh ? InpColorResist : InpColorSupport);

      PanelLabel(row++, StringFormat("%-4s %-10s %s  %+.*f (%.1fx spread) %s%s",
                                     g_lv[i].tf,
                                     g_lv[i].isHigh ? "RESIST" : "SUPPORT",
                                     DoubleToString(g_lv[i].price, _Digits),
                                     _Digits, distPrice,
                                     distSpr,
                                     IsLevelStable(i) ? "" : "[new] ",
                                     g_lv[i].touched ? "[touched]" : ""),
                 clr);
   }

   int pending = 0;
   for(int i = 0; i < KL_MAX_OBS; i++) if(g_obs[i].active) pending++;

   PanelLabel(row++, StringFormat("journal: %d touches written, %d measuring, %d fills",
                                  g_touchesLogged, pending, g_tradesLogged), clrSilver);

   // Clear leftover rows from a previously longer panel.
   for(int r = row; r < row + KL_MAX_LEVELS + 4; r++)
   {
      string name = KL_PANEL_PREFIX + IntegerToString(r);
      if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   }
}

void DeleteAllObjects()
{
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
      string n = ObjectName(0, i);
      if(StringFind(n, KL_PREFIX) == 0) ObjectDelete(0, n);
   }
}

//==================== CSV ====================
void CsvAppend(string file, string header, string row)
{
   int h = FileOpen(file, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      Print("KL: cannot open ", file, " err=", GetLastError());
      return;
   }
   if(FileSize(h) == 0) FileWriteString(h, header + "\r\n");
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, row + "\r\n");
   FileClose(h);
}

string TouchCsvHeader()
{
   return "touch_time,level,type,tf,stable,mid_at_touch,atr_signal,atr_merge,spread_avg,"
          "horizon_bars,bars_to_mfe,mfe_price,mae_price,mfe_atr,mae_atr,mfe_spread,mae_spread,"
          "close_at_horizon,net_move_price,net_move_atr";
}

string TradeCsvHeader()
{
   return "time,deal,position,magic,type,entry,volume,price,sl,tp,profit,comment,"
          "nearest_level,nearest_type,nearest_tf,dist_price,dist_atr,dist_spread,"
          "level_count,atr_signal,spread_avg";
}

//==================== TOUCH OBSERVATIONS ====================
void OpenObservation(int levelIdx)
{
   int slot = -1;
   for(int i = 0; i < KL_MAX_OBS; i++)
      if(!g_obs[i].active) { slot = i; break; }
   if(slot < 0)
   {
      if(InpDebug) Print("KL: observation buffer full, touch not measured");
      return;
   }

   g_obs[slot].active         = true;
   g_obs[slot].touchTime      = TimeCurrent();
   g_obs[slot].level          = g_lv[levelIdx].price;
   g_obs[slot].isHigh         = g_lv[levelIdx].isHigh;
   g_obs[slot].tf             = g_lv[levelIdx].tf;
   g_obs[slot].stable         = IsLevelStable(levelIdx);
   g_obs[slot].midAtTouch     = KLMid();
   g_obs[slot].atrSignal      = KLATR(g_atrSignalHandle, 1);
   g_obs[slot].atrMerge       = KLATR(g_atrMergeHandle, 1);
   g_obs[slot].spreadAvg      = g_spreadEMA;
   g_obs[slot].barsElapsed    = 0;
   g_obs[slot].barsToMFE      = 0;
   g_obs[slot].mfe            = 0.0;
   g_obs[slot].mae            = 0.0;
   g_obs[slot].closeAtHorizon = 0.0;
}

void CloseObservation(int slot)
{
   double atr = g_obs[slot].atrSignal;
   double spr = g_obs[slot].spreadAvg;

   // Net move measured in the bounce direction: up off a support, down off a
   // resistance. A negative net move means the level did not hold.
   double net = g_obs[slot].isHigh
                ? (g_obs[slot].midAtTouch - g_obs[slot].closeAtHorizon)
                : (g_obs[slot].closeAtHorizon - g_obs[slot].midAtTouch);

   string row = StringFormat(
      "%s,%.*f,%s,%s,%s,%.*f,%.*f,%.*f,%.*f,%d,%d,%.*f,%.*f,%.3f,%.3f,%.2f,%.2f,%.*f,%.*f,%.3f",
      TimeToString(g_obs[slot].touchTime, TIME_DATE | TIME_SECONDS),
      _Digits, g_obs[slot].level,
      g_obs[slot].isHigh ? "RESISTANCE" : "SUPPORT",
      g_obs[slot].tf,
      g_obs[slot].stable ? "stable" : "new",
      _Digits, g_obs[slot].midAtTouch,
      _Digits, atr,
      _Digits, g_obs[slot].atrMerge,
      _Digits, spr,
      g_obs[slot].barsElapsed,
      g_obs[slot].barsToMFE,
      _Digits, g_obs[slot].mfe,
      _Digits, g_obs[slot].mae,
      KLSafeDiv(g_obs[slot].mfe, atr),
      KLSafeDiv(g_obs[slot].mae, atr),
      KLSafeDiv(g_obs[slot].mfe, spr),
      KLSafeDiv(g_obs[slot].mae, spr),
      _Digits, g_obs[slot].closeAtHorizon,
      _Digits, net,
      KLSafeDiv(net, atr));

   CsvAppend(g_touchCsv, TouchCsvHeader(), row);
   g_touchesLogged++;
   g_obs[slot].active = false;

   if(InpDebug)
      Print("KL: touch closed ", g_obs[slot].isHigh ? "RESIST " : "SUPPORT ",
            DoubleToString(g_obs[slot].level, _Digits),
            "  MFE ", DoubleToString(KLSafeDiv(g_obs[slot].mfe, spr), 1), "x spread",
            "  MAE ", DoubleToString(KLSafeDiv(g_obs[slot].mae, spr), 1), "x spread");
}

// Called once per completed signal-TF bar, with that bar's OHLC.
void UpdateObservations(double barHigh, double barLow, double barClose)
{
   for(int i = 0; i < KL_MAX_OBS; i++)
   {
      if(!g_obs[i].active) continue;

      double fav, adv;
      if(g_obs[i].isHigh)   // resistance -> the bounce is DOWN
      {
         fav = g_obs[i].midAtTouch - barLow;
         adv = barHigh - g_obs[i].midAtTouch;
      }
      else                  // support -> the bounce is UP
      {
         fav = barHigh - g_obs[i].midAtTouch;
         adv = g_obs[i].midAtTouch - barLow;
      }

      g_obs[i].barsElapsed++;
      if(fav > g_obs[i].mfe) { g_obs[i].mfe = fav; g_obs[i].barsToMFE = g_obs[i].barsElapsed; }
      if(adv > g_obs[i].mae) g_obs[i].mae = adv;
      g_obs[i].closeAtHorizon = barClose;

      if(g_obs[i].barsElapsed >= InpOutcomeBars) CloseObservation(i);
   }
}

//==================== TOUCH DETECTION ====================
// Presence-based, exactly as in TouchDetection.mqh: a level counts as touched
// when it falls inside the current signal candle's range. A touch EVENT fires
// only on the transition - the previous bar must not have contained it - so a
// level price sits inside for twenty bars still produces one event, not twenty.
void CheckTouches()
{
   if(g_lvCount <= 0) return;

   double curHigh  = iHigh(_Symbol, InpSignalTF, 0);
   double curLow   = iLow (_Symbol, InpSignalTF, 0);
   datetime curBar = iTime(_Symbol, InpSignalTF, 0);

   for(int i = 0; i < g_lvCount; i++)
   {
      double price = g_lv[i].price;
      if(IsLevelTooFar(price)) continue;

      bool inRange = (curLow <= price && curHigh >= price);
      if(!inRange) continue;

      if(!g_lv[i].touched)
      {
         g_lv[i].touched = true;
         Print(StringFormat("KL TOUCH: %s | %s %s | level %s | bar %s | range [%s / %s]",
                            g_lv[i].isHigh ? "RESISTANCE" : "SUPPORT",
                            g_lv[i].tf,
                            IsLevelStable(i) ? "stable" : "NEW-this-bar",
                            DoubleToString(price, _Digits),
                            TimeToString(curBar, TIME_DATE | TIME_MINUTES),
                            DoubleToString(curLow, _Digits),
                            DoubleToString(curHigh, _Digits)));
      }

      // One measured event per level per bar, and only on a fresh entry
      // into the level's price.
      if(g_lv[i].prevBarTouched)       continue;
      if(g_lv[i].firedBarTime == curBar) continue;
      g_lv[i].firedBarTime = curBar;

      if(!InpLogTouches) continue;
      if(InpStableTouchesOnly && !IsLevelStable(i)) continue;

      OpenObservation(i);
   }
}

void RefreshPrevBarTouched()
{
   double prevHigh = iHigh(_Symbol, InpSignalTF, 1);
   double prevLow  = iLow (_Symbol, InpSignalTF, 1);
   for(int i = 0; i < g_lvCount; i++)
      g_lv[i].prevBarTouched = (prevLow <= g_lv[i].price && prevHigh >= g_lv[i].price);
}

//==================== YOUR-TRADE JOURNAL ====================
// Records every fill on this symbol regardless of magic, so manual clicks are
// captured, and stamps each one with the level context at that moment.
void LogDeal(ulong dealTicket)
{
   if(!InpLogMyTrades) return;
   if(!HistoryDealSelect(dealTicket)) return;
   if(HistoryDealGetString(dealTicket, DEAL_SYMBOL) != _Symbol) return;

   ENUM_DEAL_TYPE  dt = (ENUM_DEAL_TYPE) HistoryDealGetInteger(dealTicket, DEAL_TYPE);
   if(dt != DEAL_TYPE_BUY && dt != DEAL_TYPE_SELL) return;

   ENUM_DEAL_ENTRY de = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   double price = HistoryDealGetDouble(dealTicket, DEAL_PRICE);

   // Nearest level to the fill price, in whichever direction.
   double bestDist = 0.0, bestLevel = 0.0;
   string bestType = "none", bestTF = "-";
   for(int i = 0; i < g_lvCount; i++)
   {
      double d = MathAbs(g_lv[i].price - price);
      if(bestLevel == 0.0 || d < bestDist)
      {
         bestDist  = d;
         bestLevel = g_lv[i].price;
         bestType  = g_lv[i].isHigh ? "RESISTANCE" : "SUPPORT";
         bestTF    = g_lv[i].tf;
      }
   }

   double atr = KLATR(g_atrSignalHandle, 1);
   string comment = HistoryDealGetString(dealTicket, DEAL_COMMENT);
   StringReplace(comment, ",", " ");

   string row = StringFormat(
      "%s,%I64u,%I64u,%I64d,%s,%s,%.2f,%.*f,%.*f,%.*f,%.2f,%s,%.*f,%s,%s,%.*f,%.3f,%.2f,%d,%.*f,%.*f",
      TimeToString((datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME), TIME_DATE | TIME_SECONDS),
      dealTicket,
      HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID),
      HistoryDealGetInteger(dealTicket, DEAL_MAGIC),
      (dt == DEAL_TYPE_BUY) ? "BUY" : "SELL",
      EnumToString(de),
      HistoryDealGetDouble(dealTicket, DEAL_VOLUME),
      _Digits, price,
      _Digits, HistoryDealGetDouble(dealTicket, DEAL_SL),
      _Digits, HistoryDealGetDouble(dealTicket, DEAL_TP),
      HistoryDealGetDouble(dealTicket, DEAL_PROFIT),
      comment,
      _Digits, bestLevel,
      bestType,
      bestTF,
      _Digits, bestDist,
      KLSafeDiv(bestDist, atr),
      KLSafeDiv(bestDist, g_spreadEMA),
      g_lvCount,
      _Digits, atr,
      _Digits, g_spreadEMA);

   CsvAppend(g_tradeCsv, TradeCsvHeader(), row);
   g_tradesLogged++;

   Print(StringFormat("KL FILL: %s %s %.2f @ %s | nearest %s %s at %s (%.1fx spread away)",
                      (dt == DEAL_TYPE_BUY) ? "BUY" : "SELL",
                      EnumToString(de),
                      HistoryDealGetDouble(dealTicket, DEAL_VOLUME),
                      DoubleToString(price, _Digits),
                      bestTF, bestType,
                      DoubleToString(bestLevel, _Digits),
                      KLSafeDiv(bestDist, g_spreadEMA)));
}

//==================== LIFECYCLE ====================
int OnInit()
{
   g_atrMergeHandle  = iATR(_Symbol, InpTF_Mid,    14);
   g_atrSignalHandle = iATR(_Symbol, InpSignalTF,  14);
   if(g_atrMergeHandle == INVALID_HANDLE || g_atrSignalHandle == INVALID_HANDLE)
   {
      Print("KL: failed to create ATR handles");
      return INIT_FAILED;
   }

   g_touchCsv = "KinoliveLines_touches_" + _Symbol + ".csv";
   g_tradeCsv = "KinoliveLines_trades_"  + _Symbol + ".csv";

   for(int i = 0; i < KL_MAX_OBS; i++) g_obs[i].active = false;

   g_spreadEMA = KLSpreadNow();

   CollectLevels();
   RefreshPrevBarTouched();
   DrawLevels();
   DrawPanel();

   g_lastLevelBar  = iTime(_Symbol, PERIOD_M1,   0);
   g_lastSignalBar = iTime(_Symbol, InpSignalTF, 0);

   EventSetTimer(1);

   Print("KinoliveLines started on ", _Symbol,
         " | levels ", g_lvCount,
         " | signal TF ", KLTFName(InpSignalTF),
         " | horizon ", InpOutcomeBars, " bars",
         " | journals -> Common\\Files\\", g_touchCsv, " and ", g_tradeCsv);
   Print("KinoliveLines does not trade. It only draws, measures and records.");

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   DeleteAllObjects();
   if(g_atrMergeHandle  != INVALID_HANDLE) IndicatorRelease(g_atrMergeHandle);
   if(g_atrSignalHandle != INVALID_HANDLE) IndicatorRelease(g_atrSignalHandle);
   ChartRedraw();
}

void OnTick()
{
   // Rolling spread, so every measurement is expressed against what trading
   // this symbol actually costs rather than a snapshot of one lucky tick.
   double s = KLSpreadNow();
   if(g_spreadEMA <= 0) g_spreadEMA = s;
   else                 g_spreadEMA = g_spreadEMA * 0.99 + s * 0.01;

   // --- new signal-TF bar: settle observations, roll the touch memory ---
   datetime sigBar = iTime(_Symbol, InpSignalTF, 0);
   if(sigBar != g_lastSignalBar)
   {
      g_lastSignalBar = sigBar;
      UpdateObservations(iHigh (_Symbol, InpSignalTF, 1),
                         iLow  (_Symbol, InpSignalTF, 1),
                         iClose(_Symbol, InpSignalTF, 1));
      RefreshPrevBarTouched();
   }

   // --- new M1 bar: rebuild the level set (same cadence as KinoliveTrader) ---
   datetime m1Bar = iTime(_Symbol, PERIOD_M1, 0);
   if(m1Bar != g_lastLevelBar)
   {
      g_lastLevelBar = m1Bar;
      CollectLevels();
      DrawLevels();
   }

   CheckTouches();
}

void OnTimer()
{
   DrawPanel();
   ChartRedraw();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &request,
                        const MqlTradeResult      &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.deal == 0) return;
   LogDeal(trans.deal);
}
//+------------------------------------------------------------------+
