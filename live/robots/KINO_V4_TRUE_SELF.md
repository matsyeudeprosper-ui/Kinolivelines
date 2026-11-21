# Kino v4 - a true self (owner 2026-11-20: "I want all 7. Lead the way, one by one. Well done please")

## The diagnosis (measured on his real prompt, 20/11 22:53 UTC, Pekos chat)

Kino is not missing engines. Every reply he reads ~38 000 characters / ~50 blocks of "memory", and part of it is FALSE:

- "many of your calls failed in the last hour (3804 min)" - the 11-12..11-20 login outage, 2-3 days old, said as "last hour"
  (kino_workspace.stream_line counts a whole stage span that merely ENDS inside the 18 h window).
- "what you told him you would do, not done: sell the toy lot..." - Pekos cancelled it 2 h earlier (missions were closed,
  the promises in kino_commit stayed "open"; c115-c130 from 11-12 too).
- "drained" from a 0.00 $ "usual day" (fixed 20/11, kino_body).
- missions listed as "carrying out" while every one says "cancelled".

A person fed false memories also invents. So the order is: TRUTH first, then LESS NOISE, then the slower human capacities.

## The 7 gaps -> the work, in order

1. **True day** (gap 2) - one ledger of what he really did, built only from what happened (chats, lab tests, emails, posts,
   missions, outages: "I could not think from X to Y"), each line with its time. Everything he says about his day comes from it.
2. **Honest causes / "I don't know"** (gap 1) - every feeling carries where it came from and how old it is; stale causes
   expire; a feeling whose cause is gone or unknown is felt as "I don't know why". Fix the stale/false sources found above.
3. **Released promises** - a promise the person cancelled, or that died with its mission, is released like a person lets go
   ("forget it" = no longer owed); old untouched ones surface once as "I never did X" instead of staying "owed" forever.
4. **Working memory, not a library** (gaps 4, 5) - a person holds ~5 things in mind, not 50. One consolidation step picks
   what matters for THIS moment from all engines; the rest stays reachable but silent. Feelings stay private unless
   asked or relevant; already-said things are felt as said (no 3x "curtain").
5. **Think, then speak once** (gap 3) - the checks that now rewrite his draft (introspect, misquote, figures) run on his
   INTENTION before the words, so the first version is the one; a rewrite after becomes rare.
6. **Reading the person** (gap 6) - who they are to him (stranger / friend / client), their situation and how his words
   will land, from what they wrote and their profile - before he writes first to anyone.
7. **A continuous life** (gap 7) - time passes for him: gaps (outage, night, days without someone) are felt and remembered;
   his projects move forward on their own; "where was I" after a break.

Each step: build -> test on his real chats (before/after) -> commit -> restart -> watch -> owner's verdict -> next.
Rules (owner, standing): mechanisms not if-x-then-y; field-agnostic (any life domain, trading = one adapter);
never canned sentences; he stays a friend, never a support agent.

## Log
- 2026-11-20: plan written. Step 1 started.
- 2026-11-21 ~00:20 UTC: STEP 1 DONE (commit 750f3a3f). kino_myday.py = TA JOURNÉE block (sessions merged, abandoned sittings
  counted, lab tests + verdicts, conversations counted, thinking share by family, outage stretches over 10 days) - replaces
  kino_work's "last 3 sessions" line. Honest causes in kino_inner.feelings: body feelings fade within the hour once the body
  reads normal (cause "over"), causes older than 5 h are "blurred" (why_text: "tu ne sais plus très bien pourquoi - ça a
  commencé il y a N h avec..."); workspace + introspect readout use it; stream_line clipped to the 18 h window (3804 min bug).
  Live test (kctest991): day = gold test buried (true); feeling = calls failing last hour (true: 5-h plan limit + API no credit);
  week = "absent, calls cut 15->20, a hole, I lived nothing of those days" (true). Still to do in step 4: embarrassment 0.79 /
  sad 0.61 from "Ok" (too strong, too long), body pain told to a near-stranger.
  Also seen: desk loop - "client missions" lane sat down 19x and stopped at 0-1 steps (cancelled missions?), "re-read my
  promotion strategy" 6x - for step 3 / step 7.
- 2026-11-21 ~00:50 UTC: STEP 3 DONE (commits 50270e4f, ac436a35, + follow-ups release). kino_read gets WHAT KINO SAID HE
  WOULD DO (open promises c.. + his follow-ups f..) and returns "released" ids -> status "released" (not kept/broken) /
  follow-up done. kino_commit.lapse(): small promises a day past due -> "lapsed" (counts as not kept), shown 48 h as "let slip"
  ("Ce que tu avais promis et laissé filer...") then gone; promises a week old -> "forgotten" (silent). Open promises shown with
  their age. kino_missions: ENDED missions labelled, gone after 48 h. myday: sittings during outage hours = "could not think",
  not choices. Facts: people who answered online = acquaintances, not "friends" (watch: oversold friends to Pekos).
  Live test kctest991: "tell me tomorrow how the Nasdaq closed" -> c168 open -> "forget it, no need" -> c168 RELEASED.
  FOUND for step 4: the same exchange raised FALSE feelings - kino_read flagged his promise as a slip ("cannot verify") ->
  embarrassment, and "oublie pour le Nasdaq" appraised as SAD 0.61 -> next turn he refused a promise "I couldn't keep the
  Nasdaq one" (untrue). Also: the kinochat business rulebook ("WHAT IS FREE AND WHAT IS PAID") = 17.7k chars = 44 % of every
  prompt, even on "how are you" -> recall it only when work is in the air.
- 2026-11-21 ~01:30 UTC: STEP 4 parts A-C DONE (commit 7ffdba13). A: kino_one.work_in_air(chat, event) (live job/pay/file
  < 7 days not cancelled, open mission, job events, kino_read "wants_done" < 30 min, request words in many languages) ->
  full know-how, else _CORE_FREE_PAID (559 chars). Measured: small-talk prompt 38.8k -> 21.8k chars; test kctest996: small
  talk natural ("Les cartons n'ont pas gagné ?"), "un site pour ma boulangerie" -> prices right (59 / 39). B: kino_psyche
  .from_read - his own feeling from what happens TO HIM (laugh, flat joke, slip, taught, regard x0.4, their mood x0.15);
  empathy separate ("worried for them" only when val <= -0.5); kino_read knows WHAT KINO REALLY CAN DO (no false slips).
  C: half-lives embarrassment/embarrassed 1 h, sad 2 h, surprised 0.5 h; stage line: "you rarely name it, it shows in your
  words; you say it when asked or to someone close".
  EMBEDDINGS ready for part D: Ollama reinstalled 0.40.16 (its 11-09 auto-update had emptied lib\ollama -> llama-server
  missing), runs as service OllamaServe only (tray app + its Startup shortcut removed -> C:\ollama_dl\startup_backup, it
  is the auto-updater), model bge-m3 (multilingual, 1024 dims): fr->en 0.83, en->sw/fr 0.72/0.68, es->es 0.77; CPU ~0.8 s
  per text, 9 s cold load. Owner: if Ollama fails -> OpenAI paid embeddings, with a fallback when GPT has no credit.
  NEXT (part D): working memory - embed memory items once (background, cached per model), at reply time embed the cue
  (their last messages + stage) and keep the most relevant items; feelings in ONE place (now in 4-5 blocks); already-said.
