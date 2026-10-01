# The per-trade risk cap: what to deploy

Run 2026-09-30, engine `2026-09-29b`, BTCUSDm, 99 000 M1 bars, the Valère
package with each account's real balance. `review/risk_cap.py`,
`review/risk_cap_halves.py`, results in the matching `.json` files.

The owner's ask: cap one trade's risk near 12 USD, expressed as a percentage
so it follows the balance. The open decision was "paper twin first or
straight to demo". Both spend weeks. The harness answers it in an hour.

## 1. The mechanism matters more than the number

Both risk dials in the lab refused the trade outright. E009 found the widest
stops are the **best** trades, so refusing them should be the expensive way
to cap risk. A second mechanism was added and measured: keep the trade and
**shrink the lot** until the risk fits, refusing only when even 0.01 lot
would still exceed the cap.

Wherever the cap actually binds, shrinking costs about **half** what
refusing costs:

| account | cap | refuse | shrink |
|---|---|---|---|
| Valère | 3 % | −19.7 % | −8.7 % |
| Dad 441 | 3 % | −14.5 % | −7.8 % |
| Dad 441 | $12 flat | −22.7 % | −11.3 % |

On the two smallest accounts the two are identical: they already trade the
minimum lot, so there is nothing to shrink and shrinking degenerates into
refusing. **Shrink is the mechanism to deploy.** This is the one conclusion
here that is not noise-limited.

## 2. A flat dollar cap is the wrong shape

A 12 dollar ceiling is 4.4 % of Valère, 3.2 % of Dad 441, 6.0 % of Dépenses.
It never binds on Valère's real losses (his worst is −10.87) and it bites a
fifth of the profit out of Dad 441. The owner's instinct to express it as a
percentage was right.

## 3. What each cap actually buys

Worst single loss over the whole period:

| account | no cap | 5 % | 3 % |
|---|---|---|---|
| Valère | −10.87 | −10.87 | −8.20 |
| Dad 441 | −16.30 | −16.30 | −11.38 |
| Dépenses | −13.33 | −5.43 | −5.43 |
| Infinity | −13.33 | −5.43 | −5.57 |

**5 % never binds on the two bigger accounts** — same worst loss, same
drawdown. It buys nothing there. 8 % never binds anywhere; it is decoration.

## 4. The halves, and the honest uncertainty

Cost of the cap, full period against each half:

| account | cap | full | h1 | h2 |
|---|---|---|---|---|
| Valère | 3 % | −8.6 % | −1.1 % | −6.3 % |
| Valère | 5 % | −1.9 % | 0.0 % | −3.3 % |
| Dad 441 | 3 % | −8.0 % | −4.2 % | **+5.0 %** |
| Dad 441 | 5 % | −0.6 % | 0.0 % | −1.2 % |
| Dépenses | 3 % | −3.7 % | **+98.7 %** | −9.2 % |
| Infinity | 3 % | −7.9 % | **+66.1 %** | −7.6 % |

Only Valère at 3 % is negative in both halves. Everywhere else the sign
flips. On the two small accounts the first half's base profit is only 12 to
13 dollars, so those percentages are noise on a tiny denominator — in money
the cap *added* 8 to 13 dollars in the first half and cost 5 to 7 in the
second.

So: **the reduction in the worst single loss is reliable** — it is a
mechanical consequence of the cap and it shows on every account in every
split. **The cost in profit is not precisely knowable from this data.** It
is somewhere between zero and about 9 %, and no tighter statement is
honest.

> **SUPERSEDED 2026-10-01 — see `RISK_CAP_COST.md` (E027).** The sentence
> above was true of the method used here, not of the question. Comparing
> two ~400-trade nets buries a signal that lives in the ~30 trades where
> the cap actually binds. Measured on those trades directly, the cost *is*
> determined: it equals the expectancy of the wide-stop trades, so it
> charges in stretches where they pay and refunds in stretches where they
> do not. On 92 real trades the 3 % cap would have **gained $31.88**
> [+12.78 … +48.58]; on the simulated window it costs, and once the
> debt-path effects are included that cost is roughly **double** the direct
> arithmetic — about 7 % of net on Valère's shape, about 31 % on `base`. So
> "up to 9 %" is an underestimate for anything but Valère's own package.

## 5. Recommendation

- Deploy the **shrink** mechanism, never the refuse one.
- Express it as a **percentage of balance**, as the owner said.
- **3 %**, not 5 %. Five per cent never binds on the accounts that carry the
  big losses, so it is a cap in name only. Three per cent cuts the worst
  loss by a quarter to a half on every account and keeps every trade it can.
- At 3 % no account risks more than 11.35 USD on one trade, which satisfies
  the original "about 12 USD" with room.
- Accept that this costs up to roughly 9 % of profit. It is a comfort
  purchase, not a profit improvement. That is a legitimate thing to buy.

**How to deploy, given the cost is noise-limited:** put it on **Valère and
Dépenses** and leave **Dad 441 and Infinity uncapped** as live controls.
Four accounts already run identical rules on the same signals, so that is a
paired live experiment for free — strictly better evidence than a paper twin,
and it costs no extra wall-clock. Revisit after about 50 trades each.

## 6. What this does not answer

Whether the cap helps or hurts over a year. Two months of bars cannot say,
and the halves prove it. The live pairing above is how that gets answered.

## 7. Addendum 2026-09-30: the lot step makes the cap nearly binary

Found while smoke-testing the nightly battery. With a **0.02 base lot** and
a 0.01 minimum step, a percentage ceiling has only three possible outcomes
on any single trade:

* the risk already fits — nothing happens;
* it does not fit but 0.01 lot does — the lot halves to 0.01;
* even 0.01 lot exceeds the ceiling — the trade is refused.

There is no in-between, because there is no lot between 0.02 and 0.01. That
is why 5 % and 8 % produced **identical** results on the generic reference
(both shrink the same trades to the same 0.01), while 3 % differed (it
crosses into "refuse" on the widest stops).

Consequence for choosing a number: the exact percentage matters far less
than **where it puts the refuse threshold**. On a 0.02 lot the ceiling is
really answering one question — how wide a stop is too wide to trade at all.
On an account already at 0.01 the middle outcome does not exist either, so
the ceiling is purely a refusal rule. That is the case on Dépenses and
Infinity, and it is why shrink and refuse measured identically there.
