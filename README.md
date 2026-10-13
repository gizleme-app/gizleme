# Gizleme

End-to-end encrypted messaging that runs in the browser. **No phone number. No app. No trace.**

- Live: https://gizleme.com — open a friend's invite link, pick a name, reply.
- Languages: English, French (auto from the browser, switchable in Settings).

## What it is

- A single-page web app (`index.html`, `app.js`, `i18n.js`) with no third-party scripts, installable as a
  PWA, served by Cloudflare with a strict Content-Security-Policy (`_headers`).
- Accounts are a username + password only. Contacts and groups follow the account across devices in an
  encrypted vault; there is deliberately no password reset.
- Four Supabase Edge Functions (`gizleme-auth`, `gizleme-vault`, `gizleme-mbox`, `gizleme-push`) and
  Supabase Realtime for live presence and broadcast. The server only ever holds ciphertext.

## Features

- Invite links (`#i=`) that work asynchronously: the invitee can write immediately, even if you're offline.
  Single-use: at the first live meeting the link key is replaced by one only the two devices can compute.
- Automatic identity check at every connection (HMAC under the shared contact key) + in-person safety code.
- Encrypted store-and-forward mailbox (14 days), real inbox with unread counts and previews, receipts
  (✓ sent / ✓✓ received), offline banner, tap-to-retry.
- View-once photos, disappearing messages (24 h by default), auto-lock, privacy screen, hidden previews.
- Groups with a shared key in the link fragment.
- Web Push ("New message from X"; never message content).

## Security

See [SECURITY.md](SECURITY.md) for the cryptography, the threat model and the known limitations, and
https://gizleme.com/privacy.html for what the server keeps and for how long.

## Repository layout

```
index.html            markup + styles
app.js                application code (crypto, UI, sync)
i18n.js               translations (English keys → French)
sw.js                 service worker (offline shell, Web Push)
_headers              Cloudflare security headers (CSP, HSTS, …)
manifest.webmanifest  PWA manifest
vendor/               supabase-js (pinned version, served same-origin)
privacy.html/.js      privacy page (FR/EN)
```

The Edge Functions are deployed on Supabase and are not part of this repository.

## License

All rights reserved for now.
