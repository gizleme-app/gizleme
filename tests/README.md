# Tests

End-to-end scenarios: each `testNN.py` serves the app from the repository root, swaps supabase-js for a
small in-process emulator of the relay (Realtime presence + broadcast) and of the Edge Functions (accounts,
vault, mailbox, push, TURN), and drives real Chromium instances with Playwright — two or three users
pairing, writing, calling, locking, logging out. Every check prints `name: True/False`; a scenario passes
when every check is `True` and no page error was recorded.

```
pip install playwright pillow numpy
python -m playwright install --with-deps chromium
python3 tests/run.py            # every scenario (≈ 10 min)
python3 tests/run.py 32 36      # a selection
```

Node.js is needed for `test24` (it runs the service worker's notification composer in a VM). Scratch
files go to `$TMPDIR/gizleme-tests/` (override with `GZ_TEST_TMP`). Checks whose names start with
`safariIos_` only hold on iOS Safari and are reported but not counted.

| Scenario | What it covers |
|----------|----------------|
| test18 | accounts, lock/unlock, at-rest encryption, deep links in the fragment, log-out wipe, CSP |
| test19–21 | contacts, invite links, inbox, unread counts, receipts |
| test22, test27 | legacy (v2) invite-key rotation and the reconciliation window |
| test23 | nicknames (rename for me: header, list, record, cleared) and message tones (options, selection persisted and previewed) |
| test24 | push: notification names composed on the device (hashed keys), French templates |
| test25 | photos: large/PNG/small, re-encoding (no EXIF), chunked base64 |
| test26, test28, test29 | phone layout: keyboard, header and status dot, lock screen |
| test30 | location sharing, turning a chat into a group, group invitations (opt-in) |
| test31 | audio/video calls (real WebRTC between browsers), group calls, offline ringing |
| test32 | invite links v3: one-time pre-key, hello, reuse detection, link-key messages refused |
| test33 | voice messages (record, send, receive, play / pause / replay, history, own replay) and the relay keeping a blob for the other members |
| test34 | rejoining a room after failed joins |
| test35 | invite links: expiry, 4-digit code, QR |
| test36 | mailbox forward secrecy: weekly key chain, advancing, holding, convergence |
| test37 | groups: signed messages, spoofing and tampering flagged, identity key in the vault; group reactions and replies |
| test38 | groups: key rotation, removing a member |
| test39 | key chain for existing contacts, seeded at a live meeting |
| test40 | vault merge rules for the key chain |
| test41 | Turkish: detection, every string translated (placeholders intact), switching, dates, initials, privacy page |
| test42 | reactions (double tap / double click, toggle, replace, counts) and replies (swipe, ↩, quote jump), persistence |
| test43 | quiet sounds (none on send, connect or reaction; a small echo in the open chat; the rate-limited chime elsewhere) and the glowing row |
| test44 | Settings → Sounds, per-chat mute (menu, list, merge, silent pushes), unread count in the title / on the icon, the "New messages" line, invites through WhatsApp / the share sheet opening the new chat, the "new version" pill |
| test45 | signing up / logging in from an invite link: no false "link already used", messages both ways, a wrongly flagged chat heals |
| test46 | merging two chats with the same person: order, hidden record, old key lands here, lock/unlock, removal |
| test47 | review fixes: chain week carried in the hello, tombstones, unread cleared on removal, admin self-wrap, update pill on New chat, service-worker shell and notification tap |
| test48 | v29: editing a sent message (right click / long press, author-only rules, 24 h, draft kept, history, preview, group signer), a call ringing again every 7 s then "missed call" (tag, kind, service-worker alert with the ringing icon), full-screen 1:1 video (HD capture, one tile whichever device answers, buttons fade and come back with a tap, ⛶ full screen, camera switch on a simulated Samsung that can't open two cameras), install invitation shown again until installed (iPhone / Android steps, "don't show again", legacy flag), a colour per chat avatar (right click / long press in the list, header and call screen, vault newest-wins), typing / recording indicators (header, end of chat, list; stop, fade, setting off both ways, relay sees only msg/rcpt events) |
| test49 | v31: the chat timer in the header (menu, red / blue states, synced to the other side, older change ignored, Settings selector), kept photos when it's off (both sides, after a lock, after the relay's copy is gone), long press / right click → Save (download) and Forward (to another chat, following that chat's timer), view-once again when it's on |
| test50 | v32: the new message bar (+ ↔ keyboard, camera and mic while empty, send once typed, the attachment panel), several photos at once, documents (sent, received, opened as a download, a 3 MB one in pieces, the 10 MB limit), a poll (votes both ways, a changed vote, after a lock), an event ("going", the .ics), the list preview |
| test51 | v34–v36: an installed iPhone app on iOS 26 whose viewport is the screen minus the status bar (WebKit 301994) never sizes itself under the band, drops the home-indicator padding and gives the band the bar's colour — only in that case; the text size setting (applied, kept, fields ≥ 16 px, bad values ignored); the iPhone display mode (on by default in the installed iPhone app, off in Safari and on Android, ?sbtest=1 / 0, Settings, an explicit "Standard" kept) |
| test52 | v36: darker accent fills in dark mode, short system lines on a pill in the UI font, a calm chat header, the message menu (emojis on top, labelled actions), the big "Chats" title with a gear and one + on phones, a colour per contact (same on both sides), grouped bubbles, the ↓ button counting new messages without moving the chat, the incoming call screen (labels, status, pulse) |
| test53 | v37: the welcome step (one button above the fold, promises under it, no form; then the form alone; the first name follows the username until typed; "I already have an account"; French; an invite link skips it), Settings in pages (root, Account with delete last, back, Escape, reopens on the root), Chat info (from the name, the avatar or ⋮; content, colour, timer, mute, wire, full screen on a phone, remove) and the short ⋮ menu |
| test54 | v38: delete for everyone (both sides, history rewritten, preview, survives a lock), only the author's message obeys, delete for me (here only, not shown again if re-delivered), a deletion arriving before its message; search (accents and Turkish letters folded, deleted messages left out, chats by name, a hit opens the chat at the message, clearing); search inside a chat (count, previous, highlight, Escape); no emoji left in the interface chrome |
| test55 | v39: big emojis (1–3 alone, sizes, animations by emoji, played on send / arrival and on a tap, still from history and with reduced motion, an edit can make a message big; 4 emojis, emoji + text, digits stay normal), a video call answered without the camera (no camera track, their picture arrives, ours later on a tap), "weak connection" (shown after two bad readings, hidden after three good, none on a clean call, reset at hang-up), audio calls without that choice, the type scale and radii tokens, the hidden attribute always wins |
| test56 | v40 layout: the invite screen's "4-digit code" checkbox and label at three text sizes; beside a chat, the chats list's title and buttons fit and the open-chat tabs stay on screen (phone on its side, computer; text sizes up to 1.4; French, Turkish) |
| test57 | v41: a 1 500-message history opens in under a second with one scroll at the end; a burst of 3 photos stays in the chat it started in when you switch mid-way; a message written offline waits (pending, saved, survives a reload) and leaves by itself when the network is back, the header saying "you're offline" meanwhile; the delete-account Cancel and Escape; unique ids; a notification may only open the app's own chat route; an invite link opened while signed in asks first (and not after signing up through it); no timer on a new account; the sender is told when a photo goes view-once; links are clickable and ask before opening; the unlock label in French on Android |
| test58 | v42: notification keys name a direction (inviter / opener) — each side registers its own, a sender wakes the other's with no sender marker and falls back to the pair's key only when nobody holds the new one; a hello with a wrong tag binds nothing; blob uploads and acknowledgements carry the session token; a delivered message's id survives a lock and a copy re-deposited with the same id is not shown again; a group's first key fingerprint is known, rotations carry their number and the fingerprint they replace, a member tracks both, and a removed member re-sealing the old rotation under a key it still holds (with the seen ids forgotten) is refused; a signed envelope 20 days old is dropped while a fresh one shows; "X is typing" needs a member's signature; an unsigned disappearing-timer envelope is ignored; a lock empties the safety code, chat info, members and caller name; a session the server no longer knows signs the device out at unlock (a valid one stays in). |
