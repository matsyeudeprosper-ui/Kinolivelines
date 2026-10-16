# Backtest precision plan (owner GO 2026-10-15)

Goal: robot tests members can trust - one method for every robot, market and broker, with its accuracy measured.

| step | what | status |
|---|---|---|
| 1 | Fidelity vs a real account (Valère, synchronised replay) | DONE 10-15: decisions 98.4%, median $0.10/trade; add-risk bug fixed (reply 22) |
| 2 | Re-run every test with the fixed engine | DONE 10-15: BTC Pekos owl +68.58, Owl +51.10; no other market passes the real-money rule |
| 3 | Fair display: per 30 days, trade count, "peu" under 80 | DONE 10-15 (Zone de test) |
| 4 | Precise data for every market: real broker ticks -> 1-second bid/ask, same window for all, pulled on an IDLE terminal only | NEXT |
| 5 | Tests on the MEMBER'S OWN broker (their prices, spread, symbol, contract size, min lot), BTC included, as markets already do; label "Testé sur <courtier>" | after 4 |
| 6 | Fidelity per broker: proven only where real trades exist - say so on the page until a member of that broker has trades to compare | after 5 |
| 7 | Re-run everything, stamp each result with engine version + data fingerprint; re-run on any engine change | last |

Honest limit: no past test is beyond question; what can be guaranteed is the same method for everyone,
reproducible, with its measured accuracy shown.
