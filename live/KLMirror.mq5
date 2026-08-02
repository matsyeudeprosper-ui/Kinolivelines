//+------------------------------------------------------------------+
//| KLMirror.mq5                                                      |
//| Copies KinoliveLines demo trades onto this account with the       |
//| direction REVERSED.                                               |
//+------------------------------------------------------------------+
//
// HOW IT WORKS
//   An MQL5 program can only see its own terminal and its own account, so this EA
//   cannot read the demo account directly. A publisher process on the demo side writes
//   each open and close to a small text file in the terminal COMMON folder, which every
//   MT5 instance on this machine shares. This EA polls that file and acts on new lines.
//
//   signal file:  <COMMON>\Files\kl_mirror_signals.csv
//   format:       seq,epoch,event,ticket,side,volume,price,sl,tp
//   event:        OPEN or CLOSE
//
// THE REVERSAL
//   A demo BUY becomes a SELL here, and the stop and target are reflected through the
//   entry price so the mirrored trade has the same distances:
//
//       demo BUY  entry E, SL E-40, TP E+20
//       mirror    SELL  E, SL E+40, TP E-20
//
// WHAT THIS COSTS - measured, not guessed
//   The two accounts are exact mirrors, so exactly one of them wins on every trade:
//       price hits the demo target -> demo +$1.00, here -$2.00   = -$1.00 for the pair
//       price hits the demo stop   -> demo -$2.00, here +$1.00   = -$1.00 for the pair
//   There is no third outcome. The pair loses $1.00 every time, because the winning
//   side collects $1 while the losing side pays $2. Each account independently loses
//   one spread per trade; running two loses two spreads instead of one. Reversing the
//   direction does not offset the loss, it doubles it.
//
//   THIS ACCOUNT IS REAL MONEY. At the observed trade rate a $42.70 balance funds
//   roughly eleven days. That was accepted deliberately.
//
// SAFETY
//   * refuses to run on any account other than InpAccount
//   * refuses volumes above InpMaxLots
//   * stops trading entirely once equity falls below InpMinEquity
//   * only ever touches positions carrying its own magic number
//   * ignores any signal older than InpMaxSignalAge seconds, so a stale file cannot
//     fire a burst of trades after a restart
//
#property copyright "KinoliveLines"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

input long   InpAccount        = 134499778;   // ONLY this account may trade
input string InpSymbol         = "BTCUSDm";
input double InpMaxLots        = 0.05;        // hard ceiling
input double InpMinEquity      = 5.0;         // stop trading below this
input int    InpMagic          = 778001;
input int    InpMaxSignalAge   = 120;         // seconds; older signals are ignored
input int    InpPendingMaxMin  = 180;         // orphan backstop only; 0 disables
input string InpSignalFile     = "kl_mirror_signals.csv";
input int    InpPollMs         = 1000;

CTrade   trade;
long     g_seq_done = -1;      // highest sequence number already acted on
bool     g_halted   = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_LOGIN) != InpAccount)
     {
      PrintFormat("KLMirror REFUSING: account is %I64d, EA is locked to %I64d",
                  AccountInfoInteger(ACCOUNT_LOGIN), InpAccount);
      return(INIT_FAILED);
     }
   if(!SymbolSelect(InpSymbol, true))
     {
      PrintFormat("KLMirror: cannot select %s", InpSymbol);
      return(INIT_FAILED);
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);

   // Start from the END of the existing file. Without this, attaching the EA would
   // replay every signal ever written and open a burst of positions at once.
   g_seq_done = LastSeqInFile();
   PrintFormat("KLMirror ready on %I64d (%s). Resuming after seq %I64d. "
               "Mirroring %s with direction REVERSED.",
               AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_SERVER),
               g_seq_done, InpSymbol);
   EventSetMillisecondTimer(InpPollMs);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
//| Highest sequence number currently in the file (for a cold start)  |
//+------------------------------------------------------------------+
long LastSeqInFile()
  {
   long last = -1;
   int h = FileOpen(InpSignalFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return(last);
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      string p[];
      if(StringSplit(line, ',', p) >= 9)
         last = MathMax(last, (long)StringToInteger(p[0]));
     }
   FileClose(h);
   return(last);
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   if(g_halted)
      return;

   if(AccountInfoDouble(ACCOUNT_EQUITY) < InpMinEquity)
     {
      Print("KLMirror HALTED: equity below InpMinEquity. No further trades.");
      g_halted = true;
      return;
     }

   ExpireOrphanPendings();

   int h = FileOpen(InpSignalFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return;

   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      string p[];
      if(StringSplit(line, ',', p) < 9)
         continue;

      // Skip the CSV header. It splits into nine fields like any other row, and
      // StringToInteger("seq") is 0, so it used to be read as sequence 0 with epoch 0
      // and rejected as "1785612434 s old" - harmless, since rejecting it was the right
      // outcome, but it looked like a fault in the log every time the EA started.
      if(p[0] == "seq")
         continue;

      long seq = (long)StringToInteger(p[0]);
      if(seq <= g_seq_done)
         continue;                                  // already handled

      long   epoch  = (long)StringToInteger(p[1]);
      string event  = p[2];
      long   ticket = (long)StringToInteger(p[3]);
      string side   = p[4];
      double vol    = StringToDouble(p[5]);
      double price  = StringToDouble(p[6]);
      double sl     = StringToDouble(p[7]);
      double tp     = StringToDouble(p[8]);

      g_seq_done = seq;                             // consume regardless of outcome

      if(TimeCurrent() - (datetime)epoch > InpMaxSignalAge)
        {
         PrintFormat("KLMirror: seq %I64d ignored, %d s old", seq,
                     (int)(TimeCurrent() - (datetime)epoch));
         continue;
        }

      // PEND_OPEN is the normal path now: the master rests a pending, so this rests the
      // mirrored one straight away and both fill at the same moment. OPEN survives for
      // genuine market entries, which the publisher only emits when a position appears
      // without having been a pending first.
      if(event == "PEND_OPEN" || event == "OPEN")
         MirrorOpen(ticket, side, vol, price, sl, tp);
      else if(event == "PEND_CANCEL" || event == "CLOSE")
         MirrorClose(ticket);
     }
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| Open the REVERSED position                                       |
//+------------------------------------------------------------------+
void MirrorOpen(long src_ticket, string side, double vol, double price,
                double sl, double tp)
  {
   if(HasOpenMirror())
     {
      PrintFormat("KLMirror: already holding a mirror, skipping ticket %I64d", src_ticket);
      return;
     }
   if(vol > InpMaxLots)
     {
      PrintFormat("KLMirror: volume %.2f exceeds cap %.2f, skipping", vol, InpMaxLots);
      return;
     }

   // ---- LIMIT, not market ----------------------------------------------------
   // Market entries drifted 11 to 26 points from the demo fill because the signal
   // arrives a second or two late and the EA took whatever price existed then. On the
   // first pair that put the mirror 26 points offside before it started, so a "40 point"
   // stop was really 66. A limit fills at the intended price or not at all.
   //
   // The mirror enters on the OPPOSITE side of the book, so its price is one spread
   // away from the demo fill. A demo BUY filled at ask E was sellable at E - spread at
   // that instant, so that is where the mirror belongs. Those two cannot be equal - you
   // cannot buy and sell at one price - and that one spread is inherent, not slippage.
   double spread = SymbolInfoDouble(InpSymbol, SYMBOL_ASK)
                 - SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   bool   src_is_buy = (StringFind(side, "BUY") >= 0);
   int    dg = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);

   double entry = src_is_buy ? price - spread : price + spread;
   entry = NormalizeDouble(entry, dg);

   // Distances are taken from the SOURCE trade and applied to the MIRROR's own entry,
   // rather than reflecting through the demo price. Reflecting was what made the
   // geometry wrong once the fill landed somewhere else.
   double risk   = MathAbs(price - sl);
   double reward = MathAbs(tp - price);
   double m_sl, m_tp;
   if(src_is_buy)                                   // mirror SELLS
     { m_sl = entry + risk;  m_tp = entry - reward; }
   else                                             // mirror BUYS
     { m_sl = entry - risk;  m_tp = entry + reward; }
   m_sl = NormalizeDouble(m_sl, dg);
   m_tp = NormalizeDouble(m_tp, dg);

   string comment = StringFormat("KLmir#%I64d", src_ticket);
   double bid = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   bool   ok  = false;

   // NEVER SKIP - pick the order type that can rest at this price.
   //
   // The previous version refused whenever price had already moved past the entry,
   // which lost the pair entirely. That is not necessary: a price is reachable from
   // either side, only the order type differs.
   //
   //   selling at M, M ABOVE the bid  -> SELL_LIMIT  (fills as price rises to M)
   //   selling at M, M BELOW the bid  -> SELL_STOP   (fills as price falls to M)
   //
   // Either way the fill lands on M. One asymmetry to know: a STOP becomes a market
   // order the instant it triggers, so it can slip in a fast move, while a LIMIT can
   // never fill worse than its price. Both beat the market entry this replaced, which
   // drifted 11 to 26 points.
   //
   // The broker also enforces a minimum distance for pending orders. Inside that band
   // nothing can rest at all, so there it genuinely is market-or-nothing, and market is
   // right: a point or two off beats missing the pair.
   long   stops_pts = SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist  = stops_pts * SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
   string how       = "";

   if(src_is_buy)                                   // mirror SELLS at `entry`
     {
      if(MathAbs(entry - bid) <= min_dist)
        { ok = trade.Sell(vol, InpSymbol, 0.0, m_sl, m_tp, comment); how = "SELL market (inside stops level)"; }
      else if(entry > bid)
        { ok = trade.SellLimit(vol, entry, InpSymbol, m_sl, m_tp, ORDER_TIME_GTC, 0, comment); how = "SELL_LIMIT"; }
      else
        { ok = trade.SellStop(vol, entry, InpSymbol, m_sl, m_tp, ORDER_TIME_GTC, 0, comment); how = "SELL_STOP"; }
     }
   else                                             // mirror BUYS at `entry`
     {
      if(MathAbs(entry - ask) <= min_dist)
        { ok = trade.Buy(vol, InpSymbol, 0.0, m_sl, m_tp, comment); how = "BUY market (inside stops level)"; }
      else if(entry < ask)
        { ok = trade.BuyLimit(vol, entry, InpSymbol, m_sl, m_tp, ORDER_TIME_GTC, 0, comment); how = "BUY_LIMIT"; }
      else
        { ok = trade.BuyStop(vol, entry, InpSymbol, m_sl, m_tp, ORDER_TIME_GTC, 0, comment); how = "BUY_STOP"; }
     }

   PrintFormat("KLMirror %s src=%I64d %s %.2f -> %s @ %.2f  SL %.2f TP %.2f "
               "(demo filled %.2f, spread %.2f, bid %.2f)  ret=%u %s",
               ok ? "PLACED" : "FAILED", src_ticket, side, vol,
               how, entry, m_sl, m_tp, price, spread, bid,
               trade.ResultRetcode(), trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Close the mirror opened for a given source ticket                |
//+------------------------------------------------------------------+
void MirrorClose(long src_ticket)
  {
   string want = StringFormat("KLmir#%I64d", src_ticket);

   // A limit that never filled must be cancelled when the source closes, or it sits in
   // the book forever holding the single mirror slot and blocking every later signal.
   for(int i = OrdersTotal()-1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      if(OrderGetString(ORDER_COMMENT) != want)    continue;
      bool ok = trade.OrderDelete(t);
      PrintFormat("KLMirror %s unfilled limit for src=%I64d (ticket %I64u) - price never came back",
                  ok ? "CANCELLED" : "FAILED TO CANCEL", src_ticket, t);
      return;
     }

   for(int i = PositionsTotal()-1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_COMMENT) != want)    continue;
      bool ok = trade.PositionClose(t);
      PrintFormat("KLMirror %s mirror of src=%I64d (ticket %I64u)",
                  ok ? "CLOSED" : "FAILED TO CLOSE", src_ticket, t);
      return;
     }
   // Not an error: the mirror may already have hit its own stop or target, which is
   // the normal case since the two sides resolve at opposite barriers.
   PrintFormat("KLMirror: no open mirror for src=%I64d (already resolved)", src_ticket);
  }

//+------------------------------------------------------------------+
//| ORPHAN BACKSTOP - not a trading rule                              |
//|                                                                   |
//| Deciding when a pending has become pointless is the MASTER's job. |
//| The demo rulebook already does it: rule 8 cancels any resting      |
//| order once its entry drifts beyond 1.5x ATR(M15) from price,       |
//| because an unreachable order holds the only slot and blocks every  |
//| setup that arrives while it waits. That cancellation now relays    |
//| here as PEND_CANCEL, so the mirror follows automatically and the   |
//| two sides cannot diverge. Duplicating that logic here would be     |
//| worse, not better - two independent judgements on one trade.       |
//|                                                                   |
//| What this DOES guard is the case the relay cannot cover: the       |
//| publisher dying while a mirror order rests. The signal would never |
//| arrive, and a GTC order on a REAL account would sit indefinitely,  |
//| possibly filling hours later with nothing on the demo side facing  |
//| it. So the age here is deliberately generous - long enough never   |
//| to interfere with normal operation, short enough to bound that.    |
//+------------------------------------------------------------------+
void ExpireOrphanPendings()
  {
   if(InpPendingMaxMin <= 0)
      return;
   for(int i = OrdersTotal()-1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      datetime setup = (datetime)OrderGetInteger(ORDER_TIME_SETUP);
      int age_min = (int)((TimeCurrent() - setup) / 60);
      if(age_min < InpPendingMaxMin) continue;
      bool ok = trade.OrderDelete(t);
      PrintFormat("KLMirror %s orphaned pending %I64u after %d min - no cancel signal "
                  "arrived, publisher may be down", ok ? "EXPIRED" : "FAILED TO EXPIRE",
                  t, age_min);
     }
  }

//+------------------------------------------------------------------+
//| A resting limit counts as "holding the slot" just as a position   |
//| does - rule 1 on the demo side is one at a time, and the mirror   |
//| has to match that or it will stack orders.                        |
//+------------------------------------------------------------------+
bool HasOpenMirror()
  {
   for(int i = PositionsTotal()-1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return(true);
     }
   for(int i = OrdersTotal()-1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetInteger(ORDER_MAGIC) == InpMagic)
         return(true);
     }
   return(false);
  }
//+------------------------------------------------------------------+
