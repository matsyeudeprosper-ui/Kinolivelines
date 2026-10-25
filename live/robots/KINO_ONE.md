# Kino as one mind (2026-10-25)

Owner: "When I ask you to say what a human would say, you get it right; when it comes from Kino it smells of a bot.
I don't want rule-based style - I want a genius AI figuring the response." Then: "Go redesign now."

## Why the old Kino smelled of a bot (measured on the owner's chats, 2026-10-25)

- Every reply read ~120k characters of standing instructions + ~23k per message, in ~35 blocks, mostly "don't" rules.
- The reply was a JSON form (say, chips, mind, them, beliefs, ...), not a message.
- A second model (the judge) rewrote 107 of its last 166 decisions; ~50 text patterns then trimmed what was left.
- Facts arrived as shouted labels ("TEST SUR LES PRIX PASSÉS (pas le fantôme, pas le réel)") and came back in that register.
- First word 13-17 s.

## The design

One mind writes every word (`robots/kino_one.py`):

| Input | What it is |
|---|---|
| SELF (~3.7k chars, stable -> warm cached process) | who he is, how he talks - a person, not a rulebook |
| Facts (`_one_facts`) | plain sentences built by code from the account, robots, tests, luck, jobs - no instructions |
| Memory (`_one_memory`) | portrait, their goal, standing asks, their life, jokes, decisions, his notes, recalled episodes, what he said about himself, open promises, HIS day (journal, thoughts, feelings, research) |
| Thread of mind | the one line he wrote to himself last turn (`#fil`) |
| The conversation | last 40 messages with UTC times |

He answers in plain text. Lines at the end are real actions done by code: `#test <robot>`, `#chance`, `#construire <change>`,
`#retiens <fact>`, and `#fil <thread>` (never shown). "Je lance" is therefore true by construction.

The only check after him is code: a money/% figure that matches nothing he was given (rounding tolerated) goes back to HIM once
with "this figure is not in what you know" - his voice is never replaced by another model's. No judge, no voice gates, no
pattern rewrites for his bubbles (`_chat_msg` skips them when `m["one"]`).

Unprompted turns (events) use the same mind: "nobody wrote to you; write only if you really want to; otherwise answer …".
The pace floors (gap, backoff, quiet hours) still apply before the turn - they are policy, not style.

## Wiring

- A conversation with `c["brain"] == "one"` takes `_one_turn` in `_chat_quick0` (after the pace floors).
- Created from the Atelier sheet (owner only): "Kino · un seul esprit (test)"; test accounts `ONE_TEST_UIDS` (std, fresh, demo)
  can create one too, and their chats never feed his self-ledgers.
- Facts + memory are built while the member is still typing (`_one_prefetch` from `_chat_listen`).
- Logs: `robots/kino_one.log` (TURN first/total/retry/chars/acts/thread), `robots/kino_timing.log` (`one=1`).

## Measured (test account std, 2026-10-25)

| | Old Kino | One mind |
|---|---|---|
| Prompt | ~140k chars | ~8k chars (3.7k self + 4-5k turn) |
| First word (warm) | 13-17 s | 1.7-2.0 s |
| Whole reply | up to 37 s | 3-4 s |

## Blind test

`/<owner token>/blind`: the owner's real messages of the last 3 days, the old reply and the one mind's reply on the same
conversation (generated, never posted), shown as A/B in random order; he picks the more human one. Data in
`robots/one_blind.json`, votes in `robots/one_blind_votes.json`. Note: the one mind reads TODAY's facts, so a figure can differ
from what was true at the time of the old reply - judge the voice, not the number.

## Next

1. Owner's blind verdict decides whether the one mind becomes the default brain (then the old pipeline retires engine by engine).
2. Real tool calls for deep lookups (trade history, a chart moment) instead of a bigger fact sheet.
3. Live calls through the same mind.
4. Opus vs Sonnet for the one mind, measured blind with first-word time (owner's call).
