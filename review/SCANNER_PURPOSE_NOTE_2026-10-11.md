# Setup scanner - purpose, status and decisions for GPT (2026-10-11, evening)

Follows `review/SCANNER_V2_REPORT_2026-10-11.md` (method, fidelity, calendar backtests, the five corrections
after GPT's review). Nothing live changed; the frozen entry study is untouched.

## Owner's question
Mike, looking at the Scanner screen (four indices "Bientôt"): "Here's what we are building already. How would
that serve us?"

## The answer given (Claude)
1. **Research, now** - it answers "can the robot's setup trade elsewhere when BTC is blocked?" with live
   records from the robot's own engine on 12 low-BTC-correlation markets, at no cost or risk. After 4-6 weeks
   the virtual column can confirm or contradict each market's backtest; a market that holds becomes a candidate
   for a second robot, on demo first.
2. **Learning about the rule** - the same setup already differs sharply by market (USTEC/XAUUSD positive,
   GBPUSD clearly negative over the same 30 calendar days). Understanding why may show when the setup works and
   when the BTC robot should stand aside.
3. **Product, only once proven** - for Signal members (manual traders) a live "where is a setup now" list is a
   distinctive feature and keeps the app useful when BTC is quiet. It must NOT be presented as something to
   follow before the virtual results prove it: today "Bientôt" only means the structure is near a trigger.

Told plainly: today it is a watch list with records, not a source of trades.

## Status at this check-in
* Daemon `live/owl_scanner.py` (engine tag `v2-robot-struct`) running since 2026-10-11 23:04 UTC with the
  corrections (calendar windows, no entry on a candle older than 90 s, restart replay of open virtual trades).
* `live/scanner/forward.jsonl`: no virtual trade yet (markets reopening after the weekend); first logged
  refusal: USTEC `against_structure`.
* Backtests (30 calendar days) in `live/scanner/backtest_<SYM>.json`.

## Decisions that are GPT's
1. **Random-entry control** design per symbol (same count, same direction rule, same stop-distance
   distribution) for the leads USTEC, XAUUSD, US30, US500 - and whether to add halves / the previous 30 days.
2. **Preregistered forward criterion** before any symbol is considered further (e.g. >= 30 virtual trades;
   forward avg R > 0 after a cost haircut and inside the backtest's bootstrap interval).
3. **When / whether the scanner may be shown to Signal members as more than a test**, and with what wording
   (Claude's proposal: only symbols that passed, labelled as tests, never as advice).
4. Whether the scanner should also model the weather brakes so the BTC line can be compared with the robot's
   *taken* trades, not only its signals.

## Small UI item noted, not done (owner has not asked)
The row subtitle is cut on a phone ("se rapproche de son déclench…"); proposed: shorter text and a distance in
the market's own unit ("à 0,4 % du déclencheur") instead of a bare bar.
