<!-- Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE -->
# Gizleme protocol specification

Status: describes the app as of **v48** (`APP_VERSION` in `app.js`). The code is the reference: where this
document and the code disagree, the code wins, and the disagreement is a bug in one of them — please open an
issue. This document is written for reviewers and auditors; it complements [SECURITY.md](../SECURITY.md)
(design rationale and known limitations) and [THREAT-MODEL.md](THREAT-MODEL.md) (assets, adversaries,
residual risks). It does not repeat the rationale: it says **what is done, exactly**.

Gizleme is *not* the Signal protocol. There is no X3DH, no Double Ratchet, no per-message ratcheting on the
offline path. The design is a smaller one built from WebCrypto primitives; its differences from Signal are
listed in §14 so that a reviewer knows where to look hardest.

Conventions: `||` is concatenation, `b64` is standard base64 with padding, `b64url` is base64url without
padding, `utf8(x)` is the UTF-8 bytes of a string. Source references are to `app.js` functions.

---

## 1. Primitives

All cryptography runs in the browser through WebCrypto (`crypto.subtle`); there is no JavaScript
implementation of any primitive. The Edge Functions use the same `crypto.subtle` (Deno) for SHA-256 and HMAC.

| Name | Definition |
|---|---|
| ECDH | P-256, raw uncompressed public keys (65 bytes), 256-bit shared secret (`deriveBits`). Key pairs are generated extractable (`genKP`), including the live-session and ephemeral pairs. |
| ECDSA | P-256 / SHA-256 (signatures in groups). |
| HKDF(ikm, info, L=32) | HKDF-SHA-256, **salt = `utf8("vesper/v1")`** (a fixed legacy name from the project's first codename), `info = utf8(info)`, `L` bytes. |
| AES-GCM | 256-bit key, **96-bit random IV** from `crypto.getRandomValues`, 128-bit tag, **no additional authenticated data**. Output is stored as `{iv: b64, ct: b64}` (`ct` includes the tag). |
| HMAC | HMAC-SHA-256. |
| SHA-256 | WebCrypto digest. |
| PBKDF2 | PBKDF2-HMAC-SHA-256, **200 000 iterations**, 256-bit output (`pbkdf2bits`, `pinWrapKey`). |
| Random | `crypto.getRandomValues` only. |

Every HKDF use has its own `info` label (§3). Labels are versioned (`/v1`, `/v2`) so a derivation can change
without colliding with the old one.

---

## 2. Key hierarchy

```
password ──PBKDF2(salt_account)──▶ AK ──┬─ SHA-256 ─▶ av ──SHA-256──▶ verifier   (server stores verifier)
                                        └─ HKDF "gz-abk-wrap/v1" ─▶ wrap key ──AES-GCM──▶ ABK (random 32 B)
ABK (account backup key, one per account, wrapped on the server, cached on devices under MK)
 ├─ HKDF "gz-contacts/v1" ─▶ vault key ──AES-GCM──▶ vault blob  {contacts, groups, identity, tombstones…}
 └─ HKDF "gz-acct/v1" (16 B) ─▶ account marker `_acct` (opaque; replaces the username in presence/mailbox/push)

MK (device master key, random 32 B, per device)
 ├─ wrapped by PBKDF2(password or PIN, random salt)           (localStorage `LS_MKPIN`)
 ├─ optionally wrapped by a WebAuthn PRF output (Face ID…)    (localStorage `LS_MKBIO`)
 └─ = AES-GCM key `gHistKey` for: local contacts/groups/meta blob, message history, kept media, cached ABK

per contact (1:1) — held in the vault record:
 ck  (contact key, 32 B)
 ├─ HKDF "gz-auth/v1"            ─▶ HMAC key that signs the session public key (pairing proof)
 ├─ HKDF "gz-rv/v1|<UTC day>"    ─▶ rendezvous room code of the day
 ├─ HKDF "gz-mbox/v1" (16 B)     ─▶ mailbox id        HKDF "gz-mbox-key/v1" ─▶ mailbox key (static)
 ├─ HKDF "gz-notify/v2|i|o", "gz-notify/v1" ─▶ push notification keys
 ├─ HKDF "gz-hist/v1" (16 B)     ─▶ opaque history id `hk` ("h:…")
 └─ HKDF "gz-safety/v1" (16 B)   ─▶ safety code (legacy contacts)
 kc, kce  (mailbox chain root and its week, v3 contacts)
 └─ HKDF "gz-chain/next" per week ─▶ root_n ─ HKDF "gz-mbox-key/v2" ─▶ weekly mailbox key

per live session (1:1): fresh ECDH P-256 pair per room join
 secret ─ HKDF "root" ─▶ root ─ HKDF "msg|<dir>|<i>" ─▶ per-message key

per group: gk (random 32 B, in the invite link fragment and the vault)
 ├─ HKDF "gz-group-msg/v1" ─▶ message key (live and mailbox)
 ├─ HKDF "gz-mbox/v1" (16 B) ─▶ mailbox id (HKDF of gk, same label)
 └─ HKDF "gz-safety/v1" (16 B) ─▶ group safety code

per account: identity = ECDSA P-256 (sign) + ECDH P-256 (ek/dk, key delivery), in the vault
```

---

## 3. Derivation labels

| Label (`info`) | Input key material | Length | Used for |
|---|---|---|---|
| `gz-abk-wrap/v1` | AK | 32 | key that wraps the ABK on the server |
| `gz-contacts/v1` | ABK | 32 | vault encryption key |
| `gz-acct/v1` | ABK | 16 | account marker (`b64url`) |
| `gz-auth/v1` | ck (or `prev` ck) | 32 | HMAC key for the pairing proof |
| `gz-contact/v1` | ECDH secret of the first live meeting (room-code contacts) | 32 | `ck` |
| `gz-contact/v2` | ECDH secret (pre-v3 invite rotation) | 32 | rotated `ck` |
| `gz-contact/v3\|<ckLink>` | ECDH secret of the link opening | 32 | `ck` of a v3 contact |
| `gz-invite/v1` | link secret `s` | 32 | `ckLink`, naming the link's mailbox and first room |
| `gz-safety/v1`, `/v2`, `/v3` | ck / live secret / v3 secret | 16 | safety codes (§5.4) |
| `gz-chain/v1` | v3 ECDH secret | 32 | seed of the mailbox chain `kc` |
| `gz-chain/live\|<ck>` | live ECDH secret | 32 | chain seed for pre-chain contacts (§7.3) |
| `gz-chain/next` | chain root | 32 | next week's root |
| `gz-mbox/v1` | ck or gk | 16 | mailbox id, `b64url` (22 chars) |
| `gz-mbox-key/v1` | ck (or a link's `ckLink`) | 32 | static mailbox key of a 1:1 contact (groups use the message key of `gz-group-msg/v1`) |
| `gz-mbox-key/v2` | weekly chain root | 32 | weekly mailbox key |
| `gz-rv/v1\|<day>` | ck | 10 | rendezvous room code: first 7 bytes, each mapped to the 32-symbol alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` by `byte mod 32`; `<day>` = `floor(ms / 86 400 000)` (UTC) |
| `gz-hist/v1` | the conversation's first ck | 16 | opaque history id, `"h:" \|\| b64url` |
| `gz-notify/v1`, `gz-notify/v2\|i`, `…\|o` | ck | 32 | push notification keys, `b64url` |
| `gz-pin/v1\|<4 digits>` | link ECDH secret | 16 | proof of the invite code |
| `gz-hello/v1\|<fs>\|<ke>\|<m>` | link ECDH secret | 16 | tag binding the hello's fields |
| `gz-group-msg/v1` | gk | 32 | group message key |
| `gz-gk2/v1` | ECDH(ephemeral, member `ek`) | 32 | wraps a rotated group key for one member |
| `root` | live ECDH secret | 32 | live session root |
| `msg\|<dir>\|<i>` | live root | 32 | one live message key |

---

## 4. Accounts and the vault

### 4.1 Registration

1. The user picks a username (`^[a-z0-9_.]{3,20}$`, case-folded) and a password.
2. The client draws a 16-byte random `salt` and computes `AK = PBKDF2(password, salt)`,
   `av = b64(SHA-256(AK))`, `verifier = b64(SHA-256(unb64(av)))`.
3. `gizleme-auth` action `register` `{username, display, salt, verifier}` stores the row. The server never
   receives `AK` or the password; it receives `av` only at login.
4. A random device master key `MK` is generated and wrapped (§9). On the first device a random `ABK` is
   created and wrapped with `HKDF(AK, "gz-abk-wrap/v1")`; it is adopted only after the server confirmed it
   stored it (`pushAbk` is set-once and atomic; a second device that loses the race re-pulls and unwraps the
   winner's key).

### 4.2 Login

`salt` (action) returns the account's salt, or a deterministic fake salt (`HMAC(authsecret, "salt|"+user)`,
first 16 bytes) for unknown names. The client recomputes `AK`, sends `av`. The server compares
`SHA-256(av)` to the stored verifier and returns a **session token**: 32 random bytes (`b64`); the server
stores only `SHA-256(token)` with a one-year expiry. The client keeps `{token, username, display}` in
`localStorage` (`gz-session`) — **not** encrypted. The token authenticates `gizleme-vault`, `changepw`,
`delete`, `rename`, `validate`, `gizleme-turn`, and the `putblob`, `delblob`, `ack` actions of `gizleme-mbox` (the
last three are tolerated without a token until 2026-12-15).

`av` is a static value: it is replayable if captured (SECURITY.md, "Login proof is replayable").

### 4.3 Password change and deletion

`changepw` requires the session token **and** the current `av`; it writes the new `salt`, `verifier` and the
re-wrapped ABK in one database transaction (`gz_change_password`), and deletes the account's other sessions.
The ABK itself does not change; contact keys do not rotate. `delete` requires the same two proofs.

### 4.4 The vault

`gizleme-vault`, all actions behind the session token:

- `pull` → `{abk, contacts, cver}`
- `pushAbk {abk}` — set-once (only where the stored `abk` is null)
- `rewrapAbk {abk, av}` — requires the new `av`
- `pushContacts {contacts, cver}` — optimistic concurrency on `cver`: a push based on an old version gets
  `{ok:false, conflict:true, cver}` and the client merges (`mergeContacts`) and retries. The write is
  conditional on the version it was based on.

The blob (`contacts`) is `AES-GCM(vault key, JSON({contacts, groups, ident, gone, …}))`; the server refuses
one whose serialized form exceeds 300 000 characters. It contains, per contact: `ck`, `kc`/`kce`, `sv`, `hk`, `name`, flags and per-chat
settings; per group: `rid`, `gk`, `adm`, `mem`, rotation state; and the account identity key pair (`ident`:
ECDSA `pk`/`sk`, ECDH `ek`/`dk`). **Whoever holds the ABK holds every key in it.**

New device: derive `AK` from the password, `pull`, unwrap the ABK, decrypt the vault, merge. Known device:
the ABK is cached in `localStorage` (`gz-abk`) under `MK`, so unlock needs no network.

---

## 5. Establishing a 1:1 contact

### 5.1 Room-code contacts (manual rooms)

Two people type the same room code. The channel is `ratchet-<code>`. They run the live handshake (§6) with
no prior shared secret, so **the pairing is unauthenticated** (`verifyPeerTag` returns `"n/a"`); the UI
shows the root fingerprint and they compare it out of band. On the first pairing both derive
`ck = HKDF(secret, "gz-contact/v1")` and save the contact.

### 5.2 Invite links (v3) — the normal path

The link is `https://gizleme.com/#i=<b64url(JSON)>`; the fragment is never sent to a server. Fields:

| Field | Meaning |
|---|---|
| `s` | 32-byte random link secret (`b64`) |
| `p` | inviter's one-time ECDH public key (raw P-256, `b64`, 80–100 chars) |
| `n` | inviter's display name |
| `x` | expiry (ms since epoch); default 24 h, 1 h to 7 days; 5 min of skew tolerated |
| `c` | `1` if a 4-digit code (spoken, never in the link) is required |
| `f` | `1` if the inviter's build keeps a mailbox chain |

Inviter (`newPendingInvite`, `persistPendingInvite`): generates `s` and the ECDH pair `(p, pk)`; the private
half `pk` is stored (PKCS#8) in the pending contact record, i.e. in the vault, so any of the inviter's
devices can finish the agreement. `ckLink = HKDF(s, "gz-invite/v1")` names the link's mailbox and the first
rendezvous room.

Opener: generates an ephemeral ECDH pair `(e, ·)`, computes `secret = ECDH(e_priv, p)`, and sends a **hello**
`{t:"hello", v:3, e: b64(e_pub), n, h, m?, fs?, ke?}` in two places: the link's mailbox (encrypted under the
key derived from `ckLink`) and the room's presence. Where present:
- `m = HKDF(secret, "gz-pin/v1|"+code, 16)` proves the invite code;
- `fs = 1`, `ke = epoch` offer a mailbox chain;
- `h = HKDF(secret, "gz-hello/v1|"+fs+"|"+ke+"|"+m, 16)` binds those fields to the secret. Since 2026-12-15 a
  hello without `h` is refused (`HELLO_TAG_FROM`).

Inviter (`processHello`), for the **first** valid hello only: recompute `secret = ECDH(pk, e)`; check `h`;
check the code tag `m` (three wrong codes cancel the link: `dead`); check the expiry; then derive
(`v3Agree`):

```
ck  = HKDF(secret, "gz-contact/v3|" || ckLink)
sv  = HKDF(secret, "gz-safety/v3", 16)            // the safety code
kc  = HKDF(secret, "gz-chain/v1")                  // chain root, only if the opener offered fs
kce = current week     // the inviter instead takes the opener's offered `ke` when it is a number
                       // not above the current week and within 1000 weeks of it (processHello)
```

and discard `pk`. The opener derives the same values from `ECDH(e_priv, p)`. Any later hello for the same
link is not bound: the inviter is warned (once per distinct foreign ephemeral key, at most three times) and the late opener receives a `used` note addressed to its
ephemeral key. Under `ckLink` the inviter writes nothing but its notes to a late or wrong-code opener (`used`, `nopin`); whatever the inviter writes before the link
is opened waits on the inviter's device and is sent under the agreed key afterwards.

### 5.3 Older invite generations

v1/v2 links (the link key is a bearer secret, rotated at the first authenticated live pairing with
`HKDF(secret, "gz-contact/v2")`, with a 14-day reconciliation window `RECON_MS`) are still read for pending
invitations created by older builds. New links are v3.

### 5.4 Safety codes

`sv` (16 bytes) is shown as five emoji (from the first 5 bytes) and 12 bytes of hex (`safetyEmoji`, `safetyHex`). It is bound to the v3 agreement, to
the first live meeting (`gz-safety/v2`) or to `ck` (`gz-safety/v1`, legacy), so someone who merely
intercepted a link cannot produce a matching one. Users compare it in person; the app does not enforce it.

---

## 6. The live channel (1:1)

**Transport.** Supabase Realtime, *private* channel `ratchet-<code>` (presence + broadcast, no self-receive).
For a contact, `<code>` is the rendezvous code of the day (§3, `gz-rv/v1`), so the room changes at 00:00 UTC
(`rolloverRooms`); while a pairing is being reconciled, the pre-rotation room is used.
Realtime authorization only requires the topic to match `ratchet-%` (migration `…_gizleme_schema.sql`):
**knowing the topic name is the only access control on the channel.** All authentication is end-to-end.

**Presence payload** (`presencePayload`), in clear to the relay:

```
{ id, name, u, pub, tag?, tagp?, rk?, hello?, fsu? }
  id    random per-room-join identifier
  name  display name   u  account marker (_acct)
  pub   session ECDH public key (raw P-256, b64)
  tag   b64(HMAC-SHA-256(HKDF(ck,"gz-auth/v1"), pub))      — the pairing proof
  tagp  the same with the pre-rotation key, while reconciling (pre-v3)
  rk    "I see you on the new key too" (pre-v3 reconciliation)
  hello the opener's hello while the link is being bound
  fsu   "I hold no mailbox chain for this contact; offer to start one" (pre-chain contacts)
```

**Pairing** (`onSync` → `verifyPeerTag` → `establish`): among the other entries in presence, only one whose
`tag` verifies under the contact key is eligible; entries of the account's own devices (`u == _acct`) are not
peers. If several qualify the most recent is chosen, with a notice. `tag` signs `pub` only: it does not cover
the room, the day, the peer's key, or the role.

**Session key.** `secret = ECDH(my_priv, peer_pub)`; `root = HKDF(secret, "root")`;
`rootFp = SHA-256(root)[0:4]` shown as `xxxx·xxxx`. The ECDH pair is generated per room join, so a new
session means new keys.

**Message.** `i` is the sender's counter for this root (starts at 0), `dir = senderId || ">" || receiverId`
(the random presence ids), `mk = HKDF(root, "msg|"+dir+"|"+i)`. The plaintext is
`JSON({…envelope, mid})` with `mid` a random 16-hex id. Broadcast event `msg` payload:
`{from, dir, i, iv, ct, mid}`. Receiver (`onMsg`) accepts a message only if `from` is the paired peer, `dir`
equals `peer.id>my.id`, `i` is an integer **greater than the last accepted** `i` (`recvI`), and `mid` is
unseen; after decryption the `mid` inside must equal the one outside. A failed decryption triggers a mailbox
fetch (the message may have been sent to the peer's other device).

**Envelope types** (the plaintext's `t`): `txt`, `img`, `aud` (voice note), `doc`, `poll`, `evt`, `loc`
(location), `ginv` (a group invitation sent in a chat), `vote`, `react`, `edit`, `del`, `exp` (disappearing
timer), `typ`, `rcpt` (receipt), `call`, `hello`/`used`/`nopin` (invite links), and in groups `hi`, `gk2`.
`QUIET_T = {react, edit, exp, vote, del}` produce no sound or unread count.

---

## 7. The mailbox (offline delivery)

### 7.1 Server side

`gizleme-mbox`, table `gizleme_mbox(mbox, mid, from_user, data, ts, delivered_at)`, unique `(mbox, mid)`:

- `put {mbox, mid, data}` — `mbox` matches `^[A-Za-z0-9_-]{22}$`, `mid` matches `^[a-z]?[a-f0-9]{16}$`,
  `JSON(data) ≤ 400 000`; insert-ignore on `(mbox, mid)`; **no authentication** (the key is the access).
  Limits: 120/min per mailbox, 300/min per IP.
- `get {mbox, since}` / `getmany {boxes:[{mbox,since}]}` (≤150 boxes, ≤1500 rows, oldest first) — **no
  authentication**; returns `{mid, from_user, data, ts}` with `ts` assigned by the server.
- `putblob`, `delblob`, `ack` — require the session token (since v42; builds from before are tolerated until
  2026-12-15, `TOKEN_GRACE_UNTIL`).
- `ack {mbox, mids}` marks rows `delivered_at`; the sweep deletes delivered rows after **48 h**
  (`DELIVERED_GRACE_H`) and anything after **14 days** (`TTL_DAYS`).

The relay stores `data = {iv, ct, ep?}`. `ep` is the sender's week number, in clear.

### 7.2 Client side

`mbox id = b64url(HKDF(secret, "gz-mbox/v1", 16))` where `secret` is the contact's current `ck` (1:1) or the
group key `gk` (groups). It is **stable for the life of the contact or key**.

Deposit (`depositOne`): inner plaintext `JSON({…envelope, n: displayName, mid, a: _acct})`, encrypted with a
fresh 96-bit IV under the mailbox key. A 1:1 message is deposited under every key the contact is reachable
on (`depositCKSet`: for a v3 contact only the current `ck`; for older contacts also the previous one while reconciling).

Fetch (`fetchMailbox`, `fetchMailboxId`): the cursor `since` per mailbox lives in the encrypted local
meta; items are skipped if their `mid` was already seen or if they are older than the chat's disappearing
window. For an item with `ep`: the key is `mboxKeyForContact(contact, ep)` (§7.3); if this device has no chain
yet and the item is under 48 h old, the item is left for later. After decryption: `env.mid` must equal the
outer `mid`; `env.a == _acct` marks a message written by one of the account's own devices (shown as sent, never
acknowledged); everything else is dispatched like a live envelope. Acknowledgements go out for the ids that
were not self-written.

### 7.3 The weekly chain (v3 contacts)

```
epoch(t)    = floor(t / 604 800 000 ms)
root_{n+1}  = HKDF(root_n, "gz-chain/next")
key_n       = AES key from HKDF(root_n, "gz-mbox-key/v2")
```

A contact record holds `(kc, kce)`: the root of epoch `kce`. A device keeps only the root of
`current − 2` (`CHAIN_KEEP`) and replaces `(kc, kce)` with it (`advanceChains`); the chain is one-way, so
older roots cannot be recomputed. A deposit made in week *n* is encrypted under `key_n` and carries `ep = n`.
`chainRootAt` refuses `ep < kce` and gaps over 1000. The chain is seeded from the v3 link agreement
(`gz-chain/v1`), or, for a contact that predates it, from the first authenticated live session in which both
sides advertise `fsu` (`gz-chain/live|<ck>`, derived on both ends, never sent). Concurrent seeds converge on
the lexicographically smaller root at the same epoch (`mergeContacts`).

---

## 8. Groups

**Link.** `https://gizleme.com/#g=<b64url(JSON{rid, gk, name, adm?, rot?})>`; `rid` is 16 random symbols of `0-9a-z` (`newRid`, about 82 bits; validators accept 8–32 such characters),
`gk` 32 random bytes, `adm` the creator's ECDSA public key (88 chars of `b64`). The fragment is stripped from
the address bar when consumed.

**Channel and mailbox.** Channel `ratchet-<rid>` (or `ratchet-<rid>-<gkFp>` once the key has been rotated,
where `gkFp` is the first 8 characters of `b64url(SHA-256(gk))`). Message key `HKDF(gk, "gz-group-msg/v1")`.
Mailbox id: `b64url(HKDF(gk, "gz-mbox/v1", 16))`, encrypted under the same message key. Live and mailbox use
the same envelope encryption (no per-message live key in groups).

**Signed messages.** Every account has an identity: ECDSA P-256 `(pk, sk)` and ECDH P-256 `(ek, dk)`, created
once and carried in the vault (devices converge on the oldest `ident`). A group message is the envelope plus
`mid`, `n` (name), `sts` (sender clock, ms), `pk`, `ek`, and `sig`, with

```
sig = ECDSA-SHA-256(sk,  utf8("gz-gsig/v1|" || rid || "|" || JSON(obj without sig and a)))
```

`verifyGroupEnv` returns `ok | bad | changed | unsigned | stale`: `bad` — signature fails; `stale` — `sts`
older than 16 days (`STS_WINDOW`) or more than 1 h in the future (`STS_SKEW`); `changed` — a name already
bound to another `pk`; `unsigned` — missing `pk`/`sig`. Member keys are learned from the first signed message
(trust on first use) and stored in the group's `mem` map. After 2026-12-15 a message without `sts` is `stale`.
Actions that change a chat (`exp`, `react`, `vote`, `edit`, `del`, `typ`) must be validly signed.

**Rotation / removal** (admin only: `adm` equals the signer's `pk`). `rotateGroup` draws a new `gk'` and an
ephemeral ECDH pair `E`. For each remaining member with a known `ek` — and for the admin's own other devices —
it computes `k = HKDF(ECDH(E_priv, ek), "gz-gk2/v1")` and wraps `gk'` with AES-GCM into `w[pk]`. The signed
envelope is `{t:"gk2", g: fp(gk'), e: E_pub, w, x:[removed pks], rc: rotationNumber, p: fp(previous gk)}`. A
member applies it (`onGk2`) only if it is signed by `adm`, `g` is not a key the group has already used
(`fpSeen`, kept in the vault), and — when `rc` is a number — `rc` exceeds the rotation count it holds. (`p` is
signed but receivers do not check it; a non-numeric `rc` skips the count check.) A member with no wrap in `w`
concludes it was removed — but only when the message was read under the current key (`cur`), not from an old
mailbox. The previous key stays readable for 14 days (`prevGk`, `rotAt`) so late writers are not lost.

---

## 9. Local storage

- `MK` — 32 random bytes per device. Wrapped as `{salt, iv, ct}` by `PBKDF2(password-or-PIN, salt)` (200 000
  iterations) → AES-GCM (`setupPin`/`unlockPin`; at account login the *password* is the unlock secret), and
  optionally as `{c, s, iv, ct}` with a WebAuthn **PRF** extension output as the key (`bioPrfKey`,
  `userVerification: "required"`).
- With `MK` unlocked (`gHistKey`): the contacts/groups/meta blob (`gz-local`), the cached ABK (`gz-abk`),
  message history and kept media in IndexedDB `vesper` (v3; stores `msgs`, `media`). Database keys use the
  opaque ids `hk` derived from `ck` (`gz-hist/v1`), never `ck` itself.
- In clear in `localStorage`: the session token and username (`gz-session`), the vault owner marker, the push
  device id (`gz-devid`) and push flag, the per-chat disappearing-timer maps and global default (`gz-exp-rooms`,
  `gz-exp-ts`, `gz-exp-global` — keyed by the opaque `hk` for 1:1 chats but by the group's `rid` for groups;
  since v48 the timer is also kept in the vault record), UI preferences (text size, language, theme…), and the
  PIN/biometric wrapping records (which are ciphertext). Logout removes `gz-exp-rooms` but, as of v48, leaves
  `gz-exp-ts`, `gz-exp-global` and `gz-devid` behind (listed as W14).
- On lock, `MK`-derived keys leave memory and rendered chats are cleared; on logout or a revoked session the
  device is wiped.

---

## 10. Media and documents

A photo, voice note or document piece is encrypted on the device with AES-256-GCM under a **fresh random
256-bit key** and IV, then uploaded with `putblob` (≤ 2 000 000 bytes; session required — until 2026-12-15 a request without a token is still served, see §7.1). The server stores
the ciphertext under a random 48-hex-character name (`<48 hex>.bin`), in a bucket that is public-read by URL
but closed to the anon API; it returns the path. A photo or voice envelope carries `{path, k, iv, mime, …}`; a document envelope carries
`{name, size, mime, k, parts:[{p, iv}]}` — one key, one IV per part. The key travels only inside the encrypted
message. A document is cut into pieces of at most 1 800 000 bytes (10 MB in all, ≤ 6 parts). View-once photos are deleted from the relay after
being viewed (`delblob`); everything else is swept after 14 days.

---

## 11. Calls

Signalling (`offer`, `answer`, `ice`, join/leave) is sent as `t:"call"` envelopes through the chat's own
encrypted, authenticated channel (live path; groups use the group channel), so the SDP and its DTLS
fingerprints are covered by the same keys as messages. In a **group**, call signalling is accepted unless the
signature verdict is `bad`: an `unsigned` or `changed` call envelope is still processed, so the SDP is
authenticated to “a holder of `gk`”, not necessarily to the named signer. Media uses WebRTC **DTLS-SRTP**, peer to peer; group
calls are a full mesh capped at 4. ICE servers: STUN, plus short-lived Cloudflare TURN credentials from
`gizleme-turn` (session required; a 900 s credential minted from a server-held key and shared for two
minutes). There is no application-layer end-to-end encryption on top of DTLS-SRTP; a TURN relay sees
ciphertext and endpoints.

---

## 12. Push notifications

Each side of a 1:1 contact registers a **notification key** `b64url(HKDF(ck, "gz-notify/v2|"+role))` with
`role ∈ {i, o}` (inviter/opener), together with its Web Push subscription and the account marker
(`gizleme-push` `register`: the device's complete set of keys; keys no longer listed are deleted). To wake a
contact the sender calls `notify {notify_key, kind}` with the **other** side's key. The relay sends a Web
Push whose body is fixed text (“New message”, “Incoming call”, “Missed call”, “A contact wants to chat”), a
tag, and a URL `https://gizleme.com/#n=<notify_key>`; the receiving device's service worker adds the contact's
name from a local cache keyed by `SHA-256(notify_key)`. At most 8 devices per key; limits 12 per 10 min for
messages and 40 for call alerts per key, 120 per IP; endpoints are restricted to the browser vendors' push
services. `gz-notify/v1` (the pair's single key) is registered for contacts that have a role only until 2027-02-01; contacts without a role, and every open live room, register it regardless (and a sender falls back to it).

---

## 13. Server API summary

| Function | Actions | Auth |
|---|---|---|
| `gizleme-auth` | `check`, `register`, `salt`, `login` | none (rate-limited) |
| | `changepw`, `delete` | session token **and** `av` |
| | `rename`, `validate` | session token |
| | `logout` | deletes the presented token if any; always answers ok |
| `gizleme-vault` | `pull`, `pushAbk`, `pushContacts` | session token |
| | `rewrapAbk` | session token **and** `av` |
| `gizleme-mbox` | `put`, `get`, `getmany` | none — knowledge of the mailbox id |
| | `putblob`, `delblob`, `ack` | session token (until 2026-12-15 a request with no token is still served, and the per-account blob limit is then skipped; an unknown token is never accepted) |
| `gizleme-push` | `vapid`, `register`, `notify` | none — `notify` needs the notification key; `register` accepts any subscription for any keys |
| | `unregister` | the device's `owner` id (no notification key needed) |
| `gizleme-turn` | (default) | session token |

All functions: `POST` JSON, CORS restricted to `https://gizleme.com` and `https://www.gizleme.com` (a
browser-only control), service-role database access, RLS enabled on every table with no policies. Rate limits
are a Postgres counter (`gz_rl_hit`); **if the counter itself errors the request is allowed** (fail-open).
Tables: `gizleme_accounts`, `gizleme_sessions`, `gizleme_vault`, `gizleme_mbox`, `gizleme_push_subs`,
`gizleme_config` (server secrets: `authsecret`, the VAPID key, and the TURN key unless it is supplied through the function secrets `CF_TURN_KEY_ID`/`CF_TURN_KEY_TOKEN`, plus the media-sweep marker), `gizleme_rl`. The schema is in
`supabase/migrations/`; the function tests are in `tests/edge/`.

---

## 14. Differences from established protocols — where to look hardest

1. **No ratchet on the offline path.** A mailbox message is encrypted under a key that is static per contact
   (legacy) or per week (v3 chain). There is no post-compromise security: a device that learns a chain root
   (a device keeps the root of `current − 2`) reads the three weeks still on the relay and **every later
   week**, because an existing chain is never re-seeded — only a contact with no chain gets one, at a live
   meeting. Earlier weeks stay unreadable.
2. **Live handshake is a bare ECDH.** `root = HKDF(secret, "root")` does not bind the two public keys, the
   room, or the identities into the KDF; authentication is the HMAC over the sender's own `pub` (§6).
3. **The contact key `ck` is a long-lived symmetric secret** shared by both sides and replicated in the vault
   of each. Compromise of either vault yields mailbox access for that contact (for v3 chains: the three weeks
   still on the relay and everything after).
4. **Groups use one static symmetric key** (no sender keys, no per-member ratchets). Rotation is
   admin-initiated and signed.
5. **Account authentication is password-derived only** (PBKDF2-200k → `av` → verifier). A leak of the
   `gizleme_accounts` table allows an offline guess of the password, and the password unwraps the ABK, hence
   the vault.
6. **Nonces are random 96-bit** under long-lived keys (static mailbox key, group key); no counter-based
   nonce scheme.
7. **No padding.** Ciphertext length reveals plaintext length (the mailbox accepts up to 400 000 characters).
8. **Delivery of the client is part of the trust base** (§ THREAT-MODEL, “web delivery”).

See [THREAT-MODEL.md](THREAT-MODEL.md) for how each of these is weighed and what is planned.
