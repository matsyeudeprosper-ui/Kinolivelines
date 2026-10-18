# Piece ablation on other markets — preregistered 2026-10-18

Goal (owner, verbatim): "We need a second source of edge so we can combine running poches for a higher profit
that's the goal now." Bitcoin is the first proven pocket (Owl beats 40/40 random seeds, review/BTC_RANDOM_CONTROL_2026-10-17.md).
Gold / Nasdaq / Dow win money on the 60-day bench but sit inside luck (80th–90th of the random draws).

Question: is one of the Owl's Bitcoin-tuned FILTER pieces (entry and exit kept as they are) what holds the other
markets inside luck? Suspects named BEFORE any run:

| twin | filters kept | what it tests |
|---|---|---|
| Owl sans Orage | tendance-fond, mouvement | the storm ceiling (Bitcoin percentiles) |
| Owl sans Mouvement | tendance-fond, orage | the movement brake (Bitcoin points) |
| Owl sans Tendance | orage, mouvement | the background-trend filter |
| Owl sans filtres | none | all three at once |

Markets: XAUUSD and USTEC (the two closest to the 95th line). Bench: the same 60-day tick packs as the Owl's own
market tests (17 Aug -> 15 Oct 2026), drag 0.35, $200, package base. One replay per twin per market, no seeds.

## Reading rule (fixed before the runs)
- Noise band = the random control's middle half on that market: XAUUSD −22.6 .. +24.6 (Owl, 20 seeds),
  USTEC −12.5 .. +17.1. A twin must beat the Owl by MORE than the band's width (~47 on gold, ~30 on Nasdaq),
  on BOTH halves, on BOTH markets, to count.
- Only a twin that passes gets the 40-seed random control (2 h). Nothing else is retuned on this window.
- A twin that wins by removing a brake is the closed "trade-reduction" family in reverse: more trades. It still needs
  the control; the Bitcoin brake measurement (removing Mouvement costs 43–65 % and doubles drawdown) stands for Bitcoin.
- Nothing live changes whatever the result (owner order 2026-10-17).

## Runs (60-day packs, $200, drag 0.35)
| robot | gold | Nasdaq | both halves gold | verdict |
|---|---|---|---|---|
| Owl (reference) | +27.54 | +22.35 | +0.93 / +26.61 | - |
| sans Orage | **+59.87** | -16.22 | +30.32 / +29.54 | gold only; 20-draw control 95th (19/20) -> 40-draw confirm queued |
| sans Mouvement | +19.23 | +10.42 | - | worse on both: eliminated |
| sans Tendance | -27.04 | -60.61 | - | much worse on both: the trend filter does real work |
| sans filtres | -62.54 | -62.94 | - | worst: the filters together carry the edge |

Reading: no filter is "incompatible" with both markets. Removing the trend filter or all filters destroys the
result everywhere, removing the movement brake costs a little everywhere. Only the storm ceiling looks Bitcoin-tuned
on GOLD (and helps there), while it protects Nasdaq. Candidate = a gold-only robot without Orage, pending the
40-draw control (gold history: 19/20 once became 36/40).

Incident during the runs: the runner's automatic 4-process controls starved the VPS ~17 min (live bots froze, no
open position); fixed in study/robot_runner.py (wait for room, 2 processes). See memory feedback_research_starved_live_bots.
