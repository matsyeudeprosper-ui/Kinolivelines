# Kino upgrades — log and next steps

Owner's principle (2026-11-03): no "if X do Y" rules. Engines that work like a person, in any field of life, not just trading.

## Done

| Date | What | Kind | Where |
|---|---|---|---|
| 11-03 | Ways notebook: what each person taught him about how they do and want things; newest word wins; editable | engine | robots/kino_ways.py, chat menu "Ce que tu m'as appris" |
| 11-03 | They see: his intuition notices what the person sees that he hasn't said | sense | kino_read they_see → kino_person |
| 11-03 | Hearing himself: words, numbers, apologies, repeated phrases over 24 h | measurement | _voice_mirror |
| 11-03 | Price levels checked against what he was given | check | kino_one.unknown_figures |
| 11-03 | Speed: heavy memory prepared ahead (every 100 s while active); fresh parts at reply time | engine | _one_prefetch, _one_fresh |
| 11-03 | Attention: how much the person can take in right now | measurement | _one_fresh |
| 11-03 | Lessons drawn the same day after 3 slips | engine (extended) | kino_read → kino_social.lessons_night |
| 11-03 | New conversation sees where the last one stopped | sense | _one_fresh |
| 11-03 | Push leads with the action | ux | _kino_msg_push |
| 11-03 | Owed (open commitments), today's timeline, slow mood as tone, what he is busy with | senses | robots/kino_human2.py |
| 11-03 | Fields: notes per new field (learned / unclear / next question) | engine | robots/kino_fields.py |
| 11-03 | Beliefs held and defended, changed for a reason | wording of an existing engine | kino_beliefs.block |

## In progress (owner "go", 11-03 evening)

1. Trust: latitude per kind of action, learned from what the person approves, corrects or undoes (decays over weeks); replaces the single fixed-step number.
2. Conflict check inside the action path: before he acts, his action is compared with the person's notebook; a conflict turns it into a question, not a silent act. Replaces the fixed sentence.
3. Patterns in any record: hypotheses from a person's own records, re-checked on new data, only survivors kept; replaces the hard-coded 4-hour trade buckets.

## Next (proposed)

- Thinking before speaking on hard questions: "let me check" that really comes back with the answer.
- Opinions that persist across days: views he brings up himself, not only when asked.
- Emotional range in his words (not only reports of feelings).
- Many members at once: a test with 5+ synthetic members to prove no mixing.
- Getting up to speed in a field: active learning (asking, reading with his browser, checking he understood).
- Voice: hesitation and laughter on calls (TTS side).
