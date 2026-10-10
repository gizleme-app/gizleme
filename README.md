# Gizleme

End-to-end encrypted, ephemeral messaging web app.
**message secure. mood unfiltered.**

- Live: https://gizleme.com
- Single-file app (`index.html`), hosted on Cloudflare.
- Crypto in the browser: ECDH (P-256) key agreement, HKDF ratchet (per-message keys), AES-256-GCM.
- Relay via Supabase Realtime (ciphertext only). Encrypted photo blobs in Supabase Storage.
- Features: disappearing photos (view-once), PIN-locked local history, Face ID / Touch ID (WebAuthn), notification sounds, native share.

Private project — not for redistribution.
