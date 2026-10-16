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
