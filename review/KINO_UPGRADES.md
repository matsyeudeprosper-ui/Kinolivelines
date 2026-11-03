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

## Done 11-03 evening (owner "go" - proper engines)

| What | Kind | Where |
|---|---|---|
| Trust per kind of act (order:open / close / modify, robot, build, auto): Beta belief from approvals and corrections credited to his acts of the last 30 min, 14-day fade. Replaces the single fixed-step number | engine | robots/kino_trust.py, fed by kino_read about_kino_act |
| Conflict check in the act path: an order he sends alone is checked against the person's notebook; a conflict becomes a confirm card with the reason. The fixed "say it out loud" sentence is removed | engine | robots/kino_conflict.py, _order_direct |
| Patterns in any record: hunches from slices of a person's records, re-checked on new records only, dropped after failing; adapters per source (trades first). Replaces the 4-hour trade buckets | engine | robots/kino_patterns.py |

Known limits: an undo (person closing or changing his act right after) is not yet counted as a correction; the conflict check runs for orders only (not robot switches yet); patterns need about 12+ records and found nothing on the owner's last 30 trades (correct: no strong pattern).

## Done 11-03 late

| What | Kind | Where |
|---|---|---|
| A hand close or a stop/target change right after his order counts as a soft correction of that kind of act | engine (trust) | kino_trust.undone, member order route |
| A robot switch he does on his own is checked against the person's notebook; a doubt becomes a question | engine (conflict) | _desk_robot_set |
| Isolation test: 5 made-up people, notebook / trust / patterns stay apart, field notes hold no names | test | live/review/test_kino_isolation.py (passes) |

"Let me check" that comes back already exists (the `regarde` lookup: 17:32 "let me check" -> 17:34 answer); a deeper multi-step "work it out" stays next.

## Done 11-03 21:xx

| What | Kind | Where |
|---|---|---|
| Hearing himself misquote: a message that restates the person's rule differently from their newest word (an added "fully", a "1-minute" they never said) is rewritten once in their wording before it goes out | engine | kino_conflict.misquote, _one_turn |

| Voice follows feeling: his strongest live feeling (habituated) becomes a delivery note for read-aloud (gpt-4o-mini-tts instructions, in the cache key) and for live calls (realtime instructions); natural hesitations where a person makes them | engine link | _voice_delivery, _tts_mp3, live_session |

## Next (proposed)

- Thinking before speaking on hard questions: "let me check" that really comes back with the answer.
- Opinions that persist across days: views he brings up himself, not only when asked.
- Emotional range in his words (not only reports of feelings).
- Many members at once: a test with 5+ synthetic members to prove no mixing.
- Getting up to speed in a field: active learning (asking, reading with his browser, checking he understood).
