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

| Weekly self-review of his own behaviour: his Sunday look back now reads the record of his week (reactions to his acts by kind, slips and lessons, misquotes caught, acts held back, what people taught him) and writes the ONE thing about how he behaves that he wants to change, and how he will notice | engine link | kino_human2.week_mirror, kino_work WEEKLY |

| Reflection driven by what nags, not the calendar (owner: "do humans wait for a day to review?"): corrections, slips, misquotes, held-back acts and undos stir an unresolved nag (weighted, fades in a day); in a quiet moment (10 min without talk, nothing running) a high nag brings him back to it and he settles 1-2 resolves in his own words; the same situation coming back reinforces a resolve ("being tested right now"), unused resolves fade in days. Replaces the "3 slips" trigger; the Sunday look back stays as an optional habit | engine | robots/kino_rumination.py, _urge_tick, kino_read |

## Done 11-03 late: what people naturally do (list 3, all 10)

| What | Kind | Where |
|---|---|---|
| Learns preferences from BEHAVIOUR, not only words: how the person answers his messages (length, numbers, ends with a question, hour, weekday) becomes patterns that are re-checked on new data. First real finding on the owner: he answers 95% of the time when Kino ends with a question, 66% otherwise; less often 00-04 UTC | engine (adapter on kino_patterns) | kino_human3.habits_line |
| Follow-ups on their life: something coming up they mention (an exam, a trip) is held with a due time; when it has happened he sees it once until he has asked | engine | kino_read 'upcoming', kino_human3.followup_line |
| Imperfect memory: a notebook word not heard again fades (half after 3 weeks) and is shown as held less surely; saying it again makes it fresh | engine | kino_ways.sureness |
| Shared language: words that became theirs grow with use | engine | kino_read 'shared_term', kino_human3.shared_line |
| Repair after friction: a tense moment is kept for 12 h with what happened since and how they seem now | engine | kino_read 'friction', kino_human3.friction_line |
| Learned rhythm: their busiest hour, their quiet stretch (found across midnight), how they open after a long gap - from all their chats (seeded from history; owner: busiest 17:00, quiet 03-07 UTC) | engine | kino_human3._day / rituals_line |
| Saying no from his own values: his constitution (values + refuse) is held up to each request (intuition read) and to each act he does on his own (conflict check); a standing OK in their notebook counts as their OK (tested: owner auto trade at step 1 passes, unasked order is held) | engine link | kino_read 'asks_against', kino_conflict.check, against_line |
| Experience across people with nobody in it: a resolve settled with one person that matches another person's resolve becomes one general lesson (no names, no digits, checked against every member name) | engine | robots/kino_wisdom.py, kino_rumination.quiet |
| Opening up gradually: closeness from days known, messages across all chats and relationship trust; how much of himself he shares follows it | engine | kino_human3.closeness_line |
| Tiredness: a long stretch without a real break (25 min gap) with his slips in it; either can call a pause | engine | kino_human3.fatigue_line |

## Done 11-03 late (round 4) - checked against what already exists first

Already there, NOT rebuilt: his own repeated phrases (tics / _voice_mirror), what he said about himself (kino_said), closeness (kino_social.block), timing his own messages to their hours (_active_hour, kino_urge).

| What | Kind | Where |
|---|---|---|
| Questions left hanging, both ways: a question either of them asked that the talk moved past stays open (2 days) until the read sees it answered or taken up | engine | kino_read 'dropped_question' / 'answered_now', kino_human3.questions_line |
| A talk cut off by a trade event: where it was (topic, what about) until the talk comes back to it; nothing when they changed subject themselves or it was trade talk | engine | kino_human3.thread_line |
| Duplicate closeness line removed (kino_social already measures it); rhythm now in the person's own clock | fix | kino_human3 |

## Done 11-03 late (round 5) - from the watch numbers

| What | Kind | Where |
|---|---|---|
| Surprise scaled by how unlikely the outcome was with THAT person: P(what came / what he guessed) learned from his earlier checked guesses; a coin flip surprises no one, a rare outcome surprises more. Owner (std): 29 "my read was off" -> 4 | engine | kino_surprise._people |
| The intuition is told what "short" means in the check (under 40 characters) | fix | kino_read 'next' |
| TRIED AND DROPPED: showing the intuition its own guess record. Replay on 24 real points: old 10/24, new 10/24 (always-"long" 12/24) - no effect; his answer length is not predictable from the talk (when it guessed short: short 17, long 15) | measured null | - |

## Done 11-03 late (round 6)

| What | Kind | Where |
|---|---|---|
| His hand follows his mouth: before an order goes out on its own, the words he sends with it and his questions to the person not yet answered are part of the check - "I'm holding off, do you want that wide stop?" sent WITH the order (17:50) now becomes a question card. Tested 4 cases: the 17:50 one held, a plain "taking the sell" passes, an unrelated old question passes, an unanswered sizing question holds | engine (kino_conflict own words) | kino_conflict.check(words, pending), _order_direct |
| Watch metric fixed: "4-word repeats" counted the server's "-> Order sent" lines, error bubbles and every overlapping 4 words of one repeated sentence (48) - now repeated phrases in his voice (14 in 12 h, mostly "the first red candle") | measurement | review/kino_humanity.py |

## Done 11-03/04 (list 7)

| What | Kind | Where |
|---|---|---|
| LIVE FIX: the top-chart line called the stand-in candle (the newest lower candle, always added by pullback_view) "its latest candle", so the real move candle (23:22, closed bullish 23:23) read as "before it" and the 23:29 first red was missed. Now: last REAL top candle + when it closed, the stand-in named, and the lower candles closed since, in order with colour. Replayed at 23:31:15: "...23:23 green, 23:25 green, 23:27 green, 23:29 RED" | fix | _pb_top_line |
| Glancing back after acting: 5-20 s after his order, what the account shows is held against what he sent (side, size, stop, target - target as re-set from the fill); a difference wakes him to say what he found and stirs a nag | engine | robots/kino_lookback.py, _look_back, _order_direct |
| Noticing he had to be asked twice: the read flags a re-ask with what was meant vs what he answered (real 22:55 "yes but your bet...?" caught; 22:54 not); shown while fresh + count this week; stirs a nag | engine | kino_read 're_asked', kino_human3.misread_line, kino_rumination 'misread' |
| TRIED AND DROPPED: learning what he usually asks per situation. 526 questions seeded from 3 weeks; trained on all but the last 3 days, the top-3 per situation predicted 2 of 41 recent questions (top-3 overall: 1/41); 164 kinds, his questions follow the day's work | measured null | - |

## Next (proposed)

- Thinking before speaking on hard questions: "let me check" that really comes back with the answer.
- Opinions that persist across days: views he brings up himself, not only when asked.
- Emotional range in his words (not only reports of feelings).
- Many members at once: a test with 5+ synthetic members to prove no mixing.
- Getting up to speed in a field: active learning (asking, reading with his browser, checking he understood).
