//+------------------------------------------------------------------+
//|  KLCustomFeed.mq5   -   SERVICE, not a script or an EA           |
//|                                                                  |
//|  Keeps the KinoliveLines custom symbols fed so their charts move  |
//|  like normal ones. A Service is the right tool here: it runs in   |
//|  the background with no chart attached, survives you closing and  |
//|  reopening charts, and restarts with the terminal.                |
//|                                                                  |
//|  Reads the CSVs that live_feed.py keeps current in the COMMON     |
//|  folder. Creates the symbols if they do not exist, so this alone  |
//|  is enough to get running - the KLCustomChart script is only      |
//|  needed to OPEN the chart windows.                                |
//|                                                                  |
//|  Sends no orders. The symbols it creates are non-tradeable.       |
//+------------------------------------------------------------------+
#property service
#property strict

#define POLL_MS 3000

//+------------------------------------------------------------------+
struct Feed
  {
   string csv;
   string symbol;
   datetime last;      // newest bar time already pushed
  };

//+------------------------------------------------------------------+
//| Create the custom symbol if needed. Cloning BTCUSDm copies digits,|
//| point and tick size, without which the price scale is nonsense.   |
//+------------------------------------------------------------------+
bool EnsureSymbol(const string sym)
  {
   if(SymbolSelect(sym, true) && SymbolInfoInteger(sym, SYMBOL_CUSTOM))
      return(true);
   if(!CustomSymbolCreate(sym, "Custom\\KinoliveLines", "BTCUSDm"))
     {
      int e = GetLastError();
      if(e != 5304)                       // 5304 = already exists
        {
         PrintFormat("CustomSymbolCreate(%s) err=%d", sym, e);
         return(false);
        }
     }
   // Chart-only: nothing real backs this instrument, so make it impossible to
   // trade by accident.
   CustomSymbolSetInteger(sym, SYMBOL_TRADE_MODE, SYMBOL_TRADE_MODE_DISABLED);
   SymbolSelect(sym, true);
   return(true);
  }

//+------------------------------------------------------------------+
//| Read the CSV and push only bars NEWER than what we already sent,  |
//| plus the newest one again in case it is still forming.            |
//| Returns how many bars were pushed, or -1 on a read failure.       |
//+------------------------------------------------------------------+
int PushNew(Feed &f)
  {
   int fh = FileOpen(f.csv, FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return(-1);                          // feed not running yet; caller retries

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
      // Re-push the last known bar as well as anything after it: the newest
      // Renko brick can still be extending when we read.
      if(bt < f.last) continue;

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

   int added = CustomRatesUpdate(f.symbol, rates);
   if(added < 0)
     {
      PrintFormat("%s CustomRatesUpdate err=%d", f.symbol, GetLastError());
      return(-1);
     }
   f.last = rates[n - 1].time;
   return(n);
  }

//+------------------------------------------------------------------+
void OnStart()
  {
   Feed feeds[2];
   feeds[0].csv = "kl_custom_bars.csv"; feeds[0].symbol = "BTCUSDm.BRK";   feeds[0].last = 0;
   feeds[1].csv = "kl_renko_bars.csv";  feeds[1].symbol = "BTCUSDm.RENKO"; feeds[1].last = 0;

   for(int i = 0; i < 2; i++)
      EnsureSymbol(feeds[i].symbol);

   Print("KLCustomFeed service started - BTCUSDm.BRK and BTCUSDm.RENKO");

   int quiet = 0;
   while(!IsStopped())
     {
      for(int i = 0; i < 2; i++)
        {
         int got = PushNew(feeds[i]);
         if(got < 0)
           {
            // Only complain occasionally, or a stopped Python feed would fill
            // the journal with one line every three seconds.
            if(quiet % 100 == 0)
               PrintFormat("%s: cannot read COMMON\\Files\\%s - is live_feed.py running?",
                           feeds[i].symbol, feeds[i].csv);
           }
         else
            if(got > 1)
               ChartRedrawAll(feeds[i].symbol);
        }
      quiet++;
      Sleep(POLL_MS);
     }
   Print("KLCustomFeed service stopped");
  }

//+------------------------------------------------------------------+
//| Redraw every open chart showing this symbol.                      |
//+------------------------------------------------------------------+
void ChartRedrawAll(const string sym)
  {
   long cid = ChartFirst();
   while(cid >= 0)
     {
      if(ChartSymbol(cid) == sym)
         ChartRedraw(cid);
      cid = ChartNext(cid);
     }
  }
//+------------------------------------------------------------------+
