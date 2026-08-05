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
input bool   InpShowBots = true;           // draw the two bots' live trades
input color  InpPlainCol = clrDodgerBlue;  // plain bot   (magic 770404)
input color  InpRecovCol = clrOrange;      // harvest bot (magic 770405)

#define PFX  "KLRL_"
#define TPFX "KLRL_T_"                     // trade objects, cleaned separately
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
   else if(StringFind(_Symbol, ".BRK") >= 0)   g_csv = "kl_custom_bars.csv";
   else                                        g_csv = "";   // real symbol: draw only

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
      "%s  live %.2f   %s\nlast brick close %.2f  (%s)  bars %d\nnext UP brick  in %.1f pts  (at %.2f)\nnext DOWN brick in %.1f pts  (at %.2f)\nforming: %+.1f pts of %.0f\nfeed: %s",
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
