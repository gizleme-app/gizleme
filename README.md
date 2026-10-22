# Gizleme

End-to-end encrypted messaging that runs in the browser. **No phone number. No app. No trace.**

- Live: https://gizleme.com — open a friend's invite link, pick a name, reply.
- Languages: English, French, Turkish (picked from the browser's preferred languages, switchable in Settings).

## What it is

- A single-page web app (`index.html`, `app.js`, `i18n.js`) with no third-party scripts, installable as a
  PWA, served by Cloudflare with a strict Content-Security-Policy (`_headers`).
- Accounts are a username + password only. Contacts and groups follow the account across devices in an
  encrypted vault; there is deliberately no password reset.
- Five Supabase Edge Functions (`gizleme-auth`, `gizleme-vault`, `gizleme-mbox`, `gizleme-push`,
  `gizleme-turn`) and Supabase Realtime for live presence and broadcast. The server only ever holds
  ciphertext.

## Features

- Invite links (`#i=`) that work asynchronously: the invitee can write immediately, even if you're offline.
  The link is a ticket, not a key: it carries a one-time public key and the first device to open it agrees
  the contact key by ECDH with the inviter — nobody can derive that key from the link; later openers are
  rejected and the inviter is warned. Links expire (24 h by default), can be protected by a 4-digit code
  said by voice (three wrong codes cancel the link), and can be shown as a QR code to scan in person.
- Automatic identity check at every connection (HMAC under the shared contact key) + in-person safety code.
- Encrypted store-and-forward mailbox (delivered messages deleted 48 h after being fetched, undelivered
  after 14 days) under a per-contact one-way key chain that moves forward weekly — old keys are destroyed,
  so a later compromise cannot read earlier weeks (see SECURITY.md); real inbox with unread counts and
  previews, receipts
  (✓ sent / ✓✓ received), offline banner, tap-to-retry. The mailboxes of all chats are read in one relay call
  per pass, at a pace that follows activity (20 s while the chat is alive, 45–60 s when quiet, every two
  minutes while the app is hidden — pushes wake the device meanwhile) (v43).
- Disappearing messages (off by default since v41; one tap turns them on), set per chat from the timer in its header — red and crossed out
  when off, blue with 5 / 30 / 60 (minutes) or 24 (hours) when on — and applied to both sides. While the
  timer runs, photos are view-once; with it off they stay in the chat on both phones, and a long press on one
  offers Save (to the gallery / Photos) and Forward (to another chat). Auto-lock, privacy screen, hidden
  previews.
- A long press on a message (right click or double click on a computer) opens its menu: the reactions on top,
  then Reply, Edit, Copy (and Forward, Save for a kept photo) as a labelled list. Reactions: one per person, tap it again to take it back. Replies: also a swipe to the right; the
  quote jumps to the original. Your own text messages can be edited for 24 hours ("edited" shows on the
  bubble, on every side). All three are ordinary encrypted messages — signed in groups — so the relay learns
  nothing new, and only the author's own edit is ever applied.
- Links in messages are clickable (a tap first confirms the site). A message written without network waits on
  the device and leaves on its own when the network is back; the header says "you're offline" meanwhile.
- Delete a message from its menu: "Delete for me" removes it from this device; "Delete for everyone" (your own
  message, within 48 hours) removes it from the other devices too and leaves "This message was deleted" in
  its place. It can't reach a copy someone already saw or saved (see SECURITY.md).
- Search: a field under the "Chats" title finds chats by name and, below them, messages — with accents
  ignored (cafe finds café, sukru finds Şükrü); a tap opens the chat at that message. Inside a chat, ⋮ →
  Search highlights every match, with previous / next. Everything is searched on the device; nothing is
  indexed or sent.
- One to three emojis sent on their own are drawn big and move — once when they arrive or are sent, again
  on a tap (a heart beats, a laugh shakes, a hand waves, a party popper jumps…); never with "reduce motion".
- Voice messages (up to 2 min): recorded on the device with one small built-in codec (IMA ADPCM, 16 kHz —
  the same bytes decode in every browser, no container or codec negotiation), encrypted exactly like a
  photo under a key that only travels inside the message; the relay keeps the ciphertext for 14 days (so
  every member of a group, and each of your devices, can fetch it) and each device keeps its own copy,
  encrypted, for replay.
- Groups with a shared key in the link fragment; a two-person chat can be turned into a group (the
  contact is invited inside the encrypted chat, the link for the others is offered right away). Group
  messages are signed by their author (✓ / ⚠ on each bubble); the creator can remove members or renew the
  key — the new key reaches each remaining member under their own key, the removed one is locked out.
  Rotations are numbered and never go backwards; signed messages carry their sender's clock and a stale
  copy is dropped (v42, see SECURITY.md).
- The message bar: "+" on the left opens the attachments where the keyboard would be — Photos (several at
  once), Camera, Location, Document, Poll, Event — and turns into a keyboard icon to go back; the camera and
  the microphone sit next to the field while it's empty, the send button replaces them once you type.
- Documents up to 10 MB (encrypted on the device, sent in 1.8 MB pieces; each device keeps its own encrypted
  copy once fetched), polls (one or several answers) and events (date, time, place; "going / can't go";
  "Add to calendar" as an .ics file). Votes are encrypted, quiet envelopes like reactions.
- Location sharing: coordinates travel only inside the encrypted message; "Open in Maps" hands them to the
  phone's own maps app — Gizleme never fetches anything from a map provider.
- Quiet by design, with its own sound: "Gizleme", a three-note glass chime (one note per syllable), for a
  message in a chat you are not looking at — at most once every few seconds — and a small echo of it in the
  chat you have open; nothing when you send, when someone comes online or for a reaction. That chat's row
  glows briefly in the list. Settings → Notifications and sounds: messages and calls / calls only / no sound. Mute a chat for
  1 hour, 8 hours or until you turn it back on (it follows your account; its notifications arrive silently).
- Unread count in the tab title and on the app icon (a number, never a name), and a "New messages" line
  where you left off when you open a chat. Scrolled up in a chat, you stay where you are when messages
  arrive: a round ↓ shows how many came in and takes you back down.
- Two chats with the same person (say, a new invite after the old chat broke) can be merged from the chat
  info (tap its name → Merge with another chat…): the earlier chat's messages show in this one in time order, it leaves
  the list, and anything still sent on its key lands here. Never automatic — a name proves nothing — and only
  on your devices.
- "Typing…" and "recording a voice message…": in the chat's header, as three dots (or a microphone) at the
  end of the chat and in the chats list — live-only encrypted signals that stop when the message is sent and
  fade after a few seconds of nothing. Settings → Privacy → Typing indicators: off means you neither send nor see them.
- Settings → Chats → Text size: five sizes, from small to largest, for the whole app (typing fields
  never go below 16 px, so an iPhone doesn't zoom into them).
- iPhone / iPad: the installed app uses the "Compatibility" display by default (the page laid out inside
  the safe area, under an opaque status bar), which avoids the band iOS 26 can paint over the bottom of the
  screen; Settings → Chats → iPhone display switches back to "Standard".
- Drawn icons throughout the interface (system lines, the chats list, cards, dialogs, the welcome screen);
  emojis are kept for what people write and react with.
- Chat info: a tap on a chat's name (or its avatar) opens everything about that chat in one place — audio,
  video, location, nickname, colour, disappearing messages, mute, identity check, notify, turn into a group,
  merge, new keys, what the relay sees, remove or leave. The ⋮ menu keeps the quick ones: Chat info, search,
  mute, share my location (and invite, in a group).
- Settings in pages: your name at the top (Profile), then Privacy, Chats, Notifications and sounds, Install
  the app and Account, where "Delete account" sits at the very bottom, apart. The on/off settings are
  switches (v44).
- Usable with a keyboard and a screen reader (v44): the chats list rows are buttons with a spoken name
  (name, unread, last message, time) that Enter opens; bubbles take the focus and Enter opens their menu;
  every dialog has a role and a name, the focus goes in, stays in and comes back; Escape closes the dialog
  or menu on top; the toast, the sign-in message and the call status are announced; photos have alt text;
  colour names are in the app's language. Every question the app asks (remove a contact, leave or join a
  group, accept an invite, open a link, log out, a nickname, a group name…) is its own dialog, with named
  buttons — never the browser's confirm / prompt. Targets are at least 40×44 px in the chat header and
  44×44 in the list header; secondary texts in sent bubbles, the offline banner and the comparison table
  read at 4.5:1 or more; a muted microphone shows and says it; a voice recording shows its clock and stops
  at two minutes instead of sending itself.
- Robust to the edges (v45): removing a contact or leaving a group erases that chat's records and media from
  the device (not only its row); a chat left open across midnight UTC follows its rendezvous room, on both
  sides; the account backup answering 401 is said (after the session has been checked twice), a backup that
  couldn't be opened at log-in is opened at the next "online" and the empty list says so meanwhile; while
  the account marker is unknown a message waits in the queue instead of reaching your other devices as the
  contact's; the composer keeps a draft per chat; the composer of a group you were removed from is off, and
  being invited back no longer trips over the old rotation; photos' blob URLs are revoked when their
  bubbles go, documents over 1 MB are decrypted on the tap; the chats list's preview is the newest message
  by time; a full storage is said once; the pull at unlock no longer races the cached backup key.
- Tested on the server side too (v46): the five Edge Functions have Deno tests against a stand-in for
  supabase-js (`tests/edge/`, no network), run in CI with `deno check`; the browser scenarios wait on
  conditions instead of fixed delays (`tests/harness.py`), every check is a boolean or an error, and the
  suite runs in one time zone. The mailbox of a contact is read once right after pairing (what they deposited
  while the two sides were not in the same room yet); the chats list's previews follow a language switch.
- A first visit opens on a short welcome — the logo, one sentence, "Create my account" and "I already have
  an account", the three promises underneath — then the form alone. An invite link goes straight to the form.
- A colour for each chat: every contact has its own colour from the start (worked out from the contact key,
  so it is the same on both phones), and a long press (right click on a computer) on a chat in the list opens
  a palette of twelve colours for its round avatar — in the list, at the top of the chat and on the call screen. Saved
  in your encrypted contact list, so it follows your account; the other person never sees it.
- An app left open for days notices a new release when it comes back to the foreground: a small pill,
  "New version available — tap to update" (on the lock screen it simply reloads).
- Web Push: the wire carries only "New message" / "Incoming call" / "Missed call" / "A contact wants to
  chat"; the receiving device adds the contact's name ("New message from X"). Never message content. The
  key a device is woken under names its side of the contact (inviter or opener), not the pair, so the
  relay's subscription table doesn't say who talks to whom (v42).
- Installing: while Gizleme isn't installed on a device, a window offers to add it — one button where the
  browser can install it itself, illustrated steps on iPhone / iPad, Android and Safari on a Mac. It comes
  back the next day, then every three days (six times at most), unless you tap "Don't show this again".
- Audio and video calls (WebRTC): media goes peer-to-peer and is end-to-end encrypted by construction
  (DTLS-SRTP); the signalling travels inside the chat's already-encrypted channel, so the relay sees
  nothing but ciphertext. Group calls are a mesh of up to 4 people. A contact who is offline is woken
  with a push ("📞 X is calling you", with a ringing-phone icon) that rings again every 7 seconds while the
  call rings and turns into "Missed call" if nobody picks up. A two-person video call fills the screen (HD
  capture, your own picture small in a corner; the buttons fade after a few seconds and come back with a
  tap; full screen including the system bars on Android, ⛶ on a computer). Switching between the front and
  back cameras releases the current one first, which phones such as Samsung's require. A video call can be
  answered without the camera: the camera isn't opened at all, their picture still comes in, and tapping the
  camera button later turns yours on without a new connection. During a call, "Weak connection" appears when
  this device measures heavy packet loss, a long round trip or a frozen picture (WebRTC's own statistics,
  read locally), and goes away once things are better. A Cloudflare TURN relay (see
  SECURITY.md) only forwards ciphertext and takes over when both sides sit behind strict NATs.

## Security

See [SECURITY.md](SECURITY.md) for the cryptography, the threat model and the known limitations,
[AUDIT.md](AUDIT.md) for the internal audit (October 2026: findings, fixes, open items), and
https://gizleme.com/privacy.html for what the server keeps and for how long.

## Repository layout

```
index.html            markup + styles
app.js                application code (crypto, UI, sync) — the readable source
app.min.js            the same, minified by tools/build.py: what the page loads (v43)
boot.js               the first screen (unlock / log in / welcome) drawn before app.js has loaded (v43)
i18n.js               translations (English keys → French, Turkish)
sb.js                 iPhone display mode, read before the page is drawn (see v35)
sw.js                 service worker (offline shell served cache-first, Web Push)
tools/build.py        the release step: stamps the version into sw.js and index.html, builds app.min.js
_headers              Cloudflare security headers (CSP, HSTS, …)
manifest.webmanifest  PWA manifest
vendor/               supabase-js and qrcode-generator (pinned versions, served same-origin)
privacy.html/.js      privacy page (FR/EN/TR)
supabase/             the server: database schema (migrations/) and the five Edge Functions (functions/)
tests/                end-to-end scenarios (Playwright) and their runner
```

The files at the root are what gizleme.com serves (Cloudflare static assets, `wrangler.jsonc`;
`.assetsignore` keeps the docs, tests, tools and server code off the site). One step before a release:
`python3 tools/build.py` (needs node) writes `APP_VERSION` from `app.js` into `sw.js` and `index.html` and
rebuilds `app.min.js`; test59 fails when that was forgotten. The scripts are loaded with `?v=NN`, cached for
a year by the CDN and served cache-first by the service worker, so an installed app opens from the device;
only the page itself and `sw.js` are revalidated on every load, and a new version arrives through the
worker (new cache name, fresh files, the "new version" pill). To run your own,
see [supabase/README.md](supabase/README.md) and point `SB_URL`/`SB_KEY` in `app.js` and `connect-src` in
`_headers` at your project. To check your changes, see [tests/README.md](tests/README.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md) — privately, please.

## License

Gizleme is free software: [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only). If you run a
modified version as a service, you must offer its source to its users. The name, logo and domain are not
covered by the licence — see [TRADEMARKS.md](TRADEMARKS.md). Third-party components:
[THIRD_PARTY.md](THIRD_PARTY.md).
