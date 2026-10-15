# Contributing

Thanks for looking. Gizleme is small on purpose: a few files, no build step, no framework, no third-party
script at runtime. Changes that keep it that way are the easiest to accept.

## Before you write code

- **Security issues are not issues.** Report them privately (see [SECURITY.md](SECURITY.md)).
- For anything larger than a fix, open an issue first and describe what the relay would learn: Gizleme's
  rule is that the server stores ciphertext, opaque identifiers and timestamps, and nothing it can read.
  A feature that needs more is discussed before it is built.

## Making a change

1. `app.js` is one file on purpose (one IIFE, no modules) so the whole client can be read top to bottom.
   Keep new code next to the code it belongs with, and comment the *why*, not the *what*.
2. Every user-visible string goes through `t("…")` with its French translation in `i18n.js`.
3. Crypto: Web Crypto only (ECDH/ECDSA P-256, HKDF-SHA-256, AES-256-GCM). Every derivation gets its own
   info string (`"gz-<purpose>/v<n>"`). No new primitive without an issue first.
4. If you change what is stored or sent, update [SECURITY.md](SECURITY.md) and `privacy.html` in the same
   pull request — the documents describe what the code does, never more.
5. Bump `CACHE` in `sw.js` when you change a file it caches, or installed apps keep the old one.

## Tests

```
pip install playwright pillow numpy && python -m playwright install --with-deps chromium
python3 tests/run.py
```

Add or extend a scenario in `tests/` for what you change (see [tests/README.md](tests/README.md)). A pull
request is merged when every scenario passes.

## Licence of contributions

Gizleme is under the AGPL-3.0 (see [LICENSE](LICENSE)). By opening a pull request you agree that your
contribution is published under that licence. The maintainer may ask larger contributors to sign a short
contributor agreement so the project keeps the option of offering it under other terms as well; small
fixes never need one.
