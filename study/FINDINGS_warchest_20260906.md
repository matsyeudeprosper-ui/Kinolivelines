# War-chest recovery (version C) — tested and DEPLOYED 2026-09-06

User idea: in debt, collect small wins into a chest; a fighter only
fires when the chest can pay for its risk. Recovery bullets are bought
with fresh winnings, never with base capital.

## Results (M1 replay, 69 days + Sep 1→6 window, half-TP config)

| variant                         | 69d net | maxDD | worst day | Sep  |
|---------------------------------|---------|-------|-----------|------|
| deployed rulebook (doors)       | −104    | 145   | −44       | +4.0 |
| chest strict (1 fighter/69d!)   | −41     | 46    | −3.9      | −2.7 |
| control: no gate, same mechanics| −42     | 50    | −8.8      | −4.9 |
| **C: wins-only fill + half-bar**| **−39** | **44**| **−4.0**  | −2.3 |
| C + 2-win-streak key            | −43     | 48    | −3.9      | −2.6 |
| double-cycle (entry+1 fighter)  | −90     | 95    | −16       | −2.0 |
| double-cycle, full-bank bar     | −87     | 97    | −20       | +1.0 |
| double-cycle, fighter waits     | −58     | 77    | −15       | −9.5 |

Key lessons:
- The big saving comes from trading SMALL while in debt (spread scales
  with lots). The chest gate adds calm, not profit — fighters funded by
  the chest are net-free (22 fired in C, same net as 1 fired).
- Strict rules starve the pot: only wins fill it, and the bar is HALF
  the fighter risk, else fighters never fire (1 in 69 days).
- The double-cycle (auto door-fighter per page) costs ~$50 vs C: 82%
  win rate but avg loss −2.13 vs avg win +0.26, and the debt book never
  clears (~$170 left after 69d) so scaled cycles fire forever.
- Streak key ("2 wins in a row") changes nothing measurable.
- All variants still lose over 69d — this is loss management, not edge.

## Deployed rules (owl_manual_bot.py, CHEST_MODE=True)
- Doors/flip-waits OFF; all entries from fresh structures.
- Losses → debt book. In debt: 0.01 collection pages; TP wins fill
  the chest (wins-only; losses don't drain it).
- Fighter (next_lot, ladder +0.01, cap 0.04) fires on a structure
  signal when chest ≥ 0.5 × dist·lot, wall ≥ 60pts, risk ≤ $35.27.
  Registered in recov_links → inherits lock40/partial85/bank70/heal.
- Fighter exit=sl: chest spent, ladder steps, debt grows if negative.
  Fighter win: whole book cleared, ladder resets 0.02.
- Ledger persisted in state + owl_ledger.json → app card
  "Plan de récupération" (dette / cagnotte / progress bar).
- Rollback: CHEST_MODE=False + restart, or
  owl_manual_bot.py.rollback-prechest-20260906.
