//+------------------------------------------------------------------+
//|  KLCustomChart.mq5                                               |
//|  Loads filtered bars from a CSV into a CUSTOM SYMBOL and opens   |
//|  a chart on it.                                                  |
//|                                                                  |
//|  Companion to charting/build_custom_bars.py, which writes the    |
//|  CSV into the MT5 COMMON folder. This exists because the         |
//|  MetaTrader5 Python package has no CustomSymbolCreate - custom   |
//|  symbols can only be built from MQL5.                            |
//|                                                                  |
//|  READ-ONLY with respect to trading. It creates a symbol, pushes  |
//|  bars and opens a chart. It never sends an order, and the symbol |
//|  it makes is explicitly set NON-TRADEABLE so nothing can.        |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

enum ENUM_KL_PRESET
  {
   PRESET_BREAKOUT,   // Breakout filter  (your rule)
   PRESET_RENKO       // Renko bricks
  };

input ENUM_KL_PRESET InpPreset = PRESET_BREAKOUT;   // which chart to build
input string InpBaseSymbol     = "BTCUSDm";         // clone tick size / digits from this
input bool   InpOpenChart      = true;              // open a chart when done
input bool   InpAttachIndi     = true;              // attach KLRenkoLive to it

#define INDI_NAME "KLRenkoLive"

//+------------------------------------------------------------------+
int OnStart()
  {
   //--- 0. resolve the preset -------------------------------------------
   // A dropdown rather than two free-text fields, so picking a chart cannot be
   // got wrong by typing a filename that does not exist.
   string InpCsv    = (InpPreset == PRESET_RENKO) ? "kl_renko_bars.csv" : "kl_custom_bars.csv";
   string InpSymbol = (InpPreset == PRESET_RENKO) ? "BTCUSDm.RENKO"     : "BTCUSDm.BRK";

   //--- 1. read the CSV -------------------------------------------------
   // FILE_COMMON: the shared folder every terminal on the machine can see,
   // which is how the Python side hands data over without knowing which
   // terminal you are running this from.
   int fh = FileOpen(InpCsv, FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("Cannot open COMMON\\Files\\%s  err=%d. Run build_custom_bars.py first.",
                  InpCsv, GetLastError());
      return(1);
     }

   MqlRates rates[];
   int n = 0;
   bool header = true;
   while(!FileIsEnding(fh))
     {
      string s_time = FileReadString(fh);
      if(FileIsEnding(fh) && s_time == "")
         break;
      string s_o = FileReadString(fh);
      string s_h = FileReadString(fh);
      string s_l = FileReadString(fh);
      string s_c = FileReadString(fh);
      string s_tv= FileReadString(fh);
      string s_sp= FileReadString(fh);
      string s_rv= FileReadString(fh);

      if(header) { header = false; continue; }      // skip the column names
      if(s_time == "") continue;

      ArrayResize(rates, n + 1);
      rates[n].time         = (datetime)StringToInteger(s_time);
      rates[n].open         = StringToDouble(s_o);
      rates[n].high         = StringToDouble(s_h);
      rates[n].low          = StringToDouble(s_l);
      rates[n].close        = StringToDouble(s_c);
      rates[n].tick_volume  = (long)StringToInteger(s_tv);
      rates[n].spread       = (int)StringToInteger(s_sp);
      rates[n].real_volume  = (long)StringToInteger(s_rv);
      n++;
     }
   FileClose(fh);

   if(n == 0)
     {
      Print("CSV contained no bars.");
      return(1);
     }

   //--- 2. create the custom symbol ------------------------------------
   // Cloning the base symbol copies digits, point and tick size, so prices
   // render correctly. Without it the chart shows nonsense scaling.
   bool exists = SymbolSelect(InpSymbol, true);
   if(!exists || !SymbolInfoInteger(InpSymbol, SYMBOL_CUSTOM))
     {
      if(!CustomSymbolCreate(InpSymbol, "Custom\\KinoliveLines", InpBaseSymbol))
        {
         int e = GetLastError();
         if(e != 5304)   // 5304 = already exists, which is fine
           {
            PrintFormat("CustomSymbolCreate(%s) failed err=%d", InpSymbol, e);
            return(1);
           }
        }
     }

   // Chart-only. Make it impossible to trade this synthetic instrument by
   // accident - it has no real liquidity behind it.
   CustomSymbolSetInteger(InpSymbol, SYMBOL_TRADE_MODE, SYMBOL_TRADE_MODE_DISABLED);
   CustomSymbolSetString (InpSymbol, SYMBOL_DESCRIPTION,
                          "KinoliveLines filtered bars - closes outside prior range");
   SymbolSelect(InpSymbol, true);

   //--- 3. replace the history -----------------------------------------
   // Wipe first so a re-run with different settings cannot leave stale bars
   // interleaved with new ones.
   CustomRatesDelete(InpSymbol, 0, D'2100.01.01');
   int added = CustomRatesUpdate(InpSymbol, rates);
   if(added < 0)
     {
      PrintFormat("CustomRatesUpdate failed err=%d", GetLastError());
      return(1);
     }
   PrintFormat("%s: loaded %d bars (%s -> %s)", InpSymbol, added,
               TimeToString(rates[0].time), TimeToString(rates[n-1].time));

   //--- 4. show it ------------------------------------------------------
   // ALWAYS M1. CustomRatesUpdate writes into the symbol's M1 history and the
   // terminal builds every higher timeframe from that, so viewing on M5 would
   // merge several of our filtered candles into one. On M1 each pushed bar is
   // exactly one candle, whatever timeframe it was derived from. Gaps between
   // kept bars simply do not render, the same way weekends do not.
   if(InpOpenChart)
     {
      long cid = ChartOpen(InpSymbol, PERIOD_M1);
      if(cid == 0)
         PrintFormat("ChartOpen failed err=%d - open it by hand from Market Watch.", GetLastError());
      else
        {
         ChartSetInteger(cid, CHART_MODE, CHART_CANDLES);
         ChartSetInteger(cid, CHART_AUTOSCROLL, true);
         ChartSetInteger(cid, CHART_SHIFT, true);

         // Attach KLRenkoLive. Without it the chart is a dead custom symbol:
         // nothing feeds it new bars and none of the indicator's options exist,
         // which reads as "the feature is missing" rather than "the indicator
         // is not on this chart". Both charts this script builds get it.
         if(InpAttachIndi)
           {
            int h = iCustom(InpSymbol, PERIOD_M1, INDI_NAME);
            if(h == INVALID_HANDLE)
               PrintFormat("iCustom(%s) failed err=%d - is %s.ex5 compiled and in MQL5\\Indicators?",
                           INDI_NAME, GetLastError(), INDI_NAME);
            else if(!ChartIndicatorAdd(cid, 0, h))
               PrintFormat("ChartIndicatorAdd failed err=%d", GetLastError());
            else
               PrintFormat("Attached %s to chart %I64d", INDI_NAME, cid);
            // the chart holds its own reference once added
            if(h != INVALID_HANDLE) IndicatorRelease(h);
           }

         ChartRedraw(cid);
         PrintFormat("Opened chart %I64d on %s M1", cid, InpSymbol);
        }
     }
   return(0);
  }
//+------------------------------------------------------------------+
