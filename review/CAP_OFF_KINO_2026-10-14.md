# Daily profit cap on/off - Mike's account (package valere), 2026-10-14

Owner question: "what is the bot's result if there's no daily profit cap?"
Replay: lab/harness.py (same engine and rules as the live bot), package `valere` with the live
pullback-direction filter ON (mode trend), 41.7 days of BTCUSD M1 (2026-09-02 -> 2026-10-14),
spread 7, lot 0.02 (engine dollars, not account dollars). Script/json: study/cap_off_kino_2026-10-14.*

| cost | cap $3: trades / net / worst | no cap: trades / net / worst | verdict |
|---|---|---|---|
| spread only | 45 / +40.12 / 26.42 | 63 / +84.56 / 26.42 | A (both halves better, worst same) |
| + $0.35 drag | 49 / +10.98 / 32.36 | 61 / +47.78 / 32.36 | A |

First run without the filter (wrong vs live) for the record: B at spread only, C with drag.
Matches the 2026-10-10 matrix (cap off = more money, same dip). Small sample; owner decides.
