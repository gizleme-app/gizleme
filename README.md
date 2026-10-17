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
  (✓ sent / ✓✓ received), offline banner, tap-to-retry.
- View-once photos, disappearing messages (24 h by default), auto-lock, privacy screen, hidden previews.
- Reactions (double tap / double click on a message → emoji picker; one reaction per person, tap it again to
  take it back) and replies (swipe a message to the right, or ↩ in the picker; the quote jumps to the
  original). Both are ordinary encrypted messages — signed in groups — so the relay learns nothing new.
- Voice messages (up to 2 min): recorded on the device with one small built-in codec (IMA ADPCM, 16 kHz —
  the same bytes decode in every browser, no container or codec negotiation), encrypted exactly like a
  photo under a key that only travels inside the message; the ciphertext is deleted from the relay once
  the recipient fetched it and kept, encrypted, on their device for replay.
- Groups with a shared key in the link fragment; a two-person chat can be turned into a group (the
  contact is invited inside the encrypted chat, the link for the others is offered right away). Group
  messages are signed by their author (✓ / ⚠ on each bubble); the creator can remove members or renew the
  key — the new key reaches each remaining member under their own key, the removed one is locked out.
- Location sharing: coordinates travel only inside the encrypted message; "Open in Maps" hands them to the
  phone's own maps app — Gizleme never fetches anything from a map provider.
- Quiet by design: one tone for a message in a chat you are not looking at (at most once every few
  seconds), nothing when you send, when someone comes online or for a reaction; that chat's row glows
  briefly in the list. Calls keep their ringtone.
- Web Push: the wire carries only "New message" / "Incoming call" / "A contact wants to chat"; the
  receiving device adds the contact's name ("New message from X"). Never message content.
- Audio and video calls (WebRTC): media goes peer-to-peer and is end-to-end encrypted by construction
  (DTLS-SRTP); the signalling travels inside the chat's already-encrypted channel, so the relay sees
  nothing but ciphertext. Group calls are a mesh of up to 4 people. A contact who is offline is woken
  with a push ("Incoming call"). A Cloudflare TURN relay (see SECURITY.md) only forwards
  ciphertext and takes over when both sides sit behind strict NATs.

## Security

See [SECURITY.md](SECURITY.md) for the cryptography, the threat model and the known limitations,
[AUDIT.md](AUDIT.md) for the internal audit (October 2026: findings, fixes, open items), and
https://gizleme.com/privacy.html for what the server keeps and for how long.

## Repository layout

```
index.html            markup + styles
app.js                application code (crypto, UI, sync)
i18n.js               translations (English keys → French)
sw.js                 service worker (offline shell, Web Push)
_headers              Cloudflare security headers (CSP, HSTS, …)
manifest.webmanifest  PWA manifest
vendor/               supabase-js and qrcode-generator (pinned versions, served same-origin)
privacy.html/.js      privacy page (FR/EN)
supabase/             the server: database schema (migrations/) and the five Edge Functions (functions/)
tests/                end-to-end scenarios (Playwright) and their runner
```

There is no build step: the files at the root are what gizleme.com serves (Cloudflare static assets,
`wrangler.jsonc`; `.assetsignore` keeps the docs, tests and server code off the site). To run your own,
see [supabase/README.md](supabase/README.md) and point `SB_URL`/`SB_KEY` in `app.js` and `connect-src` in
`_headers` at your project. To check your changes, see [tests/README.md](tests/README.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md) — privately, please.

## License

Gizleme is free software: [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only). If you run a
modified version as a service, you must offer its source to its users. The name, logo and domain are not
covered by the licence — see [TRADEMARKS.md](TRADEMARKS.md). Third-party components:
[THIRD_PARTY.md](THIRD_PARTY.md).
