# Three brakes suggested by the loss profile, replayed (2026-09-28)

Owner, after `valere_loss_profile.py` showed Valere's 13 losses were quick
follow-ups (median 23 min after the previous close), opened after a big
hour (+375 pts), more often on weekends: "run the untested ideas replayed
properly". `loss_profile_gates_test.py`, real `B.Struct()` engine, 41.7 days
of M1, spread 7, each brake ON TOP of the deployed rules, halves independent.

| brake | trades | win | net | worst debt | halves (net) |
|---|---|---|---|---|---|
| A deployed | 260 | 60.8% | +163.82 | 63.26 | +161.80 / −5.69 |
| wait 30 min after a close | 201 | 61.7% | +57.38 | 91.37 | −50 / −55 |
| wait 60 min after a close | 162 | 59.3% | +57.01 | 96.71 | −78 / −27 |
| no entry after a 300-pt hour | 230 | 61.3% | +137.97 | 61.58 | −61 / +35 |
| **no entry after a 500-pt hour** | 257 | 60.7% | +163.40 | **49.71** | −29 / +29 |
| no Sunday | 214 | 61.7% | +178.65 | 61.15 | −26 / +41 |
| no weekend | 189 | 61.4% | +136.05 | 71.12 | −61 / +33 |

## Verdicts
- **Waiting after a close: NO.** Loses two thirds of the profit and makes
  the debt worse in the full period. The quick follow-ups are the recovery
  working, not a flaw.
- **No weekend: NO.** −$28 and worse debt.
- **No Sunday: not proven.** +$15 over the full period but the halves
  disagree (−26 / +41); one bad Sunday on the live account is the whole
  story so far.
- **No entry after a 300-pt hour: NO.** −$26, halves disagree.
- **No entry after a 500-pt hour: the only one worth watching.** Same
  profit (−$0.42), worst debt −$13.55, and the drawdown improves in BOTH
  halves (−11 / −28) while the net halves cancel out (−29 / +29). It blocks
  only 20 of 260 entries, so the evidence is thin. Not deployed; a rule
  change is the owner's call and would need `package_parity.py`.

Bottom line for the owner: none of the three stories behind the losses
survives as a money rule. The one that costs nothing is "skip an entry when
the last hour already ran more than 500 points"; it trims the worst debt
without touching the profit, on 20 trades.
