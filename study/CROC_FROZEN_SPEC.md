# PURE CROC — FROZEN SPECIFICATION (v1.0, frozen 2026-08-24)

The exact rule set that produced +$1,700.42 / +$23.53 per month over 6 years
(eras +$1,082.21 / +$226.97 / +$380.08, zero deaths), as implemented in
`kino_rangesweep_panel.py` run with arguments `500 30 12 off off`.
NOTHING below may change during validation.

## Data & costs
- Price series: Coinbase BTC-USD M1 OHLC (6 years, stitched parts) + the most
  recent ~99,000 bars of real Exness BTCUSDm M1 from MT5. Single symbol.
- Bars are treated as bid. SPREAD = 10.0 price points, charged on BUY entries
  only (buy entry price = next bar open + 10; sells enter at next bar open).
  Sell exits are not spread-adjusted (asymmetric approximation, ~$0.10 average
  round-trip cost per 2-leg entry at 0.01+0.01 lots). Cost stress tests scale
  this SPREAD constant.
- No commission, no slippage beyond the spread convention. Same-bar TP touch
  uses bar high/low of the bid series.

## Range construction
- Range = highest high and lowest low of the last 12 COMPLETED H1 candles
  (H1 candles aggregated from the M1 stream; the forming hour is excluded).
- Dead-range guard: no signals while (rangeHigh − rangeLow) <= 50 points.

## Sweep detection & persistence
- Evaluated on every COMPLETED M1 bar.
- If bar low < rangeLow: swept_lo flag set. If bar high > rangeHigh:
  swept_hi flag set.
- Flags persist within the clock hour and RESET at every hour boundary
  (swept_lo = swept_hi = False). They also reset on entry.

## Reclaim & entry
- BUY: swept_lo is set AND the current completed M1 closes back ABOVE
  rangeLow AND the close is above the open (green body).
- SELL: swept_hi is set AND the M1 closes back BELOW rangeHigh AND red body.
- No reclaim-candle quality rule, no sweep-depth rule, no minute-of-hour
  restriction, no light/trend/session/D1 filter. Signals allowed on every
  hour of every day.
- Entry executes at the NEXT M1 bar's open (+10 pts if BUY). One entry per
  clock hour maximum (shared counter across both directions).

## Position & exits (the full active exit stack)
- Size: two positions of 0.01 lots each, same direction, same entry price
  ("split legs"). $1 price point = $0.01 per 0.01 lot.
- Initial TPs at assignment: newest leg entry +150 pts ($1.50); the other leg
  +75 pts — immediately re-assigned by recovery (see below), so in practice
  both legs target +150 while unharmed.
- RECOVERY (re-run on every position-set change): per direction, sort open
  positions by entry order. Newest keeps TP = entry + 150. Older positions:
  if price >= its entry ("winner") TP = entry + 150; if price < entry
  ("loser"), losers are paired deepest-with-shallowest at joint TP =
  midpoint + 5 pts; an odd unpaired loser gets TP = entry + 5 pts
  (breakeven escape). Mirror for sells.
- ESCAPE (rare): on an H4 regime flip against open positions with both
  directions hedged, wrong-way legs get breakeven TPs, oldest trend leg
  holds without TP (frozen), plus an H1-close deadline cut. (Inherited from
  the engine; fires on a tiny fraction of Croc trades.)
- TIME STOP: any position still open 30 minutes after entry closes at the
  current bar open (NMIN = 30).
- HOUR-CLEAN: a position group from a previous hour whose combined P&L
  >= max($1.00, 50 pts x total volume) is closed at market.
- No stop-loss. Account death threshold ~$8 equity per open position
  (never hit in the frozen run).

## Frozen result (for reference)
+$1,700.42 over 73 months = +$23.53/mo | eras +$1,082.21/+$226.97/+$380.08 |
0 deaths | ~21,990 leg-closes (~150 entries/mo) | max banked DD $283.73 |
worst float -$132.50 | min equity $466.24 from $500 | months 47/73 positive |
worst month -$144.28 | best +$140.56.

## Live implementation delta (disclosed, not part of the frozen backtest)
The live Owl runs HALF size (one 0.01 leg, not two), the same 12xH1 range /
sweep / reclaim / 1-per-hour rules, $1.50 TP via recovery, 30-min time stop,
and additionally the account-wide HOUR-FLAT (everything closed at hour
boundaries) plus stack cap 3 and $50 balance floor. Live fills pay the real
Exness spread on both sides.
