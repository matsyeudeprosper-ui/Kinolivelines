# Acquisition flow review (2026-10-16, owner: "make sure we are ready to welcome users")

Walked end to end on two throwaway accounts (Automatique on the idle Exness demo 436771046, Signal app-only),
captured at phone size with `review/phone_shot.mjs`, then removed.

## The flow as it stands
1. Landing `/` -> "Creer un compte" -> `/offres` (three cards) -> sheet per package.
2. Automatique sheet: first name, MT5 account, password (eye), server (book hint while typing), "Verifier mon compte".
   No code on this screen. Signal / Strategie sheets: ident, password, code or crypto payment.
3. POST /activate -> 302 `/verif?j=<id>` (refresh/back safe, kept 1 h): waiting screen (3 check lines) -> result card
   (pill, broker, 4 facts, robots that pay here, code field) -> "Activer mon compte" -> welcome page (step 3 done,
   "Ouvrir mon OwlNest") -> home. Red: three doors, nothing built. Failed login: plain-words causes.
4. Home, first minutes (Automatique): "Votre robot se prepare" in the balance slot, then balance + "Bienvenue" card
   (what will appear) + robot state + first-visit tour. Signal: the Owl's live view, "Signal" state card, inviting
   notifications card, glance with real numbers.
5. Login from the landing: MT5 number + MT5 password (Automatique) or ident + password (Signal); wrong password ->
   clear page.

## Fixed in this pass (commits 9df9ab9 .. 2779f70)
- Verification URL; wrong/missing code returns to the verdict, never the landing.
- Welcome pages on the flow shell; "1 jours" grammar; one button instead of a bare URL.
- Automatique home skeleton -> preparing message; Signal: "Manuel" -> "Signal", "En pause" -> "Signal, vous tradez
  vous-meme", "Quoi de neuf" hidden the first week, glance read from the payload (was another tab's empty tile),
  notifications card invites instead of alarming.
- Sheet: tile + glow, step strip, grouped fields with icons, (i) tips instead of hint paragraphs, pinned header.

## Verified
- Probe resolves the broker's Bitcoin name into the record (BTCUSDm on the Standard demo); the bot starts with it.
- Manager spawns worker + bot; provisioner cleans the terminal (0 expert blocks, 6 EA folders removed).
- Market bots only start from the allowed list at a bots restart; `live/market_hold.json` keeps a market out.

## Still to watch
- A bot can take 2-3 manager retries while a fresh terminal boots (seen 15:41 -> 15:48): harmless, but the
  "preparing" message covers it.
- The offers page cards (older design) next to the new sheet; the landing is the 10-11 overhaul.
- Owner-side: the code still comes from the owner by hand for Automatique (family only).

## Retention review (same day)
What keeps a member: pushes (Bilan du jour per member 18:30-23:00 UTC, "Votre semaine" on Monday with a share image,
the robot's signals and trade events; the owner alone gets the morning and the Monday digest), the inbox, the
subscription reminders 5 and 2 days before the end and a notice at expiry (Automatique: the robot is paused by
expiry and the home shows "Renouveler l'acces" with the code field; Signal/Strategie: "Abonnement termine", renew
by code or crypto in Reglages > Abonnement), the first-visit tour, the journey in Reglages.

Fixed: the home's renew card vanished the moment a package expired (it only counted future ends) - it now stays
up to 45 days with the right words ("Signal a expire il y a 3 jours - Renouveler relance vos signaux tout de
suite"; "Automatique a expire il y a 10 jours - Entrer le code"); "Ajoutez Manuel" -> "Ajoutez Signal"; the
legacy "Essai termine / Premium" line; the settings account card showed "Bon apres-midi Visiteur" as the name.
Verified on the live page with fake plan dates (3 states). Still by hand: the owner issues Automatique renewal
codes; crypto renewal exists for Signal/Strategie only.

## Robustness pass (same day)
`review/route_crawl.py` hits every public route, every member sub-route (demo token and a bogus token), the POST
routes with empty and bogus bodies, plus hostile paths (300 chars, %00, ../). Before: 0 x 5xx, 0 tracebacks, 0
dropped connections, 46 blank 404s. After: a "Page introuvable" page for browsers (JSON for scripts) at every 404
site, and do_GET/do_POST wrapped: any exception answers a "Un instant" page that retries by itself (JSON
{"error":"server","retry":true} for scripts) and logs the traceback to live/owl_app_errors.log. Offline: the
service worker serves the cached page after 4 s or an offline page; the app shows "Connexion perdue" and retries.
Re-crawl: 0 flagged.
