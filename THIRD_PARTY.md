# Third-party components

Everything Gizleme serves comes from this repository (`script-src 'self'`): no CDN, no analytics, no fonts
fetched from elsewhere. The third-party code is vendored under `vendor/` with its licence:

| Component | Version | Licence | Used for |
|-----------|---------|---------|----------|
| [supabase-js](https://github.com/supabase/supabase-js) (`vendor/supabase-*.js`, UMD build from npm) | see file name | MIT — © Supabase | Realtime presence/broadcast, Edge Function calls, storage URLs |
| [QR Code Generator for JavaScript](https://github.com/kazuhikoarase/qrcode-generator) (`vendor/qrcode-1.4.4.js`) | 1.4.4 | MIT — © 2009 Kazuhiko Arase | Drawing the invite QR code (the word "QR Code" is a registered trademark of DENSO WAVE INCORPORATED) |

Server side, the Edge Functions (`supabase/functions/`) import `jsr:@supabase/supabase-js@2` (MIT) and
`npm:web-push@3.6.7` (MIT — © web-push-libs) at deploy time.

Browser APIs only (Web Crypto, WebRTC, Web Push, IndexedDB, MediaRecorder-free audio capture via the Web
Audio API, BarcodeDetector where available) — nothing else.
