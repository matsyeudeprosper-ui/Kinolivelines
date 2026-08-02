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
//   A demo BUY becomes a SELL here. The ENTRY is mirrored - one spread away, which is
//   inherent because you cannot buy and sell at one price. The EXIT is not mirrored at
//   all: this side always aims for +$1.00 and risks -$2.00 in account currency, computed
//   from its own entry, and the demo's own stop and target are ignored.
//
//       demo BUY  entry E,     SL E-20, TP E+40      ($1 risk, $2 reward)
//       mirror    SELL E-spread, TP -$1.00, SL -$2.00 from ITS entry
//
// WHAT THIS COSTS - and what it gives up
//   An earlier version put both accounts' barriers on the SAME two prices with their
//   roles swapped, so the two closed on the same tick and every demo loss was an equal
//   live win. That version cost exactly one spread per pair, always, which is the floor.
//
//   This version does not do that, by explicit user instruction: fixed dollar exits on
//   the live side matter more than simultaneous closing. The consequence is that the two
//   sides close at different prices and different times, so they no longer offset and
//   the combined result becomes path-dependent rather than a fixed number. Do not read
//   the two accounts as a hedge any more - they are two separate trades that happen to
//   start at the same moment in opposite directions.
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
input double InpTargetUSD      = 1.00;        // exit +$1 exactly, in account currency
input double InpStopUSD        = 2.00;        // exit -$2 exactly, in account currency
input int    InpMaxConcurrent  = 3;           // mirrors open at once; was effectively 1
input int    InpPendingMaxMin  = 180;         // orphan backstop only; 0 disables
input string InpSignalFile     = "kl_mirror_signals.csv";
input int    InpPollMs         = 1000;

CTrade   trade;
long     g_seq_done = -1;      // highest sequence number already acted on
bool     g_halted   = false;
ulong    g_resynced[];         // tickets whose SL/TP have been fixed to the real fill

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
   ResyncFilledStops();

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
   // ONE-AT-A-TIME NO LONGER WORKS, because a filled mirror now outlives its source.
   //
   // The demo runs one position at a time, so a single mirror slot used to be exactly
   // right - the mirror was closed alongside the demo and the slot freed immediately.
   // Now that a filled mirror runs to its own barriers it can still be open when the NEXT
   // demo trade appears, and a hard limit of one would silently skip that pair. Skipping
   // is the worst outcome available: the demo takes the trade unhedged.
   //
   // So a small cap instead of one. Overlap should be brief - the mirror's barriers are
   // 20 and 40 points, minutes away at normal volatility - and InpMinEquity plus
   // InpMaxLots still bound the total risk. Anything beyond the cap means mirrors are
   // NOT resolving and something is wrong, so it is worth refusing loudly.
   int held = CountOpenMirrors();
   if(held >= InpMaxConcurrent)
     {
      PrintFormat("KLMirror: %d mirrors already open (cap %d), SKIPPING ticket %I64d - "
                  "this demo trade will be unhedged. Mirrors are not resolving.",
                  held, InpMaxConcurrent, src_ticket);
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

   // THE EXIT IS A FIXED AMOUNT OF MONEY, NOT A COPY OF THE DEMO'S BARRIERS.
   //
   // The demo's sl and tp are deliberately IGNORED here. This side always exits at
   // +InpTargetUSD or -InpStopUSD in account currency, measured from its own entry.
   //
   // The distance is computed from the symbol's contract terms rather than hard-coded
   // in points, so the money stays exact if the volume ever changes:
   //
   //     money per 1.0 of price movement = (tick value / tick size) * volume
   //     distance                        = dollars wanted / that
   //
   // WHAT THIS GIVES UP, said plainly. The previous version put both accounts' barriers
   // on the same two prices, so they closed on the same tick and every demo loss was an
   // equal live win - the pair cost exactly one spread, always. This does not do that.
   // The two sides now close at different prices and different times, so the results no
   // longer offset. That is a deliberate choice by the user: the live exit amounts are
   // what matters, and the demo is free to finish whenever it finishes.
   double tick_val = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz  = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0.0 || tick_sz <= 0.0)
     {
      PrintFormat("KLMirror: bad contract terms (tick value %.5f, tick size %.5f) - skipping %I64d",
                  tick_val, tick_sz, src_ticket);
      return;
     }
   double per_unit = (tick_val / tick_sz) * vol;    // account currency per 1.0 of price
   double tp_dist  = InpTargetUSD / per_unit;
   double sl_dist  = InpStopUSD   / per_unit;

   // SANITY GUARD ON THE CONVERSION.
   // Converting dollars to a distance depends on the broker's contract terms, and a
   // wrong tick value would silently produce something absurd - a 400 point stop where
   // the demo used 20. Measured on this account the conversion gives $1 = 20 points and
   // $2 = 40 points, the same magnitudes the demo runs, so anything far outside the
   // demo's own distances means the contract terms are not what is assumed. Refuse
   // rather than place it.
   double demo_risk   = MathAbs(price - sl);
   double demo_reward = MathAbs(tp - price);
   double demo_big    = MathMax(demo_risk, demo_reward);
   double demo_small  = MathMin(demo_risk, demo_reward);
   if(demo_big > 0.0 && demo_small > 0.0)
      if(MathMax(tp_dist, sl_dist) > 4.0 * demo_big
      || MathMin(tp_dist, sl_dist) < 0.25 * demo_small)
        {
         PrintFormat("KLMirror: REFUSING %I64d - dollar conversion gives target %.1f / stop %.1f points "
                     "against demo %.1f / %.1f. Check tick value (%.5f) and tick size (%.5f).",
                     src_ticket, tp_dist, sl_dist, demo_reward, demo_risk, tick_val, tick_sz);
         return;
        }

   double m_sl, m_tp;
   if(src_is_buy)                                   // mirror SELLS: profit is downward
     { m_tp = entry - tp_dist;  m_sl = entry + sl_dist; }
   else                                             // mirror BUYS: profit is upward
     { m_tp = entry + tp_dist;  m_sl = entry - sl_dist; }
   m_tp = NormalizeDouble(m_tp, dg);
   m_sl = NormalizeDouble(m_sl, dg);

   // Report what the rounding to whole ticks actually bought us, so a symbol whose tick
   // is too coarse to land on $1.00 exactly is visible in the log rather than assumed.
   PrintFormat("KLMirror: %.2f lots -> $%.4f per price unit; target %.2f pts = $%.4f, stop %.2f pts = $%.4f",
               vol, per_unit,
               MathAbs(m_tp - entry), MathAbs(m_tp - entry) * per_unit,
               MathAbs(m_sl - entry), MathAbs(m_sl - entry) * per_unit);

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
//| Source closed: cancel an UNFILLED order, but LEAVE a filled one    |
//+------------------------------------------------------------------+
//
// A FILLED MIRROR IS NO LONGER CLOSED WHEN THE SOURCE CLOSES.
//
// It used to be, and that quietly destroyed the whole point of the pair. The live side is
// given its own fixed dollar barriers - $1 target, $2 stop - and then was shut at market
// the instant the demo closed, so it almost never reached either. Measured over the night
// of 2026-08-01: four of eight live trades exited this way, averaging -$0.39 each, none
// of them collecting the $1 they existed to collect.
//
// 02:38 is the clearest case. The demo SELL was stopped out by a spike UP:
//
//     02:38:35  demo SELL stopped out at 63,458.27   -$1.00   (spike up)
//     02:38:36  live BUY  closed by EA at 63,442.05  -$0.35   (spike already gone)
//
// The live BUY should have profited from exactly that spike. One second later it had
// reversed 16 points and the EA sold into it, so BOTH sides lost. The very move that
// triggers the demo's stop is the move the mirror is supposed to earn from, and closing
// on the same tick gives it away every time.
//
// So a filled mirror now lives its own life and resolves at its own barriers. That is
// what unlinked dollar exits actually means, and it is what the user asked for.
//
// An UNFILLED order is different and is still cancelled: it has no position to protect,
// and leaving it resting would hold the single mirror slot forever and block every later
// signal.
//
void MirrorClose(long src_ticket)
  {
   string want = StringFormat("KLmir#%I64d", src_ticket);

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
      PrintFormat("KLMirror: src=%I64d closed, LEAVING mirror #%I64u open to run to its own "
                  "SL %.2f / TP %.2f. Currently %+.2f.",
                  src_ticket, t, PositionGetDouble(POSITION_SL),
                  PositionGetDouble(POSITION_TP), PositionGetDouble(POSITION_PROFIT));
      return;
     }
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
//| Re-set SL and TP from the price the position ACTUALLY filled at    |
//+------------------------------------------------------------------+
//
// WHY THIS EXISTS. MirrorOpen computes the barriers from the price it INTENDS to fill
// at, because that is all it knows when it places the order. A pending that rests and
// fills quietly does land there - but a STOP order becomes a market order the instant it
// triggers, so in a fast move it fills wherever the book happens to be.
//
// Observed on 2026-08-01 23:20: the mirror was placed for an entry of 63,498.13 with a
// 20-point target and 40-point stop, and filled at 63,504.32 - 6.19 points worse. The
// barriers were left where they were, so from the real fill they measured 14 points and
// 46 points. It stopped out at -$2.32 instead of the -$2.00 that was asked for.
//
// This pass runs every tick, reads POSITION_PRICE_OPEN - the true fill - and moves the
// barriers to sit at exactly InpTargetUSD and InpStopUSD from it. It is idempotent: once
// a position is right it computes the same numbers and changes nothing.
//
// WHAT IT CANNOT FIX. Slippage on the EXIT. A stop order guarantees a trigger price, not
// a fill price, so a $2.00 stop can still cost more when price gaps through it - that has
// been seen on the demo side too, which has no mirror logic at all. This makes the
// barriers exact; it does not make the outcomes exact.
//
void ResyncFilledStops()
  {
   double tick_val = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz  = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0.0 || tick_sz <= 0.0)
      return;
   int    dg   = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   double pt   = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
   double stops= SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_STOPS_LEVEL) * pt;
   double bid  = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double ask  = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);

   for(int i = PositionsTotal()-1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != InpSymbol) continue;

      bool done = false;                      // tried already - do not retry every second
      for(int k = ArraySize(g_resynced)-1; k >= 0; k--)
         if(g_resynced[k] == t) { done = true; break; }
      if(done) continue;

      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol  = PositionGetDouble(POSITION_VOLUME);
      bool   is_buy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);

      double per_unit = (tick_val / tick_sz) * vol;
      if(per_unit <= 0.0) continue;
      double tp_dist = InpTargetUSD / per_unit;
      double sl_dist = InpStopUSD   / per_unit;

      double want_tp = NormalizeDouble(is_buy ? open + tp_dist : open - tp_dist, dg);
      double want_sl = NormalizeDouble(is_buy ? open - sl_dist : open + sl_dist, dg);

      double cur_sl = PositionGetDouble(POSITION_SL);
      double cur_tp = PositionGetDouble(POSITION_TP);
      if(MathAbs(cur_sl - want_sl) < pt/2 && MathAbs(cur_tp - want_tp) < pt/2)
        {
         ArrayResize(g_resynced, ArraySize(g_resynced)+1);
         g_resynced[ArraySize(g_resynced)-1] = t;
         continue;                            // already exact, nothing to do
        }

      // The broker rejects a barrier that price has already reached or is inside the
      // minimum stop distance of. If the move was violent enough for that, the position
      // is about to close anyway and the honest thing is to say so, not to retry.
      double ref_close = is_buy ? bid : ask;
      bool reachable = is_buy
                     ? (want_sl < ref_close - stops && want_tp > ref_close + stops)
                     : (want_sl > ref_close + stops && want_tp < ref_close - stops);
      if(!reachable)
        {
         PrintFormat("KLMirror: cannot resync #%I64u - price %.2f already past the "
                     "corrected barriers (SL %.2f, TP %.2f). Leaving as placed.",
                     t, ref_close, want_sl, want_tp);
         ArrayResize(g_resynced, ArraySize(g_resynced)+1);
         g_resynced[ArraySize(g_resynced)-1] = t;
         continue;
        }

      if(trade.PositionModify(t, want_sl, want_tp))
         PrintFormat("KLMirror: resynced #%I64u to its real fill %.2f - SL %.2f (%.1f pts, $%.2f), "
                     "TP %.2f (%.1f pts, $%.2f). Was SL %.2f, TP %.2f.",
                     t, open, want_sl, MathAbs(open-want_sl), MathAbs(open-want_sl)*per_unit,
                     want_tp, MathAbs(want_tp-open), MathAbs(want_tp-open)*per_unit,
                     cur_sl, cur_tp);
      else
         PrintFormat("KLMirror: resync of #%I64u FAILED, retcode %d (%s). Barriers left at "
                     "SL %.2f, TP %.2f.", t, trade.ResultRetcode(),
                     trade.ResultRetcodeDescription(), cur_sl, cur_tp);

      ArrayResize(g_resynced, ArraySize(g_resynced)+1);
      g_resynced[ArraySize(g_resynced)-1] = t;
     }

   if(ArraySize(g_resynced) > 200)             // keep the list from growing forever
      ArrayRemove(g_resynced, 0, 100);
  }

//+------------------------------------------------------------------+
//| How many mirrors are live right now - positions AND resting orders |
//+------------------------------------------------------------------+
//
// A resting order counts. It is a commitment that can become a position at any tick, so
// ignoring it would let the cap be exceeded the moment the book came back.
//
int CountOpenMirrors()
  {
   int n = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
     }
   for(int i = OrdersTotal()-1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0) continue;
      if(OrderGetInteger(ORDER_MAGIC) == InpMagic)
         n++;
     }
   return(n);
  }
//+------------------------------------------------------------------+
