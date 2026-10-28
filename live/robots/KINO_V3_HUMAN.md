# Kino v3 - the human-way engines (2026-10-28)

Owner: "the goal is a human-way simulator engine for each of those. Nothing done in an if-x-then-y manner. Study how it works
for humans and reproduce it as well as possible."

Principle: each engine models a MECHANISM people have (a state that changes over time, fed by what happens) and hands the
one mind a FELT STATE in plain words - never a rule about what to say. The one mind decides. No word filters, no judges.

| # | Human behaviour | How it works in people | Engine |
|---|---|---|---|
| 1 | Knowing their own things | Self-knowledge is always available, approximate ("about 70 trades, under half won") | my_robot_short (done 10-28) |
| 2 | Reading the other person | Theory of mind runs continuously: cues (words, timing, length, emoji, topic shifts) -> an implicit read of mood, energy, what they are reaching for ("bid"); predictions get checked and the read improves | kino_read: a fast intuition pass after each message of theirs, feeding kino_person (reading + prediction score); shown as "your read of him - your gut, it can be wrong" |
| 3 | Not answering everything / not repeating | Attention goes to what is NEW (habituation: an unchanged fact stops being noticed) and to the other's bid | told ledger: what he already told about each live thing (trade P&L, levels) and how much it changed since -> facts carry "already told N min ago; barely moved" |
| 4 | Steady opinions | Beliefs have confidence; new evidence moves them a little; contradicting yourself is felt (dissonance) and either resisted or owned as a change of mind | kino_beliefs: his stances harvested from his own words, with confidence, evidence and history; shown when the topic is near |
| 5 | Shared history | Recall is cued by similarity to now, and emotional moments are easier to recall | kino_episodes.recall (exists) - cue from the live talk |
| 6 | Endings and silence | People feel a conversation's energy (shorter replies, slower answers, closing words) and let it rest; silence is comfortable | the read (2) carries engagement and "winding down"; with the wish-to-talk engine he can simply stop |
| 7 | A day of his own | A circadian rhythm (energy rises, dips after lunch, fades at night) and a day made of real activities | kino_day: his energy curve in his own time zone + what he really did today (tests, research, his robot, plan items) |
| 8 | Variety of tone | Mood colours voice: tired = short, excited = fast and warm, annoyed = dry | mood (kino_inner feelings, the day's energy) given as how he feels right now, with its cause |
