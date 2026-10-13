# Security

Gizleme is an end-to-end encrypted messaging web app. This document describes how it is built, what it
protects against, what it does not, and how to report a problem.

## Reporting a vulnerability

Email **admin@gizleme.com**. Please include steps to reproduce. We aim to acknowledge within 72 hours and
to fix confirmed issues before any public disclosure. There is no bug bounty programme at this time.

## Architecture in one paragraph

A single-page web app (`index.html`, `app.js`, no third-party scripts, served with a strict CSP) talks to
four Supabase Edge Functions (`gizleme-auth`, `gizleme-vault`, `gizleme-mbox`, `gizleme-push`) and to
Supabase Realtime for live presence/broadcast. All cryptography runs in the browser with WebCrypto. The
server only ever stores ciphertext, password verifiers, session-token hashes, push subscriptions and
rate-limit counters.

## Cryptography

| Purpose | Primitive |
|---|---|
| Live key agreement | ECDH P-256, fresh key pair per session |
| Key derivation | HKDF-SHA-256 (salt `vesper/v1`, versioned `info` labels per purpose) |
| Message encryption | AES-256-GCM, random 96-bit IV, message id sealed inside the ciphertext |
| Per-message live keys | HKDF(root, `msg|<direction>|<counter>`) — counter must increase, direction must match the paired peer |
| Contact key `ck` | HKDF(first ECDH secret) for room-code contacts; HKDF(invite-link secret) for link contacts, replaced by HKDF(first authenticated session's ECDH secret, `gz-contact/v2`) at the first live pairing; never sent to a server |
| Pairing authentication | HMAC-SHA-256 under HKDF(ck, `gz-auth/v1`) over the session public key; unverified presence entries are never paired with |
| Mailbox | id = HKDF(ck, `gz-mbox/v1`); contents AES-GCM under HKDF(ck, `gz-mbox-key/v1`); sender name and message id inside the ciphertext |
| Receipts | AES-GCM under the mailbox key, 1:1 only |
| Groups | random 256-bit group key `gk` in the invite link fragment; messages AES-GCM under HKDF(gk) |
| Password | PBKDF2-SHA-256, 200,000 iterations, 16-byte random salt → `AK`; server stores `SHA-256(SHA-256(AK))` |
| Account backup | random ABK wrapped with AES-GCM under HKDF(AK, `gz-abk-wrap/v1`); contacts blob AES-GCM under HKDF(ABK, `gz-contacts/v1`) |
| Local storage | contacts/groups/meta blob and message history AES-GCM under a random device master key, itself wrapped by the password (PBKDF2) and optionally by a WebAuthn PRF output (Face ID / fingerprint) |
| Account marker | HKDF(ABK, `gz-acct/v1`) — opaque, replaces the username in presence, mailbox and push records |

## Threat model

**Protected against**

- A passive or active relay/server (including a compromised Supabase project) reading message or photo
  content, or the contact list.
- A relay replaying, reflecting or re-labelling live messages (direction, counter and sealed id checks).
- Someone who merely reaches a room (relay, leaked daily room code) being paired with an existing contact
  (HMAC pairing check with the shared key).
- Online password guessing (per-account and per-IP rate limits), username enumeration via the salt
  endpoint (deterministic fake salts), notification phishing (notification URLs pinned to gizleme.com
  server- and worker-side), push endpoint abuse (allow-listed push services), anonymous storage access
  (bucket closed to the public key; uploads/deletes through a rate-limited function).
- Supply-chain injection through a CDN (no third-party scripts; CSP `script-src 'self'`).
- A device picked up while the app is locked: keys are out of memory; local data is encrypted at rest.
- Cross-account leakage on a shared browser (vault owner check and full wipe on log-out).

**Not protected against (known limitations)**

- **Forward secrecy for mailbox messages.** Messages that go through the mailbox (and every contact
  message does, so offline devices can collect it) are encrypted under a stable per-contact key. A later
  compromise of that key exposes mailbox ciphertext still on the server (≤ 14 days) and any captured
  copies. The live path uses fresh ECDH per session but the mailbox copy does not.
- **Invite links are bearer keys until the first live meeting.** Anyone holding an invite link derives the
  same contact key and can read and write as that contact — until the two parties are online together for
  the first time. At that first pairing, authenticated with the link key, both sides derive a new contact
  key from the session's ECDH secret (`HKDF(secret, gz-contact/v2)`), retire the link key, and move the
  rendezvous rooms, mailbox and push keys to it; the conversation history stays attached through a stable
  history key, and the account vault carries `{ck, prev, hk, rot}` to the user's other devices. After
  that, a copy of the link gives nothing: a device still signing with the retired key is not paired with
  (a calm note, not an alarm) and the old mailbox is no longer read. An impostor who opened the link and
  paired *before* the real invitee still becomes the contact — the in-person safety code is the check for
  that.
- **Groups have no sender authentication and no key rotation.** Any member or the relay could re-label a
  group message; leaving a group does not revoke the key. Create a new group to exclude someone.
- **Offline password guessing by the server.** The verifier is derived with PBKDF2-200k; a weak password
  can be brute-forced from a database leak, which would then unlock that account's backup (contact keys).
  Use a long password. A memory-hard KDF or an aPAKE is a planned upgrade.
- **Metadata.** The relay sees connection timing, IP addresses, mailbox identifiers (opaque) and traffic
  volume. Co-presence in a room reveals that two opaque identities talk, not who they are.
- **Web delivery.** Code is delivered at each load; a compromised origin could serve malicious code. The
  CSP, HSTS and the absence of third-party scripts limit, but do not remove, this trust in the host.
- **Screenshots and the operating system.** No web app can prevent screenshots or protect against a
  compromised OS or browser.

## Server-side controls

- Edge Functions use the service-role key; tables have RLS enabled with no policies (reachable only through
  the functions). Storage bucket policies deny anonymous SELECT/INSERT/DELETE.
- Rate limits (Postgres counter, service-role only): login 10/15 min per account + 60/15 min per IP,
  register 10/h per IP, salt/check 60/min per IP, notify 12/10 min per key, mailbox puts 120/min per
  mailbox, blob uploads 30/min per IP.
- Password change and account deletion require both the session token and the current password.
- HTTP headers: CSP (`script-src 'self'`), HSTS, X-Frame-Options DENY, Referrer-Policy no-referrer,
  Permissions-Policy, COOP same-origin.

## Data retention

See [privacy.html](https://gizleme.com/privacy.html).
