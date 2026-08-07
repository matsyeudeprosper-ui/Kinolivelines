//+------------------------------------------------------------------+
//|  KLRenkoLive.mq5  -  live price overlay for the KinoliveLines     |
//|                      custom Renko / breakout charts               |
//|                                                                   |
//|  A custom symbol has NO live ticks - its price is just the close   |
//|  of the last bar that was pushed into it. So this reads the bid    |
//|  from the REAL symbol and draws it on top:                         |
//|                                                                    |
//|    - a horizontal line at the live price, with a label             |
//|    - a shaded box from the last brick's close up/down to the live  |
//|      price: the brick currently forming                            |
//|    - how many points remain before the next brick confirms         |
//|                                                                    |
//|  Draws only. Sends no orders and modifies no data.                 |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0
#property strict

input string InpSource   = "BTCUSDm";      // real symbol to take the live price from
input double InpBrick    = 50.0;           // brick size in points (match the feed)
input int    InpReversal = 2;              // bricks needed to turn (match the feed)
input color  InpUpColor  = clrSteelBlue;   // forming zone, upward
input color  InpDnColor  = clrIndianRed;   // forming zone, downward
input color  InpLineCol  = clrGold;        // live price line
input bool   InpFill     = false;          // solid block (true) or outline (false)
input bool   InpRebuild  = false;          // wipe and rebuild this custom symbol
input bool   InpShowBots = true;           // draw the two bots' live trades
input color  InpPlainCol = clrDodgerBlue;  // plain bot   (magic 770404)
input color  InpRecovCol = clrOrange;      // harvest bot (magic 770405)

//--- vertical time separators -------------------------------------------
enum ENUM_KLSEP
  {
   KLSEP_NONE  = 0,   // none
   KLSEP_HOUR  = 1,   // every hour
   KLSEP_DAY   = 2,   // every day
   KLSEP_MONTH = 3    // every month
  };
input ENUM_KLSEP     InpSep      = KLSEP_NONE;   // vertical time separators
input color          InpSepCol   = clrDimGray;   // separator colour
input ENUM_LINE_STYLE InpSepStyle = STYLE_DOT;   // separator style
input int            InpSepWidth = 1;            // separator width
input bool           InpSepLabel = true;         // write the time on each line
input int            InpSepScan  = 4000;         // how many bricks back to scan

#define PFX  "KLRL_"
#define TPFX "KLRL_T_"                     // trade objects, cleaned separately
#define SPFX "KLRL_S_"                     // separators, cleaned separately
#define MAGIC_PLAIN 770404
#define MAGIC_RECOV 770405

//--- this indicator ALSO feeds the chart --------------------------------
// Originally the feeding was a separate MQL5 Service. That needed the user to
// add and start a service, then attach an indicator - three manual steps, and
// in practice the service never got started, so the chart sat frozen and looked
// broken. Doing both here means one drag-and-drop makes the chart live AND
// draws the price line. The Service still exists for headless use, but nothing
// depends on it now.
string g_csv = "";
datetime g_lastPushed = 0;
bool g_breakout = false;      // .BRK chart: filtered M5 candles, NOT bricks -
                              // the renko countdown would be fiction there
int g_sepBars = -1;                        // bar count when separators were last drawn
int g_sepDrawn = 0;                        // how many lines the last pass created
int g_sepErr = 0;                          // last ObjectCreate error, 0 = none
string g_sepNote = "off";                  // shown on the chart so a silent
                                           // failure cannot look like "no lines
                                           // needed" - the two are very different

//+------------------------------------------------------------------+
//| Which hour / day / month a brick belongs to.                      |
//|                                                                    |
//| Times here are MT5 SERVER time, so "day" means the broker's day,   |
//| not yours. On Exness that boundary is not midnight UTC. This is    |
//| deliberate: the chart, the bricks and these lines then all agree   |
//| with each other, which is what you need when reading a chart.      |
//| The journal stays in UTC, so the two will differ by the server     |
//| offset - do not match them up by eye.                              |
//+------------------------------------------------------------------+
long SepBucket(datetime t, ENUM_KLSEP mode)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   switch(mode)
     {
      case KLSEP_HOUR:  return((long)t / 3600);
      case KLSEP_DAY:   return((long)t / 86400);
      case KLSEP_MONTH: return((long)s.year * 12 + s.mon);
     }
   return(0);
  }

//+------------------------------------------------------------------+
//| Vertical lines where the clock crosses into a new hour/day/month. |
//|                                                                    |
//| READ THIS BEFORE TRUSTING THE SPACING. Renko bricks are not evenly |
//| spaced in time - a brick prints when price moves, not when the     |
//| clock ticks. So a line marks THE FIRST BRICK AFTER the boundary,   |
//| not the boundary itself, and a quiet hour that produced no brick   |
//| at all gets no line. Two adjacent hourly lines can therefore sit   |
//| one brick apart, or hundreds. That is the chart telling you where  |
//| the volatility was, but it is not a time axis.                     |
//+------------------------------------------------------------------+
void DrawSeparators()
  {
   ObjectsDeleteAll(0, SPFX);
   g_sepDrawn = 0;
   g_sepErr   = 0;
   int bars = Bars(_Symbol, _Period);

   if(InpSep == KLSEP_NONE)
     {
      g_sepNote = "off";
      g_sepBars = bars;
      return;
     }
   if(bars < 3)
     {
      g_sepNote = "only " + IntegerToString(bars) + " bars";
      return;                                // do NOT latch g_sepBars: retry later
     }

   // i+1 must stay in range, hence bars-2 as the oldest index we can compare
   int oldest = MathMin(InpSepScan, bars - 2);
   int drawn  = 0;

   for(int i = oldest; i >= 0; i--)
     {
      datetime tNew = iTime(_Symbol, _Period, i);
      datetime tOld = iTime(_Symbol, _Period, i + 1);
      if(tNew <= 0 || tOld <= 0) continue;
      if(SepBucket(tNew, InpSep) == SepBucket(tOld, InpSep)) continue;

      string nm = SPFX + IntegerToString(drawn);
      if(!ObjectCreate(0, nm, OBJ_VLINE, 0, tNew, 0))
        {
         g_sepErr = GetLastError();          // record it; silence here was the
         ResetLastError();                   // whole problem last time
         continue;
        }
      ObjectSetInteger(0, nm, OBJPROP_COLOR, InpSepCol);
      ObjectSetInteger(0, nm, OBJPROP_STYLE, InpSepStyle);
      ObjectSetInteger(0, nm, OBJPROP_WIDTH, InpSepWidth);
      ObjectSetInteger(0, nm, OBJPROP_BACK, true);        // behind the bricks
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);      // keep the object list clean

      string stamp = (InpSep == KLSEP_MONTH)
                     ? TimeToString(tNew, TIME_DATE)
                     : (InpSep == KLSEP_DAY
                        ? TimeToString(tNew, TIME_DATE)
                        : TimeToString(tNew, TIME_MINUTES));
      ObjectSetString(0, nm, OBJPROP_TOOLTIP,
                      stamp + "  (first brick of the new period)");
      if(InpSepLabel)
         ObjectSetString(0, nm, OBJPROP_TEXT, stamp);

      drawn++;
     }
   g_sepBars  = bars;
   g_sepDrawn = drawn;
   g_sepNote  = StringFormat("%s, %d lines, scanned %d of %d bars%s",
                             InpSep == KLSEP_HOUR ? "hourly" :
                             InpSep == KLSEP_DAY  ? "daily" : "monthly",
                             drawn, oldest + 1, bars,
                             g_sepErr == 0 ? "" :
                             ", ObjectCreate err " + IntegerToString(g_sepErr));
   PrintFormat("KLRenkoLive separators: %s", g_sepNote);
  }

//+------------------------------------------------------------------+
//| Draw the two bots' open trades, and return a text block for the   |
//| corner readout.                                                    |
//|                                                                    |
//| WHY THIS IS HAND-DRAWN. The bots trade BTCUSDm. This chart is a     |
//| CUSTOM symbol built from BTCUSDm prices, so MT5 shows no position   |
//| markers on it at all - as far as the terminal is concerned there is |
//| nothing open on this instrument. The vertical price scale is the    |
//| same though, so a horizontal line at an entry price lands exactly   |
//| where it belongs. Time is not usable: brick timestamps are the      |
//| moment a brick CLOSED, not a clock, so entry arrows would sit in    |
//| the wrong column. Lines only, no arrows.                            |
//|                                                                    |
//| Reads positions. Sends nothing.                                     |
//+------------------------------------------------------------------+
string DrawBotTrades()
  {
   // clear last pass - positions close and their lines must go with them
   ObjectsDeleteAll(0, TPFX);
   if(!InpShowBots) return("");

   int    nP = 0, nR = 0;
   double pP = 0.0, pR = 0.0;
   int    k  = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0 || !PositionSelectByTicket(tk))          continue;
      if(PositionGetString(POSITION_SYMBOL) != InpSource) continue;
      long mg = PositionGetInteger(POSITION_MAGIC);
      if(mg != MAGIC_PLAIN && mg != MAGIC_RECOV)          continue;

      bool   recov = (mg == MAGIC_RECOV);
      color  col   = recov ? InpRecovCol : InpPlainCol;
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double tp    = PositionGetDouble(POSITION_TP);
      double prof  = PositionGetDouble(POSITION_PROFIT);
      bool   isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);

      if(recov) { nR++; pR += prof; } else { nP++; pP += prof; }

      string nm = TPFX + "e" + IntegerToString(k);
      ObjectCreate(0, nm, OBJ_HLINE, 0, 0, open);
      ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
      ObjectSetInteger(0, nm, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, nm, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, nm, OBJPROP_BACK, false);
      ObjectSetString (0, nm, OBJPROP_TOOLTIP,
                       StringFormat("%s %s %.2f  P&L %+.2f",
                                    recov ? "HARVEST" : "plain",
                                    isBuy ? "BUY" : "SELL", open, prof));
      k++;

      if(tp > 0.0)
        {
         string tn = TPFX + "t" + IntegerToString(k);
         ObjectCreate(0, tn, OBJ_HLINE, 0, 0, tp);
         ObjectSetInteger(0, tn, OBJPROP_COLOR, col);
         ObjectSetInteger(0, tn, OBJPROP_WIDTH, 1);
         ObjectSetInteger(0, tn, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, tn, OBJPROP_SELECTABLE, false);
         ObjectSetString (0, tn, OBJPROP_TOOLTIP,
                          StringFormat("%s target %.2f",
                                       recov ? "HARVEST" : "plain", tp));
         k++;
        }
     }

   // today's realised, per bot, straight from deal history
   double rP = 0.0, rR = 0.0;
   int    cP = 0,   cR = 0;
   datetime from = TimeCurrent() - 86400 * 3;
   if(HistorySelect(from, TimeCurrent() + 3600))
     {
      for(int d = HistoryDealsTotal() - 1; d >= 0; d--)
        {
         ulong dt = HistoryDealGetTicket(d);
         if(dt == 0) continue;
         if(HistoryDealGetString(dt, DEAL_SYMBOL) != InpSource)      continue;
         if(HistoryDealGetInteger(dt, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
         long mg = HistoryDealGetInteger(dt, DEAL_MAGIC);
         double pr = HistoryDealGetDouble(dt, DEAL_PROFIT)
                   + HistoryDealGetDouble(dt, DEAL_SWAP)
                   + HistoryDealGetDouble(dt, DEAL_COMMISSION);
         if(mg == MAGIC_RECOV)      { rR += pr; cR++; }
         else if(mg == MAGIC_PLAIN) { rP += pr; cP++; }
        }
     }

   return(StringFormat(
      "HARVEST  %d open  floating %+.2f   |  closed %d  %+.2f\n"
      "plain    %d open  floating %+.2f   |  closed %d  %+.2f\n"
      "-----------------------------------------------\n",
      nR, pR, cR, rR, nP, pP, cP, rP));
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   // Pick the data file from whichever custom symbol we are attached to.
   if(StringFind(_Symbol, ".RENKO") >= 0)      g_csv = "kl_renko_bars.csv";
   else if(StringFind(_Symbol, ".BRK") >= 0) { g_csv = "kl_custom_bars.csv"; g_breakout = true; }
   else                                        g_csv = "";   // real symbol: draw only

   // Wipe and rebuild. The feed only ADDS bars, it never removes them, so after
   // a filter-rule change the chart holds a mix: bars the old rule kept sitting
   // next to bars the new rule keeps. Nothing marks them apart and the chart
   // looks like neither rule. Tick this once after any rule change.
   if(InpRebuild && g_csv != "")
     {
      CustomRatesDelete(_Symbol, 0, D'2100.01.01');
      g_lastPushed = 0;                     // so PushNew re-sends everything
      PrintFormat("KLRenkoLive: cleared %s and rebuilding from %s", _Symbol, g_csv);
     }

   EventSetMillisecondTimer(1000);          // the custom symbol gets no ticks,
   if(g_csv != "")                          // so a timer is the only clock here
      PushNew();                            // fill it immediately, do not wait
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Load bars from the CSV and push any that are newer than the last  |
//| we sent. Returns bars pushed, or -1 if the file is unreadable.    |
//+------------------------------------------------------------------+
int PushNew()
  {
   if(g_csv == "") return(0);
   int fh = FileOpen(g_csv, FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE) return(-1);

   MqlRates rates[];
   int n = 0;
   bool header = true;
   while(!FileIsEnding(fh))
     {
      string s_t = FileReadString(fh);
      if(FileIsEnding(fh) && s_t == "") break;
      string s_o = FileReadString(fh);
      string s_h = FileReadString(fh);
      string s_l = FileReadString(fh);
      string s_c = FileReadString(fh);
      string s_v = FileReadString(fh);
      string s_s = FileReadString(fh);
      string s_r = FileReadString(fh);
      if(header) { header = false; continue; }
      if(s_t == "") continue;
      datetime bt = (datetime)StringToInteger(s_t);
      if(bt < g_lastPushed) continue;       // already sent; re-send the newest one
      ArrayResize(rates, n + 1);
      rates[n].time        = bt;
      rates[n].open        = StringToDouble(s_o);
      rates[n].high        = StringToDouble(s_h);
      rates[n].low         = StringToDouble(s_l);
      rates[n].close       = StringToDouble(s_c);
      rates[n].tick_volume = (long)StringToInteger(s_v);
      rates[n].spread      = (int)StringToInteger(s_s);
      rates[n].real_volume = (long)StringToInteger(s_r);
      n++;
     }
   FileClose(fh);
   if(n == 0) return(0);

   int added = CustomRatesUpdate(_Symbol, rates);
   if(added < 0) return(-1);
   g_lastPushed = rates[n - 1].time;
   return(n);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0, PFX);
   Comment("");
  }

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   return(rates_total);
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   int pushed = PushNew();
   if(pushed > 1)                            // >1 means genuinely new bars
      ChartRedraw(0);

   // Separators only change when bricks are added. Deleting and rebuilding a
   // few hundred objects on every timer tick would flicker the chart and cost
   // more than the rest of this indicator put together.
   if(g_sepBars != Bars(_Symbol, _Period))
      DrawSeparators();

   Redraw();
  }

//+------------------------------------------------------------------+
void Redraw()
  {
   double bid = SymbolInfoDouble(InpSource, SYMBOL_BID);
   if(bid <= 0)
     {
      Comment(PFX + "no price from " + InpSource);
      return;
     }

   int bars = Bars(_Symbol, _Period);
   if(bars < 2) return;

   double lastOpen  = iOpen(_Symbol, _Period, 0);
   double lastClose = iClose(_Symbol, _Period, 0);
   datetime lastT   = iTime(_Symbol, _Period, 0);
   if(lastClose <= 0) return;

   int dir = (lastClose > lastOpen) ? 1 : -1;

   //--- how far to the next brick ------------------------------------
   // Continuing the trend needs one brick from the last close; turning needs
   // InpReversal bricks measured from the last brick's OPEN. Same arithmetic
   // the feed uses, so the countdown matches what will actually print.
   double upTarget = (dir == -1 ? lastOpen : lastClose) + InpBrick * (dir == -1 ? InpReversal : 1);
   double dnTarget = (dir ==  1 ? lastOpen : lastClose) - InpBrick * (dir ==  1 ? InpReversal : 1);
   double toUp = upTarget - bid;
   double toDn = bid - dnTarget;

   //--- live price line ----------------------------------------------
   string ln = PFX + "line";
   if(ObjectFind(0, ln) < 0)
     {
      ObjectCreate(0, ln, OBJ_HLINE, 0, 0, bid);
      ObjectSetInteger(0, ln, OBJPROP_COLOR, InpLineCol);
      ObjectSetInteger(0, ln, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetInteger(0, ln, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, ln, OBJPROP_BACK, false);
      ObjectSetInteger(0, ln, OBJPROP_SELECTABLE, false);
     }
   ObjectSetDouble(0, ln, OBJPROP_PRICE, bid);

   //--- BREAKOUT chart: entirely different overlay -----------------------
   // On .BRK the bars are FILTERED M5 CANDLES, not bricks. The renko maths
   // below ("next brick in N points") would be pure fiction here - there is no
   // brick and no 50-point target. What matters on this chart is the last
   // KEPT candle's high and low, because the filter keeps the next M5 bar only
   // when its CLOSE breaks one of those two levels.
   if(g_breakout)
     {
      double kHi = iHigh(_Symbol, _Period, 0);   // bar 0 = last KEPT candle
      double kLo = iLow(_Symbol, _Period, 0);

      string hu = PFX + "bko_hi", hd = PFX + "bko_lo";
      for(int q = 0; q < 2; q++)
        {
         string nm2 = (q == 0) ? hu : hd;
         double pv  = (q == 0) ? kHi : kLo;
         if(ObjectFind(0, nm2) < 0)
           {
            ObjectCreate(0, nm2, OBJ_HLINE, 0, 0, pv);
            ObjectSetInteger(0, nm2, OBJPROP_STYLE, STYLE_DASH);
            ObjectSetInteger(0, nm2, OBJPROP_WIDTH, 1);
            ObjectSetInteger(0, nm2, OBJPROP_BACK, false);
            ObjectSetInteger(0, nm2, OBJPROP_SELECTABLE, false);
           }
         ObjectSetDouble (0, nm2, OBJPROP_PRICE, pv);
         ObjectSetInteger(0, nm2, OBJPROP_COLOR, q == 0 ? InpUpColor : InpDnColor);
         ObjectSetString (0, nm2, OBJPROP_TOOLTIP,
                          q == 0 ? "keep the next M5 bar if it CLOSES above here"
                                 : "keep the next M5 bar if it CLOSES below here");
        }

      // Seconds left in the CURRENT source M5 candle - the decision moment.
      // Server time, like every timestamp on this chart.
      long   secs  = (long)PeriodSeconds(PERIOD_M5);
      long   nowS  = (long)TimeCurrent();
      long   left  = secs - (nowS % secs);

      string botLines2 = DrawBotTrades();
      Comment(botLines2 + StringFormat(
         "%s  live %.2f   BREAKOUT chart (filtered M5 closes)\n"
         "last kept bar  high %.2f  low %.2f   bars %d\n"
         "to break UP:   %+.1f pts (close above %.2f)\n"
         "to break DOWN: %+.1f pts (close below %.2f)\n"
         "M5 closes in %d:%02d - a cross does NOT count until the close\n"
         "separators: " + g_sepNote + "\nfeed: %s",
         InpSource, bid, kHi, kLo, bars,
         kHi - bid, kHi, bid - kLo, kLo,
         (int)(left / 60), (int)(left % 60),
         g_lastPushed > 0 ? "OK, newest " + TimeToString(g_lastPushed, TIME_MINUTES)
                          : "WAITING - cannot read " + g_csv));
      ChartRedraw(0);
      return;
     }

   //--- the forming zone ------------------------------------------------
   // Drawn ONLY when price has left the last brick's body, i.e. when it is
   // actually travelling AWAY from that brick and therefore making progress
   // toward the next one. While price sits inside the body it is just noise
   // retracing within a brick that has already printed, and shading that told
   // you nothing while covering the chart.
   double bodyHi = MathMax(lastOpen, lastClose);
   double bodyLo = MathMin(lastOpen, lastClose);
   bool   inside = (bid <= bodyHi && bid >= bodyLo);

   string bx = PFX + "form";
   if(inside)
     {
      ObjectDelete(0, bx);                 // nothing to show
     }
   else
     {
      double edge = (bid > bodyHi) ? bodyHi : bodyLo;   // measure from the edge left behind
      datetime t1 = lastT;
      datetime t2 = lastT + PeriodSeconds(_Period) * 3;
      if(ObjectFind(0, bx) < 0)
        {
         ObjectCreate(0, bx, OBJ_RECTANGLE, 0, t1, edge, t2, bid);
         ObjectSetInteger(0, bx, OBJPROP_BACK, true);
         ObjectSetInteger(0, bx, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, bx, OBJPROP_WIDTH, 1);
        }
      // Outline by default. A filled block reads as a real brick and buries the
      // candles under it; a thin border marks the same zone without competing
      // with the data.
      ObjectSetInteger(0, bx, OBJPROP_FILL, InpFill);
      ObjectSetInteger(0, bx, OBJPROP_TIME, 0, t1);
      ObjectSetDouble (0, bx, OBJPROP_PRICE, 0, edge);
      ObjectSetInteger(0, bx, OBJPROP_TIME, 1, t2);
      ObjectSetDouble (0, bx, OBJPROP_PRICE, 1, bid);
      ObjectSetInteger(0, bx, OBJPROP_COLOR, bid > bodyHi ? InpUpColor : InpDnColor);
     }

   //--- the bots' live trades -------------------------------------------
   string botLines = DrawBotTrades();

   //--- readout --------------------------------------------------------
   Comment(botLines + StringFormat(
      "%s  live %.2f   %s\nlast brick close %.2f  (%s)  bars %d\nnext UP brick  in %.1f pts  (at %.2f)\nnext DOWN brick in %.1f pts  (at %.2f)\nforming: %+.1f pts of %.0f\nseparators: " + g_sepNote + "\nfeed: %s",
      InpSource, bid, inside ? "inside last brick" : "moving away",
      lastClose, dir == 1 ? "up" : "down", bars,
      toUp, upTarget, toDn, dnTarget,
      inside ? 0.0 : (bid - ((bid > bodyHi) ? bodyHi : bodyLo)), InpBrick,
      g_csv == "" ? "draw only" :
        (g_lastPushed > 0 ? "OK, newest " + TimeToString(g_lastPushed, TIME_MINUTES)
                          : "WAITING - cannot read " + g_csv)));

   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
