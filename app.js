// Gizleme — end-to-end encrypted messaging in the browser. https://gizleme.com
// Copyright (C) 2026 Oğuz Seran
// SPDX-License-Identifier: AGPL-3.0-only
// This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
// General Public License as published by the Free Software Foundation, version 3. It is distributed WITHOUT
// ANY WARRANTY; see the LICENSE file for details.
// Gizleme — application code (served same-origin; no third-party scripts, see _headers for the CSP)
(function(){
"use strict";
const SB_URL = "https://yduldeujlszirctufhsn.supabase.co";
const SB_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlkdWxkZXVqbHN6aXJjdHVmaHNuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIwNDE2MTQsImV4cCI6MjEwNzYxNzYxNH0.cp6zmzhQsUX9_dSMFghT1bCEnUSKi39YctZ6sDEOGJU";
const BUCKET = "vesper-media";
const APP_VERSION = 39;   // same number as the service worker's cache name (sw.js) — a test keeps them in step
const client = supabase.createClient(SB_URL, SB_KEY, { realtime:{ params:{ eventsPerSecond: 25 } } });

const $ = id => document.getElementById(id);
// ---------- language ----------
const LS_LANG="gz-lang";
const LANGS=["en","fr","tr"];   // English is the source; fr and tr live in i18n.js
let LANG=(()=>{ try{ const v=localStorage.getItem(LS_LANG); if(LANGS.includes(v)) return v; }catch(e){}
  // the first of the browser's preferred languages that Gizleme speaks
  const pref=(navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language||""];
  for(const l of pref){ const b=String(l||"").slice(0,2).toLowerCase(); if(LANGS.includes(b)) return b; } return "en"; })();
const DICT=(window.GZ_I18N||{});
function t(key, vars){ let v=(LANG!=="en" && DICT[LANG] && DICT[LANG][key]) || key; if(vars) for(const k in vars) v=v.split("{"+k+"}").join(vars[k]); return v; }
function LOC(){ return LANG==="fr" ? "fr-FR" : LANG==="tr" ? "tr-TR" : []; }
// Initials on avatars: Turkish casing when the app speaks Turkish (i → İ). Never used for room codes.
function up(s){ try{ return LANG==="tr" ? String(s).toLocaleUpperCase("tr-TR") : String(s).toUpperCase(); }catch(e){ return String(s).toUpperCase(); } }
// Stored placeholder names (an invite not yet opened, a default group name) are kept in English in the data
// and translated only when displayed.
const DN_KEYS={"Invited friend":1,"Friend":1,"Group":1,"Contact":1,"Member":1,"Peer":1,"Waiting for peer…":1};
function dn(n){ return (n && DN_KEYS[n]) ? t(n) : n; }
// Translate the static markup in place: every text node and label-like attribute whose English text is a
// dictionary key. Originals are remembered so the language can be switched back without a reload.
const _i18nOrig=new WeakMap();
function applyI18n(){
  document.documentElement.lang=LANG;
  const walker=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode:n=>{ const p=n.parentNode; if(!p||/^(SCRIPT|STYLE)$/.test(p.nodeName)) return NodeFilter.FILTER_REJECT; return n.nodeValue.trim()?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_SKIP; } });
  const nodes=[]; while(walker.nextNode()) nodes.push(walker.currentNode);
  for(const n of nodes){ let o=_i18nOrig.get(n); if(o===undefined){ o=n.nodeValue; _i18nOrig.set(n,o); }
    const key=o.trim(); const tr=t(key); if(tr!==key || n.nodeValue!==o) n.nodeValue=o.replace(key, tr); }
  for(const el of document.body.querySelectorAll("[placeholder],[title],[aria-label]")){
    for(const a of ["placeholder","title","aria-label"]){ if(!el.hasAttribute(a)) continue; const k="data-i18n-"+a.replace("-","");
      let o=el.getAttribute(k); if(o===null){ o=el.getAttribute(a); el.setAttribute(k,o); } el.setAttribute(a, t(o)); } }
}
function setLang(l){ LANG=l; try{ localStorage.setItem(LS_LANG,l); }catch(e){} applyI18n(); renderContacts(); renderTabs(); updateNotifyUI(); updateVerifyUI(); if(typeof _refreshSettingsUI==="function") _refreshSettingsUI(); if(typeof swNamesSoon==="function") swNamesSoon(); }
let _refreshSettingsUI=null;
// ---------- text size (Settings → Appearance): scales every text in the app; fields stay at 16 px or more so an
// iPhone doesn't zoom into them ----------
const LS_TEXT="gz-textsize", TEXT_SIZES=[0.9,1,1.12,1.25,1.4];
function textScale(){ try{ const v=+localStorage.getItem(LS_TEXT); return TEXT_SIZES.includes(v) ? v : 1; }catch(e){ return 1; } }
function applyTextScale(v){ document.documentElement.style.fontSize = v===1 ? "" : (100*v)+"%"; }
applyTextScale(textScale());
const enc = new TextEncoder(), dec = new TextDecoder();
const SALT = enc.encode("vesper/v1");
const hex = b => [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,"0")).join("");
// Chunked: spreading a whole photo into fromCharCode(...) overflows the call stack ("Maximum call stack
// size exceeded") on anything bigger than a few tens of KB, Safari first.
const b64 = b => { const u=new Uint8Array(b); let s=""; for(let i=0;i<u.length;i+=0x8000) s+=String.fromCharCode.apply(null,u.subarray(i,i+0x8000)); return btoa(s); };
const unb64 = s => Uint8Array.from(atob(s), c=>c.charCodeAt(0));
const GLYPHS="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$%&*";

async function genKP(){ return crypto.subtle.generateKey({name:"ECDH",namedCurve:"P-256"},true,["deriveBits"]); }
async function pubRaw(kp){ return crypto.subtle.exportKey("raw",kp.publicKey); }
async function importPub(raw){ return crypto.subtle.importKey("raw",raw,{name:"ECDH",namedCurve:"P-256"},false,[]); }
async function sharedSecret(priv,pub){ return crypto.subtle.deriveBits({name:"ECDH",public:pub},priv,256); }
async function hkdf(ikm,info,len=32){
  const k = await crypto.subtle.importKey("raw",ikm,"HKDF",false,["deriveBits"]);
  return crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode(info)},k,len*8);
}
async function fp(buf){ const h=await crypto.subtle.digest("SHA-256",buf); return hex(h).slice(0,8).replace(/(.{4})(.{4})/,"$1·$2"); }
async function aesKey(raw,uses){ return crypto.subtle.importKey("raw",raw,{name:"AES-GCM"},false,uses||["encrypt","decrypt"]); }
async function aesEnc(key,bytes){ const iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,bytes); return {iv:b64(iv),ct:b64(ct)}; }
async function aesDec(key,ivB64,ctB64){ return crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(ivB64)},key,unb64(ctB64)); }

// ---------- state ----------
const rooms = new Map();   // room code -> room state
const _joining = new Set(); // room codes mid-join (guards a double tap creating two channels for one room)
let active = null;         // active room code
let gHistKey = null;       // device-level history key (shared across rooms)
let myName = "";
let gABK = null;           // account backup key (follows the account; recovers synced contacts)
let gContactsKey = null;   // AES key derived from gABK, encrypts the synced contacts/groups blob
let gVaultCver = 0;        // last-seen server version of the contacts blob (optimistic concurrency)
let gEpoch = 0;            // bumped on logout so an in-flight sync from the previous account can't write into the next
let gRestoring = false;    // true while the first vault pull on an empty device is in flight (sidebar shows "Restoring…")
let _pendingNotify = null; // a #n= notification deep link that arrived before contacts were restored; retried after sync
let _acct = "";            // opaque per-account marker (HKDF of the account backup key): tells our own devices apart without naming the account
let adding = false;        // join screen is being used to ADD a room
function A(){ return active ? rooms.get(active) : null; }
function newRoom(code){ return { code, id:rid(), kp:null, pubB64:"", tag:null, authOk:false, channel:null, peer:null, root:null, rootFp:"", sendI:0, paired:false, logEl:null, unread:0, statusText:"connecting…", statusKind:"busy", statusShort:"", secure:false, peerName:"Waiting for peer…", avatar:"?", fromContact:null, title:null, group:false, rid:null, gk:null, gkMsg:null, seen:null, multiSig:"", recvI:-1 }; }
// (peerName starts as the English placeholder; dn() translates it wherever it is displayed)
// ---------- automatic identity check at every connection ----------
// Two contacts share a secret key (ck) from their first connection or invite link; the relay never has it.
// Each side signs the day's public key with it. A pairing is accepted only if the other side's signature
// verifies, so someone who merely reached the room (a relay, an intercepted room code) can't be paired with.
async function authKeyFor(ckB64){ return crypto.subtle.importKey("raw", await hkdf(unb64(ckB64),"gz-auth/v1"), {name:"HMAC",hash:"SHA-256"}, false, ["sign","verify"]); }
async function authTag(ckB64, pubB64){ return b64(await crypto.subtle.sign("HMAC", await authKeyFor(ckB64), unb64(pubB64))); }
async function authVerify(ckB64, pubB64, tagB64){ try{ return await crypto.subtle.verify("HMAC", await authKeyFor(ckB64), unb64(tagB64), unb64(pubB64)); }catch(e){ return false; } }
async function ensureTag(R){ try{ R.tag = (R.fromContact && R.pubB64) ? await authTag(R.fromContact, R.pubB64) : null;
    const c=R.fromContact?contactFind(R.fromContact):null; R.tagp = (c && c.prev && !c.v3 && reconActive(c) && R.pubB64) ? await authTag(c.prev, R.pubB64) : null; }catch(e){ R.tag=null; R.tagp=null; } }
// ---------- single-use invite links (protocol v2) ----------
// A link-derived contact key is a bearer secret: anyone who kept the link could use it. So at the first
// live pairing that is authenticated with it, both sides derive a NEW contact key from the session's ECDH
// secret — something only these two devices can compute — and retire the link key. Rendezvous rooms,
// mailbox and push keys move to the new key; history, previews and unread counts stay attached to the
// conversation through a stable history key (hk). Other devices of each account learn the new key from the
// vault (contact {ck:new, prev:old, hk, rot}).
async function rotatedCKFromSecret(secret){ return b64(await hkdf(secret,"gz-contact/v2")); }
// History / per-chat settings are keyed by an OPAQUE id derived one-way from the conversation's first key
// (HKDF, 128-bit): the key itself never appears in IndexedDB or localStorage. Stable across key rotations.
const _hid={};
async function hidFor(ck){ return "h:"+b64url(new Uint8Array(await hkdf(unb64(ck),"gz-hist/v1",16))); }
function ckHistKey(ck){ const c=contactFind(ck); if(c && c.hk && c.hk.startsWith("h:")) return c.hk; return _hid[ck] || ("c:"+ck); }
async function histKeyAsync(room){ if(typeof room==="string" && room.startsWith("c:")){ const ck=room.slice(2); if(!_hid[ck]) _hid[ck]=await hidFor((contactFind(ck)||{}).prev||ck); return _hid[ck]; } return room; }
// A contact created during the session (an invite opened, a hello received) starts without its opaque id:
// file it right away, not only at the next unlock — otherwise the chats list looks for its preview and
// unread count under a different key than the one its messages were saved under.
let _hkT=null;
function scheduleHistKeys(){ if(_hkT || !gHistKey) return; _hkT=setTimeout(()=>{ _hkT=null; ensureHistKeys().catch(()=>{}); },30); }
// at unlock: every contact gets its opaque id; anything still filed under a raw key is re-filed
async function ensureHistKeys(){
  const l=contactsLoad(); let changed=false;
  for(const c of l){ try{
    if(c.into){   // merged into another chat (here or on another device): this device's copy of its history goes there too
      const own=await hidFor(c.prev||c.ck); _hid[c.ck]=c.into; if(c.prev) _hid[c.prev]=c.into;
      for(const room of [own, "c:"+c.ck]) if(room!==c.into){ await histMove(room, c.into);
        if(_meta.unread && _meta.unread[room]!==undefined){ _meta.unread[c.into]=(_meta.unread[c.into]||0)+_meta.unread[room]; delete _meta.unread[room]; } }
      if(c.hk!==c.into){ c.hk=c.into; changed=true; } continue; }
    const nh=await hidFor(c.prev||c.ck); _hid[c.ck]=nh; if(c.prev) _hid[c.prev]=nh;
    const old=c.hk||("c:"+c.ck); if(c.hk===nh) continue;
    if(old!==nh){ await histRename(old, nh);
      const m=expRoomsMap(); if(Object.prototype.hasOwnProperty.call(m,old)){ m[nh]=m[old]; delete m[old]; try{ localStorage.setItem(EXP_R,JSON.stringify(m)); }catch(e){} }
      if(old!=="c:"+c.ck && Object.prototype.hasOwnProperty.call(m,"c:"+c.ck)){ m[nh]=m["c:"+c.ck]; delete m["c:"+c.ck]; try{ localStorage.setItem(EXP_R,JSON.stringify(m)); }catch(e){} await histRename("c:"+c.ck, nh); }
      if(_meta.unread && _meta.unread[old]!==undefined){ _meta.unread[nh]=(_meta.unread[nh]||0)+_meta.unread[old]; delete _meta.unread[old]; } }
    c.hk=nh; changed=true;
  }catch(e){} }
  if(changed){ const cur=contactsLoad(); l.forEach(c=>{ const x=cur.find(y=>y.ck===c.ck); if(x) x.hk=c.hk; }); contactsSave(cur); }   // re-read: a patch may have landed meanwhile
}
async function histRename(oldRoom, newRoom){
  if(!oldRoom || oldRoom===newRoom) return;
  try{ const db=await idb(); await new Promise((res,rej)=>{ const tx=db.transaction("msgs","readwrite"); const idx=tx.objectStore("msgs").index("room");
    const rq=idx.openCursor(IDBKeyRange.only(oldRoom)); rq.onsuccess=e=>{ const c=e.target.result; if(!c){ return; } const v=c.value; v.room=newRoom; c.update(v); c.continue(); };
    tx.oncomplete=()=>res(); tx.onerror=()=>rej(tx.error); }); }catch(e){}
}
function contactByPrev(ckOld){ return contactsLoad().find(c=>c.prev===ckOld)||null; }
// After a single-use invite link is retired, the two devices briefly run on different contact keys when one
// rotated and the other hadn't come online to rotate yet: they would then land in different rendezvous rooms
// AND different mailboxes, so each sees the other offline and no message (live or stored) ever arrives.
// During a reconciliation window the rotated side also serves the pre-rotation (link) key — its rendezvous
// room and its mailbox — so the not-yet-rotated side is still reached and converges onto the new key. The
// window ends only when BOTH sides have confirmed seeing each other on the new key (mutual rk in presence),
// never unilaterally — otherwise the two could sit on different rooms and each see the other offline.
const RECON_MS=1209600000;  // 14 days (matches mailbox retention)
function reconActive(c){ return !!(c && c.prev && c.recon && (Date.now()-c.recon < RECON_MS)); }
function rendezvousCKOf(c){ return reconActive(c) ? c.prev : (c?c.ck:null); }
function contactCKSet(ckB64){ const c=contactFind(ckB64); const out=[ckB64]; if(reconActive(c) && c.prev && c.prev!==ckB64) out.push(c.prev); return out; }
// v3 contacts (link = ticket, key agreed by DH at link-open): nothing but the hello is ever written under the
// link key, so a copy of the link reads nothing. Reading and push still cover the link key while reconciling.
function depositCKSet(ckB64){ const c=contactFind(ckB64); return (c && c.v3) ? [ckB64] : contactCKSet(ckB64); }
// what to read: the current key, the link key while reconciling, and — for a v3 contact — the link mailbox for
// 14 days after binding, so a late opener of a leaked link is noticed (hellos only ever land there).
function fetchCKSet(ckB64){ const c=contactFind(ckB64); const out=contactCKSet(ckB64);
  if(c && c.v3 && c.prev && c.rot && Date.now()-c.rot<RECON_MS && !out.includes(c.prev)) out.push(c.prev); return out; }
// "ok" | "bad" | "missing" | "stale" | "n/a" (no shared key yet in this room: first-ever connection via a room code)
async function verifyPeerTag(R, other){
  if(!R.fromContact) return "n/a";
  if(!other || !other.tag) return "missing";
  const c=contactFind(R.fromContact);
  // A v3 invite that nobody has "helloed" yet: the link key alone proves nothing (anyone holding a copy of
  // the link has it), so whoever signs with it is not paired with — the key agreement in the hello is the
  // only way in. An older app opening a v3 link is told to update (its messages are not shown either).
  if(c && c.v3 && c.pk) return "stale";
  if(await authVerify(R.fromContact, other.pub, other.tag)) return "ok";
  // They already rotated (v2) while we still hold the link key: they prove it by also signing with THAT key
  // (tagp). A relay or stranger cannot produce it — the link key never travels. (The former "candidate key"
  // check was derived from the presented public key itself and therefore forgeable: removed.)
  if(c && c.inv && !c.rot && !c.v3 && other.tagp && await authVerify(R.fromContact, other.pub, other.tagp)) return "ok";
  // One of their devices still signs with the retired link key: never paired with (that key may be in other
  // hands), but it's not an attack either — it will catch up once it syncs the account.
  if(c && c.prev && await authVerify(c.prev, other.pub, other.tag)) return "stale";
  return "bad";
}
function rid(){ return [...crypto.getRandomValues(new Uint8Array(8))].map(b=>b.toString(16).padStart(2,"0")).join(""); }
function roomCode(){ const A="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; return [...crypto.getRandomValues(new Uint8Array(6))].map(b=>A[b%A.length]).join(""); }

// ---------- contacts (saved peers -> secret, daily-rotating rendezvous room) ----------
// The per-contact key is derived from the FIRST ECDH shared secret with that peer
// (which the relay never sees) — computed locally on both sides at pairing, so the
// contact + name appear immediately and identically, with no extra round-trip.
const LS_CONTACTS="gz-contacts";          // legacy plaintext key (older builds): imported once, then removed
const B32="ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
// Contact keys and group keys are long-term secrets: on disk they live only in one AES-GCM blob encrypted
// under the device master key (unlocked by password / Face ID). In memory only while the app is unlocked.
const LS_LOCAL="gz-local";
let _contacts=[], _groups=[], _localT=null;
let _meta={unread:{},rcpt:{},viewed:{},outq:{},mbts:{},notified:{}};   // per-chat unread counts, receipts by message id, viewed view-once photos, queued sends, mailbox cursors, push-nudge times
function contactsLoad(){ return _contacts.map(c=>Object.assign({},c)); }
function contactsSave(list){ _contacts=(list||[]).filter(c=>c&&c.ck).map(c=>Object.assign({},c)); try{ _chainCache.clear(); }catch(e){} localSaveSoon(); renderContacts(); syncPushSoon();
  if(_contacts.some(c=>!(c.hk && c.hk.startsWith("h:")))) scheduleHistKeys(); }   // mailbox keys are derived from what is saved here: never reuse one across a change
function localSaveSoon(){ clearTimeout(_localT); _localT=setTimeout(()=>{ localSave().catch(()=>{}); swNamesSoon(); },250); }
// The service worker composes notification text itself ("New message from Baba"), so it needs the names
// you use for your contacts — nickname first — and the sentence templates in your language. Only names
// (never keys) leave the encrypted list; they are cleared on lock-out and account deletion.
let _swNamesT=null;
function swNamesSoon(){ clearTimeout(_swNamesT); _swNamesT=setTimeout(()=>{ swNames().catch(()=>{}); },400); }
async function nkHash(nk){ return b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(nk)))); }
async function swNames(clear){
  if(!("serviceWorker" in navigator)) return; if(!clear && !gHistKey) return;   // locked: the worker keeps what it has
  const names={}, muted={};
  // keyed by a hash of the notify key: the worker's cache (readable at rest) holds names but no capability;
  // for a muted chat, until when its notifications arrive silently
  if(!clear) for(const c of contactsLoad()){ try{ const tg=mergedTarget(c)||c; const nm=tg.alias||(DN_KEYS[tg.name]?"":realName(tg.name)); const mu=mutedUntil(tg); if(!nm && !mu) continue;   // a merged-away key: its chat's name and mute
    const h=await nkHash(await notifyKeyFor(c.ck)); if(nm) names[h]=nm; if(mu) muted[h]=mu; }catch(e){} }
  const msg={type:"names", names, muted, tmpl:{ msg:t("New message from {name}"), chat:t("{name} wants to chat on Gizleme"), call:t("{name} is calling you"), missed:t("Missed call from {name}"), anyMsg:t("New message"), anyChat:t("A contact wants to chat"), anyCall:t("Incoming call"), anyMissed:t("Missed call") }};
  try{ const reg=await navigator.serviceWorker.ready; (reg.active||navigator.serviceWorker.controller)?.postMessage(msg); }catch(e){}
}
async function localSave(){ if(!gHistKey) return; const {iv,ct}=await aesEnc(gHistKey, enc.encode(JSON.stringify({contacts:_contacts,groups:_groups,meta:_meta})));
  try{ localStorage.setItem(LS_LOCAL,JSON.stringify({iv,ct})); }catch(e){} }
async function localLoad(){   // at unlock: decrypt the local copy, and import (then delete) any plaintext left by older builds
  let c=[], g=[];
  let meta=null;
  try{ const r=JSON.parse(localStorage.getItem(LS_LOCAL)||"null"); if(r&&r.ct&&gHistKey){ const o=JSON.parse(dec.decode(await aesDec(gHistKey,r.iv,r.ct))); c=o.contacts||[]; g=o.groups||[]; meta=o.meta||null; } }catch(e){}
  _meta={unread:(meta&&meta.unread)||{}, rcpt:(meta&&meta.rcpt)||{}, viewed:(meta&&meta.viewed)||{}, outq:(meta&&meta.outq)||{}, mbts:(meta&&meta.mbts)||{}, notified:(meta&&meta.notified)||{}, ident:(meta&&meta.ident)||null, gone:(meta&&meta.gone)||{}, delm:(meta&&meta.delm)||{}};
  _identKeys=null;
  // older builds kept mailbox cursors and nudge times in localStorage: take them in, then remove them
  try{ const o=JSON.parse(localStorage.getItem(LS_MBTS)||"null"); if(o){ for(const k in o) if(!(k in _meta.mbts)) _meta.mbts[k]=o[k]; localStorage.removeItem(LS_MBTS); } }catch(e){}
  try{ const o=JSON.parse(localStorage.getItem(LS_NOTIFIED)||"null"); if(o){ for(const k in o) if(!(k in _meta.notified)) _meta.notified[k]=o[k]; localStorage.removeItem(LS_NOTIFIED); } }catch(e){}
  let legacy=false;
  try{ const lc=JSON.parse(localStorage.getItem(LS_CONTACTS)||"[]")||[], lg=JSON.parse(localStorage.getItem(LS_GROUPS)||"[]")||[];
    lc.forEach(x=>{ if(x&&x.ck&&!c.find(y=>y.ck===x.ck)){ c.push(x); legacy=true; } });
    lg.forEach(x=>{ if(x&&x.rid&&!g.find(y=>y.rid===x.rid)){ g.push(x); legacy=true; } }); }catch(e){}
  try{ localStorage.removeItem(LS_CONTACTS); localStorage.removeItem(LS_GROUPS); }catch(e){}
  _contacts=c; _groups=g; if(legacy) localSaveSoon();
  await ensureHistKeys();
  try{ await advanceChains(); }catch(e){}      // forget mailbox keys of weeks the relay no longer holds
  renderContacts(); if(pushOn()&&gPushSub) registerAllContacts(); swNamesSoon();
  // the account marker (what tells our own other devices' messages from the contact's) is restored from the
  // cached backup key first — the inbox pass must not read our own messages as theirs
  abkCacheLoad().catch(()=>false).then(()=>inboxPull(true));   // deliver what arrived while the app was closed, for every chat
}
function localClear(){ clearTimeout(_localT); _contacts=[]; _groups=[]; _meta={unread:{},rcpt:{},viewed:{},outq:{},mbts:{},notified:{}}; _identKeys=null; for(const k in _hid) delete _hid[k]; for(const k in _seenByKey) delete _seenByKey[k]; try{ _chainCache.clear(); }catch(e){} }                       // lock: out of memory, ciphertext stays on disk
function localWipe(){ localClear(); try{ updateBadge(true); }catch(e){} try{ localStorage.removeItem(LS_LOCAL); localStorage.removeItem(LS_CONTACTS); localStorage.removeItem(LS_GROUPS); }catch(e){} }
function realName(n){ return n && n!=="Peer" && n!=="Contact" && n!=="Anon" && n!=="Waiting for peer…" ? n : ""; }
function contactUpsert(name, ckB64){
  name=String(name||"").replace(/[\r\n\t]+/g," ").slice(0,40);
  const list=contactsLoad(); const i=list.findIndex(c=>c.ck===ckB64); const nm=realName(name);
  if(i>=0){ if(nm) list[i].name=nm; list[i].ts=Date.now(); }
  else list.push({name:nm||name||"Contact", ck:ckB64, ts:Date.now()});
  contactsSave(list);
}
// recon is per-device; never let it travel through the vault (a stale copy could resurrect a window we closed)
function contactsForVault(){ return contactsLoad().map(c=>{ if(c.recon){ const d=Object.assign({},c); delete d.recon; return d; } return c; }); }
// Removed contacts and left groups are remembered (tombstones, in the vault blob) so another device that still
// holds the record does not bring it back at the next merge; a record saved after the removal wins again.
function tombstone(key){ _meta.gone=_meta.gone||{}; _meta.gone[key]=Date.now(); const ks=Object.keys(_meta.gone); if(ks.length>300) ks.sort((a,b)=>_meta.gone[a]-_meta.gone[b]).slice(0,ks.length-300).forEach(k=>{ delete _meta.gone[k]; }); }
function contactRemove(ckB64){
  const T=contactFind(ckB64); const gone=c=>c.ck===ckB64 || !!(T && T.hk && c.into && c.into===T.hk);   // with the chats merged into it
  const l=contactsLoad(); const drop=new Set(l.filter(gone).map(c=>c.ck));
  [...rooms.values()].filter(R=>drop.has(R.fromContact)).forEach(R=>leaveRoom(R.code));   // or the next presence sync re-saves them
  for(const ck of drop){ try{ delete _meta.unread[ckHistKey(ck)]; }catch(e){} if(_meta.outq) delete _meta.outq[ck]; tombstone(ck); }   // nothing left to count or send
  contactsSave(l.filter(c=>!drop.has(c.ck))); updateBadge(true); }
async function ckFromSecret(secret){ return b64(await hkdf(secret,"gz-contact/v1")); }  // ECDH secret -> stable contact key
async function rvCodeFromCK(ckB64){         // secret room code for today's window
  const day=Math.floor(Date.now()/86400000);
  const u=new Uint8Array(await hkdf(unb64(ckB64),"gz-rv/v1|"+day, 10));
  let s=""; for(let i=0;i<7;i++) s+=B32[u[i]%B32.length]; return s;
}
async function openContact(ckB64, name){
  { const tg=mergedTarget(contactFind(ckB64)); if(tg) return openContact(tg.ck, tg.alias||tg.name); }
  closeSidebar();
  const rvck=rendezvousCKOf(contactFind(ckB64))||ckB64;    // while reconciling, meet on the pre-rotation room
  const code=await rvCodeFromCK(rvck);
  if(rooms.has(code)){ switchTo(code); return; }
  await doJoin(code,{fromContact:ckB64,title:name});
}
function closeSidebar(){ const s=$("sidebar"); if(s) s.classList.remove("open"); const b=$("sbBackdrop"); if(b) b.classList.remove("show"); }

// ---------- invite links: the easy way to connect, and it works even when you're not online together ----------
// The link carries a random secret in the URL fragment (never sent to a server, like group links). Both sides
// derive the same contact key from it, so the invitee is your contact the moment they open the link and can
// write to you straight away through the encrypted mailbox. The identity safety code for such contacts is
// bound to your first *live* key exchange (see establish), not to the link, so an intercepted link is detectable.
const INV_PLACEHOLDER="Invited friend";
let _pendingInvite=null;   // {s, ck, url, saved} — the link shown on the New chat screen, saved as a contact once shared/opened
async function ckFromInviteSecret(sB64){ return b64(await hkdf(unb64(sB64),"gz-invite/v1")); }
function inviteLinkFromSecret(sB64, pubB64, opts){ const o={s:sB64,n:realName(myName)?myName:""}; if(pubB64) o.p=pubB64;
  if(opts && opts.x) o.x=opts.x;          // expiry (ms since epoch): the opener refuses it after, the inviter ignores late hellos
  if(opts && opts.c) o.c=1;               // a 4-digit code, given by voice, is needed to open it (the code is never in the link)
  o.f=1;                                  // this build keeps a forward-secret mailbox chain; the opener answers with fs:1 if it does too
  return CANONICAL+"/#i="+b64url(enc.encode(JSON.stringify(o))); }
function parseInviteLink(text){ try{ const s=(text||"").trim(); const i=s.indexOf("#i="); if(i<0) return null;
  const o=JSON.parse(dec.decode(unb64url(s.slice(i+3)))); if(o&&typeof o.s==="string"&&o.s.length>20){ if(o.p!==undefined && !(typeof o.p==="string" && o.p.length>=80 && o.p.length<=100)){ delete o.p; o.damaged=1; }
    if(o.x!==undefined && !(typeof o.x==="number" && o.x>0)) delete o.x; if(o.c!==undefined && o.c!==1) delete o.c; if(o.f!==undefined && o.f!==1) delete o.f; return o; } }catch(e){} return null; }
const INV_GRACE_MS=5*60*1000;   // clock skew allowed on expiry checks
function inviteExpired(x){ return !!(x && Date.now() > x + INV_GRACE_MS); }
function inviteOpts(){ const sel=$("invExp"), pin=$("invPinOn"); return { x: Date.now() + (sel ? (+sel.value||86400000) : 86400000), c: !!(pin && pin.checked) }; }
function newPin(){ const a=crypto.getRandomValues(new Uint16Array(1))[0] % 10000; return String(a).padStart(4,"0"); }
async function pinTag(secret, pin){ return b64(await hkdf(secret, "gz-pin/v1|"+String(pin||""), 16)); }   // proves the code to the inviter; not guessable offline (needs the ECDH secret)
function contactFind(ck){ return contactsLoad().find(c=>c.ck===ck)||null; }
// ----- two chats with the same person, merged -----
// Each conversation has its own key and a name proves nothing, so Gizleme never merges chats by itself. You can
// fold an older chat into the one you are in: its messages (already on this device) are filed under this chat's
// history id, it leaves the chats list, and whatever still arrives on its key lands here too. Its record stays,
// hidden and marked into: <this chat's history id>, so its mailbox keeps being read and the merge follows the
// account to its other devices (each moves its own copy at unlock). Nothing is sent; the other side's app is
// not changed.
function mergedTarget(c){ return c && c.into ? (_contacts.find(x=>x.hk===c.into && !x.into)||null) : null; }
async function histMove(fromRoom, toRoom){ if(!fromRoom || !toRoom || fromRoom===toRoom) return;
  try{ const db=await idb(); await new Promise((res,rej)=>{ const tx=db.transaction(["msgs","media"],"readwrite");
    for(const st of ["msgs","media"]){ const rq=tx.objectStore(st).index("room").openCursor(IDBKeyRange.only(fromRoom));
      rq.onsuccess=e=>{ const c=e.target.result; if(!c) return; const v=c.value; v.room=toRoom; c.update(v); c.continue(); }; }
    tx.oncomplete=()=>res(); tx.onerror=()=>rej(tx.error); }); }catch(e){} }
function mergeCandidates(R){ if(!R || R.group || !R.fromContact) return [];
  return contactsLoad().filter(c=>c.ck!==R.fromContact && !c.into && !c.pk && c.name!==INV_PLACEHOLDER); }
async function mergeChatInto(R, oldCk){
  if(!R || R.group || !R.fromContact || !gHistKey) return false;
  await ensureHistKeys();
  const T=contactFind(R.fromContact), S=contactFind(oldCk); if(!T || !S || T.ck===S.ck || S.into || T.into) return false;
  const tHk=await hidFor(T.prev||T.ck), sOwn=await hidFor(S.prev||S.ck);
  for(const room of new Set([sOwn, S.hk, "c:"+S.ck])) if(room && room!==tHk){ await histMove(room, tHk);
    if(_meta.unread[room]!==undefined){ _meta.unread[tHk]=(_meta.unread[tHk]||0)+_meta.unread[room]; delete _meta.unread[room]; }
    delete _prev[room]; }
  const l=contactsLoad(); const s2=l.find(x=>x.ck===S.ck), t2=l.find(x=>x.ck===T.ck); if(!s2 || !t2) return false;
  t2.hk=tHk; s2.into=tHk; s2.hk=tHk; s2.its=Date.now(); _hid[S.ck]=tHk; if(S.prev) _hid[S.prev]=tHk;
  if((!realName(t2.name) || t2.name===INV_PLACEHOLDER || t2.name==="Friend") && realName(S.name)){ t2.name=S.name; t2.ts=Date.now(); }
  if(!t2.alias && S.alias){ t2.alias=S.alias; t2.ats=Date.now(); }
  contactsSave(l);
  [...rooms.values()].filter(x=>x.fromContact===S.ck).forEach(x=>leaveRoom(x.code));   // the old chat's tab, if open
  // this chat, shown again with both histories in time order
  if(R.logEl){ R.logEl.innerHTML=""; delete R.logEl.dataset.lastDay; R.reacts=null; renderHistory(R, await histLoad(tHk));
    sysline(R.logEl, t("🔗 Your earlier chat with {name} is now part of this one.",{name:S.alias||dn(S.name)})); scrollEl(R.logEl); }
  renderTabs(); renderContacts(); refreshPreviews(); updateBadge(true);
  return true;
}
function contactPatch(ck, fields){ const l=contactsLoad(); const c=l.find(x=>x.ck===ck); if(c){ Object.assign(c,fields); contactsSave(l); } }
// v3: the link carries a one-time public key (pre-key) whose private half stays with the inviter. Whoever opens
// the link agrees a contact key with it by ECDH — a key nobody can compute from the link alone. The link key
// (derived from the secret) only names the mailbox the "hello" is left in and the room where the two first meet.
async function newPendingInvite(){
  const s=b64(crypto.getRandomValues(new Uint8Array(32)));
  const kp=await genKP(); const pp=b64(await pubRaw(kp)); const pk=b64(await crypto.subtle.exportKey("pkcs8",kp.privateKey));
  _pendingInvite={ s, ck:await ckFromInviteSecret(s), pp, pk, pin:newPin(), url:"", saved:false };
  refreshInviteUrl();
}
// The link text follows the options (validity, code) until it is shared; once shared or opened it is frozen.
function refreshInviteUrl(){
  const pi=_pendingInvite; if(!pi) return;
  if(!pi.saved){ const o=inviteOpts(); pi.x=o.x; pi.c=o.c; pi.url=inviteLinkFromSecret(pi.s, pi.pp, {x:o.x, c:o.c}); }
  const o=$("invLinkOut"); if(o) o.value=pi.url;
  const pb=$("invPinBox"); if(pb){ pb.hidden=!pi.c; const v=$("invPinVal"); if(v) v.textContent=pi.pin; }
  const sel=$("invExp"), pin=$("invPinOn"); if(sel) sel.disabled=!!pi.saved; if(pin) pin.disabled=!!pi.saved;
  const qb=$("qrBox"); if(qb && !qb.hidden) drawQr(pi.url);
}
function persistPendingInvite(){   // the inviter keeps a placeholder contact that becomes the person once they open the link
  const pi=_pendingInvite; if(!pi||pi.saved) return;
  if(!contactFind(pi.ck)){ const l=contactsLoad(); const c={name:INV_PLACEHOLDER, ck:pi.ck, inv:1, is:pi.s, pk:pi.pk, pp:pi.pp, v3:1, ts:Date.now()};
    if(pi.x) c.x=pi.x; if(pi.c) c.pin=pi.pin; l.push(c); contactsSave(l); }
  pi.saved=true; refreshInviteUrl(); if(pushOn()) registerAllContacts();
}
function drawQr(url){
  const cv=$("qrCanvas"); if(!cv || typeof qrcode!=="function") return;
  try{ const q=qrcode(0,"L"); q.addData(url,"Byte"); q.make(); const n=q.getModuleCount(); const cell=6; const size=cell*n;   // crisp bitmap, shown at 240 css px
    cv.width=size; cv.height=size; cv.style.width="240px"; cv.style.height="240px"; const ctx=cv.getContext("2d"); ctx.fillStyle="#fff"; ctx.fillRect(0,0,size,size); ctx.fillStyle="#000";
    for(let r=0;r<n;r++) for(let c=0;c<n;c++) if(q.isDark(r,c)) ctx.fillRect(c*cell, r*cell, cell, cell); }catch(e){}
}
function toggleQr(){ const qb=$("qrBox"); const pi=_pendingInvite; if(!qb||!pi) return; if(qb.hidden){ persistPendingInvite(); drawQr(pi.url); qb.hidden=false; } else qb.hidden=true; }
// 4-digit code prompt for the opener (the inviter said it by voice). Resolves to the code or null.
function askPin(name){ return new Promise(res=>{
  const m=$("pinModal"), inp=$("pinInput"), msg=$("pinMsg"); if(!m||!inp) return res(null);
  $("pinSub").textContent=t("{name} protected this invite with a 4-digit code.",{name:name||t("Your contact")}); inp.value=""; msg.textContent="";
  const done=v=>{ m.classList.remove("show"); $("pinOk").onclick=null; $("pinCancel").onclick=null; inp.onkeydown=null; res(v); };
  $("pinOk").onclick=()=>{ const v=(inp.value||"").replace(/\D/g,""); if(v.length!==4){ msg.textContent=t("Enter the 4 digits"); return; } done(v); };
  $("pinCancel").onclick=()=>done(null); inp.onkeydown=e=>{ if(e.key==="Enter") $("pinOk").onclick(); };
  m.classList.add("show"); setTimeout(()=>{ try{ inp.focus(); }catch(e){} },50);
}); }
async function v3Agree(secret, ckLink){ return { ck:b64(await hkdf(secret,"gz-contact/v3|"+ckLink)), sv:b64(await hkdf(secret,"gz-safety/v3",16)), kc:b64(await hkdf(secret,"gz-chain/v1")), kce:epochNow() }; }
// The inviter: a hello arrived (mailbox or presence) for a link we created → bind the contact to that opener.
async function processHello(ckLink, e, n, m, fs, ke){
  const c=contactFind(ckLink); if(!c) return false;
  if(!c.pk){ const bound=contactByPrev(ckLink); if(isForeignHello(bound, e)) noteLinkReuse(bound, ckLink, e); return false; }
  if(c.dead) return false;                                   // cancelled (three wrong codes): nothing binds any more
  if(inviteExpired(c.x)){ if(!c.expired){ contactPatch(ckLink,{expired:1}); noteLinkEvent(ckLink, t("⏳ Someone opened this invite link after it expired — nothing happened. Make a new link if that was your friend."), "expired"); } return false; }
  let secret; try{ const priv=await crypto.subtle.importKey("pkcs8", unb64(c.pk), {name:"ECDH",namedCurve:"P-256"}, false, ["deriveBits"]);
    secret=await sharedSecret(priv, await importPub(unb64(e))); }catch(err){ return false; }
  if(c.pin){   // the opener must prove the code the inviter said by voice; three misses cancel the link
    const want=await pinTag(secret, c.pin); if(!m || m!==want){
      const fails=(c.pinFails||0)+1; const seen=(c.pinSeen||[]); if(seen.includes(e)) return false;   // same hello twice (mailbox + presence) counts once
      contactPatch(ckLink, fails>=3 ? {pinFails:fails, dead:1, pinSeen:seen.concat([e]).slice(-6)} : {pinFails:fails, pinSeen:seen.concat([e]).slice(-6)});
      try{ await depositOne(await mboxIdForSecret(ckLink), await mboxKeyForSecret(ckLink), "n"+rid(), {t:"nopin", e}); }catch(_e){}   // tell that opener (addressed to its ephemeral key)
      noteLinkEvent(ckLink, fails>=3 ? t("⛔ Three wrong codes on your invite link — it is cancelled. Make a new link for your friend.") : t("⚠ Someone opened your invite link with a wrong code ({n}/3). If it was your friend, give them the code again.",{n:fails}), fails>=3?"dead":"warn");
      return false; } }
  const ag=await v3Agree(secret, ckLink); const ck2=ag.ck;
  const l=contactsLoad(); const i=l.findIndex(x=>x.ck===ckLink); if(i<0 || l.some(x=>x.ck===ck2)) return false;
  const x=l[i]; x.prev=ckLink; x.hk=x.hk||("c:"+ckLink); x.ck=ck2; x.rot=Date.now(); x.recon=Date.now(); x.sv=ag.sv;
  if(fs){ x.kc=ag.kc; x.kce=(typeof ke==="number" && ke<=ag.kce && ag.kce-ke<=1000) ? ke : ag.kce; } else { delete x.kc; delete x.kce; }   // the opener's build keeps the chain too, or neither side does; the chain counts from the opener's week
  x.v3=1; x.he=e;
  if(realName(n)) x.name=n; delete x.is; delete x.pk; delete x.pp; x.ts=Date.now();
  contactsSave(l);
  const shown=x.alias||dn(x.name);
  rooms.forEach(r=>{ if(r.fromContact!==ckLink) return; r.fromContact=ck2;
    if(realName(n) && !x.alias){ r.title=n; r.peerName=dn(n); r.avatar=up(n[0]||"?"); if(r.code===active){ $("peerName").textContent=r.peerName; $("peerAvatar").textContent=r.avatar; } }
    ensureTag(r).then(()=>{ try{ if(r.tag&&r.channel) r.channel.track(presencePayload(r)); }catch(_e){} });
    if(r.logEl){ sysline(r.logEl, t("🔒 {name} opened your link · end-to-end encrypted",{name:shown})); r._linkLine=Date.now(); }
    if(r.code===active) setIdle(r); });
  renderTabs(); renderContacts(); updateVerifyUI(); if(pushOn()) registerAllContacts();
  await flushOutq(ckLink, ck2);
  setTimeout(async()=>{ let R2=null; rooms.forEach(r=>{ if(r.fromContact===ck2) R2=r; }); if(!R2) R2=await shadowRoom({t:"c",ck:ck2,name:x.name}); fetchMailbox(R2).catch(()=>{}); },400);
  return true;
}
// Something happened to a pending link (expired opener, wrong code): a line in its chat, or a toast.
function noteLinkEvent(ckLink, msg, kind){
  let R=null; rooms.forEach(r=>{ if(r.fromContact===ckLink) R=r; });
  if(R&&R.logEl) sysline(R.logEl, msg, kind!=="expired"); else toast(msg);
  if(R && R.code===active) setIdle(R); renderContacts();
}
// A hello for a link that is already bound: a copy of the link in other hands. Only the INVITER can tell — its
// bound record remembers the opener it bound to (he). The opener reads the same link mailbox (for "used" /
// "nopin" notices) and finds its own hello there; that one is never someone else's, even when it was left
// before the account marker was ready (a link opened while logging in or signing up) and so isn't flagged
// as our own. Mistaking it once told the opener "this link was already used by someone else".
function isForeignHello(bound, e){
  return !!(bound && bound.v3 && !bound.pk && bound.he && e && bound.he!==e && !(bound.hello && bound.hello.e===e) && !(bound.reuseSeen||[]).includes(e));
}
function noteLinkReuse(c, ckLink, e){
  const n=(c.reuse||0)+1; contactPatch(c.ck,{reuse:n, reuseSeen:(c.reuseSeen||[]).concat([e]).slice(-5)}); if(n>3) return;
  const msg=t("⚠ Someone else just opened the invite link you sent to {name}. They were not added — this chat's key was never in the link. If you only shared that link once, it has leaked.",{name:c.alias||dn(c.name)});
  let R=null; rooms.forEach(r=>{ if(r.fromContact===c.ck) R=r; }); if(R&&R.logEl) sysline(R.logEl,msg,true); else toast(msg);
  mboxKeyForSecret(ckLink).then(async key=>{ await depositOne(await mboxIdForSecret(ckLink), key, "u"+rid(), {t:"used", e:e||""}); }).catch(()=>{});
}
async function onHelloEnv(R, ck, env){
  if(!env || typeof env.e!=="string" || env.e.length<80 || env.e.length>100) return;
  const c=contactFind(ck);
  if(c && c.pk) { await processHello(ck, env.e, env.n, env.m, env.fs===1, env.ke); return; }
  const bound=contactByPrev(ck); if(isForeignHello(bound, env.e)) noteLinkReuse(bound, ck, env.e);
}
function onUsedEnv(R, ck, env){
  const c=R.fromContact?contactFind(R.fromContact):null; if(!c || !c.v3 || c.he || c.prev!==ck || !c.hello || !env || env.e!==c.hello.e) return;
  if(env.t==="nopin"){   // our code was wrong: this attempt is void; opening the link again asks for the code afresh
    contactPatch(c.ck,{dead:1, nopin:1}); const l=contactsLoad(); const x=l.find(y=>y.ck===c.ck); if(x){ delete x.hello; contactsSave(l); }
    { const msg=t("⚠ The code you entered was wrong — you are not connected to {name}. Open their link again and enter the code they gave you.",{name:c.alias||dn(c.name)}); if(R.logEl) sysline(R.logEl, msg, true); else toast(msg); }
    if(R.code===active) setStatus(R, t("wrong code — open the link again"), false, "warn", t("wrong code"));
    renderContacts(); return; }
  contactPatch(c.ck,{dead:1}); const l=contactsLoad(); const x=l.find(y=>y.ck===c.ck); if(x){ delete x.hello; contactsSave(l); }
  { const msg=t("⚠ This invite link had already been used by someone else before you opened it — you are not connected to {name}. Ask them for a new link.",{name:c.alias||dn(c.name)}); if(R.logEl) sysline(R.logEl, msg, true); else toast(msg); }
  if(R.code===active) setStatus(R, t("invite link already used — ask for a new one"), false, "warn", t("link used"));
  renderContacts();
}

function isPendingInvite(c){ return !!(c && c.inv && c.is && c.name===INV_PLACEHOLDER); }
async function acceptInvite(inv){   // someone opened a link: become their contact and open the chat
  const ck0=await ckFromInviteSecret(inv.s);
  let rotated=contactByPrev(ck0);                        // this link's contact already moved to an agreed key
  if(rotated && rotated.nopin){ contactRemove(rotated.ck); rotated=null; }   // a wrong-code attempt is void: start over with the code
  let ck=rotated?rotated.ck:ck0;
  let mine=contactFind(ck);
  try{ history.replaceState(null,"","/"); }catch(e){}
  if(mine && mine.is===inv.s){ toast(t("That's your own invite link — send it to a friend")); goHome(); return; }
  if(!mine && inv.damaged){ toast(t("This invite link is damaged — ask your friend for a new one")); goHome(); return; }
  if(!mine && inviteExpired(inv.x)){ toast(t("This invite link has expired — ask your friend for a new one")); goHome(); return; }
  const nm=realName(inv.n)?inv.n:"Friend";   // stored in English, shown translated (dn)
  if(!mine && inv.p){
    // v3: agree the contact key with the inviter's pre-key right now; leave a hello in the link mailbox
    let secret, eph, ephPub;
    try{ eph=await genKP(); ephPub=b64(await pubRaw(eph)); secret=await sharedSecret(eph.privateKey, await importPub(unb64(inv.p))); }catch(e){ secret=null; }
    if(!secret){ toast(t("This invite link is damaged — ask your friend for a new one")); goHome(); return; }   // never fall back to the bare link key
    let m=null; if(inv.c){ const pin=await askPin(dn(nm)); if(pin===null){ goHome(); return; } m=await pinTag(secret, pin); }
    if(secret){
      const ag=await v3Agree(secret, ck0); ck=ag.ck;
      const l=contactsLoad(); const hello={e:ephPub,n:realName(myName)?myName:""}; if(m) hello.m=m; if(inv.f){ hello.fs=1; hello.ke=ag.kce; }
      const rec={name:nm, ck, inv:1, rot:Date.now(), prev:ck0, hk:"c:"+ck, recon:Date.now(), sv:ag.sv, v3:1, hello, ts:Date.now()};
      if(inv.f){ rec.kc=ag.kc; rec.kce=ag.kce; }   // both builds keep the chain, or neither does
      l.push(rec); contactsSave(l); mine=contactFind(ck);
      // the hello carries the week the chain starts in (ke): the inviter may only read it days later, in another
      // week, and both sides must count the chain from the same week. If the deposit fails it is retried at the
      // next mailbox pass (hp) — without it the inviter would never bind.
      let okH=false; try{ const env={t:"hello",v:3,e:ephPub}; if(m) env.m=m; if(inv.f){ env.fs=1; env.ke=ag.kce; } okH=await depositOne(await mboxIdForSecret(ck0), await mboxKeyForSecret(ck0), "h"+rid(), env); }catch(e){}
      if(!okH) contactPatch(ck,{hp:1});
      if(pushOn()) registerAllContacts(); notifyPeer(ck0,"chat").catch(()=>{});
    }
  }
  if(!mine){ const l=contactsLoad(); l.push({name:nm, ck, inv:1, ts:Date.now()}); contactsSave(l); if(pushOn()) registerAllContacts(); }
  else if(!realName(mine.name)||mine.name==="Friend"){ contactPatch(ck,{name:nm,ts:Date.now()}); }
  await openContact(ck, nm);
}
// A contact who has written to us reveals their name inside the encrypted envelope — adopt it for placeholders.
function adoptNameFromMessage(R, n){
  if(!R||R.group||!R.fromContact||!realName(n)) return;
  const c=contactFind(R.fromContact); if(!c || (c.name!==INV_PLACEHOLDER && c.name!=="Friend")) return;
  contactPatch(R.fromContact,{name:n}); if(c.alias) return; R.title=n; R.peerName=dn(n); R.avatar=up(n[0]||"?");
  if(R.code===active){ $("peerName").textContent=n; $("peerAvatar").textContent=R.avatar; } renderTabs();
}
function activeCK(){ const R=A(); return R&&R.fromContact||null; }
// ---------- a colour for each chat's avatar ----------
// A long press (right click on a computer) on a chat in the list opens a small palette: the round avatar of that
// chat takes the colour chosen — in the list, at the top of the chat and on the call screen. Saved with the
// contact (or group) in your encrypted list, so it follows your account to your other devices; the other
// person never sees it.
const AVA_COLORS={violet:"#7c3aed", indigo:"#4f46e5", blue:"#2563eb", sky:"#0369a1", teal:"#0f766e", green:"#15803d",
  lime:"#4d7c0f", amber:"#b45309", orange:"#c2410c", red:"#dc2626", pink:"#db2777", slate:"#475569"};
// every contact has a colour of its own even when none was chosen: picked from its key, the same on every screen
function autoColor(seed){ const ks=Object.keys(AVA_COLORS); let h=0; for(const ch of String(seed||"")) h=(h*31+ch.charCodeAt(0))>>>0; return AVA_COLORS[ks[h%ks.length]]; }
function chatColor(rec, isGroup){ if(rec && AVA_COLORS[rec.cl]) return AVA_COLORS[rec.cl]; return (!isGroup && rec && rec.ck) ? autoColor(rec.ck) : ""; }
function recOfId(id){ id=String(id||""); if(id.startsWith("g:")) return _groups.find(g=>g.rid===id.slice(2))||null;
  if(id.startsWith("c:")) return _contacts.find(c=>c.ck===id.slice(2))||null; return null; }
function roomColor(R){ const rec=muteRecOf(R); return chatColor(rec, !!(R && R.group)); }
function paintPeerAvatar(){ const e=$("peerAvatar"); if(!e) return; const R=A(); e.style.background=R ? roomColor(R) : ""; e.classList.toggle("grp", !!(R && R.group)); }
function setAvaColor(id, key){ const now=Date.now(); id=String(id||"");
  const apply=rec=>{ if(key && AVA_COLORS[key]) rec.cl=key; else delete rec.cl; rec.cts=now; };
  if(id.startsWith("g:")){ const l=groupsLoad(); const g=l.find(x=>x.rid===id.slice(2)); if(!g) return false; apply(g); groupsSave(l); }
  else if(id.startsWith("c:")){ const l=contactsLoad(); const c=l.find(x=>x.ck===id.slice(2)); if(!c) return false; apply(c); contactsSave(l); }
  else return false;
  paintPeerAvatar(); return true; }
let _colFor=null;
function openColorPick(row){
  const id=row && row.dataset.id; const rec=recOfId(id); if(!rec) return;
  closePicker(); _colFor=id;
  const pk=$("colPick"), g=$("colGrid");
  if(!g.childElementCount){
    const d=document.createElement("button"); d.type="button"; d.className="sw auto"; d.dataset.c=""; d.textContent="↺"; d.title=t("Default colour"); d.setAttribute("aria-label",d.title); g.appendChild(d);
    for(const k in AVA_COLORS){ const b=document.createElement("button"); b.type="button"; b.className="sw"; b.dataset.c=k; b.style.background=AVA_COLORS[k]; b.setAttribute("aria-label",k); g.appendChild(b); } }
  const nm=rec.alias || dn(rec.name) || (id.startsWith("g:") ? t("Group") : t("Contact"));
  $("colTitle").textContent=t("Colour for {name}",{name:nm});
  g.querySelectorAll("button").forEach(b=>b.classList.toggle("on", (b.dataset.c||"")===(AVA_COLORS[rec.cl] ? rec.cl : "")));
  pk.hidden=false;
  const a=(row.querySelector(".ava")||row).getBoundingClientRect(), w=pk.offsetWidth, h=pk.offsetHeight;
  const ap=$("app"), dy=(ap && ap.style.transform) ? ap.getBoundingClientRect().top : 0;
  let top=a.bottom+8; if(top+h>viewH()-8) top=Math.max(8, a.top-h-8); top-=dy;
  const left=Math.max(8, Math.min(a.left, window.innerWidth-w-8));
  pk.style.top=Math.round(top)+"px"; pk.style.left=Math.round(left)+"px";
}
function closeColorPick(){ const pk=$("colPick"); if(pk) pk.hidden=true; _colFor=null; }

// ---------- search (v38): chats by name, then messages from this device's history ----------
function fold(s){ return String(s||"").toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/ı/g,"i"); }
function foldMap(s){ let out=""; const map=[]; for(let i=0;i<s.length;i++){ const f=fold(s[i]); for(let k=0;k<f.length;k++){ out+=f[k]; map.push(i); } } map.push(s.length); return {out, map}; }
let _sq="", _sRes=null, _sCache=null, _sCacheAt=0, _sGen=0, _sT=null;
function searchStale(){ _sCache=null; if(_sq) { clearTimeout(_sT); _sT=setTimeout(runSearch, 300); } }
function chatMatches(it){ return !_sq || fold((it.alias||"")+" "+dn(it.name||"")).includes(_sq); }
// put the matching part of text in <mark>, around a short window
function markText(el, text, q, win){ const {out, map}=foldMap(text); const i=out.indexOf(q); el.textContent="";
  if(i<0){ el.textContent=text; return; }
  let a=map[i], z=map[Math.min(i+q.length, map.length-1)]; if(i+q.length>=out.length) z=text.length;
  let s0=0, s1=text.length; if(win && text.length>win*2){ s0=Math.max(0, a-win); s1=Math.min(text.length, z+win); }
  el.append((s0>0?"…":"")+text.slice(s0, a)); const mk=document.createElement("mark"); mk.textContent=text.slice(a, z); el.append(mk, text.slice(z, s1)+(s1<text.length?"…":"")); }
function searchable(past, k){
  const dur=expFor(k), cut=dur?Date.now()-dur:0, ed=new Map(), gone=new Set();
  for(const r of past){ if(!r || !r.env) continue;
    if(r.env.t==="edit" && editValid(r.env)){ const c=ed.get(r.env.m); if(!c || c.ts<=(r.ts||0)) ed.set(r.env.m, {x:r.env.x, ts:r.ts||0}); }
    if(r.env.t==="gone") gone.add(r.mid); }
  const out=[];
  for(const r of past){ if(!r || !r.env || !r.mid || gone.has(r.mid)) continue; if(dur && (r.ts||0)<=cut) continue;
    const e=r.env; let x="";
    if(!e.t || e.t==="txt") x=(ed.get(r.mid)||{}).x || e.body || "";
    else if(e.t==="doc") x=e.name||""; else if(e.t==="poll") x=[e.q].concat(e.o||[]).join(" · "); else if(e.t==="evt") x=[e.ti, e.loc, e.note].filter(Boolean).join(" · ");
    else continue;
    if(x) out.push({mid:r.mid, ts:r.ts||0, dir:r.dir, who:r.who||"", x, f:fold(x)}); }
  return out; }
async function runSearch(){
  const q=_sq, gen=++_sGen, box=_sRes; if(!box) return;
  if(!q){ box.hidden=true; box.innerHTML=""; return; }
  if(!_sCache || Date.now()-_sCacheAt>60000){ _sCache=new Map(); _sCacheAt=Date.now(); }
  const chats=groupsLoad().map(g=>({t:"g", id:"g:"+g.rid, rid:g.rid, gk:g.gk, name:g.name, alias:g.alias, cl:g.cl}))
    .concat(contactsLoad().filter(c=>!c.into && c.name!==INV_PLACEHOLDER).map(c=>({t:"c", id:"c:"+c.ck, ck:c.ck, name:c.name, alias:c.alias, cl:c.cl})));
  const hits=[];
  for(const it of chats){ const k=previewKeyOf(it); let recs=_sCache.get(k);
    if(!recs){ recs=searchable(await histLoad(k), k); _sCache.set(k, recs); if(gen!==_sGen) return; }   // a newer search took over
    for(const r of recs) if(r.f.includes(q)) hits.push({it, r}); }
  if(gen!==_sGen) return;
  hits.sort((a,b)=>b.r.ts-a.r.ts);
  box.innerHTML=""; box.hidden=false;
  const h=document.createElement("div"); h.className="sr-h"; h.textContent=t("Messages"); box.appendChild(h);
  if(!hits.length){ const n=document.createElement("div"); n.className="sr-none"; n.textContent=t("No messages found"); box.appendChild(n); return; }
  for(const {it, r} of hits.slice(0, 60)){
    const b=document.createElement("button"); b.type="button"; b.className="sr"; b.dataset.mid=r.mid;
    const av=document.createElement("span"); av.className="ava"+(it.t==="g"?" grp":""); av.textContent=it.t==="g"?"👥":up(((it.alias||dn(it.name))||"?")[0]); { const c=chatColor(it, it.t==="g"); if(c) av.style.background=c; }
    const bd=document.createElement("span"); bd.className="sr-b";
    const tl=document.createElement("span"); tl.className="sr-t"; const nm=document.createElement("span"); nm.className="sr-n"; nm.textContent=it.alias||dn(it.name)||t("Chat");
    const dt=document.createElement("span"); dt.className="sr-d"; dt.textContent=fmtListTime(r.ts); tl.append(nm, dt);
    const sn=document.createElement("span"); sn.className="sr-s"; const pre=r.dir==="sent" ? t("You: ") : (it.t==="g" && r.who ? r.who+": " : "");
    const inner=document.createElement("span"); markText(inner, r.x, q, 40); sn.append(pre, inner);
    bd.append(tl, sn); b.append(av, bd);
    b.addEventListener("click",()=>openSearchHit(it, r.mid)); box.appendChild(b); }
}
// open the chat, then bring the message into view once it's drawn
function openSearchHit(it, mid){ closeSidebar();
  it.t==="g" ? openGroup(it.rid, it.gk, it.name) : openContact(it.ck, it.alias||it.name);
  const t0=Date.now(); const tick=()=>{ const R=A(); const b=R && bubbleOf(R, mid); if(b){ jumpToQuoted(R, mid); return; } if(Date.now()-t0<4000) setTimeout(tick, 100); }; setTimeout(tick, 60); }
function setSearch(v){ const q=fold(String(v||"").trim()); $("listSearchX").hidden=!v; if(q===_sq) return; _sq=q;
  if(!q){ _sCache=null; }
  renderContacts(); clearTimeout(_sT); _sT=setTimeout(runSearch, q ? 180 : 0); }

// ---------- search inside a chat (⋮ → Search) ----------
let _find={q:"", hits:[], i:-1};
function findTextEls(b){ return [...b.querySelectorAll(":scope > .txt, .doc-n, .pq, .po .pt, .et, .el, .en")]; }
function clearFind(){ (_find.hits||[]).forEach(b=>b.classList.remove("find-hit","find-cur")); try{ if(window.CSS && CSS.highlights) CSS.highlights.delete("gz-find"); }catch(e){} _find.hits=[]; _find.i=-1; }
function openFind(){ const R=A(); if(!R || !R.logEl) return; $("findBar").hidden=false; $("findInput").value=""; clearFind(); $("findCount").textContent=""; try{ $("findInput").focus(); }catch(e){} }
function closeFind(){ const fb=$("findBar"); if(!fb || fb.hidden) return; fb.hidden=true; clearFind(); }
function runFind(){ const R=A(); clearFind(); const q=fold($("findInput").value.trim()); _find.q=q;
  if(!q || !R || !R.logEl){ $("findCount").textContent=""; return; }
  const ranges=[], HL=typeof Highlight==="function" && window.CSS && CSS.highlights;
  R.logEl.querySelectorAll(".bubble").forEach(b=>{ let hit=false;
    for(const el of findTextEls(b)){ const w=document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n;
      while((n=w.nextNode())){ const {out, map}=foldMap(n.nodeValue); let from=0, i;
        while((i=out.indexOf(q, from))>=0){ hit=true; if(HL){ try{ const rg=new Range(); rg.setStart(n, map[i]); rg.setEnd(n, Math.min(n.nodeValue.length, map[i+q.length-1]+1)); ranges.push(rg); }catch(e){} } from=i+q.length; } } }
    if(hit){ b.classList.add("find-hit"); _find.hits.push(b); } });
  if(HL && ranges.length){ try{ CSS.highlights.set("gz-find", new Highlight(...ranges)); }catch(e){} }
  _find.i=_find.hits.length-1; showFindCur(); }
function showFindCur(){ _find.hits.forEach(x=>x.classList.remove("find-cur")); const b=_find.hits[_find.i];
  if(b){ b.classList.add("find-cur"); try{ b.scrollIntoView({block:"center"}); }catch(e){} }
  $("findCount").textContent= !_find.q ? "" : _find.hits.length ? t("{i} of {n}",{i:_find.i+1, n:_find.hits.length}) : t("No results");
  $("findUp").disabled=_find.i<=0; $("findDown").disabled=_find.i<0 || _find.i>=_find.hits.length-1; }
function findStep(d){ if(!_find.hits.length) return; _find.i=Math.max(0, Math.min(_find.hits.length-1, _find.i+d)); showFindCur(); }
// ---------- Chat info: everything about one chat in one place, from a tap on its name (v37) ----------
function infoId(R){ return !R ? null : R.group ? "g:"+R.rid : R.fromContact ? "c:"+R.fromContact : null; }
function infoShown(){ const m=$("infoModal"); return !!(m && m.classList.contains("show")); }
function openInfo(){ const R=A(); if(!R) return; closePicker(); closeExpMenu(); closeColorPick(); $("barMenu").hidden=true;
  refreshInfo(); $("infoModal").classList.add("show"); const c=$("infoModal").querySelector(".info-card"); if(c) c.scrollTop=0;
  if(!TOUCH_UI) try{ $("ciBack").focus({preventScroll:true}); }catch(e){} }
function closeInfo(){ const m=$("infoModal"); if(m) m.classList.remove("show"); }
const MUTE_OPTS=[["0","Off"],["3600000","For 1 hour"],["28800000","For 8 hours"],["always","Until I turn it back on"]];
function refreshInfo(){ const R=A(); if(!R || !$("infoModal")) return;
  const grp=!!R.group, id=infoId(R), rec=recOfId(id), c=(!grp && R.fromContact) ? contactFind(R.fromContact) : null;
  const name=(rec && (rec.alias || dn(rec.name))) || dn(R.peerName) || dn(R.title) || t("Chat");
  $("ciName").textContent=name;
  const ava=$("ciAva"); ava.textContent=grp ? "👥" : up((name||"?")[0]); ava.style.background=roomColor(R)||""; ava.classList.toggle("grp", grp);
  const real=c ? dn(c.name) : "", sub=grp ? t("Group") : (rec && rec.alias && real && real!==rec.alias ? real : "");
  $("ciSub").textContent=sub; $("ciSub").hidden=!sub;
  $("ciStatus").textContent=R.statusText||"";
  $("ciCall").hidden=$("callBtn").hidden; $("ciVideo").hidden=$("videoBtn").hidden;
  $("ciLoc").hidden=!(grp||R.fromContact||R.paired); $("ciInvite").hidden=!grp;
  $("ciRename").hidden=!(R.fromContact||grp); $("ciRenameV").textContent=(rec && rec.alias) || t("None");
  $("ciColorRow").hidden=!rec;
  if(rec){ const g=$("ciColors");
    if(!g.childElementCount){
      const d=document.createElement("button"); d.type="button"; d.className="auto"; d.dataset.c=""; d.textContent="↺"; d.title=t("Default colour"); d.setAttribute("aria-label",d.title); d.setAttribute("role","radio"); g.appendChild(d);
      for(const k in AVA_COLORS){ const b=document.createElement("button"); b.type="button"; b.dataset.c=k; b.style.background=AVA_COLORS[k]; b.setAttribute("aria-label",k); b.setAttribute("role","radio"); g.appendChild(b); } }
    const cur=AVA_COLORS[rec.cl] ? rec.cl : ""; g.querySelectorAll("button").forEach(b=>{ const on=(b.dataset.c||"")===cur; b.classList.toggle("on",on); b.setAttribute("aria-checked",on?"true":"false"); });
    const a=g.querySelector(".auto"); if(a) a.style.background=chatColor(Object.assign({},rec,{cl:""}), grp)||""; }
  { const es=$("ciExp"); if(!es.options.length) EXP_CHOICES.forEach(v=>{ const o=document.createElement("option"); o.value=String(v); o.textContent=expLabel(v); es.appendChild(o); });
    else [...es.options].forEach(o=>o.textContent=expLabel(+o.value));
    es.value=String(expFor(histKeyOf(R))); $("ciExpRow").hidden=$("expBtn").hidden; }
  { const ms=$("ciMute"), mu=mutedUntil(rec); ms.innerHTML="";
    for(const [v,l] of MUTE_OPTS){ const o=document.createElement("option"); o.value=v; o.textContent=t(l); ms.appendChild(o); }
    if(mu && mu<MUTE_ALWAYS){ const o=document.createElement("option"); o.value="cur"; o.textContent=t("Until {time}",{time:fmtUntil(mu)}); ms.appendChild(o); }
    ms.value= !mu ? "0" : mu>=MUTE_ALWAYS ? "always" : "cur"; $("ciMuteRow").hidden=!rec; }
  $("ciVerify").hidden=!((R.fromContact && R.paired) || grp);
  $("ciVerifyV").textContent= grp ? t("Safety code") : (c && c.v ? t("Verified ✓") : t("Not verified"));
  $("ciMembers").hidden=!grp; $("ciNotify").hidden=!(R.fromContact && !grp); $("ciToGroup").hidden=!(R.fromContact && !grp);
  $("ciMerge").hidden=!(R.fromContact && !grp && mergeCandidates(R).length);
  $("ciRekey").hidden=!(R.paired && !grp);
  $("ciRemove").hidden=!(R.fromContact || grp); $("ciRemove").querySelector(".il").textContent= grp ? t("Leave group") : t("Remove contact");
  $("infoModal").querySelectorAll(".info-sec").forEach(x=>{ x.hidden=![...x.querySelectorAll(".info-row")].some(r=>!r.hidden); });   // nothing to show: no empty box
}
function wireInfo(){ const m=$("infoModal"); if(!m) return;
  const then=(f)=>()=>{ closeInfo(); f(); };
  $("ciBack").addEventListener("click",closeInfo);
  m.addEventListener("click",e=>{ if(e.target===m) closeInfo(); });
  document.addEventListener("keydown",e=>{ if(e.key==="Escape" && infoShown()) closeInfo(); });
  $("ciCall").addEventListener("click",then(()=>$("callBtn").click()));
  $("ciVideo").addEventListener("click",then(()=>$("videoBtn").click()));
  $("ciLoc").addEventListener("click",then(sendLocation));
  $("ciInvite").addEventListener("click",()=>inviteToGroup());
  $("ciRename").addEventListener("click",()=>{ renameChat(); refreshInfo(); });
  $("ciColors").addEventListener("click",e=>{ const b=e.target.closest && e.target.closest("button"); const R=A(); const id=infoId(R); if(!b || !id) return;
    setAvaColor(id, b.dataset.c||""); renderContacts(); refreshInfo(); });
  $("ciExp").addEventListener("change",async e=>{ await chooseExp(+e.target.value); refreshInfo(); });
  $("ciMute").addEventListener("change",e=>{ const v=e.target.value, R=A(); if(!R || v==="cur") return;
    setMute(R, v==="always" ? MUTE_ALWAYS : +v); refreshInfo(); });
  $("ciVerify").addEventListener("click",then(openVerify));
  $("ciMembers").addEventListener("click",then(openMembers));
  $("ciNotify").addEventListener("click",()=>nudgeContact());
  $("ciToGroup").addEventListener("click",then(convertToGroup));
  $("ciMerge").addEventListener("click",then(openMerge));
  $("ciRekey").addEventListener("click",then(rekey));
  $("ciWire").addEventListener("click",then(()=>$("wire").classList.add("show")));
  $("ciRemove").addEventListener("click",()=>{ const R=A(); if(!R) return;
    if(R.group){ const g=groupsLoad().find(x=>x.rid===R.rid);
      if(!confirm(t("Leave the group “{name}”?\n\nYou'll need a new invite link to come back.",{name:dn(g&&(g.alias||g.name))||t("Group")}))) return;
      closeInfo(); groupRemove(R.rid); goHome(); return; }
    if(!R.fromContact) return; const c=contactFind(R.fromContact);
    if(!confirm(t("Remove {name} from your chats?\n\nTo talk again you'll need to exchange a new invite link.",{name:dn(c&&(c.alias||c.name))||t("this contact")}))) return;
    closeInfo(); contactRemove(R.fromContact); goHome(); });
}
function renderContacts(fromPreview){
  const el=$("contactList"); if(!el) return; el.innerHTML="";
  const lastTs=it=>Math.max(it.ts||0, (_prev[previewKeyOf(it)]||{}).ts||0);
  const items=groupsLoad().map(g=>({t:"g",id:"g:"+g.rid,rid:g.rid,gk:g.gk,name:g.name,alias:g.alias,cl:g.cl,ts:g.ts||0}))
    .concat(contactsLoad().filter(c=>!c.into).map(c=>({t:"c",id:"c:"+c.ck,ck:c.ck,hk:c.hk,name:c.name,alias:c.alias,cl:c.cl,v:c.v,ts:c.ts||0})))
    .sort((a,b)=>lastTs(b)-lastTs(a));                 // most recent activity first, like any chats list
  if(!fromPreview) refreshPreviews();
  if(!items.length){ const wrap=document.createElement("div"); wrap.className="sb-empty";
    const e=document.createElement("p"); e.style.margin="0 0 14px";
    if(gRestoring){ e.textContent=t("Restoring your chats…"); wrap.appendChild(e); el.appendChild(wrap); return; }
    e.textContent=t("To talk with someone, send them your invite link — when they open it, you're connected.");
    const btn=document.createElement("button"); btn.className="btn"; btn.textContent=t("Invite a friend"); btn.style.maxWidth="220px"; btn.addEventListener("click",showAddRoom);
    const e2=document.createElement("p"); e2.className="sb-empty-sub"; e2.textContent=t("Got a link from a friend? Just open it.");
    wrap.appendChild(e); wrap.appendChild(btn); wrap.appendChild(e2); el.appendChild(wrap); return; }
  const R=A(); const activeId=R?(R.group?"g:"+R.rid:(R.fromContact?"c:"+R.fromContact:"")):"";
  if(!_sRes) _sRes=$("searchResults");
  const shownItems=_sq ? items.filter(chatMatches) : items;
  if(_sq && !shownItems.length){ const n=document.createElement("div"); n.className="sr-none"; n.textContent=t("No chats found"); el.appendChild(n); }
  shownItems.forEach(it=>{
    const row=document.createElement("div"); row.className="ct"+(it.id===activeId?" active":""); row.dataset.id=it.id;
    { const pk=previewKeyOf(it), age=pulseAge(_pulse.get(pk)); if(age>=0 && it.id!==activeId){ row.classList.add("pulse"); row.style.setProperty("--pd","-"+age+"ms"); } else if(age<0) _pulse.delete(pk); }
    const ava=document.createElement("div"); ava.className="ava"+(it.t==="g"?" grp":""); ava.setAttribute("aria-hidden","true"); ava.textContent=it.t==="g"?"👥":(up((it.alias||it.name)&&(it.alias||it.name)[0]||"?"));
    if(AVA_COLORS[it.cl]){ ava.style.background=AVA_COLORS[it.cl]; ava.dataset.cl=it.cl; }   // the colour chosen for this chat (long press)
    else if(it.t==="c") ava.style.background=autoColor(it.ck);                                  // else its own colour, from its key
    const ci=document.createElement("div"); ci.className="ci";
    // line 1: name (+ verified) ……… time of the last message
    const r1=document.createElement("div"); r1.className="crow";
    const cn=document.createElement("div"); cn.className="cn"; cn.textContent=it.alias||dn(it.name)||(it.t==="g"?t("Group"):t("Contact"));
    if(it.t==="c"&&it.v){ const vb=document.createElement("span"); vb.className="vbadge"; vb.textContent="✓"; vb.title=t("Verified"); cn.appendChild(vb); }
    const muted=isMutedItem(it);
    if(muted){ row.classList.add("muted"); const mi=document.createElementNS("http://www.w3.org/2000/svg","svg"); mi.setAttribute("class","ico mute-ico"); mi.setAttribute("aria-label",t("Muted chat"));
      const u=document.createElementNS("http://www.w3.org/2000/svg","use"); u.setAttribute("href","#i-bell-off"); mi.appendChild(u); cn.appendChild(mi); }
    const pv=_prev[previewKeyOf(it)]||null;
    const ct=document.createElement("span"); ct.className="ctime"; ct.textContent=pv?fmtListTime(pv.ts):"";
    r1.appendChild(cn); r1.appendChild(ct);
    // line 2: last message ……… unread count
    const r2=document.createElement("div"); r2.className="crow";
    const unread=(it.id===activeId) ? 0 : (_meta.unread[previewKeyOf(it)]||0);
    const cm=document.createElement("div"); cm.className="cm";
    const pendingInv = it.t==="c" && it.name===INV_PLACEHOLDER;
    const pc = pendingInv ? (contactFind(it.ck)||{}) : null;
    const placeholder = pendingInv ? (pc.dead ? t("Invite cancelled · make a new link") : inviteExpired(pc.x) ? t("Invite expired · make a new link") : t("Invite sent · waiting for them to open it")) : (it.t==="g" ? t("Group · say hello") : t("Tap to start chatting"));
    // "Hide previews": nothing readable over your shoulder — only whether there's something new
    { const txt= previewsHidden()
        ? (unread ? t(unread>1?"{n} new messages":"{n} new message",{n:unread}) : (pv ? t("🔒 Encrypted message") : placeholder))
        : (pv ? pv.text : placeholder);
      if(pv && (pv.ui || previewsHidden())) iconText(cm, txt); else cm.textContent=txt; }
    if(unread) cm.classList.add("unread");
    { let TR=null; rooms.forEach(x=>{ if(!TR && x.typing && typingRowId(x)===it.id) TR=x; }); const tl=TR ? typingLabel(TR) : "";
      if(tl){ cm.dataset.was=cm.textContent; cm.textContent=tl; cm.classList.add("typing"); } }
    r2.appendChild(cm);
    if(unread && it.id!==activeId){ const ub=document.createElement("span"); ub.className="ubadge"+(muted?" muted":""); ub.textContent=unread>99?"99+":String(unread); ub.title=t("{n} unread",{n:unread}); r2.appendChild(ub); ct.classList.add("unread"); }
    ci.appendChild(r1); ci.appendChild(r2);
    const x=document.createElement("button"); x.className="cx"; x.textContent="×"; x.title=it.t==="g"?t("Leave group"):t("Remove contact"); x.setAttribute("aria-label",x.title);
    x.addEventListener("click",ev=>{ ev.stopPropagation();
      if(it.t==="g"){ if(confirm(t("Leave the group “{name}”?\n\nYou'll need a new invite link to come back.",{name:dn(it.name)||t("Group")}))) groupRemove(it.rid); }
      else { if(confirm(t("Remove {name} from your chats?\n\nTo talk again you'll need to exchange a new invite link.",{name:dn(it.name)||t("this contact")}))) contactRemove(it.ck); } });
    row.appendChild(ava); row.appendChild(ci); row.appendChild(x);
    row.addEventListener("click",()=>{ if(row._lp){ row._lp=false; return; }   // that was a long press: the colour menu is open
      it.t==="g" ? openGroup(it.rid,it.gk,it.name) : openContact(it.ck,it.alias||it.name); });
    if(_sq){ const row1=row.querySelector(".cn"), tn=row1 && row1.firstChild; if(tn && tn.nodeType===3){ const sp=document.createElement("span"); markText(sp, tn.nodeValue, _sq, 0); row1.replaceChild(sp, tn); } }
    el.appendChild(row);
  });
  if(_sRes){ if(_sq) el.appendChild(_sRes); else _sRes.hidden=true; }
  updateBadge(); scheduleMuteRefresh(); paintPeerAvatar();
}

// ---------- group chats (named, invite-only, shared group key) ----------
const LS_GROUPS="gz-groups";              // legacy plaintext key (older builds): imported once, then removed
function groupsLoad(){ return _groups.map(g=>Object.assign({},g)); }
function groupsSave(l){ _groups=(l||[]).filter(g=>g&&g.rid).map(g=>Object.assign({},g)); localSaveSoon(); renderContacts(); syncPushSoon(); }
function groupUpsert(rid,gkB64,name,adm,rot){ const l=groupsLoad(); const i=l.findIndex(g=>g.rid===rid);
  if(i>=0){ if(name) l[i].name=name; l[i].ts=Date.now(); if(rot && !l[i].rot) l[i].rot=1; }   // the admin is set once, when the group is first saved: a later link cannot name one
  else { const g={rid,gk:gkB64,name:name||"Group",ts:Date.now()}; if(adm) g.adm=adm; if(rot) g.rot=1; l.push(g); if(_meta.gone) delete _meta.gone["g:"+rid]; } groupsSave(l); }
function groupRemove(rid){ const R=rooms.get(rid); if(R){ try{ R.channel&&R.channel.unsubscribe(); }catch(e){} if(R.logEl) R.logEl.remove(); rooms.delete(rid); if(active===rid) goHome(); }
  delete _meta.unread[rid]; tombstone("g:"+rid); renderTabs(); groupsSave(groupsLoad().filter(g=>g.rid!==rid)); updateBadge(true); }
function newRid(){ const A="0123456789abcdefghijklmnopqrstuvwxyz"; return [...crypto.getRandomValues(new Uint8Array(16))].map(b=>A[b%36]).join(""); }
async function gkMsgKey(gkBytes){ return aesKey(await hkdf(gkBytes,"gz-group-msg/v1")); }
// ---- group sender authentication ----
// Every account signs its group messages with an identity key (ECDSA P-256) that follows it across devices
// in the vault. Members learn each other's keys from the first signed message (trust on first use) and are
// warned when a name shows up signing with a different key. The relay never holds a group key, so it can
// forge nothing; a member who tries to pass for another is flagged.
let _identKeys=null;   // {priv:CryptoKey, pub:CryptoKey, pk:b64}
function identLoad(){ return (_meta && _meta.ident && _meta.ident.pk && _meta.ident.sk) ? _meta.ident : null; }
async function identEnsure(){
  if(_identKeys) return _identKeys;
  let id=identLoad();
  if(!id){ const kp=await crypto.subtle.generateKey({name:"ECDSA",namedCurve:"P-256"},true,["sign","verify"]);
    id={pk:b64(await crypto.subtle.exportKey("raw",kp.publicKey)), sk:b64(await crypto.subtle.exportKey("pkcs8",kp.privateKey)), ts:Date.now()};
    _meta.ident=id; localSaveSoon(); syncPushSoon(); }
  if(!id.ek || !id.dk){ const kp=await genKP(); id.ek=b64(await pubRaw(kp)); id.dk=b64(await crypto.subtle.exportKey("pkcs8",kp.privateKey)); _meta.ident=id; localSaveSoon(); syncPushSoon(); }
  const priv=await crypto.subtle.importKey("pkcs8",unb64(id.sk),{name:"ECDSA",namedCurve:"P-256"},false,["sign"]);
  const dh=await crypto.subtle.importKey("pkcs8",unb64(id.dk),{name:"ECDH",namedCurve:"P-256"},false,["deriveBits"]);
  _identKeys={priv, dh, pk:id.pk, ek:id.ek}; return _identKeys;
}
function identAdopt(remote){   // vault merge: all devices converge on the oldest identity
  if(!remote || !remote.pk || !remote.sk) return false; const loc=identLoad();
  if(loc && loc.pk===remote.pk){   // same identity: the devices must also hold the same group ECDH key (the smaller one wins, on both)
    if(remote.ek && remote.dk && (!loc.ek || remote.ek<loc.ek)){ loc.ek=remote.ek; loc.dk=remote.dk; _meta.ident=loc; _identKeys=null; localSaveSoon(); return true; } return false; }
  if(loc && (loc.ts||0) <= (remote.ts||0)) return false;
  _meta.ident=remote; _identKeys=null; localSaveSoon(); return true;
}
const _pubCache=new Map();
async function identPub(pkB64){ if(_pubCache.has(pkB64)) return _pubCache.get(pkB64); const k=await crypto.subtle.importKey("raw",unb64(pkB64),{name:"ECDSA",namedCurve:"P-256"},false,["verify"]); _pubCache.set(pkB64,k); return k; }
async function keyFp(pkB64){ return b64url(new Uint8Array(await crypto.subtle.digest("SHA-256",unb64(pkB64)))).slice(0,8); }
function gsigData(rid, obj){ const o=Object.assign({},obj); delete o.sig; delete o.a; return enc.encode("gz-gsig/v1|"+rid+"|"+JSON.stringify(o)); }
// the inner (encrypted) object of a group message, signed: {…env, mid, n, pk, sig}
async function signGroupEnv(R, env, mid){
  const obj=Object.assign({},env,{mid, n:myName});
  try{ const id=await identEnsure(); obj.pk=id.pk; obj.ek=id.ek; obj.sig=b64(await crypto.subtle.sign({name:"ECDSA",hash:"SHA-256"}, id.priv, gsigData(R.rid, obj))); }catch(e){}
  return obj;
}
// "ok" | "bad" | "changed" | "unsigned"; records the first key seen for a name (per group, in the vault)
async function verifyGroupEnv(R, env, who){
  if(!env || !env.pk || !env.sig) return "unsigned";
  let ok=false; try{ ok=await crypto.subtle.verify({name:"ECDSA",hash:"SHA-256"}, await identPub(env.pk), unb64(env.sig), gsigData(R.rid, env)); }catch(e){ ok=false; }
  if(!ok) return "bad";
  const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g) return "ok";
  const mem=g.mem||{}; const nm=realName(who)?who:"";
  const known=Object.keys(mem).find(pk=>mem[pk].n===nm && nm);
  if(known && known!==env.pk){ return "changed"; }
  const cur=mem[env.pk];
  if(!cur || (env.ek && cur.ek!==env.ek) || (nm && cur.n!==nm)){ mem[env.pk]={n:nm||(cur&&cur.n)||"", ek:env.ek||(cur&&cur.ek)||undefined, ts:(cur&&cur.ts)||Date.now()}; g.mem=mem; groupsSave(l); }
  return "ok";
}
// ---- group key rotation (exclusion) ----
// The group's creator is its admin (its identity key travels in the group link). To renew the key — or to
// remove someone — the admin makes a fresh key and sends it in the group, wrapped for each remaining member
// under that member's identity ECDH key (learned from their signed messages). Whoever is left out of the
// wraps cannot derive the new key; the room name and the mailbox follow the key, so they see nothing more.
async function groupFp(gkBytes){ return keyFp(b64(gkBytes)); }
function groupChan(R){ const g=groupsLoad().find(x=>x.rid===R.rid); return "ratchet-"+R.rid+((g && g.rot && R.gkFp) ? "-"+R.gkFp : ""); }
async function isGroupAdmin(R){ const g=groupsLoad().find(x=>x.rid===R.rid); if(!g || !g.adm) return false; try{ return (await identEnsure()).pk===g.adm; }catch(e){ return false; } }
async function rotateGroup(R, excludePk){
  const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g) return false;
  const id=await identEnsure(); if(g.adm!==id.pk){ toast(t("Only the person who created the group can do that")); return false; }
  const mem=g.mem||{}; const keep=Object.keys(mem).filter(pk=>pk!==excludePk && pk!==id.pk && mem[pk].ek);
  const newGk=crypto.getRandomValues(new Uint8Array(32)); const eph=await genKP(); const ephPub=b64(await pubRaw(eph));
  const w={};
  const wrapFor=async(pk, ek)=>{ try{ const sec=await sharedSecret(eph.privateKey, await importPub(unb64(ek))); const k=await aesKey(await hkdf(sec,"gz-gk2/v1"));
    const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},k,newGk); w[pk]={iv:b64(iv),ct:b64(ct)}; }catch(e){} };
  for(const pk of keep) await wrapFor(pk, mem[pk].ek);
  if(id.ek) await wrapFor(id.pk, id.ek);   // the admin's own other devices (same identity) take the new key from the same message
  const env={t:"gk2", g:await groupFp(newGk), e:ephPub, w, x:excludePk?[excludePk]:[]};
  const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  const signed=await signGroupEnv(R, env, mid);
  try{ await broadcastGroup(R, signed, mid); }catch(e){} try{ await depositMailbox(R, mid, signed); }catch(e){}
  if(excludePk){ const m2=Object.assign({},g.mem||{}); delete m2[excludePk]; g.mem=m2; g.gone=(g.gone||[]).concat([excludePk]).slice(-50); groupsSave(l); }
  await applyGroupKey(R, newGk, excludePk ? t("🔑 {who} was removed — the group now uses a new key they don't have.",{who:(mem[excludePk]&&mem[excludePk].n)||t("Member")}) : t("🔑 Group key renewed."));
  return true;
}
async function applyGroupKey(R, gkBytes, line){
  const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g) return;
  g.prevGk=g.gk; g.rotAt=Date.now(); g.gk=b64(gkBytes); g.rot=(g.rot||0)+1; g.rotFp=await groupFp(gkBytes); g.ts=Date.now(); delete g.left; groupsSave(l);   // ts: the vault carries the new key to the account's other devices
  R.gk=gkBytes; R.gkMsg=await gkMsgKey(gkBytes); R.gkFp=g.rotFp; R.gcall=null; R.hiSent=false;
  try{ if(R.channel) R.channel.unsubscribe(); }catch(e){}
  if(R.bind) R.bind();
  if(R.logEl && line) sysline(R.logEl, line);
  renderContacts(); showCallBanner(R);
}
async function onGk2(R, env, vf, who){
  const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g) return;
  if(vf!=="ok" && vf!=="changed") return;
  if(!g.adm || env.pk!==g.adm){ if(R.logEl) sysline(R.logEl, t("⚠ {who} tried to change the group key but isn't the group's creator — ignored.",{who}), true); return; }
  if(!env.g || env.g===g.rotFp) return;                                       // already on that key
  let id; try{ id=await identEnsure(); }catch(e){ return; }
  const mine=env.w && env.w[id.pk];
  if(!mine){ g.left=1; groupsSave(l); if(R.logEl) sysline(R.logEl, t("⛔ {who} removed you from this group. You can't read or write here any more.",{who}), true);
    if(R.code===active){ enableComposer(false); setStatus(R, t("removed from the group"), false, "warn", t("removed")); } return; }
  try{ const sec=await sharedSecret(id.dh, await importPub(unb64(env.e))); const k=await aesKey(await hkdf(sec,"gz-gk2/v1"));
    const gk=new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(mine.iv)},k,unb64(mine.ct))); if(gk.length!==32) throw new Error("bad key");
    const gone=(Array.isArray(env.x)?env.x:[]).map(pk=>(g.mem&&g.mem[pk]&&g.mem[pk].n)||"").filter(Boolean);
    if(Array.isArray(env.x) && env.x.length){ const m2=Object.assign({},g.mem||{}); env.x.forEach(pk=>{ delete m2[pk]; }); g.mem=m2; g.gone=(g.gone||[]).concat(env.x.filter(pk=>typeof pk==="string")).slice(-50); groupsSave(l); }
    await applyGroupKey(R, gk, gone.length ? t("🔑 {who} removed {names} — new group key.",{who, names:gone.join(", ")}) : t("🔑 {who} renewed the group key.",{who}));
  }catch(e){ if(R.logEl) sysline(R.logEl, t("⚠ Couldn't read the new group key from {who} — ask them to renew it again.",{who}), true); }
}
// a silent, signed "hi" when joining: tells the others (and the admin) which key we hold, once a day per group
async function openMembers(){
  const R=A(); if(!R||!R.group) return; const g=groupsLoad().find(x=>x.rid===R.rid); if(!g) return;
  const admin=await isGroupAdmin(R); let me=null; try{ me=await identEnsure(); }catch(e){}
  const list=$("memList"); list.innerHTML=""; const mem=g.mem||{};
  const rows=[]; if(me) rows.push({pk:me.pk, n:realName(myName)?myName:t("Me"), ek:me.ek, me:true});
  for(const pk in mem) if(!me || pk!==me.pk) rows.push({pk, n:mem[pk].n||t("Member"), ek:mem[pk].ek});
  for(const m of rows){ const row=document.createElement("div"); row.className="mem-row";
    const nm=document.createElement("span"); nm.className="mn"; nm.textContent=m.n+(m.me?" ("+t("you")+")":"")+(g.adm===m.pk?" · "+t("creator"):""); row.appendChild(nm);
    const fp=document.createElement("span"); fp.className="mf"; fp.textContent=await keyFp(m.pk); row.appendChild(fp);
    if(admin && !m.me){ const x=document.createElement("button"); x.className="mx"; x.type="button"; x.textContent=t("Remove");
      x.addEventListener("click",async()=>{ if(!confirm(t("Remove {name} from the group? The group gets a new key they won't have.",{name:m.n}))) return; x.disabled=true; await rotateGroup(R, m.pk); openMembers(); });
      row.appendChild(x); }
    list.appendChild(row); }
  const missing=rows.filter(m=>!m.me && !m.ek).length;
  $("memTitle").textContent=t("Members · {n}",{n:rows.length});
  $("memSub").textContent= g.adm ? (admin ? t("You created this group: you can remove people and renew the key.") : t("Only the group's creator can remove people or renew the key.")) : t("This group was created before member keys existed: nobody can renew its key — create a new group to exclude someone.");
  $("memNote").textContent= rows.length<=1 ? t("Members appear here after their first message in the group.") : (missing ? t("{n} member(s) have not announced a key yet (older app): renewing the key now would lock them out until they reopen the group.",{n:missing}) : "");
  const rn=$("memRenew"); rn.hidden=!admin; rn.onclick=async()=>{ if(!confirm(t("Renew the group key now? Everyone listed with a key keeps access; old invite links stop working."))) return; rn.disabled=true; await rotateGroup(R, null); rn.disabled=false; openMembers(); };
  $("memModal").classList.add("show");
}
function groupGone(R, env){ const g=groupsLoad().find(x=>x.rid===R.rid); return !!(g && g.gone && env.pk && g.gone.includes(env.pk)); }
// a message that decrypts under the CURRENT key from someone on the removed list: they were invited back (only a
// fresh link carries the current key) — welcome them again
function groupUngone(R, env){ if(!env || !env.pk) return; const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g || !g.gone || !g.gone.includes(env.pk)) return;
  g.gone=g.gone.filter(pk=>pk!==env.pk); groupsSave(l); }
async function sendGroupHi(R){
  if(!R.group || R.hiSent) return; R.hiSent=true;
  const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  try{ const signed=await signGroupEnv(R, {t:"hi"}, mid); await broadcastGroup(R, signed, mid);
    if(!_meta.ghi) _meta.ghi={}; const last=_meta.ghi[R.rid]||0;
    if(Date.now()-last>86400000){ _meta.ghi[R.rid]=Date.now(); localSaveSoon(); await depositMailbox(R, mid, signed); } }catch(e){}
}
function noteVerdict(R, who, vf, pk){
  if(vf!=="bad" && vf!=="changed") return; R.vfNoted=R.vfNoted||new Set(); const k=vf+"|"+who; if(R.vfNoted.has(k)) return; R.vfNoted.add(k);
  if(!R.logEl) return;
  if(vf==="bad") sysline(R.logEl, t("⚠ A message signed as “{who}” has a broken signature — it was altered or forged. Treat it as not from them.",{who}), true);
  else keyFp(pk).then(fp=>sysline(R.logEl, t("⚠ “{who}” is now signing with a different key ({fp}). If they didn't change account, someone else is using their name.",{who,fp}), true)).catch(()=>{});
}
function openGroup(rid,gkB64,name){ closeSidebar(); doJoinGroup(rid, unb64(gkB64), name); }
async function createGroup(name){ const rid=newRid(); const gk=crypto.getRandomValues(new Uint8Array(32));
  let adm=""; try{ adm=(await identEnsure()).pk; }catch(e){}
  await doJoinGroup(rid, gk, (name||"").trim()||"New group", adm);
  const R=A(); if(R&&R.logEl){ sysline(R.logEl,t("🔒 Group created. Tap the menu ⋮ → “Invite people” to add members.")); } }
async function doJoinGroup(rid, gkBytes, name, adm, rot){
  const code=rid;
  // A link whose key differs from the one we hold: an OLD link reopened by a member who already has the renewed
  // key (keep ours), or a NEW link sent to someone who was removed / away too long to get the renewed key (take
  // the link's key, the one the group now uses). A record marked left, or holding no key, always takes the link.
  const lk=b64(gkBytes), g0=groupsLoad().find(x=>x.rid===rid);
  const keepOurs=!!(g0 && g0.rot && g0.gk && g0.gk!==lk && !g0.left);
  groupUpsert(rid, lk, name, adm, rot);
  if(keepOurs) gkBytes=unb64(g0.gk);
  else if(g0 && g0.gk && g0.gk!==lk){ const l=groupsLoad(); const x=l.find(y=>y.rid===rid); if(x){ x.prevGk=x.gk; x.rotAt=Date.now(); x.gk=lk; x.rot=(x.rot||0)+1; x.rotFp=await groupFp(gkBytes); delete x.left; x.ts=Date.now(); groupsSave(l); }
    const R0=rooms.get(code); if(R0){ await applyGroupKey(R0, gkBytes, t("🔑 Group key renewed.")); } }
  if(rooms.has(code)){ hideJoin(); switchTo(code); return; }
  if(_joining.has(code)) return; _joining.add(code);
  const R=newRoom(code);
  R.group=true; R.rid=rid; R.gk=gkBytes; R.title=name||"Group"; R.peerName=dn(name||"Group"); R.avatar="👥"; R.paired=true;
  { const g=groupsLoad().find(x=>x.rid===rid); if(g&&g.alias){ R.title=g.alias; R.peerName=g.alias; } }
  try{ R.gkMsg=await gkMsgKey(gkBytes); R.gkFp=await groupFp(gkBytes); } finally { _joining.delete(code); }
  if(rooms.has(code)){ switchTo(code); return; }
  const logEl=document.createElement("div"); logEl.className="log"; logEl.style.display="none"; $("logs").appendChild(logEl); R.logEl=logEl; watchLog(logEl);
  rooms.set(code,R); hideJoin(); switchTo(code);
  R.seen=seenSetFor(R);
  if(gHistKey){ const past=await histLoad(code); renderHistory(R, past); seedSeen(R, past); }
  R.bind=()=>{ const ch=client.channel(groupChan(R),{config:{private:true,presence:{key:R.id},broadcast:{self:false}}});
    R.channel=ch;
    ch.on("presence",{event:"sync"},()=>onSyncGroup(R));
    ch.on("broadcast",{event:"msg"},(payload)=>onMsgGroup(R,payload));
    ch.on("broadcast",{event:"rcpt"},(payload)=>onRcptGroup(R,payload));   // typing signals
    ch.subscribe(async st=>{ if(st==="SUBSCRIBED"){ R.joinFails=0; await ch.track(presencePayload(R)); const gl=groupsLoad().find(x=>x.rid===R.rid);
        if(gl && gl.left){ setStatus(R, t("removed from the group"), false, "warn", t("removed")); if(R.code===active) enableComposer(false); return; }
        setStatus(R,t("🔒 encrypted group"),true,"online",t("group"));
        if(R.code===active){ $("msgInput").disabled=false; $("sendBtn").disabled=false; setAttach(false); } fetchMailbox(R); sendGroupHi(R).catch(()=>{}); }
      else if(st==="CHANNEL_ERROR"||st==="TIMED_OUT"){ setStatus(R,t("connection problem — retrying…"),false,"busy",t("reconnecting…")); scheduleRejoin(R, ch); } }); };
  R.bind();
  fetchMailbox(R);
  try{ history.replaceState(null,"","/"); }catch(e){}
  renderContacts(); updateVerifyUI();
}
function onSyncGroup(R){
  const st=R.channel.presenceState(); const ids=new Set(); const names=[]; let cc=null, ccBy="";
  for(const k in st) for(const m of st[k]){ if(!m.id) continue; ids.add(m.id); if(m.id!==R.id && m.name) names.push(m.name); if(m.cc && m.id!==R.id && !cc){ cc=m.cc; ccBy=m.name||""; } }
  if(cc){ if(!R.gcall || R.gcall.cid!==cc) R.gcall={cid:cc, video:!!(R.gcall&&R.gcall.video), by:ccBy, ts:Date.now()}; }
  else if(!(call && call.R===R)) R.gcall=null;
  showCallBanner(R);
  const n=ids.size;
  const extra=names.length?(" · "+names.slice(0,3).join(", ")+(names.length>3?" +"+(names.length-3):"")):"";
  setStatus(R,(n>1?t("🔒 group · {n} online",{n}):t("🔒 group · 1 (just you)"))+extra,true,"online",n>1?t("{n} online",{n}):t("just you"));
}
async function broadcastGroup(R, env, mid){
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const signed=env.sig ? env : await signGroupEnv(R, env, mid);   // signed once; the signed object goes out untouched
  const ctBuf=await crypto.subtle.encrypt({name:"AES-GCM",iv}, R.gkMsg, enc.encode(JSON.stringify(signed)));
  showWire(R,b64(ctBuf));
  try{ const r=await R.channel.send({type:"broadcast",event:"msg",payload:{from:R.id,iv:b64(iv),ct:b64(ctBuf),mid}}); return r==="ok"; }catch(e){ return false; }
}
async function onMsgGroup(R,{payload:p}){
  if(!p||p.from===R.id) return;
  if(p.mid){ if(!R.seen) R.seen=new Set(); if(R.seen.has(p.mid)) return; R.seen.add(p.mid); }
  showWire(R,p.ct);
  try{
    const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(p.iv)}, R.gkMsg, unb64(p.ct));
    const env=JSON.parse(dec.decode(pt)); const now=Date.now();
    if(env.mid && p.mid && env.mid!==p.mid) throw new Error("id mismatch");
    const who=(realName(env.n)||realName(p.name)||t("Member"));          // the name the sender sealed inside, never the relay's
    const vf=await verifyGroupEnv(R, env, who); noteVerdict(R, who, vf, env.pk); env.vf=vf;
    if(groupGone(R, env)){ if(R.gkFp && (groupsLoad().find(x=>x.rid===R.rid)||{}).rot) groupUngone(R, env); else return; }   // live room = current key: invited back; else a removed member still holding the old key
    if(env.t==="hi") return;                                                 // a member announcing its key: recorded above
    if(env.t==="gk2"){ await onGk2(R, env, vf, who); return; }
    if(env.t==="call"){ if(vf!=="bad") callSignal(R, env, who).catch(()=>{}); return; }
    onInbound(R, env, who, now, p.mid, false, true);
    if(!QUIET_T.has(env.t)){ if(R.code===active) blinkEyes(); messageTone(R); }
  }catch(e){ if(p.mid && R.seen) R.seen.delete(p.mid); addText(R.logEl,"fail",t("⚠ could not decrypt this message"),""); }
}
function groupInviteLink(R){ const g=groupsLoad().find(x=>x.rid===R.rid); const o={rid:R.rid,gk:b64(R.gk),name:(g&&g.name)||R.title}; if(g&&g.adm) o.adm=g.adm; if(g&&g.rot) o.rot=1; return CANONICAL+"/#g="+b64url(enc.encode(JSON.stringify(o))); }
async function inviteToGroup(){ const R=A(); if(!R||!R.group) return;
  const url=groupInviteLink(R); const msg=t("Join my Gizleme group “{name}” 🔒\n{url}",{name:R.title,url});
  if(navigator.share){ try{ await navigator.share({text:msg}); return; }catch(e){ if(e&&e.name==="AbortError") return; } }
  try{ await navigator.clipboard.writeText(url); toast(t("Invite link copied")); }catch(e){ prompt(t("Copy this invite link:"),url); }
}
function parseInvite(text){ // accepts a full link or raw payload
  try{ const s=(text||"").trim(); const i=s.indexOf("#g="); const payload= i>=0 ? s.slice(i+3) : s;
    const obj=JSON.parse(dec.decode(unb64url(payload))); if(obj&&obj.rid&&obj.gk){ if(obj.adm!==undefined && !(typeof obj.adm==="string" && obj.adm.length===88)) delete obj.adm; if(obj.rot!==undefined && obj.rot!==1) delete obj.rot; return obj; } }catch(e){} return null; }

// ---------- offline delivery: encrypted store-and-forward mailbox ----------
const MBOX_FN="gizleme-mbox", LS_MBTS="gz-mboxts";
function myUsername(){ const s=sessLoad(); return (s&&s.username)||""; }
async function mboxFn(action,extra){ return client.functions.invoke(MBOX_FN,{body:Object.assign({action},extra||{})}); }
function roomSecretB64(R){ return R.group ? (R.gk?b64(R.gk):null) : (R.fromContact||null); }
async function mboxIdForSecret(secB64){ return b64url(new Uint8Array(await hkdf(unb64(secB64),"gz-mbox/v1",16))); }
async function mboxKeyForSecret(secB64){ return aesKey(await hkdf(unb64(secB64),"gz-mbox-key/v1")); }
// ---- forward secrecy for the mailbox: a one-way key chain per contact ----
// Seeded from the ECDH secret of the v3 link opening (never from the contact key, which stays in the vault),
// the chain root moves forward by a hash every week; keys of past weeks are thrown away once the relay can
// no longer hold their messages, and nothing kept can derive them again. A device or vault taken over
// later reads what is still in the relay (the current week and the two before) — not what came earlier.
const CHAIN_EPOCH_MS=7*86400000, CHAIN_KEEP=2;   // epochs kept behind the current one (relay retention is 14 days)
function epochNow(){ return Math.floor(Date.now()/CHAIN_EPOCH_MS); }
const _chainCache=new Map();   // "ck|ep" -> CryptoKey (per session)
async function chainRootAt(kcB64, kce, ep){
  if(!kcB64 || typeof kce!=="number" || ep<kce || ep-kce>1000) return null;
  let r=unb64(kcB64); for(let i=kce;i<ep;i++) r=new Uint8Array(await hkdf(r,"gz-chain/next")); return r;
}
async function mboxKeyForContact(c, ep){
  if(!c || !c.kc) return null; const k="ck|"+c.ck+"|"+ep; if(_chainCache.has(k)) return _chainCache.get(k);
  const root=await chainRootAt(c.kc, c.kce, ep); if(!root) return null;
  const key=await aesKey(await hkdf(root,"gz-mbox-key/v2")); _chainCache.set(k,key); if(_chainCache.size>400) _chainCache.delete(_chainCache.keys().next().value); return key;
}
// Throw away what the relay can no longer hold: the stored root is always the one of (current − 2) weeks.
function advanceChains(){
  const E=epochNow(); const l=contactsLoad(); let changed=false; const todo=l.filter(c=>c.kc && typeof c.kce==="number" && E-CHAIN_KEEP>c.kce);
  if(!todo.length) return Promise.resolve(false);
  return (async()=>{ const moved={}; for(const c of todo){ const root=await chainRootAt(c.kc, c.kce, E-CHAIN_KEEP); if(root) moved[c.ck]={kc:b64(root), kce:E-CHAIN_KEEP}; }
    const cur=contactsLoad();   // re-read: a hello or a patch may have landed while the roots were being computed
    for(const c of cur){ const m=moved[c.ck]; if(m && typeof c.kce==="number" && c.kce<m.kce){ c.kc=m.kc; c.kce=m.kce; changed=true; } }
    if(changed){ contactsSave(cur); _chainCache.clear(); } return changed; })();
}
// deposit under every key this contact is reachable on; the chain key (with its epoch) when the contact has one
async function depositToContact(ck, mid, env){
  let ok=false;
  for(const k of depositCKSet(ck)){ try{ const c=contactFind(k); const ep=epochNow(); const ckey=c?await mboxKeyForContact(c, ep):null;
    if(await depositOne(await mboxIdForSecret(k), ckey||await mboxKeyForSecret(k), mid, env, ckey?ep:undefined)) ok=true; }catch(e){} }
  return ok;
}
async function mboxIdFor(R){ const sec=roomSecretB64(R); if(!sec) return null; return mboxIdForSecret(sec); }
async function mboxKeyFor(R){ if(R.group) return R.gkMsg; const sec=roomSecretB64(R); if(!sec) return null; return mboxKeyForSecret(sec); }
function mbtsLoad(){ if(!_meta.mbts) _meta.mbts={}; return _meta.mbts; }
function mbtsGet(id){ return mbtsLoad()[id]||0; }
function mbtsSet(id,ts){ const m=mbtsLoad(); if(ts>(m[id]||0)){ m[id]=ts; localSaveSoon(); } }
async function depositOne(id, key, mid, env, ep){
  try{ const iv=crypto.getRandomValues(new Uint8Array(12));
    // the sender's display name travels inside the ciphertext, not beside it
    const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,enc.encode(JSON.stringify(Object.assign({},env,{n:myName,mid,a:_acct||undefined}))));
    const data={iv:b64(iv),ct:b64(ct)}; if(ep!==undefined) data.ep=ep;   // which week's chain key (the relay learns only the week)
    const r=await mboxFn("put",{mbox:id, mid, data});
    return !!(r && r.data && r.data.ok);
  }catch(e){ return false; }
}
async function depositMailbox(R, mid, env){
  try{
    if(R.group){ const id=await mboxIdFor(R), key=await mboxKeyFor(R); if(!id||!key) return false; return depositOne(id,key,mid,env); }
    if(!R.fromContact) return false;
    return await depositToContact(R.fromContact, mid, env);
  }catch(e){ return false; }
}
async function fetchMailbox(R){
  if(!R) return 0;
  if(R.fetching) return R.fetching;          // coalesce overlapping fetches (open + subscribe + poll)
  R.fetching=(async()=>{
    let delivered=0;
    try{
      if(!R.seen) R.seen=new Set();
      let variants=[];
      if(R.group){ const id=await mboxIdFor(R), key=await mboxKeyFor(R); if(id&&key) variants=[[id,key]];
        const g=groupsLoad().find(x=>x.rid===R.rid);   // the key before the last rotation stays readable for 14 days: late writers are not lost
        if(g && g.prevGk && g.rotAt && Date.now()-g.rotAt<RECON_MS){ try{ variants.push([await mboxIdForSecret(g.prevGk), await gkMsgKey(unb64(g.prevGk))]); }catch(e){} } }
      else if(R.fromContact){
        // a hello that could not be deposited when the link was opened: leave it now (the inviter binds from it)
        const c=contactFind(R.fromContact);
        if(c && c.v3 && c.hp && c.hello && c.prev && !c.he){ try{ const h={t:"hello",v:3,e:c.hello.e}; if(c.hello.m) h.m=c.hello.m; if(c.hello.fs){ h.fs=1; if(typeof c.kce==="number") h.ke=c.kce; }
          if(await depositOne(await mboxIdForSecret(c.prev), await mboxKeyForSecret(c.prev), "h"+rid(), h)) contactPatch(c.ck,{hp:0}); }catch(e){} }
        for(const ck of fetchCKSet(R.fromContact)) variants.push([await mboxIdForSecret(ck), await mboxKeyForSecret(ck), ck]); }
      for(const [id,key,ck] of variants) delivered += await fetchMailboxId(R, id, key, ck);
    }catch(e){}
    return delivered;
  })();
  try{ return await R.fetching; } finally { R.fetching=null; }
}
async function fetchMailboxId(R, id, key, ck){
  let delivered=0; const got=[];
  try{
    const since=mbtsGet(id);
    const {data}=await mboxFn("get",{mbox:id, since: since?new Date(since).toISOString():0});
    const items=(data&&data.items)||[]; if(!items.length) return 0;
    let maxTs=since, hold=0; const mine=_acct;
    const dur=expFor(histKeyOf(R)); const cut=dur?Date.now()-dur:0;
    const cc=(ck && !R.group) ? contactFind(ck) : null;
    for(const it of items){ const ts=Date.parse(it.ts)||Date.now(); if(ts>maxTs) maxTs=ts;
      if(it.mid && R.seen.has(it.mid)) continue;
      if(dur && ts<=cut) continue;                             // already past this chat's disappearing window
      let ikey=key;
      if(it.data && typeof it.data.ep==="number"){           // written under this contact's weekly chain key
        if(!(cc && cc.kc)){ if(!hold || ts<hold) hold=ts; continue; }   // chain not synced to this device yet: leave it, read it later
        ikey=await mboxKeyForContact(cc, it.data.ep); if(!ikey) continue;   // older than anything we still hold: unreadable by design
      }
      if(it.mid) R.seen.add(it.mid);                           // claim it before awaiting so a parallel pass can't show it too
      try{ const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(it.data.iv)},ikey,unb64(it.data.ct));
        const env=JSON.parse(dec.decode(pt));
        // "our own account's other device wrote this": decided by the marker sealed inside the ciphertext only
        const own=!!(mine && env.a && env.a===mine);
        if(it.mid && !own) got.push(it.mid);                     // never ack what we sent ourselves (the recipient may not have it yet)
        if(env.t==="hello"){ if(!own && ck) await onHelloEnv(R, ck, env); continue; }        // someone opened an invite link
        if(env.t==="used"||env.t==="nopin"){ if(!own && ck) onUsedEnv(R, ck, env); continue; }   // the link we opened was already taken / our code was wrong
        if(env.mid && it.mid && env.mid!==it.mid) throw new Error("id mismatch");
        // a v3 link mailbox (ours while pending, or our contact's former link while we watch it) carries
        // nothing but hellos: anything else there was written by someone holding a copy of the link
        if(ck && !R.group){ const cc=contactFind(R.fromContact); const pend=contactFind(ck);
          if((cc && cc.v3 && ck!==R.fromContact) || (pend && pend.v3 && pend.pk)) continue; }
        if(env.t==="rcpt"){ if(!own) markReceived(histKeyOf(R), env.mids||[]); continue; }   // the other side got our messages
        const who=realName(env.n)||(R.group?t("Member"):"");
        if(R.group && (!own || env.t==="gk2")){ const vf=await verifyGroupEnv(R, env, who); noteVerdict(R, who, vf, env.pk); env.vf=vf;
          if(groupGone(R, env)) continue; if(env.t==="hi") continue; if(env.t==="gk2"){ await onGk2(R, env, vf, who); continue; } if(env.t==="call" && vf==="bad") continue; }
        if(R.group && own && env.t==="hi") continue;
        if(!own) adoptNameFromMessage(R, env.n);
        onInbound(R, env, who, ts, it.mid, own, false);
        if(!own && !QUIET_T.has(env.t)) delivered++;
      }catch(e){ if(it.mid) R.seen.delete(it.mid);
        if(it.data && typeof it.data.ep==="number" && Date.now()-ts<48*3600*1000){ if(!hold || ts<hold) hold=ts; } }   // wrong chain on this device for now: keep it for a later pass
    }
    mbtsSet(id, hold ? Math.min(maxTs, hold-1) : maxTs);
    // tell the relay these are delivered: it keeps them 48 h more for our other devices, then drops them
    if(got.length) mboxFn("ack",{mbox:id, mids:got}).catch(()=>{});
    if(delivered && !R.shadow){ messageTone(R); if(R.code===active) blinkEyes(); }
  }catch(e){}
  return delivered;
}
// One place where every inbound message lands (live, mailbox, background): render if the chat is open,
// always save, count as unread when not being looked at, and tell the sender it arrived.
const QUIET_T=new Set(["react","edit","exp","vote","del"]);   // envelopes that change a chat without being a message: no sound, no unread
function onInbound(R, env, who, ts, mid, own, animate){
  if(env && env.t==="react"){ onReactEnv(R, env, who, ts, mid, own); return; }
  if(env && env.t==="edit"){ onEditEnv(R, env, who, ts, mid, own); return; }
  if(env && env.t==="exp"){ onExpEnv(R, env, who, ts, mid, own); return; }
  if(env && env.t==="vote"){ onVoteEnv(R, env, who, ts, mid, own); return; }
  if(env && env.t==="del"){ onDelEnv(R, env, who, ts, mid, own); return; }
  if(mid && _meta.delm && _meta.delm[mid]){ if(goneOnArrival(R, env, who, ts, mid, own)) return; }
  if(!own) typingClear(R, who);
  if(R.shadow){   // the inbox read it: show it in the open chat of that conversation (or of the chat it was merged into)
    let ck=R.fromContact; if(ck && !R.group){ const tg=mergedTarget(contactFind(ck)); if(tg) ck=tg.ck; }
    let V=null; rooms.forEach(x=>{ if(x.logEl && (R.group ? x.rid===R.rid : x.fromContact===ck)) V=x; });
    if(V) return onInboundView(R, V, env, who, ts, mid, own, animate); }
  return onInboundView(R, R, env, who, ts, mid, own, animate);
}
// R: the chat whose key carried the message (receipts go back on it); V: the chat it is shown in
function onInboundView(R, V, env, who, ts, mid, own, animate){
  const hk=histKeyOf(R); const open=!!V.logEl;
  if(own){   // sent from another of our devices: appears on this one as our own message, no sound, no badge
    if(validGinv(env)) groupAddIfNew(env.rid, env.gk, env.name, env.adm);
    if(keptPhoto(env)) keepPhotoSoon(hk, mid, env, ts);
    if(open){ if(env.t==="img"){ if(keptPhoto(env)) addImageKept(V.logEl,"sent",env,"",ts,{mid,st:stateFor(mid),room:hk}); else addText(V.logEl,"sent",t("📷 Photo"),"",false,ts,{mid,st:stateFor(mid),ui:1}); }
      else if(env.t==="aud"){ if(validAud(env)) addVoice(V.logEl,"sent",env,"",ts,{mid,st:stateFor(mid),room:hk}); }
      else if(validLoc(env)) addCard(V.logEl,"sent",locCard(env,true),"",ts,{mid,st:stateFor(mid)});
      else if(validGinv(env)) addCard(V.logEl,"sent",ginvCard(env,"","sent"),"",ts,{mid,st:stateFor(mid)});
      else if(RICH_T.has(env.t)){ if(richValid(env)){ renderRich(V,"sent",env,"",ts,{mid,st:stateFor(mid),room:hk}); refreshVoteCards(V); } }
      else addText(V.logEl,"sent",env.body,"",false,ts,{mid,st:stateFor(mid),quote:validQuote(env.q)?quoteEl(V,cleanQuote(env.q),"sent",""):null,tx:1}); }
    if(RICH_T.has(env.t) && richValid(env)) richKeepSoon(hk, mid, env, ts);
    histSave(hk,{dir:"sent",env,ts,mid}); return;
  }
  const tag=R.group?(who||""):""; const vf=R.group?env.vf:undefined;
  if(open && V.code===active && V.logEl._stick===false){ V._below=(V._below||0)+1; setTimeout(jumpUpdate,0); }
  if(open && R.group && mid && env.pk) setTimeout(()=>{ const b=bubbleOf(V, mid); if(b && !b.dataset.pk) b.dataset.pk=env.pk; }, 0);   // its signer: only they may delete it for everyone
  if(env.t==="img"){ if(keptPhoto(env)){ keepPhotoSoon(hk, mid, env, ts); if(open) addImageKept(V.logEl,"recv",env,tag,ts,{mid,room:hk,vf}); }
    else if(open) addImageRecvOnce(V.logEl,env,tag,ts,mid,vf); }
  else if(env.t==="aud"){ if(!validAud(env)) return; if(open) addVoice(V.logEl,"recv",env,tag,ts,{mid,room:hk,vf}); }
  else if(env.t==="loc"){ if(!validLoc(env)) return; if(open) addCard(V.logEl,"recv",locCard(env,false),tag,ts,{mid,vf}); }
  else if(env.t==="ginv"){ if(!validGinv(env)) return; if(open) addCard(V.logEl,"recv",ginvCard(env,who||R.title,"recv"),tag,ts,{mid,vf}); }
  else if(RICH_T.has(env.t)){ if(!richValid(env)) return; richKeepSoon(hk, mid, env, ts); if(open){ renderRich(V,"recv",env,tag,ts,{mid,room:hk,vf}); refreshVoteCards(V); } }
  else if(open) addText(V.logEl,"recv",env.body,tag,!!animate,ts,{mid,vf,quote:validQuote(env.q)?quoteEl(V,cleanQuote(env.q),"recv",who):null,tx:1,pk:R.group?(env.pk||""):""});
  histSave(hk,{dir:"recv",env,ts,who,mid,vf});
  healLinkUsed(R);
  if(!open || V.code!==active) bumpUnread(V); else updateBadge(true);
  if(!R.group && R.fromContact && mid) queueRcpt(R.fromContact, mid);
}
// A chat we opened from a link and were told "already used by someone else" — yet the inviter writes to us (or
// proves the key live) under the key we agreed with its link: it bound to US, the warning was wrong. Lift it.
function healLinkUsed(R){
  try{ if(!R || R.group || !R.fromContact) return; const c=contactFind(R.fromContact); if(!c || !c.dead || c.pk || !c.v3 || c.nopin || c.he) return;
    const l=contactsLoad(); const x=l.find(y=>y.ck===c.ck); if(!x) return; delete x.dead; contactsSave(l);
    if(R.logEl) sysline(R.logEl, t("✅ You are connected with {name} after all — ignore the warning above.",{name:c.alias||dn(c.name)}));
    if(R.code===active && !R.paired) setIdle(R); }catch(e){} }
function bumpUnread(R){ const k=histKeyOf(R); _meta.unread[k]=(_meta.unread[k]||0)+1; R.unread=(R.unread||0)+1; pulseChat(R); localSaveSoon(); renderTabs(); renderContacts(); }
function clearUnread(R){ const k=histKeyOf(R); if(_meta.unread[k]){ delete _meta.unread[k]; localSaveSoon(); } R.unread=0; }
// ----- newer version on the server -----
let _updChk=0, _updLater=false, _updSeen=0;
async function checkUpdate(force){
  const now=Date.now(); if(!force && now-_updChk<300000) return; _updChk=now;
  try{ const txt=await fetch("/sw.js?v="+now,{cache:"no-store"}).then(r=>r.ok?r.text():"");
    const m=/const CACHE = "gizleme-v(\d+)"/.exec(txt); if(m && +m[1]>APP_VERSION && +m[1]!==_updSeen){ _updSeen=+m[1]; offerUpdate(_updSeen); } }catch(e){}
}
function offerUpdate(ver){
  // lock / login screen with nothing typed (not the "New chat" screen: it holds a link being shared): reload by
  // itself — once per version, so a cache still serving the old code cannot start a reload loop
  const mode=($("join")||{dataset:{}}).dataset.mode||"";
  const idle=document.body.classList.contains("in-auth") && mode!=="newchat" && !call && !(($("pwInput")||{}).value) && !(($("userInput")||{}).value) && !(($("pw2Input")||{}).value);
  let done=""; try{ done=sessionStorage.getItem("gz-upd")||""; }catch(e){}
  if(idle && done!==String(ver)){ try{ sessionStorage.setItem("gz-upd",String(ver)); }catch(e){} location.reload(); return; }
  if(_updLater) return; $("updPill").hidden=false;
}
// ----- muted chats -----
// A muted chat makes no sound, doesn't glow and isn't counted on the app icon; its notifications still arrive,
// silently (a push must always show something). Kept with the contact / group in the encrypted vault, so it
// follows the account to its other devices (last change wins); "always" is simply the far future.
const MUTE_ALWAYS=8.64e15;
function muteRecOf(R){ if(!R) return null; if(R.group) return _groups.find(g=>g.rid===R.rid)||null;
  if(R.fromContact){ const c=_contacts.find(x=>x.ck===R.fromContact)||null; return mergedTarget(c)||c; } return null; }
function mutedUntil(rec){ const u=rec ? +rec.mu||0 : 0; return u>Date.now() ? u : 0; }
function isMutedRoom(R){ return !!mutedUntil(muteRecOf(R)); }
function isMutedItem(it){ return !!mutedUntil(it.t==="g" ? _groups.find(g=>g.rid===it.rid) : _contacts.find(c=>c.ck===it.ck)); }
function fmtUntil(ts){ const d=new Date(ts), now=new Date(); const hm=d.toLocaleTimeString(LOC(),{hour:"2-digit",minute:"2-digit"});
  return d.toDateString()===now.toDateString() ? hm : d.toLocaleDateString(LOC(),{weekday:"short"})+" "+hm; }
function setMute(R, ms){                  // ms: how long; MUTE_ALWAYS for always; 0 turns sound back on
  if(!R) return; const now=Date.now(); const until=ms ? (ms>=MUTE_ALWAYS ? MUTE_ALWAYS : now+ms) : 0;
  const apply=rec=>{ if(until) rec.mu=until; else delete rec.mu; rec.mts=now; };
  if(R.group){ const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g) return; apply(g); groupsSave(l); }
  else if(R.fromContact){ const l=contactsLoad(); const c=l.find(x=>x.ck===R.fromContact); if(!c) return; apply(c); contactsSave(l); }
  else return;
  if(until) _pulse.delete(histKeyOf(R)), R._pulseAt=0;
  renderTabs(); updateBadge();
  toast(!until ? t("Sound back on for this chat") : until>=MUTE_ALWAYS ? t("Chat muted") : t("Muted until {time}",{time:fmtUntil(until)}));
}
// a timed mute ends by itself: the list (and the icon count) follow at that moment
let _muteT=null;
function scheduleMuteRefresh(){ clearTimeout(_muteT); const now=Date.now(); let next=0;
  for(const r of _contacts.concat(_groups)){ const u=+r.mu||0; if(u>now && u<MUTE_ALWAYS && (!next || u<next)) next=u; }
  if(next) _muteT=setTimeout(()=>{ renderContacts(); renderTabs(); swNamesSoon(); }, Math.min(2147483000, next-now+500)); }
// ----- unread total: in the tab title and on the app icon -----
// Only a number — never a name. Muted chats are left out. The service worker adds one per message push while
// the app is closed; the app sets the exact figure whenever it is open.
let _badgeN=-1;
function unreadTotal(){ if(!gHistKey) return 0; const muted=new Set();
  _contacts.forEach(c=>{ if(mutedUntil(c)) muted.add(ckHistKey(c.ck)); }); _groups.forEach(g=>{ if(mutedUntil(g)) muted.add(g.rid); });
  let n=0; for(const k in (_meta.unread||{})) if(!muted.has(k)) n+=(+_meta.unread[k]||0); return n; }
function updateBadge(force){ if(!gHistKey && !force) return; const n=unreadTotal(); if(n===_badgeN && !force) return; _badgeN=n;
  try{ document.title=(n ? "("+(n>99?"99+":n)+") " : "")+"Gizleme"; }catch(e){}
  try{ if(n && navigator.setAppBadge) navigator.setAppBadge(n).catch(()=>{}); else if(navigator.clearAppBadge) navigator.clearAppBadge().catch(()=>{}); }catch(e){}
  try{ if("serviceWorker" in navigator) navigator.serviceWorker.ready.then(reg=>{ (reg.active||navigator.serviceWorker.controller)?.postMessage({type:"badge", n}); }).catch(()=>{}); }catch(e){} }
// ----- "New messages": opening a chat with unread messages puts a line above the first of them and starts there
let _sepRoom=null;
function markNew(R, n){
  if(!n && R && R.code===_sepRoom) return;            // the same chat shown again: the line stays until you leave it
  document.querySelectorAll("#logs .newsep").forEach(e=>e.remove()); _sepRoom=null;
  if(!R || !R.logEl || !n) return;
  const recv=[...R.logEl.querySelectorAll(":scope > .bubble.recv")];
  if(!recv.length){ R._newN=n; return; }              // the history isn't on screen yet: placed once it is
  R._newN=0; _sepRoom=R.code;
  const first=recv[Math.max(0, recv.length-n)], sep=document.createElement("div"); sep.className="newsep";
  sep.textContent=t(n>1?"{n} new messages":"{n} new message",{n}); R.logEl.insertBefore(sep, first);
  // after the "stick to the bottom" passes of rendering: only move up when the line would be out of sight
  const go=()=>{ try{ const l=R.logEl, top=sep.getBoundingClientRect().top-l.getBoundingClientRect().top;
    if(top<0) l.scrollTop+=top-10; }catch(e){} };
  requestAnimationFrame(()=>requestAnimationFrame(go));
}
function stateFor(mid){ if(mid && outqHas(mid)) return "pending"; return mid && _meta.rcpt[mid] ? "rcvd" : "sent"; }
// Messages written to a v3 invite before it is opened wait on this device (nothing is ever deposited under
// the link key) and are sent under the agreed key the moment the hello arrives.
function outqHas(mid){ const q=_meta.outq||{}; for(const k in q) if(q[k].some(x=>x.mid===mid)) return true; return false; }
function queueOut(R, env, mid, now, el){
  if(!_meta.outq) _meta.outq={}; (_meta.outq[R.fromContact]=_meta.outq[R.fromContact]||[]).push({env,mid,ts:now});
  histSave(histKeyOf(R),{dir:"sent",env,ts:now,mid}); localSaveSoon(); if(el) setMsgState(el,"pending");
}
async function flushOutq(fromCk, toCk){
  const q=(_meta.outq||{})[fromCk]; if(!q||!q.length){ if(_meta.outq) delete _meta.outq[fromCk]; return; }
  delete _meta.outq[fromCk]; localSaveSoon();
  let R=null; rooms.forEach(r=>{ if(r.fromContact===toCk) R=r; }); if(!R) R=await shadowRoom({t:"c",ck:toCk,name:""});
  let sent=0;
  for(const it of q){ let ok=false; try{ ok=await depositMailbox(R, it.mid, it.env); }catch(e){}
    const el=R.logEl ? R.logEl.querySelector('[data-mid="'+CSS.escape(it.mid)+'"]') : null;
    if(ok){ sent++; if(el) setMsgState(el, stateFor(it.mid)); }
    else { if(!_meta.outq) _meta.outq={}; (_meta.outq[toCk]=_meta.outq[toCk]||[]).push(it); if(el) setMsgState(el,"pending"); } }
  if(sent) notifyPeer(toCk,"msg").catch(()=>{});
  localSaveSoon();
}
// ----- receipts: "your message reached their device". Encrypted under the contact's mailbox key, so the
// relay sees neither which messages nor that it is a receipt. Sent live when paired, and always left in the
// mailbox for the sender's other devices / later polls. 1:1 chats only.
const _rcptQ={}; let _rcptT=null;
function queueRcpt(ck, mid){ (_rcptQ[ck]=_rcptQ[ck]||[]).push(mid); clearTimeout(_rcptT); _rcptT=setTimeout(()=>{ for(const k in _rcptQ){ const mids=_rcptQ[k]; delete _rcptQ[k]; flushRcpt(k,mids).catch(()=>{}); } },800); }
async function flushRcpt(ck, mids){
  const env={t:"rcpt",mids};
  // live copy (broadcast) to whoever we're paired with
  rooms.forEach(R=>{ if(R.fromContact===ck && R.paired && R.channel){ try{
    mboxKeyForSecret(ck).then(async key=>{ const iv=crypto.getRandomValues(new Uint8Array(12));
      const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,enc.encode(JSON.stringify(env)));
      R.channel.send({type:"broadcast",event:"rcpt",payload:{from:R.id,iv:b64(iv),ct:b64(ct)}}); }).catch(()=>{});
  }catch(e){} } });
  // stored copy to every key this contact is reachable on (current + link while reconciling)
  await depositToContact(ck, "r"+rid(), env);
}
async function onRcpt(R,{payload:p}){
  if(!p||p.from===R.id||!R.fromContact) return;
  for(const ck of contactCKSet(R.fromContact)){
    try{ const key=await mboxKeyForSecret(ck); const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(p.iv)},key,unb64(p.ct));
      const env=JSON.parse(dec.decode(pt)); if(env.t==="rcpt"){ markReceived(histKeyOf(R), env.mids||[]); return; }
      if(env.t==="typ"){ onTyping(R, env); return; } }catch(e){}
  }
}
// ---------- "typing…" / "recording a voice message…" ----------
// While you type (or record a voice message) in a chat, the people in it get a small signal — at once, then
// every 3 seconds while it goes on, and "stopped" when you send, empty the box or leave the chat; without news
// it fades after 6.5 s. Live only (never left in the mailbox) and encrypted: in a two-person chat under the
// same key and on the same relay event as a delivery receipt, so the relay can't tell one from the other; in a
// group under the group key. Settings → Typing indicators off: you neither send them nor see them.
const LS_TYPING="gz-typing", TYP_EVERY=3000, TYP_TTL=6500;
function typingOn(){ try{ return localStorage.getItem(LS_TYPING)!=="0"; }catch(e){ return true; } }
let _typOut={code:null, s:"", at:0};
async function typingSend(R, s){
  if(!R || !R.channel) return;
  try{ const env={t:"typ", s, a:_acct||undefined}; let key;
    if(R.group){ if(!R.gkMsg) return; key=R.gkMsg; env.n=String(myName||"").slice(0,40); }
    else { if(!R.fromContact || !R.paired) return; key=await mboxKeyForSecret(R.fromContact); }
    const iv=crypto.getRandomValues(new Uint8Array(12));
    const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv}, key, enc.encode(JSON.stringify(env)));
    R.channel.send({type:"broadcast",event:"rcpt",payload:{from:R.id,iv:b64(iv),ct:b64(ct)}});
  }catch(e){}
}
// s: "t" typing, "v" recording, "" stopped — for the chat on screen; leaving a chat stops what was sent there
function typingTick(s){
  const R=A(), now=Date.now();
  if(_typOut.code && (!R || _typOut.code!==R.code)){ const P=rooms.get(_typOut.code); if(P && _typOut.s) typingSend(P, ""); _typOut={code:null, s:"", at:0}; }
  if(!R || !typingOn()) return;
  if(s===_typOut.s && (!s || now-_typOut.at<TYP_EVERY)) return;
  _typOut={code:R.code, s, at:now}; typingSend(R, s);
}
function onTyping(R, env){
  if(!typingOn() || !env) return;
  if(_acct && env.a===_acct) return;                                  // our own other device
  const s=(env.s==="t"||env.s==="v") ? env.s : "";
  const who=R.group ? String(env.n||"").replace(/[\r\n\t]+/g," ").trim().slice(0,40) : "";
  if(R.group && !who) return;
  R.typing=R.typing||new Map();
  if(s) R.typing.set(who,{s, until:Date.now()+TYP_TTL}); else R.typing.delete(who);
  typingShow(R);
}
function typingClear(R, who){ if(R && R.typing && R.typing.delete(R.group ? String(who||"").trim().slice(0,40) : "")) typingShow(R); }
function typingList(R){ const now=Date.now(), out=[]; if(R && R.typing) for(const [k,v] of [...R.typing]){ if(v.until>now) out.push([k,v.s]); else R.typing.delete(k); } return out; }
function typingLabel(R){ if(!typingOn()) return ""; const l=typingList(R); if(!l.length) return "";
  if(!R.group) return l[0][1]==="v" ? t("recording a voice message…") : t("typing…");
  if(l.length>1) return t("{n} people are typing…",{n:l.length});
  return l[0][1]==="v" ? t("{name} is recording a voice message…",{name:l[0][0]}) : t("{name} is typing…",{name:l[0][0]}); }
function typingRowId(R){ if(R.group) return "g:"+R.rid; if(!R.fromContact) return ""; const c=contactFind(R.fromContact); const tg=mergedTarget(c); return "c:"+((tg||c||{}).ck||R.fromContact); }
function typingShow(R){
  clearTimeout(R._typT); const lab=typingLabel(R);
  if(lab){ const next=Math.min(...[...R.typing.values()].map(v=>v.until))-Date.now(); R._typT=setTimeout(()=>typingShow(R), Math.max(200, next+60)); }
  if(R.code===active) applyStatus(R);
  // three dots (or a microphone) at the end of the chat — kept last by CSS order, whatever arrives after it
  if(R.logEl){ let b=R.logEl.querySelector(":scope > .typing-bub");
    if(lab){ const voice=typingList(R).some(x=>x[1]==="v");
      if(!b){ b=document.createElement("div"); b.className="typing-bub"; b.innerHTML='<span class="tv" aria-hidden="true">🎙️</span><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>';
        const L=R.logEl, near=L.scrollHeight-L.scrollTop-L.clientHeight<140; L.appendChild(b); if(near) scrollEl(L); }
      b.classList.toggle("voice", voice); b.title=lab; b.setAttribute("aria-label", lab); }
    else if(b) b.remove(); }
  // the chats list: the preview line says it too
  const id=typingRowId(R); const row=id && document.querySelector('#contactList .ct[data-id="'+CSS.escape(id)+'"]'); const cm=row && row.querySelector(".cm");
  if(cm){ if(lab){ if(!cm.classList.contains("typing")) cm.dataset.was=cm.textContent; cm.textContent=lab; cm.classList.add("typing"); }
    else if(cm.classList.contains("typing")){ cm.textContent=cm.dataset.was||""; delete cm.dataset.was; cm.classList.remove("typing"); } }
}
async function onRcptGroup(R,{payload:p}){
  if(!p||p.from===R.id||!R.gkMsg) return;
  try{ const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(p.iv)},R.gkMsg,unb64(p.ct)); const env=JSON.parse(dec.decode(pt)); if(env && env.t==="typ") onTyping(R, env); }catch(e){}
}
function markReceived(hk, mids){
  if(!mids.length) return;
  mids.forEach(m=>{ _meta.rcpt[m]=1; });
  const keys=Object.keys(_meta.rcpt); if(keys.length>800) keys.slice(0,keys.length-800).forEach(k=>{ delete _meta.rcpt[k]; });
  localSaveSoon();
  rooms.forEach(R=>{ if(R.logEl && histKeyOf(R)===hk) mids.forEach(m=>{ const el=R.logEl.querySelector('.bubble.sent[data-mid="'+m+'"]'); if(el) setMsgState(el,"rcvd"); }); });
}
function markViewed(mid){ if(!mid) return; _meta.viewed[mid]=1; const keys=Object.keys(_meta.viewed); if(keys.length>800) keys.slice(0,keys.length-800).forEach(k=>{ delete _meta.viewed[k]; }); localSaveSoon(); }
// ----- the inbox: every saved chat is collected, not only the ones open on screen -----
async function shadowRoom(it){   // a room-shaped object for a chat that isn't open: enough for the mailbox + history
  const R=newRoom(it.t==="g"?it.rid:""); R.shadow=true; R.logEl=null;
  if(it.t==="g"){ R.group=true; R.rid=it.rid; R.gk=unb64(it.gk); R.gkMsg=await gkMsgKey(R.gk); R.title=it.name||"Group"; }
  else { R.fromContact=it.ck; R.title=it.name||""; }
  // what this device already holds (our own deposits included) must not be saved a second time
  R.seen=seenSetFor(R); try{ if(gHistKey) seedSeen(R, await histLoad(histKeyOf(R))); }catch(e){}
  return R;
}
let _inboxBusy=false, _inboxLast=0;
async function inboxPull(force){
  if(!gHistKey||_inboxBusy) return; if(!force && Date.now()-_inboxLast<15000) return;
  _inboxBusy=true; _inboxLast=Date.now();
  // messages written to an invite before it was opened: sent now if the link has since been bound (here or on
  // another device — then under the agreed key), or retried if a deposit failed
  for(const k of Object.keys(_meta.outq||{})){ try{ const c=contactFind(k); const r=c?null:contactByPrev(k);
    if(r) flushOutq(k, r.ck).catch(()=>{}); else if(c && !(c.v3 && c.pk)) flushOutq(k, k).catch(()=>{}); }catch(e){} }
  try{
    const items=groupsLoad().map(g=>({t:"g",rid:g.rid,gk:g.gk,name:g.name})).concat(contactsLoad().map(c=>({t:"c",ck:c.ck,name:c.name})));
    let bg=0;
    for(const it of items){
      let R=null; rooms.forEach(x=>{ if(it.t==="g" ? x.rid===it.rid : x.fromContact===it.ck) R=x; });
      if(R){ await fetchMailbox(R); continue; }
      try{ const S=await shadowRoom(it); const d=(await fetchMailbox(S))||0; if(!isMutedRoom(S)) bg+=d; }catch(e){}
    }
    if(bg){ messageTone(null); renderContacts(); }
  } finally { _inboxBusy=false; }
}
// One set of already-seen message ids per conversation, shared by every room object that reads its mailbox (the
// open chat, the inbox's shadow, a chat reopened later): two readers of one mailbox can't both deliver a message.
const _seenByKey={};
function seenSetFor(R){ const k=histKeyOf(R)||R.code||""; return _seenByKey[k]||(_seenByKey[k]=new Set()); }
function seedSeen(R, past){ R.seen=seenSetFor(R); (past||[]).forEach(r=>{ if(r && r.mid) R.seen.add(r.mid); }); }

// ---------- identity verification (safety code from the first shared secret) ----------
const SAFE_EMOJI=["🐶","🐱","🐭","🐹","🐰","🦊","🐻","🐼","🐨","🐯","🦁","🐮","🐷","🐸","🐵","🐔","🐧","🐦","🦆","🦉","🦋","🐝","🐞","🐢","🐍","🐙","🦀","🐠","🐬","🐳","🌵","🌲","🌴","🌸","🌻","🌹","🍁","🍄","🔥","💧","⭐","🌙","🍎","🍊","🍋","🍉","🍇","🍓","🍒","🍑","🥝","🍍","🥥","🥕","🌽","🍞","🧀","🍔","🍕","🌮","🍰","🚀","⛵","🎸"];
async function safetyBytes(ckB64){ return new Uint8Array(await hkdf(unb64(ckB64),"gz-safety/v1",16)); }
function safetyHex(b){ let s=""; for(let i=0;i<12;i++){ s+=b[i].toString(16).padStart(2,"0").toUpperCase(); if(i%2===1 && i<11) s+=" "; } return s; }
function safetyEmoji(b){ const a=[]; for(let i=0;i<5;i++) a.push(SAFE_EMOJI[b[i]%SAFE_EMOJI.length]); return a.join("  "); }
function isVerified(ck){ const c=contactsLoad().find(x=>x.ck===ck); return !!(c&&c.v); }
function setVerified(ck){ const list=contactsLoad(); const c=list.find(x=>x.ck===ck); if(c){ c.v=1; contactsSave(list); } }
function updateVerifyUI(){
  const R=A(); const vb=$("verifyBtn"); const show=!!(R&&((R.fromContact&&R.paired)||R.group));
  if(vb){ vb.hidden=!show; if(show){ const v=R.group?false:isVerified(R.fromContact); vb.classList.toggle("ok",!!v); const u=vb.querySelector("use"); if(u) u.setAttribute("href", v?"#i-shield-check":"#i-shield"); vb.title=R.group?t("Group safety code"):(v?t("Verified — tap to review"):t("Verify who you're talking to")); } }
  if(R && R.code===active){ const nm=$("peerName"); if(nm) nm.textContent = dn(R.peerName) + (!R.group&&R.fromContact&&isVerified(R.fromContact)?" ✓":""); }
}
async function openVerify(){
  const R=A(); if(!R||(!R.fromContact&&!R.group)){ toast(t("Open a chat first")); return; }
  if(R.group){
    $("verifyWho").textContent = dn(R.title)||t("this group");
    try{ const b=new Uint8Array(await hkdf(R.gk,"gz-safety/v1",16)); $("safetyEmoji").textContent=safetyEmoji(b); $("safetyCode").textContent=safetyHex(b); }
    catch(e){ $("safetyCode").textContent=t("unavailable"); }
    $("verifyStatus").textContent=t("Everyone in this group shares this code"); $("verifyStatus").classList.remove("ok");
    $("verifyMark").style.display="none"; $("verifyModal").classList.add("show"); return;
  }
  $("verifyWho").textContent = dn(R.title||R.peerName)||t("this contact");
  const va=$("verifyAuto"); if(va){
    va.innerHTML = R.authOk
      ? t("<b>Automatic check (every connection): ✓</b> this connection proved it holds the same shared key as when you first connected. It confirms continuity, not who was there the first time — the in-person check below does that, once.")
      : (R.paired ? t("<b>Automatic check:</b> first connection in this room — there was no shared key to check yet. From the next connection on, it's verified automatically.")
                  : t("<b>Automatic check (every connection):</b> runs as soon as you're both online — anyone who can't prove they hold your shared key is refused.")); }
  const c=contactFind(R.fromContact);
  if(c && c.inv && !c.sv){      // connected through a link but never live together yet: no key exchange to verify
    $("safetyEmoji").textContent="· · · · ·"; $("safetyCode").textContent=t("not yet");
    $("verifyStatus").textContent=t("The code appears after your first chat while you're both online"); $("verifyStatus").classList.remove("ok");
    $("verifyMark").style.display="none"; $("verifyModal").classList.add("show"); return;
  }
  try{ const b=(c&&c.inv&&c.sv) ? unb64(c.sv) : await safetyBytes(R.fromContact); $("safetyEmoji").textContent=safetyEmoji(b); $("safetyCode").textContent=safetyHex(b); }
  catch(e){ $("safetyCode").textContent=t("unavailable"); }
  const v=isVerified(R.fromContact);
  $("verifyStatus").textContent = v?t("Verified ✓"):t("Not verified yet");
  $("verifyStatus").classList.toggle("ok",v);
  $("verifyMark").style.display = v?"none":"inline-block";
  $("verifyModal").classList.add("show");
}
function markVerifiedNow(){ const R=A(); if(!R||!R.fromContact) return; setVerified(R.fromContact);
  $("verifyStatus").textContent=t("Verified ✓"); $("verifyStatus").classList.add("ok"); $("verifyMark").style.display="none";
  updateVerifyUI(); renderContacts(); toast(t("Marked as verified ✓")); }

// ---------- push notifications (wake the other side even when the app is closed) ----------
const PUSH_FN="gizleme-push";
const LS_DEVID="gz-devid", LS_PUSH="gz-push-on", LS_NOTIFIED="gz-notified";
let gPushSub=null, _vapid=null;
function b64url(bytes){ return b64(bytes).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,""); }
function unb64url(s){ s=(s||"").replace(/-/g,"+").replace(/_/g,"/"); while(s.length%4) s+="="; return unb64(s); }
function urlB64ToU8(s){ const pad="=".repeat((4-s.length%4)%4); const b=(s+pad).replace(/-/g,"+").replace(/_/g,"/");
  const raw=atob(b); const u=new Uint8Array(raw.length); for(let i=0;i<raw.length;i++)u[i]=raw.charCodeAt(i); return u; }
function deviceId(){ let d=null; try{ d=localStorage.getItem(LS_DEVID); }catch(e){}
  if(!d){ d=rid()+rid(); try{ localStorage.setItem(LS_DEVID,d); }catch(e){} } return d; }
function pushOn(){ try{ return localStorage.getItem(LS_PUSH)==="1"; }catch(e){ return false; } }
function pushSupported(){ return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window; }
async function notifyKeyFor(ckB64){ return b64url(new Uint8Array(await hkdf(unb64(ckB64),"gz-notify/v1"))); }
async function fn(action, extra){ return client.functions.invoke(PUSH_FN,{body:Object.assign({action},extra||{})}); }
async function vapidKey(){ if(_vapid) return _vapid; try{ const {data}=await fn("vapid"); _vapid=data&&data.publicKey||null; }catch(e){} return _vapid; }
async function registerAllContacts(){
  if(!pushOn()||!gPushSub) return;
  const nks=[]; for(const c of contactsLoad()){ try{ nks.push(await notifyKeyFor(c.ck)); if(c.prev && reconActive(c)) nks.push(await notifyKeyFor(c.prev)); }catch(e){} }
  // include any live contact rooms not yet saved
  for(const R of rooms.values()){ if(R.fromContact){ try{ const nk=await notifyKeyFor(R.fromContact); if(nks.indexOf(nk)<0) nks.push(nk); }catch(e){} } }
  if(!nks.length) return;
  try{ await fn("register",{owner:deviceId(), notify_keys:nks, sub:gPushSub.toJSON(), acct:_acct||undefined}); }catch(e){}
}
async function enablePush(){
  if(!pushSupported()){
    if(/iphone|ipad|ipod/i.test(navigator.userAgent) && !(window.navigator.standalone))
      toast(t("On iPhone: install Gizleme to your Home Screen first (⬇), then enable notifications"));
    else toast(t("Notifications aren't supported on this browser"));
    return false;
  }
  let perm=Notification.permission;
  if(perm!=="granted") perm=await Notification.requestPermission();
  if(perm!=="granted"){ toast(t("Notifications are blocked — allow them in your browser settings")); return false; }
  try{
    const reg=await navigator.serviceWorker.ready;
    const pk=await vapidKey(); if(!pk){ toast(t("Notification service unavailable")); return false; }
    gPushSub=await reg.pushManager.getSubscription();
    if(!gPushSub) gPushSub=await reg.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:urlB64ToU8(pk)});
    try{ localStorage.setItem(LS_PUSH,"1"); }catch(e){}
    await registerAllContacts();
    toast(t("Notifications on 🔔")); updateNotifyUI(); return true;
  }catch(e){ toast(t("Couldn't enable notifications")); return false; }
}
async function disablePush(){
  try{ localStorage.setItem(LS_PUSH,"0"); }catch(e){}
  try{ if(gPushSub){ await fn("unregister",{owner:deviceId()}); await gPushSub.unsubscribe(); } }catch(e){}
  gPushSub=null; toast(t("Notifications off")); updateNotifyUI();
}
async function notifyPeer(ckB64, kind){
  if(!ckB64) return false;
  { const c=contactFind(ckB64); if(c && c.v3 && c.prev && reconActive(c) && !c.nprev){ contactPatch(ckB64,{nprev:1}); notifyPeerKey(c.prev, kind).catch(()=>{}); } }
  return notifyPeerKey(ckB64, kind);
}
async function notifyPeerKey(ckB64, kind){
  const nk=await notifyKeyFor(ckB64);
  if(!_meta.notified) _meta.notified={}; const map=_meta.notified;
  const now=Date.now(); if(kind!=="call" && kind!=="missed" && map[nk]&&now-map[nk]<90000) return false;   // debounce 90s per contact (not for calls)
  map[nk]=now; localSaveSoon();
  // no name in the push: the relay and the push service see only a kind; the receiving device's service
  // worker puts the contact's own name (or nickname) on it from its local list
  try{ await fn("notify",{notify_key:nk, from:deviceId(), title:"Gizleme",
    body: kind==="msg" ? t("New message") : kind==="call" ? t("Incoming call") : kind==="missed" ? t("Missed call") : t("A contact wants to chat"),
    kind: kind==="msg"?"msg":kind==="call"?"call":kind==="missed"?"missed":"chat", url:CANONICAL+"/#n="+encodeURIComponent(nk), from_acct:_acct||undefined,
    tag: (kind==="call"||kind==="missed") ? "c"+nk.slice(0,11) : undefined}); return true; }catch(e){ return false; }   // a call's alerts replace one another (and the missed-call one replaces them)
}
async function nudgeContact(){           // manual "notify this contact" from the chat
  const R=A(); if(!R||!R.fromContact) return;
  const sent=await notifyPeer(R.fromContact);
  toast(sent?t("Notification sent 📣"):t("Already notified — give them a moment"));
}
async function pushInit(){               // restore subscription on load
  if(!pushOn()||!pushSupported()) { updateNotifyUI(); return; }
  try{ const reg=await navigator.serviceWorker.ready; gPushSub=await reg.pushManager.getSubscription();
    if(gPushSub) await registerAllContacts(); }catch(e){}
  updateNotifyUI();
}
function updateNotifyUI(){
  const on=pushOn(), sup=pushSupported();
  const st=$("notifyState"), tg=$("notifyToggle"), hint=$("notifyHint");
  if(st) st.textContent = !sup ? t("Not available on this browser") : (on?t("On"):t("Off"));
  if(tg){ tg.textContent = on?t("Turn off"):t("Enable"); tg.classList.toggle("off",on); tg.disabled=!sup; tg.style.opacity=sup?"1":".5"; }
  if(hint){ const iOS=/iphone|ipad|ipod/i.test(navigator.userAgent);
    hint.textContent = (iOS && !window.navigator.standalone) ? t("On iPhone, install Gizleme to your Home Screen first.") : ""; }
}

// ---------- master key: one history key, unlockable by PIN and/or Face ID ----------
const LS_MKPIN="gz-mkpin", LS_MKBIO="gz-mkbio";
function pinSet(){ try{ return !!localStorage.getItem(LS_MKPIN); }catch(e){ return false; } }
function bioSet(){ try{ return !!localStorage.getItem(LS_MKBIO); }catch(e){ return false; } }
function bioSupported(){ return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create); }
function bioLabel(){ return /iPhone|iPad|iPod|Macintosh/i.test(navigator.userAgent) ? "Face ID / Touch ID" : "fingerprint or face"; }
let _isInApp=null;   // set by init (needs the standalone check); showAuth reads it
async function histKeyFromMK(mk){ return crypto.subtle.importKey("raw", mk, {name:"AES-GCM"}, false, ["encrypt","decrypt"]); }
async function pinWrapKey(pin, salt){ const base=await crypto.subtle.importKey("raw", enc.encode(pin), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({name:"PBKDF2", salt, iterations:200000, hash:"SHA-256"}, base, {name:"AES-GCM", length:256}, false, ["encrypt","decrypt"]); }
async function setupPin(pin){  // new master key wrapped by PIN
  const mk=crypto.getRandomValues(new Uint8Array(32)), salt=crypto.getRandomValues(new Uint8Array(16)), iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv}, await pinWrapKey(pin,salt), mk);
  try{ localStorage.setItem(LS_MKPIN, JSON.stringify({salt:b64(salt), iv:b64(iv), ct:b64(ct)})); }catch(e){}
  return mk;
}
async function unlockPin(pin){  // -> master key, throws if wrong PIN
  const rec=JSON.parse(localStorage.getItem(LS_MKPIN));
  const mk=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(rec.iv)}, await pinWrapKey(pin, unb64(rec.salt)), unb64(rec.ct));
  return new Uint8Array(mk);
}
async function bioPrfKey(credId, prfSalt){  // WebAuthn assertion -> AES key from PRF (prompts Face ID / Touch ID)
  const a=await navigator.credentials.get({ publicKey:{
    challenge:crypto.getRandomValues(new Uint8Array(32)), rpId:location.hostname,
    allowCredentials:[{ type:"public-key", id:credId }], userVerification:"required", timeout:60000,
    extensions:{ prf:{ eval:{ first:prfSalt } } } }});
  const r=a.getClientExtensionResults(); const prf=r&&r.prf&&r.prf.results&&r.prf.results.first;
  if(!prf) throw new Error("Face ID not available on this device/browser");
  return crypto.subtle.importKey("raw", new Uint8Array(prf), {name:"AES-GCM"}, false, ["encrypt","decrypt"]);
}
async function bioEnrollWrap(mk){  // create passkey, wrap SAME master key with its PRF key
  const prfSalt=crypto.getRandomValues(new Uint8Array(32));
  const cred=await navigator.credentials.create({ publicKey:{
    challenge:crypto.getRandomValues(new Uint8Array(32)),
    rp:{ name:"Gizleme", id:location.hostname },
    user:{ id:crypto.getRandomValues(new Uint8Array(16)), name:"gizleme", displayName:"Gizleme" },
    pubKeyCredParams:[{type:"public-key",alg:-7},{type:"public-key",alg:-257}],
    authenticatorSelection:{ authenticatorAttachment:"platform", userVerification:"required", residentKey:"preferred" },
    timeout:60000, extensions:{ prf:{} } }});
  const credId=new Uint8Array(cred.rawId);
  const k=await bioPrfKey(credId, prfSalt);
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv}, k, mk);
  try{ localStorage.setItem(LS_MKBIO, JSON.stringify({c:b64(credId), s:b64(prfSalt), iv:b64(iv), ct:b64(ct)})); }catch(e){}
}
async function bioUnlock(){  // -> master key via Face ID
  const rec=JSON.parse(localStorage.getItem(LS_MKBIO));
  const k=await bioPrfKey(unb64(rec.c), unb64(rec.s));
  const mk=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(rec.iv)}, k, unb64(rec.ct));
  return new Uint8Array(mk);
}

let _db=null, _dbClosed=false, _dbP=null;   // one connection, opened once (concurrent callers share the open); closed for good at log-out
function idb(){ if(_dbClosed) return Promise.reject(new Error("db closed")); if(_db) return Promise.resolve(_db); if(_dbP) return _dbP;
  _dbP=new Promise((res,rej)=>{
    const r=indexedDB.open("vesper",2);
    r.onupgradeneeded=()=>{ const db=r.result; if(!db.objectStoreNames.contains("msgs")){ const os=db.createObjectStore("msgs",{keyPath:"id",autoIncrement:true}); os.createIndex("room","room"); }
      if(!db.objectStoreNames.contains("media")){ const ms=db.createObjectStore("media",{keyPath:"mid"}); ms.createIndex("room","room"); } };
    r.onsuccess=()=>{ const db=r.result; if(_dbClosed){ try{ db.close(); }catch(e){} return rej(new Error("db closed")); }
      db.onversionchange=()=>{ try{ db.close(); }catch(e){} if(_db===db) _db=null; };   // never block a delete
      _db=db; res(db); };
    r.onerror=()=>rej(r.error); r.onblocked=()=>rej(new Error("db blocked"));
  }).finally(()=>{ _dbP=null; });
  return _dbP; }
// Saved history and per-chat settings are keyed by a stable id: the contact key for 1:1 contact chats
// (their live room code rotates daily and would otherwise hide yesterday's messages), the rid for groups.
function histKeyOf(R){ return R && R.fromContact ? ckHistKey(R.fromContact) : (R?R.code:""); }
async function histSave(room, rec){ // rec = {dir, env, ts}
  if(!gHistKey) return;
  try{ room=await histKeyAsync(room);
    const {iv,ct}=await aesEnc(gHistKey, enc.encode(JSON.stringify(rec)));
    const db=await idb(); const tx=db.transaction("msgs","readwrite");
    tx.objectStore("msgs").add({room,iv,ct,ts:rec.ts||Date.now()});
    tx.oncomplete=()=>refreshPreviews();          // the chats list shows the latest message
  }catch(e){}
}
// Media (voice messages) fetched once from the relay, then kept here — encrypted under the same master key
// as the history — so they replay without the server (the blob is deleted from the relay after the fetch).
async function mediaPut(room, mid, bytes, ts){
  if(!gHistKey||!mid) return;
  try{ room=await histKeyAsync(room); const {iv,ct}=await aesEnc(gHistKey, bytes);
    const db=await idb(); db.transaction("media","readwrite").objectStore("media").put({mid,room,iv,ct,ts:ts||Date.now()}); }catch(e){}
}
async function mediaGet(mid){
  if(!gHistKey||!mid) return null;
  try{ const db=await idb(); const rec=await new Promise((res,rej)=>{ const rq=db.transaction("media").objectStore("media").get(mid); rq.onsuccess=()=>res(rq.result||null); rq.onerror=()=>rej(rq.error); });
    if(!rec) return null; return new Uint8Array(await aesDec(gHistKey,rec.iv,rec.ct)); }catch(e){ return null; }
}
function histSweep(room, cutoff){ // delete saved records older than cutoff (ms epoch)
  try{ histKeyAsync(room).then(rm=>{ room=rm; return idb(); }).then(db=>{ const tx=db.transaction(["msgs","media"],"readwrite");
    for(const st of ["msgs","media"]){ const idx=tx.objectStore(st).index("room");
      const rq=idx.openCursor(IDBKeyRange.only(room)); rq.onsuccess=e=>{ const c=e.target.result; if(!c) return;
        if((c.value.ts||0) && c.value.ts<=cutoff) c.delete(); c.continue(); }; } }); }catch(e){}
}
// Last saved message of a chat (one reverse cursor step + one decrypt) — for the conversation list preview.
async function histLast(room){
  if(!gHistKey||!room) return null;
  try{ room=await histKeyAsync(room); const db=await idb();
    // the last records, newest first (a few, since reactions are skipped: they are not what the list should show)
    const recs=await new Promise((res,rej)=>{ const out=[]; const idx=db.transaction("msgs").objectStore("msgs").index("room");
      const rq=idx.openCursor(IDBKeyRange.only(room),"prev"); rq.onsuccess=e=>{ const c=e.target.result; if(!c || out.length>=25){ res(out); return; } out.push(c.value); c.continue(); }; rq.onerror=()=>rej(rq.error); });
    const ed={};
    for(const rec of recs){ const r=JSON.parse(dec.decode(await aesDec(gHistKey,rec.iv,rec.ct))); if(r && r.env && (r.env.t==="react" || r.env.t==="exp" || r.env.t==="vote")) continue;
      if(r && r.env && r.env.t==="edit"){ if(editValid(r.env) && !ed[r.env.m]) ed[r.env.m]=r.env.x; continue; }   // newest first: the first edit seen is the latest
      r.ts=r.ts||rec.ts||0; if(r.mid && ed[r.mid] && r.env && (!r.env.t || r.env.t==="txt")) r.env=Object.assign({},r.env,{body:ed[r.mid]}); return r; }
    return null;
  }catch(e){ return null; }
}
// Preview cache for the chats list: key -> {text, ts, dir}. Refreshed in the background after each render.
const _prev={}; let _prevT=null;
function previewKeyOf(it){ return it.t==="g" ? it.rid : ckHistKey(it.ck); }   // the same key history and unread counts use
function previewText(r, isGroup){
  if(!r) return "";
  if(r.env && r.env.t==="gone") return r.dir==="sent" ? t("🚫 You deleted this message") : (isGroup && r.who ? r.who+": " : "")+t("🚫 This message was deleted");
  const body = r.env && r.env.t==="img" ? t("📷 Photo") : r.env && r.env.t==="aud" ? t("🎤 Voice message") : r.env && r.env.t==="loc" ? t("📍 Location") : r.env && r.env.t==="ginv" ? t("👥 Group invitation") : (r.env && r.env.body) || "";
  if(r.dir==="sent") return t("You: ")+body;
  return (isGroup && r.who ? r.who+": " : "") + body;
}
function fmtListTime(ts){
  if(!ts) return ""; const d=new Date(ts), now=new Date();
  const sameDay=d.toDateString()===now.toDateString();
  if(sameDay) return d.toLocaleTimeString(LOC(), {hour:"2-digit", minute:"2-digit"});
  const y=new Date(now); y.setDate(now.getDate()-1); if(d.toDateString()===y.toDateString()) return t("Yesterday");
  if(now-d < 6*86400e3) return d.toLocaleDateString(LOC(), {weekday:"short"});
  return d.toLocaleDateString(LOC(), {day:"2-digit", month:"2-digit", year:"2-digit"});
}
function refreshPreviews(){           // debounced; re-renders the list only if a preview changed
  clearTimeout(_prevT); _prevT=setTimeout(async()=>{
    if(!gHistKey) return;
    const items=groupsLoad().map(g=>({t:"g",rid:g.rid})).concat(contactsLoad().map(c=>({t:"c",ck:c.ck,hk:c.hk})));
    let changed=false;
    for(const it of items){ const k=previewKeyOf(it); const r=await histLast(k);
      const dur=expFor(k); if(r && dur && (r.ts||0)<=Date.now()-dur){ if(_prev[k]){ delete _prev[k]; changed=true; } continue; }   // expired: no preview
      const nx=r?{text:previewText(r,it.t==="g"),ts:r.ts||0,dir:r.dir,ui:!!(r.env && r.env.t && r.env.t!=="txt")}:null; const old=_prev[k];
      if((nx&&!old)||(!nx&&old)||(nx&&old&&(nx.text!==old.text||nx.ts!==old.ts))){ if(nx) _prev[k]=nx; else delete _prev[k]; changed=true; } }
    if(changed) renderContacts(true);
  }, 120);
}
async function histLoad(room){
  if(!gHistKey) return [];
  try{ room=await histKeyAsync(room);
    const db=await idb();
    const recs=await new Promise((res,rej)=>{ const out=[]; const idx=db.transaction("msgs").objectStore("msgs").index("room");
      const rq=idx.openCursor(IDBKeyRange.only(room)); rq.onsuccess=e=>{ const c=e.target.result; if(c){ out.push(c.value); c.continue(); } else res(out); }; rq.onerror=()=>rej(rq.error); });
    const out=[];
    for(const r of recs){ try{ const pt=await aesDec(gHistKey,r.iv,r.ct); const o=JSON.parse(dec.decode(pt)); if(!o.ts) o.ts=r.ts||0; out.push(o); }catch(e){} }
    out.sort((a,b)=>(a.ts||0)-(b.ts||0));      // stable: same-moment records keep their order
    return out;
  }catch(e){ return []; }
}

// ---------- media (encrypted blobs in Supabase Storage) ----------
// Photos are re-encoded on the device before encryption: at most 1600px, JPEG, and small enough for the
// relay's 2 MB cap. Formats only some phones can show (HEIC from iPhones) always become JPEG so the other
// side can open them. Small JPEG/PNG/WebP/GIF files are sent as they are.
const BLOB_MAX = 1800000;                             // the relay refuses raw blobs above 2 000 000 bytes
const WEB_IMG = {"image/jpeg":1,"image/png":1,"image/webp":1,"image/gif":1};
async function decodeImage(file){
  try{ return await createImageBitmap(file, {imageOrientation:"from-image"}); }catch(e){}
  try{ return await createImageBitmap(file); }catch(e){}
  const url=URL.createObjectURL(file);                 // last resort: the <img> decoder (HEIC on Safari)
  try{ return await new Promise((res,rej)=>{ const im=new Image(); im.onload=()=>res(im); im.onerror=()=>rej(new Error("decode")); im.src=url; }); }
  finally{ setTimeout(()=>URL.revokeObjectURL(url),30000); }
}
async function downscale(file){
  // every photo is re-encoded from decoded pixels, even a small one: EXIF (GPS position, camera, date) is
  // never sent. PNG stays PNG (transparency), everything else becomes JPEG.
  let img; try{ img=await decodeImage(file); }catch(e){ throw new Error(t("unsupported image")); }
  const w=img.naturalWidth||img.width, h=img.naturalHeight||img.height;
  const png=file.type==="image/png" && file.size<500000;
  let max=1600, q=0.82, blob=null;
  for(let attempt=0; attempt<5; attempt++){                     // shrink until it fits
    const scale=Math.min(1, max/Math.max(w,h));
    const c=document.createElement("canvas"); c.width=Math.max(1,Math.round(w*scale)); c.height=Math.max(1,Math.round(h*scale));
    c.getContext("2d").drawImage(img,0,0,c.width,c.height);
    blob=await new Promise(r=>c.toBlob(r, png?"image/png":"image/jpeg", q));
    if(!blob) break;
    if(blob.size<=BLOB_MAX) break;
    q=Math.max(0.5,q-0.12); max=Math.round(max*0.8);
  }
  if(img.close) try{ img.close(); }catch(e){}
  if(!blob) throw new Error(t("unsupported image"));
  if(blob.size>BLOB_MAX) throw new Error(t("photo too large"));
  return blob;
}
async function uploadImage(file){
  const small = await downscale(file);
  const mime = small.type || "image/jpeg";
  const bytes = new Uint8Array(await small.arrayBuffer());
  const meta = await uploadBytes(bytes, "photo"); meta.mime = mime;
  Object.defineProperty(meta, "_bytes", {value:bytes, enumerable:false});   // kept on this device for a kept photo; never sent
  return meta;
}
// Any media: encrypted on the device under a fresh random key that only ever travels inside the message.
async function uploadBytes(bytes, what){
  const key = crypto.getRandomValues(new Uint8Array(32));
  const ck = await aesKey(key);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ctBuf = await crypto.subtle.encrypt({name:"AES-GCM",iv}, ck, bytes);
  // The relay names the object with a random id (nothing about the chat in the path) and is the only
  // writer of the bucket; the AES key never leaves the message.
  const r = await mboxFn("putblob",{data:b64(ctBuf)});
  const path = r && r.data && r.data.ok && r.data.path;
  if(!path){ const code=(r&&r.data&&r.data.error)||(r&&r.error&&r.error.context&&r.error.context.status)||"";
    throw new Error(code==="rate_limited"||code===429 ? (what==="voice"?t("too many voice messages — wait a minute"):t("too many photos — wait a minute")) : code==="too_big"||code===413 ? (what==="voice"?t("voice message too long"):t("photo too large")) : t("upload failed")); }
  return { path, k:b64(key), iv:b64(iv) };
}
async function fetchBytes(meta){ // meta={path,k,iv} -> decrypted bytes
  const { data } = client.storage.from(BUCKET).getPublicUrl(meta.path);
  const resp = await fetch(data.publicUrl, {cache:"no-store"});
  if(!resp.ok) throw new Error("gone");
  const ctBuf = await resp.arrayBuffer();
  const ck = await aesKey(unb64(meta.k));
  return new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(meta.iv)}, ck, ctBuf));
}
function validImg(m){ return !!(m && typeof m.path==="string" && (/^[a-f0-9]{48}\.bin$/.test(m.path) || /^[A-Za-z0-9]{1,40}\/[a-f0-9]{16}\.bin$/.test(m.path)) && typeof m.k==="string" && m.k.length===44 && typeof m.iv==="string" && m.iv.length===16); }
async function fetchImage(meta){ // meta={path,k,iv,mime}
  if(!validImg(meta)) throw new Error("bad");
  const plain = await fetchBytes(meta);
  return URL.createObjectURL(new Blob([plain], {type:meta.mime||"image/jpeg"}));
}

// ---------- voice messages ----------
// One small, self-contained codec on both ends (IMA ADPCM, 16 kHz mono, 4 bits/sample ≈ 8 kB/s): the same
// bytes decode everywhere, so no browser-specific container or codec ever matters. The audio is treated
// exactly like a photo — encrypted on the device under a key that only travels inside the message.
const VOICE_RATE=16000, VOICE_MAX_S=120, VOICE_MAGIC=[71,90,65,49];   // "GZA1"
const IMA_STEP=[7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767];
const IMA_IDX=[-1,-1,-1,-1,2,4,6,8];
function adpcmEncode(pcm){ let pred=0, idx=0; const out=new Uint8Array((pcm.length+1)>>1);
  for(let i=0;i<pcm.length;i++){ const step=IMA_STEP[idx]; let diff=pcm[i]-pred, code=0; if(diff<0){ code=8; diff=-diff; }
    let d=step>>3; if(diff>=step){ code|=4; diff-=step; d+=step; } if(diff>=(step>>1)){ code|=2; diff-=step>>1; d+=step>>1; } if(diff>=(step>>2)){ code|=1; d+=step>>2; }
    pred+=(code&8)?-d:d; if(pred>32767) pred=32767; else if(pred<-32768) pred=-32768;
    idx+=IMA_IDX[code&7]; if(idx<0) idx=0; else if(idx>88) idx=88;
    if(i&1) out[i>>1]|=code<<4; else out[i>>1]=code; }
  return out; }
function adpcmDecode(data, n){ let pred=0, idx=0; const out=new Float32Array(n);
  for(let i=0;i<n;i++){ const code=(i&1)?(data[i>>1]>>4)&15:data[i>>1]&15; const step=IMA_STEP[idx];
    let d=step>>3; if(code&4) d+=step; if(code&2) d+=step>>1; if(code&1) d+=step>>2;
    pred+=(code&8)?-d:d; if(pred>32767) pred=32767; else if(pred<-32768) pred=-32768;
    idx+=IMA_IDX[code&7]; if(idx<0) idx=0; else if(idx>88) idx=88; out[i]=pred/32768; }
  return out; }
function voicePack(pcm16){ const body=adpcmEncode(pcm16); const out=new Uint8Array(10+body.length); out.set(VOICE_MAGIC,0);
  new DataView(out.buffer).setUint16(4,VOICE_RATE,true); new DataView(out.buffer).setUint32(6,pcm16.length,true); out.set(body,10); return out; }
function voiceUnpack(bytes){ if(!bytes || bytes.length<10 || VOICE_MAGIC.some((b,i)=>bytes[i]!==b)) return null;
  const dv=new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength); const rate=dv.getUint16(4,true), n=dv.getUint32(6,true);
  if(rate<8000||rate>48000||n>rate*(VOICE_MAX_S+5)||((n+1)>>1)>bytes.length-10) return null;
  return { rate, samples: adpcmDecode(bytes.subarray(10), n) }; }
// Capture-rate float samples -> 16 kHz 16-bit (box low-pass + linear pick: plenty for speech)
function voiceDownsample(chunks, srcRate){
  let n=0; for(const c of chunks) n+=c.length; const src=new Float32Array(n); let o=0; for(const c of chunks){ src.set(c,o); o+=c.length; }
  const r=srcRate/VOICE_RATE, w=Math.max(1,Math.round(r)), m=Math.floor(n/r); const out=new Int16Array(m);
  for(let j=0;j<m;j++){ const p=Math.floor(j*r); let acc=0, k=0; for(let i=p;i<p+w&&i<n;i++){ acc+=src[i]; k++; }
    let v=k?acc/k:0; v=Math.max(-1,Math.min(1,v)); out[j]=v<0?v*32768:v*32767; }
  return out; }
let rec=null;   // {stream, src, proc, gain, chunks, t0, timer, rate}
function fmtSec(sec){ sec=Math.max(0,Math.round(sec)); return Math.floor(sec/60)+":"+String(sec%60).padStart(2,"0"); }
async function startRec(){
  const R=A(); if(!R || rec) return; if(!R.group && !R.fromContact && !R.paired) return;
  if(!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)){ toast(t("Voice messages aren't available in this browser")); return; }
  if(call){ toast(t("You're in a call")); return; }
  // a context of its own, created inside the tap (autoplay rules) and closed after: on iOS the hardware
  // rate can change when the mic opens, and a fresh context is the one that reports it correctly
  let ctx; try{ ctx=new (window.AudioContext||window.webkitAudioContext)(); if(ctx.state!=="running") ctx.resume().catch(()=>{}); }catch(e){ toast(t("Voice messages aren't available in this browser")); return; }
  let stream; try{ stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}}); }
  catch(e){ try{ ctx.close(); }catch(_e){} toast(mediaErr(e)); return; }
  if(rec){ try{ stream.getTracks().forEach(tr=>tr.stop()); ctx.close(); }catch(e){} return; }   // a second tap raced the first
  try{ if(ctx.state!=="running") await ctx.resume(); }catch(e){}
  const src=ctx.createMediaStreamSource(stream); const proc=ctx.createScriptProcessor(4096,1,1); const gain=ctx.createGain(); gain.gain.value=0;
  const chunks=[]; proc.onaudioprocess=e=>{ if(rec && rec.proc===proc) chunks.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
  src.connect(proc); proc.connect(gain); gain.connect(ctx.destination);   // silent sink: the processor only runs when connected
  rec={stream, ctx, src, proc, gain, chunks, t0:Date.now(), rate:ctx.sampleRate, timer:null};
  const comp=document.querySelector(".composer"); if(comp) comp.classList.add("rec"); $("recBar").hidden=false;
  rec.timer=setInterval(()=>{ if(!rec) return; typingTick("v"); if((Date.now()-rec.t0)/1000>=VOICE_MAX_S) stopRec(true); },250);   // 2-minute cap; "recording…" for the others
  typingTick("v");
}
function recTeardown(){ const r=rec; rec=null; if(!r) return null; clearInterval(r.timer);
  r.rate=r.ctx.sampleRate;   // read at the end: the rate the samples were really captured at
  try{ r.proc.onaudioprocess=null; r.src.disconnect(); r.proc.disconnect(); r.gain.disconnect(); }catch(e){} try{ r.stream.getTracks().forEach(tr=>tr.stop()); }catch(e){} try{ r.ctx.close(); }catch(e){}
  const comp=document.querySelector(".composer"); if(comp) comp.classList.remove("rec"); $("recBar").hidden=true;
  typingTick(""); return r; }   // "recording…" ends with the recording
async function stopRec(send){
  const r=recTeardown(); if(!r) return; if(!send) return;
  const dur=(Date.now()-r.t0)/1000; if(dur<0.6){ toast(t("Too short — hold on a little longer")); return; }
  const pcm=voiceDownsample(r.chunks, r.rate); if(!pcm.length){ toast(t("Nothing was recorded — check the microphone")); return; }
  await sendVoice(voicePack(pcm), Math.min(dur, pcm.length/VOICE_RATE));
}
function validAud(env){ return env && env.t==="aud" && typeof env.path==="string" && /^[a-f0-9]{48}\.bin$/.test(env.path) && typeof env.k==="string" && env.k.length===44 && typeof env.iv==="string" && env.iv.length===16 && typeof env.dur==="number" && env.dur>0 && env.dur<=VOICE_MAX_S+1; }
async function sendVoice(bytes, dur){
  const R=A(); if(!R||!bytes) return; if(!R.group && !R.fromContact && !R.paired) return;
  const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid); const now=Date.now();
  const env0={t:"aud",dur:Math.round(dur*10)/10};
  const el=addVoice(R.logEl,"sent",env0,"",now,{mid,st:"pending",bytes});
  mediaPut(histKeyOf(R), mid, bytes, now);
  const go=async()=>{ try{ const meta=await uploadBytes(bytes,"voice"); const env={t:"aud",path:meta.path,k:meta.k,iv:meta.iv,dur:env0.dur}; await deliverOut(R, env, mid, el, now); }
    catch(e){ setMsgState(el,"failed"); el._retry=()=>{ el._retry=null; setMsgState(el,"pending"); go(); }; toast(t("Voice message not sent — ")+(e&&e.message?e.message:t("check your connection"))); } };
  await go();
}
let _vplay=null;   // {src, el, raf}
function vbtnState(b, st){ b.dataset.st=st; b.textContent=""; b.appendChild(icoEl(st==="pause"?"i-pause":"i-play","")); b.setAttribute("aria-label", st==="pause" ? t("Pause") : t("Play voice message")); }
function voiceStop(){ const v=_vplay; _vplay=null; if(!v) return; try{ v.src.onended=null; v.src.stop(); }catch(e){} cancelAnimationFrame(v.raf); vbtnState(v.btn,"play"); v.fill.style.width="0%"; v.dur.textContent=fmtSec(v.total);
  try{ const as=navigator.audioSession; if(as && as.type==="playback") as.type="auto"; }catch(e){} }
async function voicePlay(st){
  if(_vplay && _vplay.el===st.el){ voiceStop(); return; }
  voiceStop(); await initAudio(); if(!audioCtx) return;
  // on iPhone the "playback" session keeps the message audible with the silent switch on; handed back when it stops
  try{ const as=navigator.audioSession; if(as && as.type!=="playback") as.type="playback"; }catch(e){}
  const buf=audioCtx.createBuffer(1, st.pcm.samples.length, st.pcm.rate); buf.getChannelData(0).set(st.pcm.samples);
  const src=audioCtx.createBufferSource(); src.buffer=buf; src.connect(audioCtx.destination);
  const total=buf.duration, full=st.full||total, off=st.off||0, t0=audioCtx.currentTime;   // after a seek: what plays is the tail, the bar and the length show the whole
  const v={src, el:st.el, btn:st.btn, fill:st.fill, dur:st.durEl, total:full, raf:0}; _vplay=v;
  vbtnState(st.btn,"pause");
  const tick=()=>{ if(_vplay!==v) return; const p=off+(1-off)*Math.min(1,(audioCtx.currentTime-t0)/total); v.fill.style.width=(p*100).toFixed(1)+"%"; v.dur.textContent=fmtSec(full*(1-p)); v.raf=requestAnimationFrame(tick); };
  src.onended=()=>{ if(_vplay===v) voiceStop(); }; src.start(); v.raf=requestAnimationFrame(tick);
}
// Bubble: ▶ + progress + length. The bytes come from memory (just recorded), from the local media store
// (played before), or — the first time — from the relay (which deletes the blob after 14 days; the key only
// ever travels inside the message).
function addVoice(logEl, cls, env, tag, ts, opts){
  opts=opts||{}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble "+cls+" voice"; d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  if(tag) d.appendChild(whoEl(tag, opts&&opts.vf));
  const row=document.createElement("div"); row.className="vc";
  const btn=document.createElement("button"); btn.className="vbtn"; btn.type="button"; vbtnState(btn,"play");
  const bar=document.createElement("div"); bar.className="vbar"; const fill=document.createElement("div"); fill.className="vfill"; bar.appendChild(fill);
  const durEl=document.createElement("span"); durEl.className="vdur"; durEl.textContent=fmtSec(env.dur||0);
  row.appendChild(btn); row.appendChild(bar); row.appendChild(durEl); d.appendChild(row);
  metaRow(d, ts, cls==="sent"?(opts.st||"pending"):null);
  const st={el:d, btn, fill, durEl, pcm:null, bytes:opts.bytes||null, busy:false};
  btn.addEventListener("click", async()=>{
    if(st.busy) return; initAudio();   // inside the tap: iOS only unlocks audio in a user gesture
    if(!st.pcm){ st.busy=true; btn.disabled=true; durEl.textContent="…";
      try{ let bytes=st.bytes || await mediaGet(opts.mid);
        if(!bytes){ if(!validAud(env)) throw new Error("bad"); bytes=await fetchBytes(env); await mediaPut(opts.room||"", opts.mid, bytes, ts); }   // the relay keeps the blob for its 14 days: the other members / your other devices fetch it too
        const pcm=voiceUnpack(bytes); if(!pcm) throw new Error("bad"); st.pcm=pcm; st.bytes=null; durEl.textContent=fmtSec(pcm.samples.length/pcm.rate);
      }catch(e){ st.busy=false; btn.disabled=false; durEl.textContent=fmtSec(env.dur||0); toast(e&&e.message==="gone"?t("This voice message has expired"):t("Couldn't play this voice message")); return; }
      st.busy=false; btn.disabled=false; }
    voicePlay(st);
  });
  bar.addEventListener("click", e=>{ if(!_vplay || _vplay.el!==d || !st.pcm) return; const r=bar.getBoundingClientRect(); const p=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
    voiceStop(); const n=Math.floor(p*st.pcm.samples.length); const cut={rate:st.pcm.rate, samples:st.pcm.samples.subarray(n)}; voicePlay({el:d,btn,fill,durEl,pcm:cut, off:p, full:st.pcm.samples.length/st.pcm.rate}); });
  d.addEventListener("click",e=>{ if(e.target===btn||e.target===bar||e.target===fill) return; if(d.classList.contains("failed") && d._retry) d._retry(); });
  logEl.appendChild(d); scrollEl(logEl, cls==="sent");
  return d;
}

// ---------- animations ----------
function scramble(el,final,done){
  if(matchMedia("(prefers-reduced-motion:reduce)").matches||!final){ el.textContent=final; done&&done(); return; }
  const chars=[...final], n=chars.length, total=Math.min(1600,420+n*30), start=performance.now();
  (function tick(now){ const t=Math.min(1,(now-start)/total), rev=Math.floor(t*n); let o="";
    for(let i=0;i<n;i++) o += chars[i]===" "?" ":(i<rev?chars[i]:GLYPHS[(Math.random()*GLYPHS.length)|0]);
    el.textContent=o; if(t<1) requestAnimationFrame(tick); else { el.textContent=final; done&&done(); } })(start);
}

// ---------- UI ----------
let audioCtx=null;
function initAudio(){ try{ if(!audioCtx) audioCtx=new (window.AudioContext||window.webkitAudioContext)(); if(audioCtx.state!=="running") return audioCtx.resume(); }catch(e){} return Promise.resolve(); }
// What may make a sound: "all" (messages and calls, the default) | "calls" (messages are silent, a call still
// rings) | "none". The former on/off switch maps onto it: "off" used to keep the ringtone, so it means "calls".
const LS_SOUNDS="gz-sounds";
function soundMode(){ try{ const v=localStorage.getItem(LS_SOUNDS); if(v==="all"||v==="calls"||v==="none") return v;
  return localStorage.getItem("vesper-sound")==="off" ? "calls" : "all"; }catch(e){ return "all"; } }
function setSoundMode(m){ if(m!=="all"&&m!=="calls"&&m!=="none") return; try{ localStorage.setItem(LS_SOUNDS,m); localStorage.removeItem("vesper-sound"); }catch(e){} }
function soundAllowed(kind){ if(kind==="preview") return true; const m=soundMode(); return m==="all" || (m==="calls" && kind==="call"); }
// A small synthetic hall for the bell tones (stereo noise with an exponential decay, built once per audio
// context): the signature chime rings like an announcement in a station concourse. Dry if anything is missing.
let _hall=null;
function hallOf(ctx){
  if(_hall && _hall.ctx===ctx) return _hall.node;
  const sr=ctx.sampleRate, n=Math.floor(sr*1.9), b=ctx.createBuffer(2,n,sr);
  for(let ch=0;ch<2;ch++){ const d=b.getChannelData(ch); let lp=0, s=ch?7919:104729;
    for(let i=0;i<n;i++){ s=(s*16807)%2147483647; const w=s/1073741823.5-1; lp+=.32*(w-lp); const t=i/sr;
      d[i]=lp*Math.exp(-t/.46)*(t<.018?t/.018:1)*(t>1.5?.5+.5*Math.cos(Math.PI*(t-1.5)/.4):1); } }
  const cv=ctx.createConvolver(); cv.buffer=b; cv.connect(ctx.destination); _hall={ctx,node:cv}; return cv;
}
// seq: notes {f, t0, dur, gain, type?, a? (attack, s)}; kind: "msg" | "call" | "preview"; wet: hall level (0 = dry)
function beep(seq, kind, wet){ if(!audioCtx || !soundAllowed(kind||"msg")) return; const ctx=audioCtx, now=ctx.currentTime;
  const out=ctx.createGain(); out.connect(ctx.destination);
  if(wet){ try{ const wg=ctx.createGain(); wg.gain.value=wet; out.connect(wg); wg.connect(hallOf(ctx)); }catch(e){} }
  seq.forEach(n=>{ const o=ctx.createOscillator(), g=ctx.createGain(); o.type=n.type||"sine"; o.frequency.value=n.f;
    g.gain.setValueAtTime(0, now+n.t0); g.gain.linearRampToValueAtTime(n.gain||0.06, now+n.t0+(n.a||0.012));
    g.gain.exponentialRampToValueAtTime(0.0001, now+n.t0+n.dur); o.connect(g).connect(out);
    o.start(now+n.t0); o.stop(now+n.t0+n.dur+0.03); }); }
// Bell notes: each partial [ratio, relative gain, relative length] rings and fades on its own.
const BELL={
  warm:  [[1,1,1],[1.0018,.38,.92],[2,.24,.46],[3,.08,.24],[4.16,.05,.10]],
  glass: [[1,1,1],[1.0012,.25,.9],[2.76,.30,.34],[5.40,.10,.16],[8.93,.035,.07]],
  soft:  [[1,1,1],[1.0026,.50,.96],[2,.13,.42],[3,.03,.20]],
};
function bell(f,t0,gain,len,kind){ return BELL[kind].map(([r,g,l])=>({f:f*r,t0,dur:len*l,gain:gain*g,a:.004})); }
// Message tones, all synthesized (no audio files, works offline). "gizleme" is the signature chime — three
// notes of glass bells in a small hall, one per syllable, Giz·le·me — and the default; "classic" is the original.
const LS_TONE="gz-tone";
const TONES={
  gizleme:[...bell(1318.51,0,.026,1.0,"glass"), ...bell(987.77,.16,.026,1.0,"glass"), ...bell(1661.22,.32,.022,1.4,"glass")],
  classic:[{f:783.99,t0:0,dur:0.18,gain:0.042},{f:587.33,t0:0.07,dur:0.26,gain:0.040},{f:392.00,t0:0.07,dur:0.30,gain:0.016}],
  pop:    [{f:659.25,t0:0,dur:0.07,gain:0.05,type:"triangle"},{f:987.77,t0:0.06,dur:0.12,gain:0.045,type:"triangle"}],
  chime:  [{f:1046.50,t0:0,dur:0.55,gain:0.038},{f:2093.00,t0:0,dur:0.30,gain:0.010},{f:1318.51,t0:0.14,dur:0.50,gain:0.030},{f:1567.98,t0:0.28,dur:0.55,gain:0.022}],
  marimba:[{f:523.25,t0:0,dur:0.16,gain:0.034,type:"triangle"},{f:659.25,t0:0.11,dur:0.16,gain:0.034,type:"triangle"},{f:783.99,t0:0.22,dur:0.24,gain:0.034,type:"triangle"}],
  soft:   [{f:392.00,t0:0,dur:0.38,gain:0.030},{f:523.25,t0:0.16,dur:0.42,gain:0.026}]
};
const TONE_WET={gizleme:.24};
// In the chat you have open, a message gets a small, quiet echo of the chime rather than the whole of it.
const TONE_INCHAT=[...bell(987.77,0,.012,.6,"glass"), ...bell(1661.22,.09,.011,.85,"glass")];
function toneName(){ try{ const v=localStorage.getItem(LS_TONE); return TONES[v]?v:"gizleme"; }catch(e){ return "gizleme"; } }
function setTone(n){ if(!TONES[n]) return; try{ localStorage.setItem(LS_TONE,n); }catch(e){} }
function soundRecv(){ const n=toneName(); beep(TONES[n], "msg", TONE_WET[n]||0); }
// Sound policy: the chime for a message in a chat you are not looking at (or while the app is in the
// background), at most once every few seconds — a mailbox catch-up after a while away rings once; a small
// echo of it in the chat you have open. Nothing when you send, when someone comes online or for a reaction;
// nothing at all for a muted chat. Calls keep their own sounds. Settings → Sounds decides what may ring.
let _toneAt=0, _tickAt=0;
function messageTone(R){
  if(R && isMutedRoom(R)) return;
  const now=Date.now();
  if(R && !R.shadow && R.code===active && !document.hidden){ if(now-_tickAt<1500) return; _tickAt=now; beep(TONE_INCHAT, "msg", .16); return; }
  if(now-_toneAt<4000) return; _toneAt=now; soundRecv();
}
// A message for a chat you are not looking at: its row in the list (and its tab) glows twice, gently.
const PULSE_MS=2600; const _pulse=new Map();   // history key -> when it started
function pulseChat(R){ try{ if(isMutedRoom(R)) return; const k=histKeyOf(R); if(k) _pulse.set(k, Date.now()); R._pulseAt=Date.now(); }catch(e){} }
function pulseAge(at){ const a=at ? Date.now()-at : PULSE_MS; return a<PULSE_MS ? a : -1; }
// Preview from Settings. Must run inside a tap (iOS only unlocks audio in a user gesture) and waits for the
// context to actually be running. On iPhone, Web Audio follows the silent switch; for the preview alone we
// ask for the "playback" session so the chosen tone can be heard even then, and hand the session back after.

// ---------- calls: audio / video over WebRTC ----------
// Media goes peer-to-peer (DTLS-SRTP — encrypted end to end by construction; a TURN relay, when one is
// configured, only forwards ciphertext). Signalling (offers, answers, ICE candidates) travels inside the
// chat's existing encrypted and authenticated channel, so the relay sees nothing about a call but
// ciphertext and the DTLS fingerprints are protected by the same session that protects messages. Groups
// use a mesh (every participant streams to every other) — fine for a few people, capped at CALL_MAX.
const CALL_RING_MS=45000, CALL_MAX=4, TURN_FN="gizleme-turn", CALL_REPUSH_MS=7000;
let call=null;        // the one call this device is in
let _iceCache=null;
async function iceServers(){
  const dflt=[{urls:["stun:stun.cloudflare.com:3478","stun:stun.l.google.com:19302"]}];
  if(_iceCache && _iceCache.exp>Date.now()) return _iceCache.servers;
  try{ const {data}=await client.functions.invoke(TURN_FN,{body:{token:(sessLoad()||{}).token||""}});
    if(data && data.ok && Array.isArray(data.iceServers) && data.iceServers.length){ _iceCache={servers:data.iceServers, exp:Date.now()+Math.max(60,(data.ttl||600)-60)*1000}; return data.iceServers; } }catch(e){}
  return dflt;
}
function callSig(R, env){ if(!R) return Promise.resolve(false); const e=Object.assign({t:"call"},env); return R.group ? broadcastGroup(R, e, rid()) : (R.paired ? broadcast(R, e, rid()) : Promise.resolve(false)); }
function callSend(env){ return call ? callSig(call.R, env) : Promise.resolve(false); }
function callUIShow(on){ $("callUI").hidden=!on; document.body.classList.toggle("in-call",!!on); if(!on){ $("callUI").classList.remove("bare","ringing"); clearTimeout(_bareT); } }
// ---- full screen for video calls ----
// On a phone the call takes the whole screen — the system bars too (Android; an iPhone has no such switch for a
// web page). The ⛶ button does the same on a computer. Asked for inside the tap that starts or accepts the call,
// as browsers require.
let _bareT=null, _fsByCall=false;
function fsActive(){ return !!(document.fullscreenElement || document.webkitFullscreenElement); }
function fsCan(){ const el=document.documentElement; return !!(el.requestFullscreen || el.webkitRequestFullscreen) && (document.fullscreenEnabled!==false); }
function fsEnter(){ try{ if(fsActive() || !fsCan()) return; const el=document.documentElement;
    const p=el.requestFullscreen ? el.requestFullscreen({navigationUI:"hide"}) : el.webkitRequestFullscreen(); _fsByCall=true; if(p && p.catch) p.catch(()=>{ _fsByCall=false; }); }catch(e){} }
function fsExit(){ try{ _fsByCall=false; if(!fsActive()) return; const p=document.exitFullscreen ? document.exitFullscreen() : document.webkitExitFullscreen(); if(p && p.catch) p.catch(()=>{}); }catch(e){} }
function callFsAuto(video){ if(video && TOUCH_UI && !/iphone|ipad|ipod/i.test(navigator.userAgent)) fsEnter(); }
// show the buttons now, and let them fade after 4 s while the other person's picture is on screen
function callChrome(){ const ui=$("callUI"); clearTimeout(_bareT); ui.classList.remove("bare");
  $("callFs").hidden=!(call && call.video && fsCan() && !/iphone|ipad|ipod/i.test(navigator.userAgent));
  if(!call || !call.t1 || !$("callIncoming").hidden) return;
  if(!$("callStage").querySelector(".peer:not(.audio)")) return;
  _bareT=setTimeout(()=>{ if(call && call.t1 && $("callStage").querySelector(".peer:not(.audio)")) ui.classList.add("bare"); }, 4000); }
function callStatus(txt){ const e=$("callStatus"); if(e) e.textContent=txt; }
function fmtDur(ms){ const s=Math.max(0,Math.floor(ms/1000)); return String(Math.floor(s/60)).padStart(2,"0")+":"+String(s%60).padStart(2,"0"); }
function mediaErr(e){ const n=e&&e.name||"";
  if(n==="NotAllowedError"||n==="SecurityError") return t("Microphone / camera access was denied — allow it for gizleme.com in your browser settings");
  if(n==="NotFoundError"||n==="OverconstrainedError") return t("No microphone or camera found");
  if(n==="NotReadableError") return t("The microphone or camera is in use by another app");
  return t("Couldn't start the microphone / camera"); }
async function callMedia(video, facing, hd){
  if(rec) stopRec(false);   // the microphone goes to the call
  const audio={echoCancellation:true,noiseSuppression:true,autoGainControl:true};
  // a two-person call fills the screen: ask for HD; a group mesh sends to several people, so it stays at 640×480
  const v= video ? {facingMode:facing||"user", width:{ideal:hd?1280:640}, height:{ideal:hd?720:480}, frameRate:{ideal:hd?30:24}} : false;
  try{ return await navigator.mediaDevices.getUserMedia({audio, video:v}); }
  catch(e){ if(video){ return navigator.mediaDevices.getUserMedia({audio, video:false}); } throw e; }
}
// ----- ring sounds (synthesized; the ringtone plays even if message sounds are off) -----
let _ringI=null;
function startRing(kind){ stopRing(); const play=()=>{ initAudio();
    if(kind==="tone") beep([{f:659.25,t0:0,dur:.3,gain:.05},{f:880,t0:.35,dur:.3,gain:.05},{f:659.25,t0:.7,dur:.3,gain:.05},{f:880,t0:1.05,dur:.45,gain:.05}], "call");
    else beep([{f:425,t0:0,dur:1.0,gain:.028},{f:450,t0:0,dur:1.0,gain:.022}], "call"); };
  play(); _ringI=setInterval(play, kind==="tone"?2600:3200); }
function stopRing(){ clearInterval(_ringI); _ringI=null; }
function soundEnd(){ beep([{f:523.25,t0:0,dur:.14,gain:.04},{f:392,t0:.15,dur:.24,gain:.04}], "call"); }
// ----- stage (remote participants) -----
function peerEl(pid, name){
  const st=$("callStage"); let d=st.querySelector('[data-pid="'+CSS.escape(pid)+'"]');
  // a two-person call has one picture, whichever of their devices answers: the tile is reused, never doubled
  // (two tiles would split the screen in half)
  if(!d){ d=st.querySelector('[data-pid="?"]') || ((call && !call.group) ? st.querySelector(".peer") : null);
    if(d){ d.dataset.pid=pid; d.querySelector(".pname").textContent=name||""; d.querySelector(".pav").textContent=up((name||"?")[0]||"?"); } }
  if(d && call && !call.group) st.querySelectorAll(".peer").forEach(x=>{ if(x!==d) x.remove(); });
  if(!d){ d=document.createElement("div"); d.className="peer audio"; d.dataset.pid=pid;
    const bg=document.createElement("video"); bg.className="bgv"; bg.autoplay=true; bg.playsInline=true; bg.muted=true; bg.setAttribute("aria-hidden","true"); d.appendChild(bg);
    const v=document.createElement("video"); v.className="mainv"; v.autoplay=true; v.playsInline=true; d.appendChild(v);
    v.addEventListener("loadedmetadata",()=>fitVideo(v)); v.addEventListener("resize",()=>fitVideo(v));
    const av=document.createElement("div"); av.className="pav"; av.textContent=up((name||"?")[0]||"?"); d.appendChild(av);
    if(call && !call.group && call.R){ const c=roomColor(call.R); if(c) av.style.background=c; }
    const nm=document.createElement("div"); nm.className="pname"; nm.textContent=name||""; d.appendChild(nm);
    st.appendChild(d); }
  st.className="call-stage n"+Math.min(4,Math.max(1,st.children.length)); return d;
}
function restage(){ const st=$("callStage"); st.className="call-stage n"+Math.min(4,Math.max(1,st.children.length)); st.querySelectorAll("video.mainv").forEach(fitVideo); }
// The other person's picture fills the whole screen, cropped at the edges as on a phone call app — always on a
// phone or tablet. On a computer, a phone held upright would lose most of the face that way: there it is shown
// whole, over a blurred, enlarged copy of itself that fills the rest of the screen.
const TOUCH_UI = matchMedia("(pointer:coarse)").matches;
function fitVideo(v){ try{ const box=v.parentElement; if(!box || !v.classList.contains("mainv")) return; const vw=v.videoWidth, vh=v.videoHeight; if(!vw||!vh) return;
  const r=box.getBoundingClientRect(); if(!r.width||!r.height) return;
  const va=vw/vh, ba=r.width/r.height; const fit=!TOUCH_UI && ((ba>1.15 && va<0.9) || (ba<0.87 && va>2.0));
  v.classList.toggle("fit", fit); box.classList.toggle("fitted", fit); }catch(e){} }
window.addEventListener("resize",()=>{ if(call) $("callStage").querySelectorAll("video.mainv").forEach(fitVideo); });
async function newPeer(pid, name, initiator){
  if(!call) return null;
  const pc=new RTCPeerConnection({iceServers:await iceServers(), bundlePolicy:"max-bundle"});
  if(!call) { try{ pc.close(); }catch(e){} return null; }
  const P={pid, name, pc, cands:[], remoteSet:false, el:peerEl(pid,name), stream:new MediaStream(), connected:false};
  call.peers.set(pid,P); if(call.early && call.early.has(pid)){ P.cands.push(...call.early.get(pid)); call.early.delete(pid); }
  if(call.local) call.local.getTracks().forEach(tr=>pc.addTrack(tr, call.local));
  pc.onicecandidate=e=>{ if(e.candidate && call) callSend({a:"ice",cid:call.cid,to:pid,from:call.me,cand:e.candidate.toJSON()}); };
  pc.ontrack=e=>{ P.stream.addTrack(e.track); const v=P.el.querySelector("video.mainv"); if(v.srcObject!==P.stream) v.srcObject=P.stream; v.play().catch(()=>{});
    if(e.track.kind==="video"){ const bg=P.el.querySelector("video.bgv"); if(bg && !bg.srcObject){ bg.srcObject=new MediaStream([e.track]); bg.play().catch(()=>{}); }
      { const mv=P.el.querySelector("video.mainv"), tk=e.track, pic=()=>!!mv && mv.videoWidth>0 && !tk.muted;     // no picture yet (or none coming: answered without camera) → the avatar
        P.el.classList.toggle("audio", !pic());
        if(mv) mv.addEventListener("resize",()=>{ if(!tk.muted && mv.videoWidth>0){ P.el.classList.remove("audio"); callChrome(); } });
        setTimeout(()=>{ if(call && !pic()){ P.el.classList.add("audio"); callChrome(); } }, 1500); }
      callChrome();
      e.track.onmute=()=>{ P.el.classList.add("audio"); callChrome(); }; e.track.onunmute=()=>{ P.el.classList.remove("audio"); callChrome(); }; } };
  pc.onconnectionstatechange=()=>{ const st=pc.connectionState;
    if(st==="connected"){ clearTimeout(P.discT); P.connected=true; onCallConnected(); }
    else if(st==="failed"){ dropPeer(pid,"failed"); }
    else if(st==="disconnected"){ clearTimeout(P.discT); P.discT=setTimeout(()=>{ if(pc.connectionState==="disconnected") dropPeer(pid,"lost"); },8000); } };
  if(initiator){ const offer=await pc.createOffer(); await pc.setLocalDescription(offer);
    callSend({a:"offer",cid:call.cid,to:pid,from:call.me,sdp:{type:pc.localDescription.type,sdp:pc.localDescription.sdp},video:call.video,n:myName}); }
  return P;
}

// ---------- "weak connection" during a call (v39): measured here, from WebRTC's own statistics ----------
// Bad when, over the last 2 s, more than 8 % of packets were lost (theirs to us, or ours as they report it),
// the round trip is above 0.8 s, or their picture stopped while it should be moving. Shown after two bad
// readings in a row, hidden after three good ones, so a single hiccup doesn't flash it.
function qualSample(sm){ if(!call || !call.t1) return; const q=call.q||(call.q={bad:0, good:0, on:false});
  const bad=!!sm && ((sm.loss||0)>0.08 || (sm.rtt||0)>0.8 || !!sm.frozen);
  if(bad){ q.bad++; q.good=0; if(q.bad>=2) q.on=true; } else { q.good++; q.bad=0; if(q.good>=3) q.on=false; }
  const w=$("callWeak"); if(w) w.hidden=!q.on; }
async function qualTick(){ if(!call || !call.t1) return; let worst={loss:0, rtt:0, frozen:false};
  for(const P of call.peers.values()){ let st; try{ st=await P.pc.getStats(); }catch(e){ continue; } const prev=P._qs||{}, cur={};
    st.forEach(x=>{
      if(x.type==="inbound-rtp" && !x.isRemote){ const k=x.kind||x.mediaType; cur["l"+k]=x.packetsLost||0; cur["r"+k]=x.packetsReceived||0; if(k==="video") cur.fd=x.framesDecoded||0; }
      if(x.type==="remote-inbound-rtp" && typeof x.fractionLost==="number") worst.loss=Math.max(worst.loss, x.fractionLost);
      if(x.type==="candidate-pair" && (x.nominated || x.selected) && x.state==="succeeded" && typeof x.currentRoundTripTime==="number") worst.rtt=Math.max(worst.rtt, x.currentRoundTripTime); });
    for(const k of ["audio","video"]){ const dl=(cur["l"+k]||0)-(prev["l"+k]||0), dr=(cur["r"+k]||0)-(prev["r"+k]||0); if(dl+dr>20) worst.loss=Math.max(worst.loss, Math.max(0,dl)/(Math.max(0,dl)+Math.max(1,dr))); }
    const vt=P.stream.getVideoTracks()[0]; if(vt && !vt.muted && vt.readyState==="live" && typeof prev.fd==="number" && cur.fd===prev.fd && !P.el.classList.contains("audio")) worst.frozen=true;
    P._qs=cur; }
  qualSample(worst); }
function dropPeer(pid, why){
  if(!call) return; const P=call.peers.get(pid); if(!P) return; call.peers.delete(pid); clearTimeout(P.discT);
  try{ P.pc.close(); }catch(e){} if(P.el) P.el.remove(); restage();
  if(!call.group){ endCall(call.t1?"ended":"failed", true); return; }      // 1:1: the call is over
  if(call.peers.size===0) callStatus(t("Waiting for others…"));
}
function anyConnected(){ return !!(call && [...call.peers.values()].some(P=>P.connected)); }
function onCallConnected(){
  if(!call) return;
  if(!call.t1){ call.t1=Date.now(); call.state="live"; stopRing(); clearTimeout(call.ringT); clearTimeout(call.pushT); soundConnect(); callChrome(); $("callUI").classList.remove("ringing"); }
  if(!call.qT) call.qT=setInterval(()=>{ qualTick().catch(()=>{}); }, 2000);
  if(!call.timer) call.timer=setInterval(()=>{ if(!call||!call.t1) return;
    if(call.group && call.peers.size===0) callStatus(t("Waiting for others…"));
    else callStatus(fmtDur(Date.now()-call.t1)+(call.group?" · "+t("{n} in the call",{n:call.peers.size+1}):"")); },1000);
  callStatus(call.group && call.peers.size===0 ? t("Waiting for others…") : "00:00");
}
function setLocalPreview(){ const v=$("callLocal"); if(!call||!call.local){ v.hidden=true; v.srcObject=null; return; }
  const hasV=call.local.getVideoTracks().some(tr=>tr.enabled); v.srcObject=call.local; v.hidden=!hasV; v.play().catch(()=>{});
  $("callCam").hidden=!call.local.getVideoTracks().length && !call.noCam; $("callFlip").hidden=!call.local.getVideoTracks().length || !/iphone|ipad|ipod|android/i.test(navigator.userAgent);
  $("callMute").classList.toggle("on", !call.local.getAudioTracks().every(tr=>tr.enabled));
  $("callCam").classList.toggle("on", (call.local.getVideoTracks().length>0 && !hasV) || !!call.noCam); }
function showOutgoing(){ callUIShow(true); $("callUI").classList.add("ringing"); $("callName").textContent=call.name||""; $("callIncoming").hidden=true; $("callCtl").hidden=false; $("callStage").innerHTML=""; setLocalPreview(); }
// the ringing alerts the service worker showed for a call are closed once the app itself rings (or the call ends)
function closeCallNotifs(){ try{ if(!("serviceWorker" in navigator)) return; navigator.serviceWorker.ready.then(reg=>reg.getNotifications()).then(ns=>{ (ns||[]).forEach(n=>{ if(n.data && n.data.ring) n.close(); }); }).catch(()=>{}); }catch(e){} }
function showIncoming(){ callUIShow(true); closeCallNotifs(); $("callUI").classList.add("ringing"); $("callName").textContent=call.name||""; callStatus(call.video?t("Encrypted video call"):t("Encrypted voice call")); $("callIncoming").hidden=false; $("callNoCamW").hidden=!(call.video && !call.group); $("callCtl").hidden=true; $("callLocal").hidden=true; $("callStage").innerHTML=""; peerEl(call.from||"?", call.name); startRing("tone"); }
// ----- 1:1 -----
async function startCall(video){
  const R=A(); if(!R) return;
  if(call){ toast(t("You're already in a call")); return; }
  if(!navigator.mediaDevices || !window.RTCPeerConnection){ toast(t("Calls aren't supported in this browser")); return; }
  if(R.group) return startGroupCall(R, video);
  if(!R.fromContact && !R.paired) return;
  initAudio(); callFsAuto(video);
  let local; try{ local=await callMedia(video, null, true); }catch(e){ toast(mediaErr(e)); return; }
  if(call){ local.getTracks().forEach(tr=>tr.stop()); return; }   // a call began meanwhile (a second tap, an incoming one)
  video = video && local.getVideoTracks().length>0;
  call={R, cid:rid(), dir:"out", group:false, video, state:"calling", peers:new Map(), me:R.id, local, name:R.peerName||dn(R.title), t0:Date.now(), ackd:false};
  showOutgoing(); peerEl("?", call.name); callStatus(t("Calling…")); startRing("back");
  call.ringT=setTimeout(()=>{ if(call && !call.t1){ callSend({a:"cancel",cid:call.cid,to:call.from,from:call.me}); endCall("noanswer",true); } }, CALL_RING_MS);
  // not answered quickly (or not even online): wake their phone — "X is calling you" — and ring again every few
  // seconds until their app answers ("ringing"), they pick up or the call gives up; a "missed call" follows then
  const me=call, ringPush=()=>{ if(call!==me || me.state!=="calling" || me.ackd || !R.fromContact) return;
    me.pushed=(me.pushed||0)+1; notifyPeer(R.fromContact,"call").catch(()=>{}); me.pushT=setTimeout(ringPush, CALL_REPUSH_MS); };
  call.pushT=setTimeout(ringPush, R.paired?4000:0);
  callTryInvite();
  // the invitation is repeated until the other side acknowledges it ("ringing"): it may have been sent while
  // they were still finishing their own pairing, or simply lost on the way
  call.inviteT=setInterval(()=>{ if(call && call.state==="calling" && !call.ackd) callTryInvite(); else clearInterval(call && call.inviteT); }, 2000);
}
function callTryInvite(){
  if(!call || call.group || call.dir!=="out" || call.state!=="calling") return;
  const R=call.R; if(!R.paired || !R.peer){ callStatus(t("Reaching them…")); return; }
  call.from=R.peer.id; peerEl(R.peer.id, call.name); if(!call.ackd) callStatus(t("Calling…"));
  callSig(R,{a:"invite",cid:call.cid,from:R.id,to:R.peer.id,video:call.video,n:myName});
}
// noCam: a video call answered without opening the camera — their picture comes in, ours stays off until the
// camera button is tapped (the video line is still negotiated both ways, so turning it on needs no new offer)
async function acceptCall(noCam){
  if(!call || call.dir!=="in" || call.state!=="ringing") return; noCam=noCam===true && call.video && !call.group;
  stopRing(); clearTimeout(call.ringT); initAudio(); callFsAuto(call.video && !call.group);
  let local; try{ local=await callMedia(call.video && !noCam, null, true); }catch(e){ toast(mediaErr(e)); declineCall(); return; }
  if(!call) { local.getTracks().forEach(tr=>tr.stop()); return; }
  call.local=local; call.noCam=noCam; call.video=call.video && (noCam || local.getVideoTracks().length>0); call.state="connecting";
  $("callIncoming").hidden=true; $("callCtl").hidden=false; setLocalPreview(); callStatus(t("Connecting…"));
  callSend({a:"accept",cid:call.cid,to:call.from,from:call.me,video:call.video});
}
function declineCall(){ if(!call) return; callSend({a:"decline",cid:call.cid,to:call.from,from:call.me}); endCall("declined",true); }
function hangup(){ if(!call) return; endCall("ended"); }
function endCall(reason, silent){
  const c=call; if(!c) return; call=null;
  stopRing(); clearTimeout(c.ringT); clearTimeout(c.pushT); clearInterval(c.timer); clearInterval(c.inviteT); clearInterval(c.qT); closeCallNotifs(); if($("callWeak")) $("callWeak").hidden=true;
  if(_fsByCall) fsExit();
  // we rang their phone and they never picked up: the ringing alert there becomes "missed call"
  if(c.dir==="out" && !c.group && !c.t1 && c.pushed && !c.ackd && reason!=="declined" && reason!=="busy" && c.R && c.R.fromContact) notifyPeer(c.R.fromContact,"missed").catch(()=>{});
  if(!silent && c.R){ try{ callSig(c.R, c.group ? {a:"hangup",cid:c.cid,from:c.me} : {a:(c.dir==="out"&&!c.t1)?"cancel":"hangup", cid:c.cid, from:c.me, to:c.from}); }catch(e){} }
  c.peers.forEach(P=>{ clearTimeout(P.discT); try{ P.pc.close(); }catch(e){} });
  if(c.local) c.local.getTracks().forEach(tr=>tr.stop());
  $("callStage").innerHTML=""; $("callLocal").srcObject=null; $("callLocal").style.transform=""; callUIShow(false);
  const kind=c.video?t("Video call"):t("Audio call"); const dur=c.t1?fmtDur(Date.now()-c.t1):null;
  const line = dur ? "📞 "+kind+" · "+dur
    : reason==="declined" ? t("📞 {kind} declined",{kind}) : reason==="busy" ? t("📞 {kind} — busy",{kind})
    : reason==="missed" ? t("📞 Missed {kind}",{kind}) : reason==="noanswer" ? t("📞 {kind} — no answer",{kind})
    : reason==="failed" ? t("📞 {kind} — connection failed",{kind}) : t("📞 {kind} ended",{kind});
  if(c.R && c.R.logEl) sysline(c.R.logEl, line);
  if(c.group && c.R){ if(c.R.gcall && c.R.gcall.cid===c.cid && !anyOtherInCall(c.R)) c.R.gcall=null; try{ c.R.channel && c.R.channel.track(presencePayload(c.R)); }catch(e){} showCallBanner(c.R); }
  if(c.t1 || reason==="declined" || reason==="busy") soundEnd();
  updateCallUI();
}
function anyOtherInCall(R){ try{ const st=R.channel.presenceState(); for(const k in st) for(const m of st[k]) if(m.cc && m.id!==R.id) return true; }catch(e){} return false; }
// ----- signalling -----
async function callSignal(R, env, who){
  const a=env.a; if(!a) return;
  if(a==="gstart"){ if(R.group){ R.gcall={cid:env.cid, video:!!env.video, by:who, ts:Date.now()}; showCallBanner(R); if(!call){ if(R.logEl) sysline(R.logEl, t("📞 {name} started a {kind}",{name:who, kind:env.video?t("video call"):t("audio call")})); soundRecv(); } } return; }
  if(a==="invite"){
    if(R.group) return;   // group rooms only ever announce a call (gstart); a 1:1 ring from a group member is ignored
    if(call){ if(call.cid!==env.cid) callSig(R,{a:"busy",cid:env.cid,to:env.from,from:R.id}); else callSig(R,{a:"ringing",cid:env.cid,to:env.from,from:R.id}); return; }
    call={R, cid:env.cid, dir:"in", group:false, video:!!env.video, state:"ringing", peers:new Map(), me:R.id, from:env.from, name:who||R.peerName||dn(R.title), t0:Date.now()};
    showIncoming(); callSig(R,{a:"ringing",cid:env.cid,to:env.from,from:R.id});
    call.ringT=setTimeout(()=>{ if(call && call.state==="ringing") endCall("missed",true); }, CALL_RING_MS);
    updateCallUI(); return; }
  if(!call || env.cid!==call.cid) return;
  if(env.to && env.to!==call.me) return;
  switch(a){
    case "ringing": call.ackd=true; clearTimeout(call.pushT); if(call.state==="calling") callStatus(t("Ringing…")); break;
    case "accept": if(call.dir!=="out" || call.group) break; call.state="connecting"; stopRing(); callStatus(t("Connecting…")); await newPeer(env.from||call.from, call.name, true); break;
    case "offer": { if(!env.sdp) break; let P=call.peers.get(env.from); if(!P){ if(call.group && call.peers.size>=CALL_MAX-1) break; P=await newPeer(env.from, env.n||who||call.name, false); if(!P) break; }
      await P.pc.setRemoteDescription(env.sdp); P.remoteSet=true; for(const c of P.cands){ try{ await P.pc.addIceCandidate(c); }catch(e){} } P.cands=[];
      if(call.noCam) P.pc.getTransceivers().forEach(tr=>{ if(tr.receiver && tr.receiver.track && tr.receiver.track.kind==="video" && !tr.sender.track){ try{ tr.direction="sendrecv"; }catch(e){} } });   // room for our camera later
      const ans=await P.pc.createAnswer(); await P.pc.setLocalDescription(ans);
      callSend({a:"answer",cid:call.cid,to:env.from,from:call.me,sdp:{type:P.pc.localDescription.type,sdp:P.pc.localDescription.sdp}}); break; }
    case "answer": { const P=call.peers.get(env.from); if(!P||!env.sdp) break; await P.pc.setRemoteDescription(env.sdp); P.remoteSet=true; for(const c of P.cands){ try{ await P.pc.addIceCandidate(c); }catch(e){} } P.cands=[]; break; }
    case "ice": { const P=call.peers.get(env.from); if(!env.cand) break;
      if(!P){ if(!call.early) call.early=new Map(); const l=call.early.get(env.from)||[]; if(l.length<64) l.push(env.cand); call.early.set(env.from,l); break; }   // before the offer was handled: kept
      if(P.remoteSet){ try{ await P.pc.addIceCandidate(env.cand); }catch(e){} } else P.cands.push(env.cand); break; }
    case "decline": if(!call.group) endCall("declined",true); break;
    case "busy": if(!call.group) endCall("busy",true); break;
    case "cancel": if(!call.group) endCall("missed",true); break;
    case "hangup": if(call.group) dropPeer(env.from,"left"); else endCall("ended",true); break;
    case "gjoin": if(call.group && env.from!==call.me){ if(call.peers.size>=CALL_MAX-1) break; if(!call.peers.has(env.from)) await newPeer(env.from, env.n||who, true); } break;
  }
}
// ----- groups: "there is a call, join it" (no ringing; presence tells who is in) -----
async function startGroupCall(R, video){
  initAudio(); let local; try{ local=await callMedia(video); }catch(e){ toast(mediaErr(e)); return; }
  if(call){ local.getTracks().forEach(tr=>tr.stop()); return; }
  video = video && local.getVideoTracks().length>0;
  call={R, cid:rid(), dir:"out", group:true, video, state:"live", peers:new Map(), me:R.id, local, name:R.title||t("Group"), t0:Date.now()};
  showOutgoing(); onCallConnected();
  R.gcall={cid:call.cid, video, by:myName, ts:Date.now()}; try{ R.channel && R.channel.track(presencePayload(R)); }catch(e){}
  callSig(R,{a:"gstart",cid:call.cid,from:R.id,video,n:myName}); showCallBanner(R); updateCallUI();
}
async function joinGroupCall(){
  const R=A(); if(!R||!R.group||!R.gcall) return; if(call){ toast(t("You're already in a call")); return; }
  initAudio(); let local; try{ local=await callMedia(R.gcall.video); }catch(e){ toast(mediaErr(e)); return; }
  if(call){ local.getTracks().forEach(tr=>tr.stop()); return; }
  call={R, cid:R.gcall.cid, dir:"in", group:true, video:!!(R.gcall.video && local.getVideoTracks().length), state:"connecting", peers:new Map(), me:R.id, local, name:R.title||t("Group"), t0:Date.now()};
  showOutgoing(); callStatus(t("Connecting…")); try{ R.channel && R.channel.track(presencePayload(R)); }catch(e){}
  callSig(R,{a:"gjoin",cid:call.cid,from:R.id,n:myName,video:call.video}); showCallBanner(R); updateCallUI();
}
function showCallBanner(R){ const b=$("callBanner"); if(!b) return; if(!R || R.code!==active){ if(!R) b.hidden=true; return; }
  const on=!!(R.group && R.gcall && !(call && call.cid===R.gcall.cid)); b.hidden=!on;
  if(on) $("callBannerText").textContent= R.gcall.by ? t("{name} is in a call",{name:R.gcall.by}) : t("Call in progress"); }
function updateCallUI(){ const R=A(); const ok=!!(R && (R.group || R.fromContact || R.paired)) && !!(navigator.mediaDevices && window.RTCPeerConnection);
  const cb=$("callBtn"), vb=$("videoBtn"); if(cb) cb.hidden=!ok; if(vb) vb.hidden=!ok; }
// ----- in-call controls -----
function toggleMute(){ if(!call||!call.local) return; const on=!call.local.getAudioTracks().every(tr=>tr.enabled); call.local.getAudioTracks().forEach(tr=>tr.enabled=on); setLocalPreview(); }
// answered without the camera: the first tap opens it and puts it on the video line already there
async function camLater(){ const me=call; if(!me || !me.local || me._camBusy) return; me._camBusy=true;
  try{ const ns=await navigator.mediaDevices.getUserMedia({video:{facingMode:"user", width:{ideal:1280}, height:{ideal:720}, frameRate:{ideal:30}}});
    const tr=ns.getVideoTracks()[0]; if(!tr || call!==me){ ns.getTracks().forEach(x=>x.stop()); return; }
    me.local.addTrack(tr); me.noCam=false;
    me.peers.forEach(P=>{ const x=P.pc.getTransceivers().find(z=>z.receiver && z.receiver.track && z.receiver.track.kind==="video");
      if(x){ try{ if(x.direction!=="sendrecv") x.direction="sendrecv"; }catch(e){} x.sender.replaceTrack(tr).catch(()=>{}); } });
    setLocalPreview();
  }catch(e){ toast(mediaErr(e)); } finally{ me._camBusy=false; } }
function toggleCam(){ if(!call||!call.local) return; const vts=call.local.getVideoTracks(); if(!vts.length){ if(call.noCam) camLater(); return; } const on=!vts.every(tr=>tr.enabled); vts.forEach(tr=>tr.enabled=on); setLocalPreview(); }
// Front ↔ back camera. Many Android phones (Samsung among them) cannot open a second camera while the first is
// still running — asking for the other one first fails there — so the current camera is released before the
// other is opened: by facing ("environment" / "user"), else by device (the camera whose name says back / front,
// else any other one). If nothing opens, the camera we had comes back.
let _flipping=false;
async function flipCam(){
  if(!call || !call.local || _flipping) return; const cur=call.local.getVideoTracks()[0]; if(!cur) return;
  _flipping=true; const btn=$("callFlip"); if(btn) btn.disabled=true;
  const me=call, st=cur.getSettings ? cur.getSettings() : {}, curId=st.deviceId||"", was=call.facing||st.facingMode||"user";
  const want= was==="environment" ? "user" : "environment", on=cur.enabled, hd=!call.group;
  const size={width:{ideal:hd?1280:640}, height:{ideal:hd?720:480}};
  let devs=[]; try{ devs=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==="videoinput"); }catch(e){}
  const BACK=/back|rear|environment|arri[eè]re|r[uü]ck/i, FRONT=/front|user|avant|selfie|vorder/i;
  const byLabel=devs.filter(d=>d.deviceId && d.deviceId!==curId && (want==="environment" ? BACK.test(d.label) : FRONT.test(d.label) && !BACK.test(d.label)));
  const others=devs.filter(d=>d.deviceId && d.deviceId!==curId);
  const tries=[ {facingMode:{exact:want}}, ...byLabel.map(d=>({deviceId:{exact:d.deviceId}})), {facingMode:want}, ...others.map(d=>({deviceId:{exact:d.deviceId}})) ];
  const use=nt=>{ call.peers.forEach(P=>{ const sn=P.pc.getSenders().find(x=>x.track && x.track.kind==="video") || P.pc.getSenders().find(x=>!x.track && x.dtmf===null);
      if(sn) sn.replaceTrack(nt).catch(()=>{}); });
    call.local.getVideoTracks().forEach(x=>call.local.removeTrack(x)); call.local.addTrack(nt); nt.enabled=on; };
  try{
    cur.stop();                                                    // free the camera first
    let nt=null;
    for(const v of tries){ if(call!==me) break; try{ const ns=await navigator.mediaDevices.getUserMedia({video:Object.assign({}, v, size)}); const x=ns.getVideoTracks()[0];
        if(x && x.getSettings && curId && x.getSettings().deviceId===curId){ x.stop(); continue; }   // the same camera again
        if(x){ nt=x; break; } }catch(e){} }
    if(call!==me){ if(nt) nt.stop(); return; }
    if(nt){ use(nt); const f=(nt.getSettings && nt.getSettings().facingMode) || want; call.facing=f; $("callLocal").style.transform=f==="environment"?"none":"scaleX(-1)"; }
    else { toast(t("Couldn't switch camera"));
      try{ const ns=await navigator.mediaDevices.getUserMedia({video:Object.assign({}, curId ? {deviceId:{exact:curId}} : {facingMode:was}, size)}); const x=ns.getVideoTracks()[0]; if(x && call===me) use(x); else if(x) x.stop(); }catch(e){} }
    setLocalPreview();
  } finally { _flipping=false; if(btn) btn.disabled=false; }
}
async function previewTone(n){
  setTone(n); const p=initAudio();
  let as=null; try{ as=navigator.audioSession; if(as && as.type!=="playback"){ as.type="playback"; setTimeout(()=>{ try{ as.type="auto"; }catch(e){} },1500); } }catch(e){}
  try{ await Promise.race([p, new Promise(r=>setTimeout(r,250))]); }catch(e){}
  const n2=toneName(); beep(TONES[n2], "preview", TONE_WET[n2]||0);
}
// Warm ascending arpeggio when a call connects.
function soundConnect(){ initAudio(); beep([
  {f:523.25,t0:0,   dur:0.22,gain:0.040},   // C5
  {f:659.25,t0:0.11,dur:0.24,gain:0.044},   // E5
  {f:783.99,t0:0.22,dur:0.30,gain:0.048},   // G5
  {f:1046.50,t0:0.33,dur:0.42,gain:0.030}   // C6 bloom
]); }
// ---------- disappearing messages ----------
const EXP_G="gz-exp-global", EXP_R="gz-exp-rooms";
function expGlobal(){ try{ return +localStorage.getItem(EXP_G)||0; }catch(e){ return 0; } }
function expRoomsMap(){ try{ return JSON.parse(localStorage.getItem(EXP_R)||"{}")||{}; }catch(e){ return {}; } }
function expFor(code){ const m=expRoomsMap(); if(code&&Object.prototype.hasOwnProperty.call(m,code)){ const v=m[code]; return v===null?0:(+v||0); } return expGlobal(); }
function setExpGlobal(ms){ try{ localStorage.setItem(EXP_G,String(ms||0)); }catch(e){} sweepEphemeral(); }
function setExpRoom(code,val){ const m=expRoomsMap(); if(val==="") delete m[code]; else m[code]=(+val||0); try{ localStorage.setItem(EXP_R,JSON.stringify(m)); }catch(e){} sweepEphemeral(); }
// The chat's timer, from the header (⏱): one tap opens Off / 5 / 30 / 60 minutes / 24 hours. A choice applies to
// the chat for everyone in it — it travels as an encrypted {t:"exp", v} envelope (quiet, like a reaction) and each
// device applies the newest one — so both sides agree on whether photos are view-once or kept (Off: kept).
const EXP_CHOICES=[0,300000,1800000,3600000,86400000], EXP_TS="gz-exp-ts";
function expTsMap(){ try{ return JSON.parse(localStorage.getItem(EXP_TS)||"{}")||{}; }catch(e){ return {}; } }
function expLabel(ms){ return !ms ? t("Off") : ms>=86400000 ? t("24 hours") : t("{n} minutes",{n:Math.round(ms/60000)}); }
function expBadge(ms){ return !ms ? "" : ms>=86400000 ? "24" : String(Math.round(ms/60000)); }
function expLine(ms, who){ const l=expLabel(ms);
  if(!ms) return who ? t("⏱ {name} turned off disappearing messages — messages and photos stay",{name:who}) : t("⏱ You turned off disappearing messages — messages and photos stay");
  return who ? t("⏱ {name} set messages to disappear after {time}",{name:who,time:l}) : t("⏱ You set messages to disappear after {time}",{time:l}); }
function applyChatExp(R, ms, ts){ const hk=histKeyOf(R); if(!hk) return false; const m=expTsMap();
  if((m[hk]||0) > (ts||0)) return false;                              // an older change arriving late
  m[hk]=ts||Date.now(); try{ localStorage.setItem(EXP_TS, JSON.stringify(m)); }catch(e){}
  setExpRoom(hk, String(ms)); paintExpBtn(); return true; }
async function chooseExp(ms){
  const R=A(); closeExpMenu(); if(!R || !EXP_CHOICES.includes(ms)) return;
  const hk=histKeyOf(R), now=Date.now(); const had=Object.prototype.hasOwnProperty.call(expRoomsMap(),hk);
  if(had && expFor(hk)===ms) return;
  applyChatExp(R, ms, now);
  if(R.logEl) sysline(R.logEl, expLine(ms, null));
  if(!R.group && !R.fromContact && !R.paired) return;
  const env={t:"exp", v:ms, body:"⏱ "+t("Disappearing messages: {time}",{time:expLabel(ms)})}; const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  deliverOut(R, env, mid, null, now, true).catch(()=>{});
}
function onExpEnv(R, env, who, ts, mid, own){
  if(!env || !EXP_CHOICES.includes(env.v)) return;
  if(R.group && !own && env.vf==="bad") return;
  histSave(histKeyOf(R),{dir:own?"sent":"recv",env,ts,who,mid,vf:env.vf});
  if(!applyChatExp(R, env.v, ts)) return;
  let V=R.logEl ? R : null; if(!V && !R.group && R.fromContact){ const tg=mergedTarget(contactFind(R.fromContact)); const ck=tg?tg.ck:R.fromContact; rooms.forEach(x=>{ if(x.logEl && x.fromContact===ck) V=x; }); }
  if(V) sysline(V.logEl, expLine(env.v, own ? null : (R.group ? (who||t("Member")) : (R.peerName||dn(R.title)||t("Contact")))));
}
function paintExpBtn(){ const b=$("expBtn"); if(!b) return; const R=A(); if(!R){ b.hidden=true; return; }
  const ms=expFor(histKeyOf(R)); b.hidden=false; b.classList.toggle("off", !ms); $("expNum").textContent=expBadge(ms);
  b.title=t("Disappearing messages: {time}",{time:expLabel(ms)}); b.setAttribute("aria-label", b.title); }
function openExpMenu(){ const m=$("expMenu"), b=$("expBtn"), R=A(); if(!R) return; closePicker();
  const ms=expFor(histKeyOf(R)); m.querySelectorAll("button[data-v]").forEach(x=>x.classList.toggle("on", +x.dataset.v===ms));
  m.hidden=false; const r=b.getBoundingClientRect(), w=m.offsetWidth; const ap=$("app"), dy=(ap && ap.style.transform) ? ap.getBoundingClientRect().top : 0;
  m.style.top=Math.round(r.bottom+6-dy)+"px"; m.style.left=Math.round(Math.max(8, Math.min(r.right-w, window.innerWidth-w-8)))+"px"; }
function closeExpMenu(){ const m=$("expMenu"); if(m) m.hidden=true; }
function sweepEphemeral(){
  const now=Date.now();
  rooms.forEach(R=>{ const k=histKeyOf(R); const dur=expFor(k); if(!dur||!R.logEl) return; const cut=now-dur;
    [...R.logEl.children].forEach(el=>{ const ts=+(el.dataset&&el.dataset.ts||0); if(ts&&ts<=cut) el.remove(); });
    histSweep(k,cut);
  });
}
let _toastT=null;
function toast(m){ const t=$("toast"); t.textContent=m; t.classList.add("show"); clearTimeout(_toastT); _toastT=setTimeout(()=>t.classList.remove("show"), Math.max(1700, Math.min(6000, 55*m.length))); }
// to the newest message; a chat scrolled up by hand stays where it is (the ↓ button counts what arrives) unless forced
function scrollEl(el, force){ if(el && el._stick===false && !force) return; try{ el.scrollTop=el.scrollHeight; requestAnimationFrame(()=>{ try{ el.scrollTop=el.scrollHeight; }catch(e){} }); }catch(e){} }
// The on-screen keyboard shrinks the *visual* viewport; on iOS the layout viewport stays full height and
// Safari shifts the page to reveal the input, taking the header (and its back button) off-screen for good.
// Size the app to the visual viewport and pin it to its top: header stays, composer sits on the keyboard,
// and the conversation keeps showing its latest messages.
// Installed on an iPhone (standalone), window.innerHeight follows the keyboard too, so "keyboard open" is
// judged against the tallest viewport seen in this orientation rather than against innerHeight.
const vv=window.visualViewport;
let _fitT=null, _maxVH=0, _logRO=null;
function viewH(){ return Math.round((vv&&vv.height)||window.innerHeight||0); }
function fitTarget(){ const b=document.body.classList; return b.contains("in-app") ? $("app") : b.contains("in-auth") ? $("join") : null; }
// iOS 26 installed apps (WebKit bug 301994): the system reports a viewport of the screen minus the status bar
// and paints a band of that height over the bottom of the screen, in the page's background colour cached at
// launch. Nothing can be drawn under it — so the page doesn't try; it stops reserving the home-indicator space
// (the band already covers it) and the band takes the colour of the message bar (html background, below).
let _safeProbe=null;
function safeInsets(){ try{ if(!_safeProbe){ _safeProbe=document.createElement("div"); _safeProbe.style.cssText="position:fixed;left:0;top:0;width:0;height:0;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);visibility:hidden;pointer-events:none";
    document.documentElement.appendChild(_safeProbe); } const cs=getComputedStyle(_safeProbe); return {top:Math.round(parseFloat(cs.paddingTop)||0), bottom:Math.round(parseFloat(cs.paddingBottom)||0)}; }catch(e){ return {top:0,bottom:0}; } }
const STANDALONE = window.navigator.standalone===true || !!(window.matchMedia && matchMedia("(display-mode: standalone)").matches);
function iosGap(h){
  if(!STANDALONE || !window.screen) return false;
  const portrait=window.innerHeight>=window.innerWidth, sh=portrait ? Math.max(screen.width,screen.height) : Math.min(screen.width,screen.height);
  const si=safeInsets(), gap=sh-h;
  return si.top>0 && gap>8 && Math.abs(gap-si.top)<=3;
}
function fitViewport(){
  const el=fitTarget(); if(!el) return;
  const h=viewH(); if(!h) return;
  if(h>_maxVH) _maxVH=h;
  const kb=(_maxVH-h)>120;
  el.style.height=h+"px";
  if(!kb) document.documentElement.classList.toggle("ios-gap", iosGap(h));
  const top=vv?Math.round(vv.offsetTop):0; el.style.transform=top>1?("translateY("+top+"px)"):"";
  document.body.classList.toggle("kb",kb);
  if(window.scrollY) try{ window.scrollTo(0,0); }catch(e){}
  if(el.id==="app") stickLog();
}
// The latest messages stay in view whenever the conversation area changes size (keyboard, rotation, the
// composer growing to several lines) — unless the reader has scrolled up on purpose.
function stickLog(){ const R=A(); if(R&&R.logEl&&R.logEl._stick!==false) scrollEl(R.logEl); }
// scrolled up in a chat: a round ↓ brings back the latest messages, with how many arrived meanwhile
function jumpUpdate(){ const b=$("jumpBtn"); if(!b) return; const R=A(); const L=R && R.logEl;
  const far=!!(L && (L.scrollHeight-L.scrollTop-L.clientHeight)>240);
  if(!far && R) R._below=0;
  b.hidden=!far; const n=(R && R._below)||0; $("jumpCount").hidden=!n; $("jumpCount").textContent=n>99?"99+":String(n); }
function watchLog(l){
  l.addEventListener("scroll",()=>{ l._stick=(l.scrollHeight-l.scrollTop-l.clientHeight)<56; jumpUpdate(); },{passive:true});
  if(window.ResizeObserver){ if(!_logRO) _logRO=new ResizeObserver(()=>stickLog()); _logRO.observe(l); }
}
// iOS 17/18 installed apps sometimes keep the shrunken viewport after the keyboard has gone; a display
// toggle on the full-height element makes WebKit measure again.
function healViewport(){
  if(!(window.navigator.standalone || (window.matchMedia && matchMedia("(display-mode: standalone)").matches))) return;
  const el=fitTarget(); if(!el) return;
  if(viewH() >= _maxVH-4) return;
  const R=A(), st=R&&R.logEl?R.logEl.scrollTop:0, js=el.scrollTop;
  const d=el.style.display; el.style.display="none"; void el.offsetHeight; el.style.display=d||"flex";
  if(R&&R.logEl) R.logEl.scrollTop=st; el.scrollTop=js;
  setTimeout(fitViewport,50);
}
if(vv){ vv.addEventListener("resize",fitViewport); vv.addEventListener("scroll",fitViewport); }
window.addEventListener("resize",fitViewport);
window.addEventListener("orientationchange",()=>{ _maxVH=0; clearTimeout(_fitT); _fitT=setTimeout(fitViewport,350); });
function fmtTime(ts){ return new Date(ts).toLocaleTimeString(LOC(), {hour:"2-digit",minute:"2-digit"}); }
function dayLabel(ts){ const d=new Date(ts), now=new Date(); if(d.toDateString()===now.toDateString()) return t("Today");
  const y=new Date(now); y.setDate(now.getDate()-1); if(d.toDateString()===y.toDateString()) return t("Yesterday");
  return d.toLocaleDateString(LOC(), {weekday:"short", day:"numeric", month:"short"}); }
function ensureDaySep(logEl, ts){ const d=new Date(ts); const k=d.getFullYear()+"-"+d.getMonth()+"-"+d.getDate(); if(logEl.dataset.lastDay===k) return; logEl.dataset.lastDay=k;
  const el=document.createElement("div"); el.className="daysep"; el.textContent=dayLabel(ts); logEl.appendChild(el); }
const ST_GLYPH={pending:"🕓",sent:"✓",rcvd:"✓✓",failed:"!"};
function metaRow(d, ts, st){ const m=document.createElement("span"); m.className="meta"; const t=document.createElement("span"); t.className="time"; t.textContent=fmtTime(ts); m.appendChild(t);
  if(st){ const x=document.createElement("span"); x.className="st"; m.appendChild(x); } d.appendChild(m); if(st) setMsgState(d,st); }
function setMsgState(d, st){ const x=d.querySelector(".st"); if(!x) return; x.dataset.st=st; x.textContent=ST_GLYPH[st]||"";
  d.classList.toggle("failed",st==="failed"); x.title= st==="rcvd"?t("Received on their device") : st==="sent"?t("Sent") : st==="failed"?t("Not sent — tap to retry") : t("Sending…"); }
// opts: {mid, st} — st for our own messages: pending | sent | rcvd | failed
// Sender line of a group bubble, with the signature verdict: ✓ signed by the key this member has always used,
// ⚠ a different key for that name (or a broken signature), nothing for an older build that does not sign.
function whoEl(tag, vf){
  const w=document.createElement("span"); w.className="who"+(vf==="ok"?" vf-ok":(vf==="bad"||vf==="changed")?" vf-bad":""); w.textContent=tag;
  if(vf==="ok"){ const b=document.createElement("span"); b.className="vfb"; b.textContent="✓"; b.title=t("Signed with this member's usual key"); w.appendChild(b); }
  else if(vf==="bad"||vf==="changed"){ const b=document.createElement("span"); b.className="vfb warn"; b.textContent=vf==="bad"?t("⚠ bad signature"):t("⚠ different key"); w.appendChild(b); }
  return w;
}

// ---------- one to three emojis on their own: shown big, and they move (v39) ----------
const _gseg=(typeof Intl!=="undefined" && Intl.Segmenter) ? new Intl.Segmenter(undefined,{granularity:"grapheme"}) : null;
const EMO_G=/^(?:\p{Extended_Pictographic}|\p{Regional_Indicator}{2}|[#*0-9]\uFE0F?\u20E3)/u;
function graphemes(s){ return _gseg ? [..._gseg.segment(s)].map(x=>x.segment) : Array.from(s); }
function jumboCount(text){ const s=String(text||"").trim(); if(!s || s.length>48) return 0; let n=0;
  for(const g of graphemes(s)){ if(/^\s+$/.test(g)) continue; if(!EMO_G.test(g) || /^[0-9#*]$|^[\u00A9\u00AE\u2122]/.test(g)) return 0; if(++n>3) return 0; }
  return n; }
function jumboAnim(g){
  if(/^(?:❤|💖|💗|💓|💕|💞|💘|💝|🧡|💛|💚|💙|💜|🤎|🖤|🤍|❣|😍|🥰|😘|😻)/u.test(g)) return "beat";
  if(/^(?:😂|🤣|😆|😹|😄|😁)/u.test(g)) return "laugh";
  if(/^(?:👍|👌|💪|✌|🤙|👏|🙌)/u.test(g)) return "nod";
  if(/^(?:👋|🙋|🤚)/u.test(g)) return "wave";
  if(/^(?:🔥|✨|⭐|🌟|💥|⚡|☀)/u.test(g)) return "flare";
  if(/^(?:🎉|🥳|🎊|🎈|🍾|🎂|🥂)/u.test(g)) return "party";
  if(/^(?:😢|😭|😞|😔|🥺|💔|😿)/u.test(g)) return "sad";
  if(/^(?:😮|😱|😲|🤯|😳|🙀)/u.test(g)) return "wow";
  if(/^(?:🙏|🙇)/u.test(g)) return "bow";
  if(/^(?:😡|🤬|😠|👿)/u.test(g)) return "angry";
  return "hop"; }
// b: the bubble, tx: its text element; true when the text is drawn big
function jumboApply(b, tx, text, play){ const n=jumboCount(text); b.classList.remove("jumbo","j1","j2","j3","play");
  if(!n) return false;
  b.classList.add("jumbo","j"+n); tx.textContent="";
  graphemes(String(text).trim()).filter(g=>!/^\s+$/.test(g)).forEach((g,i)=>{ const e=document.createElement("span"); e.className="je"; e.dataset.anim=jumboAnim(g); e.style.setProperty("--jd",(i*90)+"ms"); e.textContent=g; tx.appendChild(e); });
  if(play) jumboPlay(b); return true; }
function jumboPlay(b){ if(!b || matchMedia("(prefers-reduced-motion:reduce)").matches) return;
  b.classList.remove("play"); void b.offsetWidth; b.classList.add("play"); clearTimeout(b._jt); b._jt=setTimeout(()=>b.classList.remove("play"), 3600); }
function addText(logEl, cls, body, tag, animate, ts, opts){
  opts=opts||{}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble "+cls; d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  if(opts.tx) d.dataset.tx="1"; if(opts.pk) d.dataset.pk=opts.pk;   // a real text message (editable by its author); the group signer
  if(tag) d.appendChild(whoEl(tag, opts&&opts.vf));
  if(opts.quote) d.appendChild(opts.quote);
  const t=document.createElement("span"); t.className="txt"; d.appendChild(t);
  if(opts.ui){ d.dataset.ui="1"; }
  if(cls==="sent"||cls==="recv") metaRow(d, ts, cls==="sent" ? (opts.st||"sent") : null);
  if(cls==="sent"){ d.addEventListener("click",()=>{ if(d.classList.contains("failed") && d._retry) d._retry(); }); }
  logEl.appendChild(d); scrollEl(logEl, cls==="sent");
  if(opts.ui) iconText(t, body);
  else if(jumboApply(d, t, body, Date.now()-ts<6000)){}                 // just sent or just arrived: it plays once
  else if(animate){ t.classList.add("scrambling"); scramble(t,body,()=>{ t.classList.remove("scrambling"); scrollEl(logEl); }); } else t.textContent=body;
  if(opts.edited) markEdited(d);
  return d;
}
// ---------- editing a sent message ----------
// An edit is an ordinary encrypted message {t:"edit", m:<id of the message>, x:<new text>} (with a plain body
// "✏️ …" so an older app shows something sensible), sent like a reaction: no sound, no push. Only the author
// can edit: in a 1:1 chat an edit applies to a message received from that same contact (or, from one of our
// own devices, to a message we sent); in a group it must be signed by the key that signed the original.
// Text messages only, within EDIT_WINDOW of sending; the latest edit wins. The bubble says "edited".
const EDIT_WINDOW=24*3600*1000;
function editValid(env){ return !!(env && env.t==="edit" && typeof env.m==="string" && MID_RE.test(env.m) && typeof env.x==="string" && env.x.trim() && env.x.length<=2000); }
function markEdited(b){ if(!b) return; b.classList.add("edited"); const m=b.querySelector(":scope > .meta"); if(m && !m.querySelector(".edm")){ const s=document.createElement("span"); s.className="edm"; s.textContent=t("edited"); m.insertBefore(s, m.firstChild); } }
function editableBubble(b){
  if(!b || !b.classList.contains("sent") || !b.dataset.tx || !b.dataset.mid || !b.querySelector(":scope > .txt")) return false;
  const st=b.querySelector(":scope > .meta .st"); if(st && st.dataset.st!=="sent" && st.dataset.st!=="rcvd") return false;   // still sending, or failed
  return Date.now()-(+b.dataset.ts||0) < EDIT_WINDOW;
}
// apply an edit to the bubble on screen (V: the room showing the chat); false if it doesn't qualify
function applyEditToBubble(V, env, own, ts){
  const b=bubbleOf(V, env.m); if(!b || !b.dataset.tx) return false;
  if(own ? !b.classList.contains("sent") : !b.classList.contains("recv")) return false;
  if(V.group && !own && (b.dataset.pk||"")!==(env.pk||"")) return false;          // a group edit: same signer as the original
  if((ts||Date.now())-(+b.dataset.ts||0) > EDIT_WINDOW+600000) return false;         // (ten minutes of clock skew allowed)
  if((+b.dataset.edts||0) > (ts||0)) return false;                                  // an older edit arriving late
  const tx=b.querySelector(":scope > .txt"); if(!tx) return false;
  tx.classList.remove("scrambling"); if(!jumboApply(b, tx, env.x, true)) tx.textContent=env.x; b.dataset.edts=String(ts||Date.now()); markEdited(b); return true;
}
function onEditEnv(R, env, who, ts, mid, own){
  if(!editValid(env)) return;
  if(R.group && !own && env.vf!=="ok") return;                                       // unsigned or forged: ignored
  histSave(histKeyOf(R),{dir:own?"sent":"recv",env,ts,who,mid,vf:env.vf});
  let V=R.logEl ? R : null;
  if(!V){ let ck=R.fromContact; if(ck && !R.group){ const tg=mergedTarget(contactFind(ck)); if(tg) ck=tg.ck; }
    rooms.forEach(x=>{ if(x.logEl && (R.group ? x.rid===R.rid : x.fromContact===ck)) V=x; }); }
  if(V) applyEditToBubble(V, env, own, ts);
}
// from saved history: the latest valid edit per message
function editsFrom(R, past){
  const orig=new Map(), out=new Map();
  for(const r of past){ if(r && r.env && r.mid && r.env.t!=="edit" && r.env.t!=="react") orig.set(r.mid, r); }
  for(const r of past){ if(!r || !editValid(r.env)) continue; const o=orig.get(r.env.m); if(!o) continue;
    const isText=!o.env.t || o.env.t==="txt"; if(!isText || o.dir!==r.dir) continue;
    if(R.group && r.dir==="recv" && (r.vf!=="ok" || (o.env.pk||"")!==(r.env.pk||""))) continue;
    if((r.ts||0)-(o.ts||0) > EDIT_WINDOW+600000) continue;
    const cur=out.get(r.env.m); if(!cur || (cur.ts||0)<=(r.ts||0)) out.set(r.env.m, {x:r.env.x, ts:r.ts||0}); }
  return out;
}
let _edit=null;   // {code, m, orig}
function startEdit(b){
  const R=A(); if(!R || !editableBubble(b) || $("msgInput").disabled) { if(b && b.dataset.tx && b.classList.contains("sent")) toast(t("Messages can only be edited within 24 hours")); return; }
  cancelReply(); closePicker();
  const orig=(b.querySelector(":scope > .txt")||{}).textContent||"";
  _edit={code:R.code, m:b.dataset.mid, orig, draft:$("msgInput").value};   // a half-typed message comes back afterwards
  $("rbName").textContent=t("Editing your message"); $("rbText").textContent=orig; $("replyBar").classList.add("editing"); $("replyBar").hidden=false;
  const ta=$("msgInput"); ta.value=orig; try{ ta.dispatchEvent(new Event("input",{bubbles:true})); ta.focus(); ta.setSelectionRange(orig.length, orig.length); }catch(e){}
}
async function sendEdit(R, text){
  const e=_edit; _edit=null; $("replyBar").classList.remove("editing"); $("replyBar").hidden=true;
  $("msgInput").value=e.draft||""; $("msgInput").style.height="auto"; try{ $("msgInput").dispatchEvent(new Event("input",{bubbles:true})); }catch(_){}
  const b=bubbleOf(R, e.m); if(!b || text===e.orig) return;
  const now=Date.now(); if(now-(+b.dataset.ts||0) > EDIT_WINDOW){ toast(t("Messages can only be edited within 24 hours")); return; }
  const env={t:"edit", m:e.m, x:text, body:"✏️ "+text}; const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  const tx=b.querySelector(":scope > .txt"), prev=tx?tx.textContent:"", wasEdited=b.classList.contains("edited"), prevTs=b.dataset.edts||"";
  if(tx && !jumboApply(b, tx, text, true)) tx.textContent=text; b.dataset.edts=String(now); markEdited(b); initAudio();
  const ok=await deliverOut(R, env, mid, null, now, true);
  if(!ok){ if(tx && !jumboApply(b, tx, prev, false)) tx.textContent=prev; b.dataset.edts=prevTs; if(!wasEdited){ b.classList.remove("edited"); const m=b.querySelector(".edm"); if(m) m.remove(); }
    toast(t("Edit not sent — check your connection")); return; }
  refreshPreviews();
}

// ---------- deleting a message (v38) ----------
// "For me": the message leaves this device — its saved copy, the reactions, edits and votes that point at it,
// its media. "For everyone": our own message, within 48 hours, also leaves the other devices: a quiet
// {t:"del", m} envelope (signed in a group) that only the author's own message obeys; "This message was
// deleted" takes its place on every side. What someone already saw, saved or forwarded can't be taken back.
const DEL_WINDOW=48*3600*1000;
function delValid(env){ return !!(env && env.t==="del" && typeof env.m==="string" && MID_RE.test(env.m)); }
function delmMark(mid, how){ if(!mid) return; _meta.delm=_meta.delm||{}; _meta.delm[mid]=Object.assign({at:Date.now()}, how||{});
  const ks=Object.keys(_meta.delm); if(ks.length>600) ks.sort((a,b)=>(_meta.delm[a].at||0)-(_meta.delm[b].at||0)).slice(0,ks.length-600).forEach(k=>{ delete _meta.delm[k]; });
  localSaveSoon(); }
// remove the saved copies of these messages, and every reaction / edit / vote that points at them, and their media
async function histPurge(room, mids){
  if(!gHistKey || !mids || !mids.size) return;
  try{ const rm=await histKeyAsync(room); const db=await idb();
    const recs=await new Promise((res,rej)=>{ const out=[]; const rq=db.transaction("msgs").objectStore("msgs").index("room").openCursor(IDBKeyRange.only(rm));
      rq.onsuccess=e=>{ const c=e.target.result; if(c){ out.push({k:c.primaryKey, v:c.value}); c.continue(); } else res(out); }; rq.onerror=()=>rej(rq.error); });
    const dels=[];
    for(const x of recs){ try{ const o=JSON.parse(dec.decode(await aesDec(gHistKey,x.v.iv,x.v.ct)));
      if((o.mid && mids.has(o.mid)) || (o.env && typeof o.env.m==="string" && mids.has(o.env.m) && /^(react|edit|vote|del)$/.test(o.env.t||""))) dels.push(x.k); }catch(e){} }
    await new Promise(res=>{ const tx=db.transaction(["msgs","media"],"readwrite"); const ms=tx.objectStore("msgs"), md=tx.objectStore("media");
      dels.forEach(k=>ms.delete(k)); mids.forEach(m=>{ try{ md.delete(m); }catch(e){} }); tx.oncomplete=res; tx.onerror=res; tx.onabort=res; });
  }catch(e){}
  refreshPreviews();
}
function goneBubble(logEl, cls, tag, ts, opts){ opts=opts||{}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=goneEl(cls, tag, ts, opts); logEl.appendChild(d); scrollEl(logEl, false); return d; }
function goneEl(cls, tag, ts, opts){ opts=opts||{};
  const d=document.createElement("div"); d.className="bubble "+cls+" gone"; d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  if(tag) d.appendChild(whoEl(tag, opts.vf));
  const s=document.createElement("span"); s.className="gone-t"; s.append(icoEl("i-ban",""), cls==="sent" ? t("You deleted this message") : t("This message was deleted")); d.appendChild(s);
  metaRow(d, ts, null); return d; }
function viewOf(R){ if(R.logEl) return R; let V=null, ck=R.fromContact; if(ck && !R.group){ const tg=mergedTarget(contactFind(ck)); if(tg) ck=tg.ck; }
  rooms.forEach(x=>{ if(!V && x.logEl && (R.group ? x.rid===R.rid : x.fromContact===ck)) V=x; }); return V; }
function bubbleToGone(V, b){ if(!b || b.classList.contains("gone")) return;
  const cls=b.classList.contains("sent")?"sent":"recv", w=b.querySelector(":scope > .who");
  const nb=goneEl(cls, "", +b.dataset.ts||Date.now(), {mid:b.dataset.mid}); if(w) nb.insertBefore(w.cloneNode(true), nb.firstChild);
  b.replaceWith(nb); if(V.reacts) V.reacts.delete(b.dataset.mid); }
// the saved original o becomes "deleted" everywhere on this device
async function goneApply(R, o, show){ const hk=histKeyOf(R);
  await histPurge(hk, new Set([o.mid]));
  await histSave(hk, {dir:o.dir, mid:o.mid, ts:o.ts||Date.now(), who:o.who, vf:o.vf, env:{t:"gone"}});
  const V=viewOf(R); if(V){ const b=bubbleOf(V, o.mid);
    if(b) bubbleToGone(V, b); else if(show) goneBubble(V.logEl, o.dir, o.dir==="sent" ? "" : (R.group ? (o.who||"") : ""), o.ts||Date.now(), {mid:o.mid, vf:o.vf}); }
  refreshPreviews(); if(typeof searchStale==="function") searchStale(); }
async function onDelEnv(R, env, who, ts, mid, own){
  if(!delValid(env)) return;
  if(R.group && !own && env.vf!=="ok") return;                                       // unsigned or forged: ignored
  const want=own ? "sent" : "recv", hk=histKeyOf(R);
  const o=(await histLoad(hk)).find(r=>r && r.mid===env.m);
  if(!o){ delmMark(env.m, {d:want, pk:(R.group && !own) ? (env.pk||"") : "", ts:ts||Date.now()}); return; }   // not here yet: it won't show when it comes
  if(!o.env || o.env.t==="gone" || o.dir!==want) return;                            // only the author's own message obeys
  if(R.group && want==="recv" && (o.env.pk||"")!==(env.pk||"")) return;
  if((ts||Date.now())-(o.ts||0) > DEL_WINDOW+600000) return;
  await goneApply(R, o);
}
// a message arriving after its deletion (out of order, or delivered again): never shown
function goneOnArrival(R, env, who, ts, mid, own){
  const m=_meta.delm[mid]; if(!m) return false;
  if(m.d==="*") return true;                                                         // deleted here, for me
  const want=own ? "sent" : "recv"; if(m.d!==want) return false;
  if(R.group && want==="recv" && (m.pk||"")!==(env && env.pk || "")) return false;
  if((m.ts||0)-(ts||0) > DEL_WINDOW+600000) return false;
  goneApply(R, {dir:want, mid, ts, who, vf:env && env.vf}, true).catch(()=>{});
  return true;
}
function relayPaths(env){ const out=[]; if(!env) return out; if(typeof env.path==="string") out.push(env.path);
  if(Array.isArray(env.parts)) env.parts.forEach(x=>{ if(x && typeof x.p==="string") out.push(x.p); }); return out; }
function canDeleteForAll(R, b){ if(!R || !b || !b.classList.contains("sent") || b.classList.contains("gone") || !b.dataset.mid) return false;
  if(!(R.group || R.fromContact || R.paired)) return false;
  const st=b.querySelector(":scope > .meta .st"); if(st && st.dataset.st && st.dataset.st!=="sent" && st.dataset.st!=="rcvd") return false;   // not sent yet, or failed
  return Date.now()-(+b.dataset.ts||0) < DEL_WINDOW; }
let _delFor=null;
function askDelete(b){ const R=A(); if(!R || !b || !b.dataset.mid) return;
  _delFor={code:R.code, m:b.dataset.mid}; const all=canDeleteForAll(R, b);
  $("delAll").hidden=!all;
  $("delMsgNote").textContent= all ? t("“For everyone” removes it from the other devices too — but they may already have seen it.")
    : (b.classList.contains("sent") ? t("Only on this device. After 48 hours a message can no longer be deleted for everyone.") : t("Only on this device. The others keep their copy."));
  $("delMsgModal").classList.add("show"); }
async function deleteForMe(){ const f=_delFor; _delFor=null; $("delMsgModal").classList.remove("show"); const R=A(); if(!f || !R || R.code!==f.code) return;
  delmMark(f.m, {d:"*"}); const b=bubbleOf(R, f.m); if(b){ b.remove(); if(R.reacts) R.reacts.delete(f.m); }
  await histPurge(histKeyOf(R), new Set([f.m])); if(typeof searchStale==="function") searchStale(); toast(t("Message deleted")); }
async function deleteForAll(){ const f=_delFor; _delFor=null; $("delMsgModal").classList.remove("show"); const R=A(); if(!f || !R || R.code!==f.code) return;
  const b=bubbleOf(R, f.m); if(!canDeleteForAll(R, b)) return;
  const now=Date.now(), env={t:"del", m:f.m, body:t("🚫 This message was deleted")}, mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  initAudio(); const ok=await deliverOut(R, env, mid, null, now, true);
  if(!ok){ toast(t("Not deleted — check your connection")); return; }
  const hk=histKeyOf(R); const o=(await histLoad(hk)).find(r=>r && r.mid===f.m) || {dir:"sent", mid:f.m, ts:+b.dataset.ts||now};
  relayPaths(o.env).forEach(p=>deleteBlob(p));                                       // its photo / voice / document leaves the relay too
  await goneApply(R, Object.assign({}, o, {dir:"sent"}));
}
// ---------- reactions and replies ----------
// Both are ordinary end-to-end encrypted messages (same live channel, same mailbox, signed in groups): the
// relay learns nothing new. A reaction is {t:"react", m:<message id>, e:<emoji or "" to remove>}; a reply is
// a text message carrying q:{m, s, o, w} — the quoted id, a short snippet, whether the replier wrote the
// quoted message (o), and its author's name in a group (w). Both also carry a plain body so an older app
// shows something sensible.
const RX_QUICK=["❤️","😂","👍","😮","😢","🙏"];
const RX_MORE=["😍","🥰","😘","😊","😁","🤣","😅","😉","😎","🤔","🙄","😴","😡","🤯","🥳","😭","🤗","🤩","👏","🙌","💪","👌","🤝","✌️","🔥","💯","🎉","✨","💔","👀","🌹","☕"];
const MID_RE=/^[A-Za-z0-9_-]{1,64}$/;
function validRx(e){ return e==="" || (typeof e==="string" && e.length<=16 && /\p{Extended_Pictographic}/u.test(e) && !/[<>&"'A-Za-z0-9\s]/.test(e)); }
function validQuote(q){ return !!(q && typeof q==="object" && typeof q.m==="string" && MID_RE.test(q.m) && typeof q.s==="string"); }
function cleanQuote(q){ return { m:q.m, s:String(q.s).slice(0,160), o:q.o===1?1:0, w:typeof q.w==="string"?q.w.slice(0,40):"" }; }
function bubbleOf(R, m){ if(!R||!R.logEl||!m) return null; try{ return R.logEl.querySelector('.bubble[data-mid="'+CSS.escape(m)+'"]'); }catch(e){ return null; } }
function whoName(b){ const w=b && b.querySelector(".who"); return w && w.firstChild && w.firstChild.nodeType===3 ? w.firstChild.nodeValue.trim() : ""; }
function bubbleSnippet(b){ if(!b) return "";
  const tx=b.querySelector(".txt"); if(tx && tx.textContent.trim()) return tx.textContent.trim().replace(/\s+/g," ").slice(0,120);
  if(b.querySelector(".vc")) return t("🎤 Voice message");
  if(b.querySelector(".tapview,.imgph,img")) return t("📷 Photo");
  const ct=b.querySelector(".cl-t"); if(ct) return ct.textContent.slice(0,120);
  return "…"; }
// who wrote the quoted message, as seen by this device
function quoteAuthor(R, q, dir, who){
  const peer=R.peerName||dn(R.title)||t("Contact");
  if(dir==="sent") return q.o ? t("You") : (R.group ? (q.w||t("Member")) : peer);
  if(q.o) return R.group ? (who||t("Member")) : peer;                    // they quoted themselves
  const b=bubbleOf(R, q.m); if(b && b.classList.contains("sent")) return t("You");
  if(!R.group) return t("You");                                          // 1:1: the only other author is me
  return (q.w && q.w===myName) ? t("You") : (q.w||t("Member"));
}
function quoteEl(R, q, dir, who){
  const d=document.createElement("div"); d.className="quote"; d.dataset.ref=q.m;
  const n=document.createElement("span"); n.className="qn"; n.textContent=quoteAuthor(R, q, dir, who);
  const s=document.createElement("span"); s.className="qs"; s.textContent=q.s;
  d.appendChild(n); d.appendChild(s); return d;
}
function jumpToQuoted(R, m){
  const b=bubbleOf(R, m); if(!b){ toast(t("Original message no longer available")); return; }
  try{ b.scrollIntoView({block:"center", behavior:"smooth"}); }catch(e){ b.scrollIntoView(); }
  b.classList.remove("flash"); void b.offsetWidth; b.classList.add("flash"); setTimeout(()=>b.classList.remove("flash"),1500);
}
// reactions: per chat, message id -> actor -> {e, n, ts}; one reaction per person per message
function rxActor(R, own, env, who){
  if(own) return {k:"me", n:t("You")};
  if(!R.group) return {k:"peer", n:R.peerName||dn(R.title)||t("Contact")};
  return {k: env && env.pk ? "k:"+env.pk : "n:"+(who||""), n: who||t("Member")};
}
function rxApply(R, m, actor, e, ts){
  if(!R.reacts) R.reacts=new Map(); let mm=R.reacts.get(m); if(!mm){ mm=new Map(); R.reacts.set(m,mm); }
  const cur=mm.get(actor.k); if(cur && (cur.ts||0)>(ts||0)) return false;          // an older change arriving late
  if(e) mm.set(actor.k,{e, n:actor.n, ts:ts||Date.now()}); else if(cur) mm.set(actor.k,{e:"", n:actor.n, ts:ts||Date.now()});
  return true;
}
function rxRender(R, m){
  const b=bubbleOf(R, m); if(!b) return; let box=b.querySelector(":scope > .reacts");
  const mm=R.reacts && R.reacts.get(m); const by=new Map();
  if(mm) mm.forEach((v,k)=>{ if(!v.e) return; const g=by.get(v.e)||{n:0,names:[],mine:false}; g.n++; g.names.push(k==="me"?t("You"):v.n); if(k==="me") g.mine=true; by.set(v.e,g); });
  if(!by.size){ if(box) box.remove(); return; }
  if(!box){ box=document.createElement("div"); box.className="reacts"; b.appendChild(box); }
  box.textContent="";
  by.forEach((g,e)=>{ const c=document.createElement("button"); c.type="button"; c.className="rx"+(g.mine?" mine":""); c.dataset.e=e;
    c.textContent=e+(g.n>1?" "+g.n:""); c.title=g.names.join(", ")+(g.mine?" · "+t("Tap to remove your reaction"):""); box.appendChild(c); });
}
function onReactEnv(R, env, who, ts, mid, own){
  if(!env || typeof env.m!=="string" || !MID_RE.test(env.m) || !validRx(env.e)) return;
  if(R.group && !own && env.vf==="bad") return;                                    // a forged group reaction counts for nothing
  if(rxApply(R, env.m, rxActor(R, own, env, who), env.e, ts)) rxRender(R, env.m);
  histSave(histKeyOf(R),{dir:own?"sent":"recv",env,ts,who,mid,vf:env.vf});
}
async function sendReaction(R, m, e){
  if(!R || !m || !MID_RE.test(m)) return; if(!R.group && !R.fromContact && !R.paired) return;
  const mm=R.reacts && R.reacts.get(m); const cur=mm && mm.get("me"); const prev=cur ? cur.e : "";
  if(prev===e) e="";                                              // the same emoji again takes it back
  if(!prev && !e) return; if(!validRx(e)) return;
  const env={t:"react", m, e, body:e}; const mid=rid(); const now=Date.now(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  rxApply(R, m, {k:"me", n:t("You")}, e, now); rxRender(R, m); initAudio();
  const ok=await deliverOut(R, env, mid, null, now, true);
  if(!ok){ rxApply(R, m, {k:"me", n:t("You")}, prev, now+1); rxRender(R, m); toast(t("Reaction not sent — check your connection")); }
}
// picker
let _rxFor=null, _rxAt=0;   // {code, m}
function rxTargetOk(b){ return !!(b && b.dataset.mid && (b.classList.contains("sent")||b.classList.contains("recv")) && !b.classList.contains("fail")); }
function openPicker(b){
  const R=A(); if(!R || !rxTargetOk(b) || !R.logEl || !R.logEl.contains(b)) return;
  if($("msgInput").disabled) return;
  if(_rxFor && _rxFor.m===b.dataset.mid && Date.now()-_rxAt<600) return;   // touch double tap + the browser's own dblclick
  _rxFor={code:R.code, m:b.dataset.mid}; _rxAt=Date.now();
  const pk=$("rxPick"), q=$("rxQuick"), g=$("rxGrid");
  if(!q.childElementCount){ RX_QUICK.forEach(e=>{ const x=document.createElement("button"); x.type="button"; x.textContent=e; x.dataset.e=e; x.setAttribute("aria-label",e); q.appendChild(x); });
    RX_MORE.forEach(e=>{ const x=document.createElement("button"); x.type="button"; x.textContent=e; x.dataset.e=e; x.setAttribute("aria-label",e); g.appendChild(x); }); }
  const mine=R.reacts && R.reacts.get(b.dataset.mid) && R.reacts.get(b.dataset.mid).get("me");
  pk.querySelectorAll("button[data-e]").forEach(x=>x.classList.toggle("on", !!(mine && mine.e===x.dataset.e)));
  const gone=b.classList.contains("gone"); pk.classList.toggle("no-rx", gone); $("rxReply").hidden=gone;
  $("rxEdit").hidden=!editableBubble(b); $("rxCopy").hidden=!b.querySelector(":scope > .txt") || !!b.dataset.ui;
  const ph=!!b.dataset.photo; $("rxSave").hidden=!ph; $("rxFwd").hidden=!ph; if(ph) prefetchPhoto(b);
  g.hidden=true; pk.classList.remove("open-grid"); pk.hidden=false; placePicker(b);
}
function placePicker(b){
  const pk=$("rxPick"); if(pk.hidden || !b) return; const r=b.getBoundingClientRect(); const w=pk.offsetWidth, h=pk.offsetHeight;
  const bar=$("bar"); const minTop=(bar ? bar.getBoundingClientRect().bottom : 0)+6;
  const ap=$("app"), dy=(ap && ap.style.transform) ? ap.getBoundingClientRect().top : 0;   // fixed inside a transformed #app: offsets follow it
  let top=r.top-h-8; if(top<minTop) top=Math.max(minTop, Math.min(r.bottom+8, viewH()-h-8)); top-=dy;
  let left=b.classList.contains("sent") ? r.right-w : r.left; left=Math.max(8, Math.min(left, window.innerWidth-w-8));
  pk.style.top=Math.round(top)+"px"; pk.style.left=Math.round(left)+"px";
}
function closePicker(){ const pk=$("rxPick"); if(pk && !pk.hidden){ pk.hidden=true; } _rxFor=null; }
// replying
let _reply=null;   // {code, m, s, o, w}
function startReply(b){
  const R=A(); if(!R || !rxTargetOk(b) || $("msgInput").disabled) return;
  if(_edit) cancelReply();
  const own=b.classList.contains("sent"); const w=own ? "" : (R.group ? whoName(b) : "");
  _reply={code:R.code, m:b.dataset.mid, s:bubbleSnippet(b), o:own?1:0, w};
  $("rbName").textContent= own ? t("Replying to your message") : t("Replying to {name}",{name: R.group ? (w||t("Member")) : (R.peerName||dn(R.title)||t("Contact"))});
  $("rbText").textContent=_reply.s; $("replyBar").hidden=false; closePicker();
  try{ $("msgInput").focus(); }catch(e){}
}
function cancelReply(){ _reply=null; const rb=$("replyBar");
  if(_edit){ const d=_edit.draft||""; _edit=null; if(rb) rb.classList.remove("editing"); const ta=$("msgInput"); if(ta){ ta.value=d; ta.style.height="auto"; try{ ta.dispatchEvent(new Event("input",{bubbles:true})); }catch(e){} } }   // leaving an edit puts back what was in the composer
  if(rb) rb.hidden=true; }
// Card bubbles (a location, a group invitation): icon, title, a mono sub-line and one action.
function addCard(logEl, cls, card, tag, ts, opts){
  opts=opts||{}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble "+cls; d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  if(tag) d.appendChild(whoEl(tag, opts&&opts.vf));
  const row=document.createElement("div"); row.className="cardl";
  const ico=document.createElement("span"); ico.className="cl-ico"; if(ICON_OF[card.ico]) ico.appendChild(icoEl(ICON_OF[card.ico],"cio")); else ico.textContent=card.ico||""; row.appendChild(ico);
  const tx=document.createElement("div"); const tt=document.createElement("div"); tt.className="cl-t"; tt.textContent=card.title||""; tx.appendChild(tt);
  if(card.sub){ const ss=document.createElement("div"); ss.className="cl-s"; ss.textContent=card.sub; tx.appendChild(ss); }
  row.appendChild(tx); d.appendChild(row);
  if(card.action){ const a=document.createElement(card.action.href?"a":"button"); a.className="cl-btn"; a.textContent=card.action.label;
    if(card.action.href){ a.href=card.action.href; a.target="_blank"; a.rel="noopener noreferrer"; }
    else { a.type="button"; a.addEventListener("click",e=>{ e.stopPropagation(); card.action.onclick(); }); }
    d.appendChild(a); }
  if(cls==="sent"||cls==="recv") metaRow(d, ts, cls==="sent" ? (opts.st||"sent") : null);
  if(cls==="sent"){ d.addEventListener("click",()=>{ if(d.classList.contains("failed") && d._retry) d._retry(); }); }
  logEl.appendChild(d); scrollEl(logEl, cls==="sent"); return d;
}
// Location: shared only inside the encrypted message; "open in Maps" hands the coordinates to the phone's own
// maps app — nothing is fetched from a map provider by Gizleme itself.
function validLoc(env){ return env && env.t==="loc" && Number.isFinite(env.lat) && Number.isFinite(env.lng) && Math.abs(env.lat)<=90 && Math.abs(env.lng)<=180; }
function mapsUrl(lat,lng){ const q=lat+","+lng;
  if(/iphone|ipad|ipod/i.test(navigator.userAgent)) return "https://maps.apple.com/?ll="+q+"&q="+encodeURIComponent(q);
  if(/android/i.test(navigator.userAgent)) return "geo:"+q+"?q="+q;
  return "https://www.openstreetmap.org/?mlat="+lat+"&mlon="+lng+"#map=17/"+lat+"/"+lng; }
function locCard(env, mine){ const acc=env.acc?t("±{m} m",{m:env.acc})+" · ":""; return { ico:"📍", title: mine?t("My location"):t("Location"), sub: acc+env.lat.toFixed(5)+", "+env.lng.toFixed(5), action:{label:t("Open in Maps"), href:mapsUrl(env.lat,env.lng)} }; }
function ginvCard(env, who, dir){ const name=String(env.name||"Group").slice(0,40);
  return { ico:"👥", title: dir==="sent" ? t("Group “{name}” created",{name}) : t("{who} invited you to the group “{name}”",{who:who||t("Contact"),name}),
    sub: dir==="sent" ? t("invitation sent in this chat") : "", action:{label: dir==="sent"?t("Open the group"):(groupsLoad().some(g=>g.rid===env.rid)?t("Open the group"):t("Join the group")), onclick:()=>{ closeSidebar(); doJoinGroup(env.rid, unb64(env.gk), name, env.adm); }} }; }
function validGinv(env){ return env && env.t==="ginv" && typeof env.rid==="string" && /^[a-z0-9]{8,32}$/.test(env.rid) && typeof env.gk==="string" && env.gk.length>=40 && env.gk.length<=64 && /^[A-Za-z0-9+\/]+=*$/.test(env.gk) && (env.adm===undefined || (typeof env.adm==="string" && env.adm.length===88)); }
function groupAddIfNew(rid, gkB64, name, adm){ const l=groupsLoad(); if(l.some(g=>g.rid===rid)) return false; const g={rid,gk:gkB64,name:(name||"Group").slice(0,40),ts:Date.now()}; if(adm) g.adm=adm; l.push(g); groupsSave(l); return true; }
function openLightbox(url, opts){
  opts=opts||{}; const t_=t;   // the countdown label shadows t below
  const lb=document.createElement("div"); lb.className="lightbox";
  const img=new Image(); img.src=url; lb.appendChild(img);
  const close=document.createElement("button"); close.className="lb-close"; close.setAttribute("aria-label",t("Close")); close.appendChild(icoEl("i-x","")); lb.appendChild(close);
  let timer=null, closed=false;
  function done(){ if(closed) return; closed=true; if(timer) clearInterval(timer); document.removeEventListener("keydown",onKey); lb.remove(); opts.onClose&&opts.onClose(); }
  function onKey(e){ if(e.key==="Escape") done(); }
  close.addEventListener("click",done);
  lb.addEventListener("click",e=>{ if(e.target===lb) done(); });
  document.addEventListener("keydown",onKey);
  if(opts.countdown){
    const t=document.createElement("div"); t.className="lb-timer"; lb.appendChild(t);
    let left=opts.countdown; t.textContent=t_("disappears in {n}s",{n:left});
    timer=setInterval(()=>{ left--; if(left<=0){ done(); } else t.textContent=t_("disappears in {n}s",{n:left}); },1000);
  }
  document.body.appendChild(lb);
}
async function deleteBlob(path){ try{ await mboxFn("delblob",{path}); }catch(e){} }
function addImageSent(logEl, meta, localUrl, ts, opts){
  opts=opts||{}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble img-wrap sent"; d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  const img=new Image(); img.src=localUrl; img.style.cursor="pointer";
  if(opts.once===false){ img.className="keep"; } else img.style.maxWidth="160px";
  img.addEventListener("click",()=>openLightbox(localUrl,{}));
  d.appendChild(img);
  if(opts.once!==false){ const o=document.createElement("span"); o.className="once"; o.textContent=t("⦿ view once"); d.appendChild(o); }
  metaRow(d, ts, opts.st||"pending");
  d.addEventListener("click",e=>{ if(e.target===img) return; if(d.classList.contains("failed") && d._retry) d._retry(); });
  logEl.appendChild(d); scrollEl(logEl, true);
  return d;
}
function addImageRecvOnce(logEl, meta, tag, ts, mid, vf){
  const opts={vf}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble recv"; d.dataset.ts=ts; if(mid) d.dataset.mid=mid;
  if(tag) d.appendChild(whoEl(tag, opts&&opts.vf));
  const btn=document.createElement("div"); btn.className="tapview"; { const l=document.createElement("span"); iconText(l, t("📷 Photo")); const sm=document.createElement("small"); sm.textContent=t("tap to view — once only"); btn.append(l, sm); }
  d.appendChild(btn);
  metaRow(d, ts, null);
  logEl.appendChild(d); scrollEl(logEl);
  let opened=false;
  btn.addEventListener("click",async()=>{
    if(opened) return; opened=true; const prev=[...btn.childNodes]; btn.textContent=t("decrypting…");
    try{
      const url=await fetchImage(meta);
      markViewed(mid);                                   // never shown again, even after a reload
      openLightbox(url,{countdown:10,onClose:()=>{ try{URL.revokeObjectURL(url);}catch(e){} if(!tag) deleteBlob(meta.path);   // in a group the others still have to see it (the relay sweeps it)
        const x=document.createElement("div"); x.className="imgph"; iconText(x, t("📷 photo viewed")); btn.replaceWith(x); }});
    }catch(e){ opened=false; btn.textContent=""; btn.append(...prev); toast(e&&e.message==="gone"?t("This photo is no longer available"):t("Couldn't open this photo")); }
  });
  return d;
}
// Saved history, rendered the same way for contacts and groups: expired records skipped, view-once photos
// shown as "tap to view" until viewed, our own messages with their delivery state.
function renderHistory(R, past){
  const hk=histKeyOf(R); const dur=expFor(hk); const cut=dur?Date.now()-dur:0; if(dur) histSweep(hk,cut);
  const edits=editsFrom(R, past);
  for(const r of past){ if(!r||!r.env) continue; if(dur&&(r.ts||0)<=cut) continue;
    if(R.group && r.dir!=="sent" && r.mid && r.env.pk && r.env.t && r.env.t!=="txt") setTimeout(()=>{ const b=bubbleOf(R, r.mid); if(b && !b.dataset.pk) b.dataset.pk=r.env.pk; }, 0);
    if(r.env.t==="edit" || r.env.t==="del") continue;                    // applied to the message it edits (above)
    if(r.env.t==="gone"){ goneBubble(R.logEl, r.dir==="sent"?"sent":"recv", r.dir==="sent"?"":(R.group?(r.who||""):""), r.ts, {mid:r.mid, vf:r.vf}); continue; }
    if(r.env.t==="vote"){ if(validVote(r.env) && !(R.group && r.dir!=="sent" && r.vf==="bad")) voteApply(R, r.env.m, rxActor(R, r.dir==="sent", r.env, r.who), r.env.c, r.ts); continue; }
    if(RICH_T.has(r.env.t)){ renderRich(R, r.dir==="sent"?"sent":"recv", r.env, r.dir==="sent"?"":(R.group?(r.who||""):""), r.ts, {mid:r.mid, st:stateFor(r.mid), room:hk, vf:r.vf}); continue; }
    if(r.env.t==="exp"){ if(EXP_CHOICES.includes(r.env.v)) sysline(R.logEl, expLine(r.env.v, r.dir==="sent" ? null : (R.group ? (r.who||t("Member")) : (R.peerName||dn(R.title)||t("Contact"))))); continue; }
    if(r.env.t==="react"){ if(typeof r.env.m==="string" && MID_RE.test(r.env.m) && validRx(r.env.e) && !(R.group && r.dir!=="sent" && r.vf==="bad"))
        rxApply(R, r.env.m, r.dir==="sent" ? {k:"me",n:t("You")} : rxActor(R,false,r.env,r.who), r.env.e, r.ts); continue; }
    if(r.env.t==="img"){
      if(keptPhoto(r.env)){ addImageKept(R.logEl, r.dir==="sent"?"sent":"recv", r.env, r.dir==="sent"?"":(R.group?(r.who||""):""), r.ts, {mid:r.mid, st:stateFor(r.mid), room:hk, vf:r.vf}); continue; }
      if(r.dir==="recv"){ if(r.mid && _meta.viewed[r.mid]) continue; addImageRecvOnce(R.logEl,r.env,R.group?(r.who||""):"",r.ts,r.mid,r.vf); }
      else addText(R.logEl,"sent",t("📷 Photo"),"",false,r.ts,{mid:r.mid,st:stateFor(r.mid),ui:1});
      continue; }
    if(r.env.t==="aud"){ if(!validAud(r.env)) continue;
      addVoice(R.logEl, r.dir==="sent"?"sent":"recv", r.env, r.dir==="sent"?"":(R.group?(r.who||""):""), r.ts, {mid:r.mid, st:stateFor(r.mid), room:hk, vf:r.vf}); continue; }
    if(r.env.t==="loc"){ if(!validLoc(r.env)) continue;
      if(r.dir==="sent") addCard(R.logEl,"sent",locCard(r.env,true),"",r.ts,{mid:r.mid,st:stateFor(r.mid)}); else addCard(R.logEl,"recv",locCard(r.env,false),R.group?(r.who||""):"",r.ts,{mid:r.mid,vf:r.vf}); continue; }
    if(r.env.t==="ginv"){ if(!validGinv(r.env)) continue;
      if(r.dir==="sent") addCard(R.logEl,"sent",ginvCard(r.env,"","sent"),"",r.ts,{mid:r.mid,st:stateFor(r.mid)}); else addCard(R.logEl,"recv",ginvCard(r.env,r.who||R.title,"recv"),R.group?(r.who||""):"",r.ts,{mid:r.mid}); continue; }
    const qq=validQuote(r.env.q) ? cleanQuote(r.env.q) : null; const ed=r.mid ? edits.get(r.mid) : null; const body=ed ? ed.x : r.env.body;
    let tb;
    if(r.dir==="sent") tb=addText(R.logEl,"sent",body,"",false,r.ts,{mid:r.mid,st:stateFor(r.mid),quote:qq?quoteEl(R,qq,"sent",""):null,tx:1,edited:!!ed});
    else tb=addText(R.logEl,"recv",body,R.group?(r.who||""):"",false,r.ts,{mid:r.mid,vf:r.vf,quote:qq?quoteEl(R,qq,"recv",r.who):null,tx:1,pk:R.group?(r.env.pk||""):"",edited:!!ed});
    if(ed && tb) tb.dataset.edts=String(ed.ts);
  }
  refreshVoteCards(R);
  if(R.reacts) R.reacts.forEach((_,m)=>rxRender(R,m));
  seedSeen(R, past);
  if(R._newN && R.code===active) markNew(R, R._newN);
}
function sysline(logEl, t, warn){ const d=document.createElement("div"); d.className="sys"+(warn?" warnline":""); iconText(d, t); logEl.appendChild(d); scrollEl(logEl); }
// ---------- icons instead of emojis in the interface (v38): emojis stay for what people write and react with ----------
const ICON_OF={"📞":"i-phone","🔒":"i-lock","🔐":"i-lock","⚠️":"i-alert","⚠":"i-alert","⛔":"i-ban","🚫":"i-ban","⏱":"i-timer","🔗":"i-link","📷":"i-camera","🎤":"i-mic","📍":"i-pin","👥":"i-users","📄":"i-file","📊":"i-poll","🗳️":"i-poll","📅":"i-calendar","✏️":"i-edit"};
const ICON_RE=/^((?:[^:\n]{1,60}): )?(📞|🔒|🔐|⚠️|⚠|⛔|🚫|⏱|🔗|📷|🎤|📍|👥|📄|📊|🗳️|📅|✏️) ?/u;
function icoEl(id, cls){ const s=document.createElementNS("http://www.w3.org/2000/svg","svg"); s.setAttribute("class","ico "+(cls||"ii")); s.setAttribute("aria-hidden","true");
  const u=document.createElementNS("http://www.w3.org/2000/svg","use"); u.setAttribute("href","#"+id); s.appendChild(u); return s; }
// text whose first word is one of the interface emojis (after an optional "Name: "): an icon, then the rest
function iconText(el, text){ text=String(text==null?"":text); el.textContent=""; const m=ICON_RE.exec(text);
  if(!m){ el.textContent=text; return el; }
  if(m[1]) el.append(m[1]); el.append(icoEl(ICON_OF[m[2]])); el.append(text.slice(m[0].length)); return el; }
// The header shows one dot and a short word (online / offline / connecting…); the full explanation is kept
// and shown on tap (phone) or hover (desktop). kind: "online" | "offline" | "busy" | "warn".
function statusShort(kind, short){ if(short) return short; return kind==="online"?t("online"):kind==="busy"?t("connecting…"):kind==="warn"?t("not verified"):t("offline"); }
function setStatus(R, txt, secure, kind, short){
  R.statusText=txt; R.secure=!!secure; R.statusKind=kind||(secure?"online":"offline"); R.statusShort=statusShort(R.statusKind, short);
  if(R.code===active) applyStatus(R);
}
function applyStatus(R){
  const bar=$("bar"); if(!bar) return;
  const ty=typingLabel(R); bar.classList.toggle("typing", !!ty);
  $("statusText").textContent=ty || R.statusShort || statusShort(R.statusKind);
  const meta=$("peerMeta"); if(meta) meta.title=R.statusText||"";
  bar.classList.toggle("secure",!!R.secure);
  ["st-online","st-offline","st-busy","st-warn"].forEach(c=>bar.classList.remove(c)); bar.classList.add("st-"+(R.statusKind||"offline"));
}
const CANONICAL="https://gizleme.com";
function localRoomUrl(code){ const u=new URL(location.href); u.search=""; u.hash="room="+(code||active||""); return u.toString(); }
function inviteParts(){
  const inNew=$("join").dataset.mode==="newchat", adv=$("join").dataset.adv==="1";
  if(inNew && !adv && _pendingInvite){            // the normal case: an invite link
    persistPendingInvite();
    const url=_pendingInvite.url;
    return {room:"", url, msg:t("Join me on Gizleme 🔒 private chat, no phone number needed — just open this link:\n{url}",{url}), invite:true};
  }
  // Legacy room code: only a room the user is explicitly creating (the code in the field, or a plain manual
  // room that's open). Never a contact's secret daily rendezvous code or a group id.
  const R=active?rooms.get(active):null; const manual=!!(R&&!R.fromContact&&!R.group);
  const room=((inNew ? $("roomInput").value : (manual ? active : ""))||"").trim().toUpperCase();
  const url=CANONICAL+"/"+(room?"#room="+room:"");           // code in the fragment: never sent to any server
  const msg=t("Join me on Gizleme 🔒 encrypted chat — room code {room}\n{url}",{room,url});
  return {room,url,msg};
}
// Once the invite has gone out (the share sheet completed, or WhatsApp took over the screen), the new chat
// opens by itself: coming back to Gizleme lands in the conversation, not on the link page.
function openInviteChatIfStill(pi){
  if(!pi || _pendingInvite!==pi || $("join").dataset.mode!=="newchat" || $("join").dataset.adv==="1") return;
  connectRoom().catch(()=>{});
}
async function shareInvite(){
  const parts=inviteParts(), {url,msg}=parts, pi=parts.invite?_pendingInvite:null;
  // One combined text field is handled most consistently across targets (WhatsApp included).
  if(navigator.share){ try{ await navigator.share({text:msg}); openInviteChatIfStill(pi); return; }catch(e){ if(e&&e.name==="AbortError") return; } }
  try{ await navigator.clipboard.writeText(url); persistPendingInvite(); toast(t("Link copied")); }catch(e){ persistPendingInvite(); prompt(t("Copy this link:"),url); }
}
const IS_PHONE=/iPhone|iPad|iPod|Android/i.test(navigator.userAgent) || (navigator.platform==="MacIntel" && navigator.maxTouchPoints>1);
function shareWhatsApp(){
  const parts=inviteParts(), pi=parts.invite?_pendingInvite:null, text=encodeURIComponent(parts.msg);
  // The message is ready in WhatsApp; the person still taps Send there — no app can send on your behalf.
  // On a computer, wa.me opens WhatsApp (desktop or web) in a new tab, and the chat opens here meanwhile.
  if(!IS_PHONE){ window.open("https://wa.me/?text="+text,"_blank","noopener"); openInviteChatIfStill(pi); return; }
  // On a phone, WhatsApp's own link scheme hands the message straight to the app. wa.me goes through a web
  // page first, and on iPhone that page stays behind — blank, with an ✕ to close — when you come back. The
  // chat opens as soon as WhatsApp has taken over the screen; if it never does (not installed), a hint.
  let gone=false, stopT=null;
  const done=()=>{ document.removeEventListener("visibilitychange",onHide); clearTimeout(stopT); };
  const onHide=()=>{ if(document.visibilityState==="hidden" && !gone){ gone=true; done(); openInviteChatIfStill(pi); } };
  document.addEventListener("visibilitychange",onHide);
  stopT=setTimeout(done, 120000);
  setTimeout(()=>{ if(!gone && !document.hidden) toast(t("WhatsApp didn't open? Use “Share link” instead.")); }, 3000);
  location.href="whatsapp://send?text="+text;
}
function enableComposer(on){ $("msgInput").disabled=!on; $("sendBtn").disabled=!on; setAttach(!on); }
// ---------- the composer: + (attachments) ↔ keyboard, camera and mic while empty, send once typed ----------
function syncComposer(){ const c=$("composer"); if(c) c.classList.toggle("has-text", !!$("msgInput").value.trim()); }
let _panel="";   // "" or "plus": the attachments shown where the keyboard would be
function openPanel(which){ const c=$("composer"); if(!c) return; _panel=which||"";
  $("plusPanel").hidden=_panel!=="plus"; c.classList.toggle("panel", !!_panel);
  $("plusBtn").setAttribute("aria-label", _panel ? t("Keyboard") : t("Attach")); $("plusBtn").title=$("plusBtn").getAttribute("aria-label");
  if(_panel){ try{ $("msgInput").blur(); }catch(e){} closePicker(); }
  const L=A() && A().logEl; if(L) scrollEl(L); }
function closePanel(focus){ if(_panel) openPanel(""); if(focus){ try{ $("msgInput").focus(); }catch(e){} } }
async function sendFiles(list){ const fs=[...(list||[])].filter(f=>f && /^image\//.test(f.type||"image/")).slice(0,10); for(const f of fs){ await sendImage(f); } }
function setAttach(dis){ $("attachBtn").disabled=dis; ["plusBtn"].forEach(id=>{ const b=$(id); if(b) b.disabled=dis; }); if(dis) closePanel(false); const m=$("micBtn"); if(m) m.disabled=dis || !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.AudioContext); if(dis && rec) stopRec(false); }

// ---------- session ----------
function idleStatus(R){
  if(!R||!R.fromContact) return t("waiting for peer…");
  if(isPendingInvite(contactFind(R.fromContact))) return t("waiting for them to open your link — anything you write will be waiting for them");
  return t("offline — messages will be delivered when they reconnect"); }
function setIdle(R){
  if(!R||!R.fromContact) return setStatus(R, idleStatus(R), false, "busy", t("waiting…"));
  const pc=contactFind(R.fromContact);
  if(isPendingInvite(pc)){ if(pc.dead) return setStatus(R, t("this invite link was cancelled after three wrong codes — make a new one"), false, "warn", t("link cancelled"));
    if(inviteExpired(pc.x)) return setStatus(R, t("this invite link has expired — make a new one"), false, "warn", t("link expired"));
    return setStatus(R, idleStatus(R), false, "busy", t("link not opened yet")); }
  if(pc && pc.v3 && pc.dead && !pc.pk) return pc.nopin ? setStatus(R, t("wrong code — open the link again"), false, "warn", t("wrong code")) : setStatus(R, t("invite link already used — ask for a new one"), false, "warn", t("link used"));
  return setStatus(R, idleStatus(R), false, "offline");
}
async function establish(R, other, authed){
  if(R.establishing) return; R.establishing=true;          // back-to-back presence syncs must not pair twice
  let peerKey, secret, root, rootFp;
  try{
    peerKey=await importPub(unb64(other.pub));
    secret=await sharedSecret(R.kp.privateKey,peerKey);
    root=await hkdf(secret,"root"); rootFp=await fp(root);
  }catch(e){ R.establishing=false; return; }
  R.establishing=false;
  const changed=rootFp!==R.rootFp;
  R.peer=other; R.root=root; R.rootFp=rootFp; if(changed){ R.sendI=0; R.recvI=-1; } R.paired=true; R.authOk=!!authed;
  const nm=String(other.name||"Peer").replace(/[\r\n\t]+/g," ").slice(0,40); R.peerName=dn(nm); R.avatar=up(nm[0]||"?");
  const alias=R.fromContact ? (contactFind(R.fromContact)||{}).alias : "";
  if(alias){ R.title=alias; R.peerName=alias; R.avatar=up(alias[0]||"?"); }
  else if(realName(nm)) R.title=nm;                    // show the person's name in the tab/header
  setStatus(R, authed ? t("🔒 secure · same key as your first connection ✓") : t("🔒 secure · key {fp}",{fp:rootFp}), true, "online");
  if(R.code===active){ $("peerName").textContent=alias||dn(nm); $("peerAvatar").textContent=R.avatar; $("msgInput").disabled=false; $("sendBtn").disabled=false; setAttach(false); }
  if(changed){
    if(!R.connLineShown || !authed){ R.connLineShown=true;   // one short line (the details are in "Verify identity"), not twice in a row
      if(!(authed && R._linkLine && Date.now()-R._linkLine<120000)) sysline(R.logEl, t("🔒 End-to-end encrypted with {name}",{name:alias||dn(nm)})); }
    if(authed) healLinkUsed(R);
    // Derive a stable per-contact key from the first shared secret (relay never sees it),
    // then save/refresh the contact — identical on both sides, no extra round-trip.
    if(!R.fromContact){ try{ R.fromContact = await ckFromSecret(secret); }catch(e){}
      // From now on this room has a shared key: sign our public key with it and re-announce, so the other
      // side's checks (and every future connection) can verify us automatically.
      try{ await ensureTag(R); if(R.tag && R.channel) R.channel.track(presencePayload(R)); }catch(e){} }
    if(R.fromContact) contactUpsert(nm, R.fromContact);
    // Link-based contact: the identity safety code is bound to this first live key exchange (both sides
    // derive the same value), so someone who merely intercepted the link can't match it.
    try{ const c=contactFind(R.fromContact); if(c && c.inv && !c.sv) contactPatch(R.fromContact,{sv:b64(await hkdf(secret,"gz-safety/v2",16))}); }catch(e){}
    // Single-use link: the pairing was authenticated with the link key, so retire it for a key only our two
    // devices can compute. Persisted first; the room switches to it only once that succeeded.
    try{ const c=contactFind(R.fromContact);
      if(authed && c && c.inv && !c.rot && !c.v3){
        const old=R.fromContact, nk=await rotatedCKFromSecret(secret);
        const l=contactsLoad(); const i=l.findIndex(x=>x.ck===old);
        if(i>=0 && !l.some(x=>x.ck===nk)){
          const e=l[i]; e.prev=old; e.hk=e.hk||("c:"+old); e.ck=nk; e.rot=Date.now(); e.recon=Date.now(); delete e.is; delete e.pk; delete e.pp; delete e.v3; e.ts=Date.now();
          const q=(_meta.outq||{})[old]; if(q&&q.length){ _meta.outq[nk]=(_meta.outq[nk]||[]).concat(q); delete _meta.outq[old]; setTimeout(()=>flushOutq(nk,nk).catch(()=>{}),500); }
          contactsSave(l);
          R.fromContact=nk; await ensureTag(R); if(R.tag && R.channel) R.channel.track(presencePayload(R));
          sysline(R.logEl, t("🔒 Invite link closed · this chat has its own key"));
        } }
    }catch(e){}
    // Contacts from before the mailbox key chain: when both sides are live, authenticated under the contact key
    // and both still without a chain (each says so in presence), seed one from this session's ECDH secret — the
    // same on both ends, never sent. A device that has no chain while its account's other device already does
    // gets it from the vault instead (the peer stops offering once it holds one).
    try{ const c=contactFind(R.fromContact);
      if(authed && c && !c.kc && !isPendingInvite(c) && other && other.fsu===1 && secret){
        const kc=b64(await hkdf(secret,"gz-chain/live|"+R.fromContact)); contactPatch(R.fromContact,{kc, kce:epochNow()}); _chainCache.clear(); R.fsuRoot=rootFp;
        try{ await ensureTag(R); if(R.channel) R.channel.track(presencePayload(R)); }catch(_e){}
        sysline(R.logEl, t("🔐 Forward secrecy is now on for this chat: the mailbox key changes every week and old keys are destroyed."));
      } }catch(e){}
    // Reconciliation ends only once BOTH sides have seen each other sign with the new (post-link) key —
    // a mutual confirmation carried in presence (rk). Ending it unilaterally would let the two land on
    // different rendezvous rooms (one still serving the link key, one not) and never see each other again —
    // the exact "we're both offline to each other" failure this window exists to prevent. Until it ends the
    // rotated side keeps serving the link room and mailbox (reconActive), so a peer who hasn't rotated yet
    // stays reachable and converges onto the new key.
    try{ const c=contactFind(R.fromContact);
      if(c && c.prev){
        const directNew=!!(other && other.tag && await authVerify(R.fromContact, other.pub, other.tag));
        if(directNew!==!!R.peerNewKey){ R.peerNewKey=directNew; try{ if(R.channel) R.channel.track(presencePayload(R)); }catch(_e){} }
        if(c.recon && directNew && other && other.rk){ const l=contactsLoad(); const x=l.find(y=>y.ck===R.fromContact); if(x){ x.recon=0; delete x.hello; contactsSave(l); moveRoomSoon(R); } }
      } else R.peerNewKey=false;
    }catch(e){}
    renderTabs(); renderContacts(); updateNotifyUI(); updateVerifyUI(); updateCallUI(); callTryInvite();
    if(pushOn()) registerAllContacts();      // make sure we're reachable under this contact
  }
}
function unpair(R){ R.paired=false; R.peer=null; R.root=null; R.rootFp=""; R.authOk=false; R.recvI=-1; R.peerNewKey=false;
  // A saved contact keeps their name in the header while offline; only an anonymous manual room shows "Waiting for peer…".
  const known=!!(R.fromContact && realName(R.title));
  R.peerName=known?dn(R.title):t("Waiting for peer…"); R.avatar=known?up(R.title[0]||"?"):"?";
  setIdle(R);
  if(R.code===active){ $("peerName").textContent=R.peerName; $("peerAvatar").textContent=R.avatar; const keep=!!R.fromContact; $("msgInput").disabled=!keep; $("sendBtn").disabled=!keep; setAttach(!keep); updateVerifyUI(); } }
function presencePayload(R){ const p={id:R.id,name:myName,u:_acct}; if(!R.group){ p.pub=R.pubB64; if(R.tag) p.tag=R.tag; if(R.tagp) p.tagp=R.tagp; if(R.peerNewKey) p.rk=1;
    const c=R.fromContact?contactFind(R.fromContact):null; if(c && c.v3 && c.hello && reconActive(c)) p.hello=c.hello;
    // no mailbox chain with this contact yet: offer to start one from this live key exchange — and keep the offer
    // up for the session that just seeded it, so the slower side still takes the same one
    if(c && !isPendingInvite(c) && (!c.kc || (R.fsuRoot && R.fsuRoot===R.rootFp))) p.fsu=1;
  } else if(call && call.R===R && call.group) p.cc=call.cid; return p; }
function retrackAll(){ rooms.forEach(R=>{ try{ R.channel&&R.channel.track&&R.channel.track(presencePayload(R)); }catch(e){} }); }
// A join that errored or timed out (cold relay, flaky network) is retried with a fresh channel after a short
// backoff rather than left on "reconnecting…" — the library's own rejoin does not always come back.
function scheduleRejoin(R, ch){
  if(!R.bind || R.rejoinT) return;
  R.joinFails=(R.joinFails||0)+1; const wait=Math.min(30000, 3000*Math.pow(2, R.joinFails-1));
  R.rejoinT=setTimeout(()=>{ R.rejoinT=null; if(rooms.get(R.code)!==R || R.channel!==ch) return; if(ch.state==="joined") return;
    try{ ch.unsubscribe(); }catch(e){} R.bind(); }, wait);
}
async function onSync(R){
  const st=R.channel.presenceState(); const me=_acct; let others=[];
  for(const k in st) for(const m of st[k]) if(m.id&&m.id!==R.id) others.push(m);
  others=others.filter(m=>!(me && m.u===me));          // my own account on another device/tab is not a peer
  // someone who just opened our invite link announces the key agreement in presence: bind first, verify after
  for(const m of others){ if(m.hello && m.hello.e && R.fromContact){ const c=contactFind(R.fromContact);
    if(c && c.pk) await processHello(R.fromContact, m.hello.e, m.hello.n||m.name, m.hello.m, m.hello.fs===1, m.hello.ke);
    else if(c && c.prev && isForeignHello(c, m.hello.e)) noteLinkReuse(c, c.prev, m.hello.e); } }
  if(others.length===0){ R.multiSig=""; if(R.paired) unpair(R); else setIdle(R); return; }
  // Authenticate every candidate with the shared contact key. Only someone holding the key we established
  // together can sign their public key, so an unverified entry is never paired with — whatever it calls itself.
  const auth=await Promise.all(others.map(m=>verifyPeerTag(R,m)));
  const cur=R.paired&&R.peer ? R.peer : null;
  const eligible=others.filter((m,i)=> auth[i]==="ok" || auth[i]==="n/a" ||
      (auth[i]==="missing" && cur && m.id===cur.id && m.pub===cur.pub));   // in-session grace for the peer we're already on
  const stale=others.filter((m,i)=>auth[i]==="stale");
  const rejected=others.filter(m=>!eligible.includes(m) && !stale.includes(m));
  // Presence lists are in join order: after a reload the last entry is the live one. Among several different
  // people, prefer the contact this chat is with.
  let o=eligible.length?eligible[eligible.length-1]:null;
  const realTitle=(R.fromContact && (contactFind(R.fromContact)||{}).name) || R.title;
  if(eligible.length>1 && realName(realTitle)){ const known=eligible.filter(m=>realName(m.name)===realTitle); if(known.length) o=known[known.length-1]; }
  const sig=others.map(m=>m.id).sort().join(",")+"|"+auth.join(",");
  if(sig!==R.multiSig){ R.multiSig=sig;
    const nm=dn(R.title)||t("your contact");
    if(rejected.length && R.fromContact){
      const who=realName(rejected[0].name)||t("someone"); const missing=auth.includes("missing");
      if(o) sysline(R.logEl,t("⚠ Someone connected as “{who}” but couldn't prove they hold your shared key with {name} — ignored. You're connected to the verified {name}.",{who,name:nm}),true);
      else sysline(R.logEl, missing
        ? t("⚠ Couldn't verify the person connecting as “{who}”: their app didn't present a key check (older Gizleme — ask them to reload). Not connected live. Your messages still reach {name} through the encrypted mailbox.",{who,name:nm})
        : t("⚠ Couldn't verify this is {name}: their key check failed — someone may be in the middle. Nothing was shared with them. Your messages still reach {name} through the encrypted mailbox; verify in person before trusting a live chat.",{name:nm}), true);
    } else if(stale.length){
      { const cc=contactFind(R.fromContact);
        if(cc && cc.v3 && cc.pk){ if(!cc.expired && !cc.dead && !(cc.pin && cc.pinFails)) sysline(R.logEl, t("⚠ Someone opened your invite link with an older Gizleme that can't do the key agreement — not connected. Ask them to update the app (reload) and open the link again."), true); }
        else if(!(cc && cc.v3 && cc.hello)) sysline(R.logEl, t("{name}'s other device still uses the retired invite key — it will catch up when it syncs the account. Not connected live with that device.",{name:nm}), false); }
    } else if(others.length>1){
      const names=[...new Set(others.map(m=>realName(m.name)||t("someone")))];
      if(names.length===1) sysline(R.logEl, t("{name} is connected from {n} devices — you're paired with the most recent one; their other device still receives your messages.",{name:names[0],n:others.length}), false);
      else sysline(R.logEl, t("⚠ {n} people are in this chat: {names}. You're paired with {with}. If you weren't expecting anyone else, stop and compare the safety code (🛡) with them in person.",{n:others.length,names:names.join(", "),with:(o&&realName(o.name)||t("the most recent"))}), true);
    }
  }
  if(!o){ if(R.paired) unpair(R); if(stale.length && !rejected.length) setIdle(R); else setStatus(R, t("⚠ not verified — not connected live"), false, "warn"); return; }
  if(!R.paired||!R.peer||R.peer.id!==o.id||R.peer.pub!==o.pub) establish(R,o,auth[others.indexOf(o)]==="ok");
  else if(o.rk && !(R.peer.rk) && R.peerNewKey && R.fromContact){ R.peer=o;   // they now confirm seeing us on the new key too
    try{ const c=contactFind(R.fromContact); if(c && c.recon){ const l=contactsLoad(); const x=l.find(y=>y.ck===R.fromContact); if(x){ x.recon=0; delete x.hello; contactsSave(l); moveRoomSoon(R); } } }catch(e){} }
}

// envelope: {t:'txt',body} | {t:'img',path,k,iv,mime,once}
async function onMsg(R, {payload:p}){
  if(!p||p.from===R.id||!R.root) return;
  // Only the peer we are paired with, only in its own direction, and only with a counter that moves forward:
  // a relay cannot replay an earlier ciphertext as new, nor reflect our own message back to us.
  if(!R.peer || p.from!==R.peer.id || p.dir!==R.peer.id+">"+R.id) return;
  const ci=+p.i; if(!Number.isInteger(ci) || ci<=R.recvI) return; R.recvI=ci;
  if(p.mid){ if(!R.seen) R.seen=new Set(); if(R.seen.has(p.mid)) return; R.seen.add(p.mid); }
  showWire(R,p.ct);
  try{
    const mk=await hkdf(R.root,"msg|"+p.dir+"|"+p.i);
    const key=await aesKey(mk);
    const pt=await aesDec(key,p.iv,p.ct);
    const env=JSON.parse(dec.decode(pt));
    if(env.mid && env.mid!==p.mid) throw new Error("id mismatch");    // the id outside must be the id the sender sealed inside
    const now=Date.now();
    if(env.t==="call"){ callSignal(R, env, R.peerName).catch(()=>{}); return; }
    onInbound(R, env, "", now, p.mid, false, true);
    if(!QUIET_T.has(env.t)){ if(R.code===active) blinkEyes(); messageTone(R); }
  }catch(e){
    if(p.mid && R.seen) R.seen.delete(p.mid);            // not decrypted here: let the encrypted mailbox copy deliver it
    if(R.fromContact){ setTimeout(()=>fetchMailbox(R),1500); }   // e.g. we're paired with their other device — the mailbox has it
    else addText(R.logEl,"fail",t("⚠ could not decrypt this message"),"");   // manual room: nothing else will deliver it
  }
}
async function broadcast(R, env, mid){
  const dir=R.id+">"+R.peer.id; const i=R.sendI++;
  const mk=await hkdf(R.root,"msg|"+dir+"|"+i); const key=await aesKey(mk);
  const {iv,ct}=await aesEnc(key, enc.encode(JSON.stringify(Object.assign({},env,{mid}))));
  showWire(R,ct);
  try{ const r=await R.channel.send({type:"broadcast",event:"msg",payload:{from:R.id,dir,i,iv,ct,mid}}); return r==="ok"; }catch(e){ return false; }
}
async function sendText(){
  const R=A(); if(!R) return;
  const text=$("msgInput").value.trim(); if(!text) return;
  if(!R.group && !R.fromContact && !R.paired) return;       // manual room with no one here yet: nothing to send to
  if(_edit && _edit.code===R.code) return sendEdit(R, text);
  typingTick("");
  const env={t:"txt",body:text}; const mid=rid(); const now=Date.now();
  if(_reply && _reply.code===R.code) env.q={m:_reply.m, s:_reply.s, o:_reply.o, w:_reply.w};
  cancelReply();
  if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  $("msgInput").value=""; $("msgInput").style.height="auto"; initAudio();
  const el=addText(R.logEl,"sent",text,"",false,now,{mid,st:"pending",quote:env.q?quoteEl(R,cleanQuote(env.q),"sent",""):null,tx:1});
  await deliverOut(R, env, mid, el, now);
}
// Delivery: live broadcast when paired, and/or the encrypted mailbox (always for contacts and groups, so
// offline devices get it). The bubble shows pending → sent, or failed with tap-to-retry; nothing is saved
// to history until it has actually left the device.
async function deliverOut(R, env, mid, el, now, quiet){   // quiet: a reaction — no sound, no push; el may be null
  let ok=false;
  // a v3 invite nobody has opened yet: hold the message here rather than depositing it under the link key
  if(!R.group && R.fromContact && !R.paired){ const c=contactFind(R.fromContact); if(c && c.v3 && c.pk){ queueOut(R, env, mid, now, el); return true; } }
  try{
    if(R.group){ const signed=await signGroupEnv(R, env, mid); const a=await broadcastGroup(R,signed,mid); const b=await depositMailbox(R,mid,signed); ok=a||b; }
    else if(R.paired){ const a=await broadcast(R,env,mid); const b=R.fromContact ? await depositMailbox(R,mid,env) : false; ok=a||b; }
    else { ok=await depositMailbox(R,mid,env); }
  }catch(e){ ok=false; }
  if(ok){
    if(el) setMsgState(el, stateFor(mid)); histSave(histKeyOf(R),{dir:"sent",env,ts:now,mid});
    if(!quiet && !R.group && R.fromContact && !R.paired) notifyPeer(R.fromContact, "msg");     // they're not here: wake their device
  } else if(el){
    setMsgState(el,"failed"); el._retry=()=>{ el._retry=null; setMsgState(el,"pending"); deliverOut(R,env,mid,el,now,quiet); };
  }
  return ok;
}
async function sendLocation(){
  const R=A(); if(!R) return; if(!R.group && !R.fromContact && !R.paired) return;
  if(!navigator.geolocation){ toast(t("Location is not available on this device")); return; }
  toast(t("Getting your location…")); initAudio();
  navigator.geolocation.getCurrentPosition(pos=>{
    const c=pos.coords; const env={t:"loc",lat:+c.latitude.toFixed(6),lng:+c.longitude.toFixed(6),acc:Math.round(c.accuracy||0)};
    const mid=rid(); const now=Date.now(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
    const el=addCard(R.logEl,"sent",locCard(env,true),"",now,{mid,st:"pending"});
    deliverOut(R, env, mid, el, now);
  }, err=>{ toast(err && err.code===1 ? t("Location access was denied — allow it for gizleme.com in your browser settings") : t("Couldn't get your location — try again outside or with Wi-Fi on")); },
  {enableHighAccuracy:true, timeout:15000, maximumAge:20000});
}
// ---------- documents, polls, events ----------
// All four are ordinary encrypted messages. A document travels like a photo — encrypted on the device under a
// random key that only exists inside the message — split in pieces of 1.8 MB (10 MB at most); each device keeps
// its own encrypted copy once fetched. Votes (polls, and "going / can't go" for events) are quiet envelopes
// {t:"vote", m, c}, like reactions: the newest vote of each person counts.
const RICH_T=new Set(["doc","poll","evt"]);
const DOC_MAX=10*1024*1024, DOC_CHUNK=1800000;
function validBlobPath(p){ return typeof p==="string" && (/^[a-f0-9]{48}\.bin$/.test(p) || /^[A-Za-z0-9]{1,40}\/[a-f0-9]{16}\.bin$/.test(p)); }
function validDoc(e){ return !!(e && e.t==="doc" && typeof e.name==="string" && e.name.length>=1 && e.name.length<=200 && Number.isFinite(e.size) && e.size>=0 && e.size<=DOC_MAX
  && typeof e.mime==="string" && e.mime.length<=100 && typeof e.k==="string" && e.k.length===44 && Array.isArray(e.parts) && e.parts.length>=1 && e.parts.length<=6
  && e.parts.every(x=>x && validBlobPath(x.p) && typeof x.iv==="string" && x.iv.length===16)); }
function validPoll(e){ return !!(e && e.t==="poll" && typeof e.q==="string" && e.q.trim() && e.q.length<=300 && Array.isArray(e.o) && e.o.length>=2 && e.o.length<=12 && e.o.every(x=>typeof x==="string" && x.trim() && x.length<=100)); }
function validEvt(e){ return !!(e && e.t==="evt" && typeof e.ti==="string" && e.ti.trim() && e.ti.length<=120 && Number.isFinite(e.at) && Number.isFinite(e.end) && e.end>=e.at && e.end-e.at<=14*86400000
  && (e.loc===undefined || (typeof e.loc==="string" && e.loc.length<=200)) && (e.note===undefined || (typeof e.note==="string" && e.note.length<=500))); }
function validVote(e){ return !!(e && e.t==="vote" && typeof e.m==="string" && MID_RE.test(e.m) && Array.isArray(e.c) && e.c.length<=12 && e.c.every(i=>Number.isInteger(i) && i>=0 && i<12) && new Set(e.c).size===e.c.length); }
function richValid(e){ return e && (e.t==="doc" ? validDoc(e) : e.t==="poll" ? validPoll(e) : e.t==="evt" ? validEvt(e) : false); }
function fmtSize(n){ return n<1024 ? n+" "+t("B") : n<1048576 ? (n/1024).toFixed(n<10240?1:0)+" "+t("kB") : (n/1048576).toFixed(1)+" "+t("MB"); }
function fileExt(name){ const m=/\.([A-Za-z0-9]{1,8})$/.exec(name||""); return m ? m[1].toUpperCase() : ""; }
async function uploadChunks(bytes){
  const key=crypto.getRandomValues(new Uint8Array(32)), ck=await aesKey(key), parts=[];
  for(let o=0; o===0 || o<bytes.length; o+=DOC_CHUNK){ const iv=crypto.getRandomValues(new Uint8Array(12));
    const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv}, ck, bytes.subarray(o, o+DOC_CHUNK));
    const r=await mboxFn("putblob",{data:b64(ct)}); const path=r && r.data && r.data.ok && r.data.path;
    if(!path){ const code=(r&&r.data&&r.data.error)||""; throw new Error(code==="rate_limited" ? t("too many files — wait a minute") : t("check your connection")); }
    parts.push({p:path, iv:b64(iv)}); if(!bytes.length) break; }
  return {k:b64(key), parts};
}
async function fetchChunks(env){ const ck=await aesKey(unb64(env.k)), out=[]; let n=0;
  for(const x of env.parts){ const { data }=client.storage.from(BUCKET).getPublicUrl(x.p); const resp=await fetch(data.publicUrl,{cache:"no-store"}); if(!resp.ok) throw new Error("gone");
    const pt=new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(x.iv)}, ck, await resp.arrayBuffer())); out.push(pt); n+=pt.length; }
  const all=new Uint8Array(n); let o=0; for(const c of out){ all.set(c,o); o+=c.length; } return all; }
async function richBytes(room, mid, env, ts){ let b=mid ? await mediaGet(mid) : null; if(b) return b;
  b=await fetchChunks(env); if(mid && room) await mediaPut(room, mid, b, ts); return b; }
// fetched once on arrival, even with the chat closed, so it outlives the relay's 14 days (big documents: on first open)
function richKeepSoon(room, mid, env, ts){ if(env.t==="doc" && env.size<=5*1048576) richBytes(room, mid, env, ts).catch(()=>{}); }
function renderRich(V, cls, env, tag, ts, opts){
  if(!V || !V.logEl || !richValid(env)) return null; opts=opts||{};
  if(env.t==="doc") return addDocBubble(V, cls, env, tag, ts, opts);
  return addVoteBubble(V, cls, env, tag, ts, opts);
}
function bubbleShell(V, cls, tag, ts, opts, extra){ ensureDaySep(V.logEl, ts); const d=document.createElement("div"); d.className="bubble "+cls+(extra?" "+extra:""); d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  if(tag) d.appendChild(whoEl(tag, opts.vf)); return d; }
function bubbleDone(V, d, cls, ts, opts){ if(cls==="sent"||cls==="recv") metaRow(d, ts, cls==="sent" ? (opts.st||"sent") : null);
  if(cls==="sent") d.addEventListener("click",e=>{ if(d.classList.contains("failed") && d._retry && !(e.target.closest && e.target.closest("button"))) d._retry(); });
  V.logEl.appendChild(d); scrollEl(V.logEl, cls==="sent"); return d; }
// --- documents ---
function addDocBubble(V, cls, env, tag, ts, opts){
  const d=bubbleShell(V, cls, tag, ts, opts, "docb"); d._rich={env, room:opts.room, mid:opts.mid};
  const row=document.createElement("div"); row.className="cardl";
  const ico=document.createElement("span"); ico.className="doc-ico"; ico.textContent=fileExt(env.name).slice(0,4)||"DOC"; row.appendChild(ico);
  const tx=document.createElement("div"); tx.className="doc-tx"; const tt=document.createElement("div"); tt.className="cl-t doc-n"; tt.textContent=env.name; tx.appendChild(tt);
  const ss=document.createElement("div"); ss.className="cl-s"; ss.textContent=fmtSize(env.size); tx.appendChild(ss); row.appendChild(tx); d.appendChild(row);
  const b=document.createElement("button"); b.type="button"; b.className="cl-btn"; b.textContent=t("Open"); b.addEventListener("click",e=>{ e.stopPropagation(); openDoc(d, b); }); d.appendChild(b);
  if(opts.mid) docPrepare(d).catch(()=>{});            // ready in advance, so one tap opens it (iPhone needs the tap itself)
  return bubbleDone(V, d, cls, ts, opts);
}
async function docPrepare(d){ if(d._file) return d._file; const x=d._rich; if(!x) return null;
  if(!d._fileP) d._fileP=(async()=>{ let b=x.mid ? await mediaGet(x.mid) : null; if(!b) return null; return (d._file=new File([b], x.env.name, {type:x.env.mime||"application/octet-stream"})); })();
  return d._fileP; }
function handFile(f){
  if(IS_IOS && navigator.canShare && navigator.canShare({files:[f]})){ navigator.share({files:[f]}).catch(()=>{}); return; }
  const a=document.createElement("a"); a.href=URL.createObjectURL(f); a.download=f.name; document.body.appendChild(a); a.click(); setTimeout(()=>{ try{ URL.revokeObjectURL(a.href); }catch(e){} a.remove(); }, 8000); }
async function openDoc(d, btn){
  if(d._file){ handFile(d._file); return; }
  const x=d._rich; if(!x) return; const lab=btn.textContent; btn.disabled=true; btn.textContent=t("decrypting…");
  try{ const b=await richBytes(x.room, x.mid, x.env, +d.dataset.ts); d._file=new File([b], x.env.name, {type:x.env.mime||"application/octet-stream"});
    btn.disabled=false; if(IS_IOS){ btn.textContent=t("Ready — tap to open"); return; } btn.textContent=lab; handFile(d._file); }
  catch(e){ btn.disabled=false; btn.textContent=lab; toast(e && e.message==="gone" ? t("This file is no longer available") : t("Couldn't open this file")); }
}
async function sendDoc(file){
  const R=A(); if(!file || !R) return; if(!R.group && !R.fromContact && !R.paired) return;
  if(file.size>DOC_MAX){ toast(t("File too large — 10 MB at most")); return; }
  initAudio(); const mid=rid(), now=Date.now(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  const name=String(file.name||"document").replace(/[\u0000-\u001f\\/]+/g,"_").slice(0,200), mime=String(file.type||"application/octet-stream").slice(0,100);
  const shell={t:"doc", name, size:file.size, mime, k:"A".repeat(43)+"=", parts:[{p:"0".repeat(48)+".bin", iv:"A".repeat(16)}]};
  const el=addDocBubble(R, "sent", shell, "", now, {mid:null, st:"pending"}); el.dataset.mid=mid;
  const go=async()=>{ const bytes=new Uint8Array(await file.arrayBuffer()); const up=await uploadChunks(bytes);
    const env={t:"doc", name, size:bytes.length, mime, k:up.k, parts:up.parts, body:"📄 "+name};
    el._rich={env, room:histKeyOf(R), mid}; el._file=new File([bytes], name, {type:mime});
    await mediaPut(histKeyOf(R), mid, bytes, now); await deliverOut(R, env, mid, el, now); };
  try{ await go(); }catch(e){ setMsgState(el,"failed"); el._retry=()=>{ el._retry=null; setMsgState(el,"pending"); go().catch(()=>{ setMsgState(el,"failed"); }); };
    toast(t("File not sent — ")+(e&&e.message?e.message:t("check your connection"))); }
}
// --- polls and events (with "going / can't go"), and the votes on them ---
function voteApply(R, m, actor, c, ts){ if(!R.votes) R.votes=new Map(); let mm=R.votes.get(m); if(!mm){ mm=new Map(); R.votes.set(m,mm); }
  const cur=mm.get(actor.k); if(cur && (cur.ts||0)>(ts||0)) return false; mm.set(actor.k,{c:c.slice(), n:actor.n, ts:ts||Date.now()}); return true; }
function onVoteEnv(R, env, who, ts, mid, own){
  if(!validVote(env)) return; if(R.group && !own && env.vf==="bad") return;
  histSave(histKeyOf(R),{dir:own?"sent":"recv",env,ts,who,mid,vf:env.vf});
  let V=R.logEl ? R : null; if(!V && !R.group && R.fromContact){ const tg=mergedTarget(contactFind(R.fromContact)); const ck=tg?tg.ck:R.fromContact; rooms.forEach(x=>{ if(x.logEl && x.fromContact===ck) V=x; }); }
  const T=V||R; voteApply(T, env.m, rxActor(R, own, env, who), env.c, ts); if(V){ const b=bubbleOf(V, env.m); if(b) paintVotes(V, b); }
}
function refreshVoteCards(R){ if(!R || !R.logEl) return; R.logEl.querySelectorAll(":scope > .bubble.voteb").forEach(b=>paintVotes(R,b)); }
function myVote(R, m){ const mm=R.votes && R.votes.get(m); const v=mm && mm.get("me"); return v ? v.c : []; }
async function castVote(R, m, c){
  const now=Date.now(); voteApply(R, m, {k:"me", n:t("You")}, c, now); const b=bubbleOf(R, m); if(b) paintVotes(R, b);
  const env={t:"vote", m, c, body:"🗳️"}; const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  deliverOut(R, env, mid, null, now, true).catch(()=>{}); }
function fmtEvtTime(at, end){ const a=new Date(at), e=new Date(end), L=LOC();
  const day=a.toLocaleDateString(L,{weekday:"long", day:"numeric", month:"long"}), hm=x=>x.toLocaleTimeString(L,{hour:"2-digit", minute:"2-digit"});
  return a.toDateString()===e.toDateString() ? day+" · "+hm(a)+" – "+hm(e) : day+" "+hm(a)+" → "+e.toLocaleDateString(L,{day:"numeric", month:"short"})+" "+hm(e); }
function addVoteBubble(V, cls, env, tag, ts, opts){
  const d=bubbleShell(V, cls, tag, ts, opts, "voteb"); d._vote=env;
  const box=document.createElement("div"); box.className=env.t==="poll" ? "poll" : "evt";
  if(env.t==="poll"){
    const q=document.createElement("div"); q.className="pq"; q.textContent=env.q; box.appendChild(q);
    const h=document.createElement("div"); h.className="ph"; h.textContent=env.multi ? t("Choose one or more") : t("Choose one"); box.appendChild(h);
    env.o.forEach((o,i)=>{ const b=document.createElement("button"); b.type="button"; b.className="po"; b.dataset.i=i;
      b.innerHTML='<span class="pc"></span><span class="pt"></span><span class="pn">0</span><span class="pbar"><i></i></span>'; b.querySelector(".pt").textContent=o; box.appendChild(b); });
    const f=document.createElement("div"); f.className="pf"; box.appendChild(f);
  } else {
    const ttl=document.createElement("div"); ttl.className="et"; ttl.textContent=env.ti; box.appendChild(ttl);
    const dd=document.createElement("div"); dd.className="ed"; dd.textContent=fmtEvtTime(env.at, env.end); box.appendChild(dd);
    if(env.loc){ const l=document.createElement("div"); l.className="el"; iconText(l, "📍 "+env.loc); box.appendChild(l); }
    if(env.note){ const n=document.createElement("div"); n.className="en"; n.textContent=env.note; box.appendChild(n); }
    const rs=document.createElement("div"); rs.className="er";
    [t("✓ Going"), t("✕ Can't go")].forEach((lab,i)=>{ const b=document.createElement("button"); b.type="button"; b.className="po rsvp"; b.dataset.i=i; b.innerHTML='<span class="pt"></span> <b class="pn">0</b>'; b.querySelector(".pt").textContent=lab; rs.appendChild(b); });
    box.appendChild(rs);
    const ics=document.createElement("button"); ics.type="button"; ics.className="cl-btn ics"; ics.textContent=t("Add to calendar"); ics.addEventListener("click",e=>{ e.stopPropagation(); addToCalendar(env, d.dataset.mid); }); box.appendChild(ics);
  }
  d.appendChild(box); bubbleDone(V, d, cls, ts, opts); paintVotes(V, d); return d;
}
function paintVotes(V, b){ const env=b && b._vote; if(!env) return; const m=b.dataset.mid; const mm=(V.votes && V.votes.get(m)) || new Map();
  const n=env.t==="poll" ? env.o.length : 2, counts=new Array(n).fill(0), names=new Array(n).fill(0).map(()=>[]); let voters=0;
  mm.forEach(v=>{ const c=v.c.filter(i=>i<n).slice(0, env.t==="poll" && env.multi ? n : 1); if(c.length) voters++; c.forEach(i=>{ counts[i]++; names[i].push(v.n); }); });
  const mine=myVote(V, m), max=Math.max(1, ...counts);
  b.querySelectorAll(".po").forEach(x=>{ const i=+x.dataset.i; x.classList.toggle("on", mine.includes(i)); x.querySelector(".pn").textContent=counts[i]||0; x.title=names[i].join(", ");
    const bar=x.querySelector(".pbar i"); if(bar) bar.style.width=Math.round(100*(counts[i]||0)/Math.max(max, voters||1))+"%"; });
  const f=b.querySelector(".pf"); if(f) f.textContent= voters ? t(voters>1?"{n} votes":"{n} vote",{n:voters}) : t("No votes yet"); }
function voteTap(btn){ const b=btn.closest(".bubble"); const R=A(); if(!R || !b || !b._vote || !b.dataset.mid || $("msgInput").disabled) return;
  const env=b._vote, i=+btn.dataset.i, cur=myVote(R, b.dataset.mid); let c;
  if(env.t==="poll" && env.multi) c= cur.includes(i) ? cur.filter(x=>x!==i) : cur.concat(i).sort((a,z)=>a-z);
  else c= cur.length===1 && cur[0]===i ? [] : [i];
  castVote(R, b.dataset.mid, c); }
function icsEsc(s){ return String(s||"").replace(/\\/g,"\\\\").replace(/[,;]/g,m=>"\\"+m).replace(/\r?\n/g,"\\n"); }
function icsTime(ms){ return new Date(ms).toISOString().replace(/[-:]/g,"").replace(/\.\d{3}/,""); }
function addToCalendar(env, mid){
  const lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Gizleme//EN","CALSCALE:GREGORIAN","BEGIN:VEVENT","UID:"+(mid||rid())+"@gizleme.com","DTSTAMP:"+icsTime(Date.now()),
    "DTSTART:"+icsTime(env.at),"DTEND:"+icsTime(env.end),"SUMMARY:"+icsEsc(env.ti)];
  if(env.loc) lines.push("LOCATION:"+icsEsc(env.loc)); if(env.note) lines.push("DESCRIPTION:"+icsEsc(env.note)); lines.push("END:VEVENT","END:VCALENDAR");
  const txt=lines.join("\r\n")+"\r\n", name=(env.ti.replace(/[^\p{L}\p{N} _-]+/gu,"").trim().slice(0,40)||"event")+".ics";
  if(IS_IOS){ location.href="data:text/calendar;charset=utf-8,"+encodeURIComponent(txt); return; }   // Safari offers "Add to Calendar"
  handFile(new File([txt], name, {type:"text/calendar"})); }
// the forms
function openPollModal(){ const l=$("pollOpts"); l.innerHTML=""; $("pollQ").value=""; $("pollMulti").checked=false; addPollOpt(); addPollOpt(); $("pollModal").classList.add("show"); setTimeout(()=>{ try{ $("pollQ").focus(); }catch(e){} },60); }
function addPollOpt(){ const l=$("pollOpts"); if(l.children.length>=12) return; const i=document.createElement("input"); i.maxLength=100; i.placeholder=t("Option {n}",{n:l.children.length+1});
  i.addEventListener("input",()=>{ const all=[...l.children]; if(all[all.length-1]===i && i.value.trim() && all.length<12) addPollOpt(); }); l.appendChild(i); }
function sendPoll(){ const R=A(); if(!R) return; const q=$("pollQ").value.trim().slice(0,300); const o=[...$("pollOpts").children].map(x=>x.value.trim().slice(0,100)).filter(Boolean);
  if(!q){ toast(t("Write the question")); return; } if(o.length<2){ toast(t("Give at least two options")); return; }
  const env={t:"poll", q, o:o.slice(0,12), body:"📊 "+q}; if($("pollMulti").checked) env.multi=1;
  $("pollModal").classList.remove("show"); sendRich(R, env); }
function openEvtModal(){ const n=new Date(Date.now()+3600000); n.setMinutes(0,0,0); const p=x=>String(x).padStart(2,"0");
  $("evtTi").value=""; $("evtLoc").value=""; $("evtNote").value=""; $("evtDate").value=n.getFullYear()+"-"+p(n.getMonth()+1)+"-"+p(n.getDate()); $("evtTime").value=p(n.getHours())+":"+p(n.getMinutes()); $("evtDur").value="3600000";
  $("evtModal").classList.add("show"); setTimeout(()=>{ try{ $("evtTi").focus(); }catch(e){} },60); }
function sendEvt(){ const R=A(); if(!R) return; const ti=$("evtTi").value.trim().slice(0,120); if(!ti){ toast(t("Give the event a name")); return; }
  const at=new Date($("evtDate").value+"T"+($("evtTime").value||"00:00")).getTime(); if(!Number.isFinite(at)){ toast(t("Pick a date")); return; }
  const env={t:"evt", ti, at, end:at+(+$("evtDur").value||3600000)}; const loc=$("evtLoc").value.trim().slice(0,200), note=$("evtNote").value.trim().slice(0,500); if(loc) env.loc=loc; if(note) env.note=note;
  env.body="📅 "+ti+" — "+fmtEvtTime(env.at, env.end); $("evtModal").classList.remove("show"); sendRich(R, env); }
function sendRich(R, env){ if(!R.group && !R.fromContact && !R.paired) return; initAudio(); const mid=rid(), now=Date.now(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  const el=renderRich(R, "sent", env, "", now, {mid, st:"pending"}); deliverOut(R, env, mid, el, now).catch(()=>{}); }
// A two-person chat grows into a group: a new group is created, the contact is told inside this encrypted
// chat (their app adds the group, live or from the mailbox), and the invite link for the other people is
// offered right away. The 1:1 history stays where it is — it is not copied into the group.
let _ginvPending=null;
async function convertToGroup(){
  const R=A(); if(!R||R.group||!R.fromContact) return;
  const c=contactFind(R.fromContact); const other=(c&&(c.alias||dn(c.name)))||dn(R.title)||t("Friend"); const me=realName(myName)||t("Me");
  const v=prompt(t("Group name:"), me+" & "+other); if(v===null) return;
  const gname=(v.trim()||(me+" & "+other)).slice(0,40);
  const grid=newRid(); const gk=crypto.getRandomValues(new Uint8Array(32)); const gkB64=b64(gk);
  let adm=""; try{ adm=(await identEnsure()).pk; }catch(e){}
  const env={t:"ginv",rid:grid,gk:gkB64,name:gname}; if(adm) env.adm=adm; const mid=rid(); const now=Date.now(); if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  const el=addCard(R.logEl,"sent",ginvCard(env,"","sent"),"",now,{mid,st:"pending"});
  deliverOut(R, env, mid, el, now).catch(()=>{});
  await doJoinGroup(grid, gk, gname, adm);
  const G=A(); if(G&&G.logEl) sysline(G.logEl, t("🔒 Group created from your chat with {name} — they have been invited.",{name:other}));
  _ginvPending={rid:grid,gk:gkB64,name:gname,adm};
  $("ginvTitle").textContent=t("Group “{name}” created",{name:gname}); $("ginvSub").textContent=t("{name} has been invited.",{name:other});
  $("ginvModal").classList.add("show");
}
// A photo is view-once while the chat's timer runs; with the timer off it is kept — in the chat, on both sides —
// and this device keeps its own encrypted copy (the relay sweeps its ciphertext after 14 days).
async function sendImage(file){
  const R=A(); if(!file||!R) return; if(!R.group && !R.fromContact && !R.paired) return; initAudio();
  const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid); const now=Date.now(); const once=expFor(histKeyOf(R))>0;
  const purl=URL.createObjectURL(file); const el=addImageSent(R.logEl, null, purl, now, {mid, st:"pending", once}); if(once) setTimeout(()=>{ try{ URL.revokeObjectURL(purl); }catch(e){} }, 60000);
  try{ await sendImageMeta(R, file, el, mid, now, once); }
  catch(e){ setMsgState(el,"failed"); el._retry=()=>sendImageRetry(R,file,el,mid,now,once); toast(t("Photo not sent — ")+(e&&e.message?e.message:t("check your connection"))); }
}
async function sendImageMeta(R, file, el, mid, now, once){
  const meta=await uploadImage(file); meta.t="img"; meta.once=once;
  if(!once){ el._meta=meta; el.dataset.mime=meta.mime||"image/jpeg"; el.dataset.photo="1"; await mediaPut(histKeyOf(R), mid, meta._bytes, now); }
  await deliverOut(R, meta, mid, el, now);
}
async function sendImageRetry(R,file,el,mid,now,once){ el._retry=null; setMsgState(el,"pending");
  try{ await sendImageMeta(R, file, el, mid, now, once!==false); }
  catch(e){ setMsgState(el,"failed"); el._retry=()=>sendImageRetry(R,file,el,mid,now,once); } }
// a kept photo: shown in the chat, from this device's copy (fetched once from the relay and kept, encrypted)
function keptPhoto(env){ return !!(env && env.t==="img" && env.once===false && validImg(env)); }
async function keptBytes(room, mid, meta, ts){ let b=mid ? await mediaGet(mid) : null; if(b) return b;
  if(!validImg(meta)) throw new Error("bad"); b=await fetchBytes(meta); if(mid && room) await mediaPut(room, mid, b, ts); return b; }
function keepPhotoSoon(room, mid, meta, ts){ keptBytes(room, mid, meta, ts).catch(()=>{}); }   // fetched on arrival, even with the chat closed
function addImageKept(logEl, cls, meta, tag, ts, opts){
  opts=opts||{}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble img-wrap "+cls; d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  d._meta=meta; d.dataset.mime=meta.mime||"image/jpeg";
  if(tag) d.appendChild(whoEl(tag, opts.vf));
  const ph=document.createElement("div"); ph.className="imgph"; iconText(ph, t("📷 Photo")); d.appendChild(ph);
  metaRow(d, ts, cls==="sent" ? (opts.st||"sent") : null);
  logEl.appendChild(d); scrollEl(logEl, cls==="sent");
  keptBytes(opts.room, opts.mid, meta, ts).then(bytes=>{
    const url=URL.createObjectURL(new Blob([bytes],{type:meta.mime||"image/jpeg"}));
    const img=new Image(); img.className="keep"; img.alt=t("Photo"); img.src=url; img.addEventListener("click",()=>openLightbox(url,{}));
    img.onload=()=>{ if(logEl.scrollHeight-logEl.scrollTop-logEl.clientHeight<480) scrollEl(logEl); };
    ph.replaceWith(img); d.dataset.photo="1";
  }).catch(()=>{ iconText(ph, t("📷 This photo is no longer available")); ph.classList.add("gone"); });
  return d;
}
// ---- saving a kept photo, forwarding it ----
async function photoFileOf(b){ const R=A(); const meta=b._meta; const bytes=await keptBytes(R?histKeyOf(R):"", b.dataset.mid, meta, +b.dataset.ts);
  const mime=b.dataset.mime||"image/jpeg", ext= mime==="image/png" ? "png" : mime==="image/webp" ? "webp" : "jpg";
  const d=new Date(+b.dataset.ts||Date.now()), p=n=>String(n).padStart(2,"0");
  return new File([bytes], "gizleme-"+d.getFullYear()+p(d.getMonth()+1)+p(d.getDate())+"-"+p(d.getHours())+p(d.getMinutes())+p(d.getSeconds())+"."+ext, {type:mime}); }
function prefetchPhoto(b){ if(!b || !b.dataset.photo || b._file) return; b._fileP=photoFileOf(b).then(f=>{ b._file=f; return f; }).catch(()=>null); }
const IS_IOS=/iphone|ipad|ipod/i.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints>1);
// iPhone: the share sheet ("Save Image" puts it in Photos). Elsewhere: a download (on Android it shows in the
// gallery's Download album).
async function savePhoto(b){
  let f=b._file; if(!f){ f=await (b._fileP||photoFileOf(b).catch(()=>null)); if(!f){ toast(t("This photo is no longer available")); return; } }
  if(IS_IOS && navigator.canShare && navigator.canShare({files:[f]})){ try{ await navigator.share({files:[f]}); }catch(e){} return; }
  const a=document.createElement("a"); a.href=URL.createObjectURL(f); a.download=f.name; document.body.appendChild(a); a.click();
  setTimeout(()=>{ try{ URL.revokeObjectURL(a.href); }catch(e){} a.remove(); }, 5000); toast(t("Photo saved")); }
let _fwdFile=null;
function openForward(b){
  const R=A(); if(!R || !b) return; _fwdFile=null; prefetchPhoto(b); const fp=b._fileP||Promise.resolve(b._file);
  fp.then(f=>{ _fwdFile=f; }).catch(()=>{});
  const here=typingRowId(R), list=$("fwdList"); list.innerHTML="";
  const items=groupsLoad().filter(g=>!g.left).map(g=>({t:"g",id:"g:"+g.rid,rid:g.rid,gk:g.gk,name:g.alias||g.name,cl:g.cl}))
    .concat(contactsLoad().filter(c=>!c.into && c.name!==INV_PLACEHOLDER).map(c=>({t:"c",id:"c:"+c.ck,ck:c.ck,name:c.alias||c.name,cl:c.cl})))
    .filter(it=>it.id!==here);
  if(!items.length){ const p=document.createElement("p"); p.className="hint"; p.textContent=t("No other chat to forward to yet."); list.appendChild(p); }
  items.forEach(it=>{ const row=document.createElement("button"); row.type="button"; row.className="merge-row";
    const av=document.createElement("span"); av.className="ava"+(it.t==="g"?" grp":""); av.textContent=it.t==="g"?"👥":up((dn(it.name)||"?")[0]); { const c=chatColor(it, it.t==="g"); if(c) av.style.background=c; }
    const tx=document.createElement("span"); tx.className="mr-t"; const nm=document.createElement("b"); nm.textContent=dn(it.name)||(it.t==="g"?t("Group"):t("Contact")); tx.appendChild(nm);
    row.appendChild(av); row.appendChild(tx); row.addEventListener("click",()=>forwardTo(it)); list.appendChild(row); });
  $("fwdModal").classList.add("show");
}
async function forwardTo(it){
  $("fwdModal").classList.remove("show");
  const f=_fwdFile; if(!f){ toast(t("This photo is no longer available")); return; }
  if(it.t==="g") openGroup(it.rid, it.gk, it.name); else await openContact(it.ck, it.name);
  const t0=Date.now(); while(Date.now()-t0<6000){ const R=A(); if(R && typingRowId(R)===it.id && R.logEl) break; await new Promise(r=>setTimeout(r,120)); }
  const R=A(); if(!R || typingRowId(R)!==it.id){ toast(t("Couldn't forward the photo")); return; }
  await sendImage(f);
}
function showWire(R, ctB64){ if(R && R.code!==active) return; try{ $("wireCt").textContent=hex(unb64(ctB64)); }catch(e){} }
let _blinkT=null;
function blinkEyes(){ const l=$("logs"); if(!l) return; l.classList.remove("blink"); void l.offsetWidth; l.classList.add("blink"); clearTimeout(_blinkT); _blinkT=setTimeout(()=>l.classList.remove("blink"),2700); }

// ---------- join ----------
async function doJoin(code, opts){
  opts=opts||{};
  if(rooms.has(code)){ hideJoin(); switchTo(code); return; }
  if(_joining.has(code)) return; _joining.add(code);
  const R=newRoom(code);
  R.fromContact=opts.fromContact||null; R.title=opts.title||null;
  if(R.fromContact && realName(R.title)){ R.peerName=dn(R.title); R.avatar=up(R.title[0]||"?"); }   // a known contact: show their name right away
  try{ R.kp=await genKP(); R.pubB64=b64(await pubRaw(R.kp)); await ensureTag(R); } finally { _joining.delete(code); }
  if(rooms.has(code)){ switchTo(code); return; }          // someone joined it while we were generating keys
  const logEl=document.createElement("div"); logEl.className="log"; logEl.style.display="none";
  $("logs").appendChild(logEl); R.logEl=logEl; watchLog(logEl);
  rooms.set(code,R);
  hideJoin();
  switchTo(code);
  if(gHistKey){
    const hk=histKeyOf(R);
    let past=await histLoad(hk);
    if(hk!==code){ // contact chat: also pick up records saved under today's daily code by older builds, then de-dupe
      const legacy=await histLoad(code); if(legacy.length){ const seenK=new Set(past.map(r=>r.mid||(r.ts+"|"+r.dir)));
        legacy.forEach(r=>{ const k=r.mid||(r.ts+"|"+r.dir); if(!seenK.has(k)){ past.push(r); seenK.add(k); } });
        past.sort((a,b)=>(a.ts||0)-(b.ts||0)); } }
    renderHistory(R, past);
  }
  R.seen=seenSetFor(R);
  R.bind=()=>{ const ch=client.channel("ratchet-"+code,{config:{private:true,presence:{key:R.id},broadcast:{self:false}}});
    R.channel=ch;
    ch.on("presence",{event:"sync"},()=>onSync(R));
    ch.on("broadcast",{event:"msg"},(payload)=>onMsg(R,payload));
    ch.on("broadcast",{event:"rcpt"},(payload)=>onRcpt(R,payload));
    ch.subscribe(async st=>{
      if(st==="SUBSCRIBED"){ R.joinFails=0; await ch.track(presencePayload(R)); if(!R.paired) setIdle(R); fetchMailbox(R); }
      else if(st==="CHANNEL_ERROR"||st==="TIMED_OUT"){ setStatus(R,t("connection problem — retrying…"),false,"busy",t("reconnecting…")); scheduleRejoin(R, ch); }
    }); };
  R.bind();
  fetchMailbox(R);   // pull anything that was queued while we were away
  // Keep the shared code in the URL only for manual/invite rooms; contact rooms use a
  // secret daily code that shouldn't linger in history, so reload lands on the chats list.
  try{ history.replaceState(null,"", opts.fromContact ? "/" : localRoomUrl(code)); }catch(e){}
}
let _installChecked=false, _showInstallInvite=null;
function enterApp(){ _dbClosed=false; $("join").style.display="none"; $("app").style.display="flex"; document.body.classList.remove("in-auth"); { const j=$("join"); j.style.height=""; j.style.transform=""; } document.body.classList.add("in-app"); fitViewport(); closeSidebar(); renderContacts(); updateNotifyUI(); armAutoLock();
  if(!_installChecked){ _installChecked=true; setTimeout(()=>{ try{ if(_showInstallInvite) _showInstallInvite(); }catch(e){} }, 2500); } }
function hideJoin(){ enterApp(); $("app").classList.remove("home"); }
function goHome(){ closeInfo(); closeFind(); typingTick(""); closeExpMenu(); closePanel(false); cancelReply(); closePicker(); stopRec(false); markNew(null, 0); active=null; rooms.forEach(r=>{ if(r.logEl) r.logEl.style.display="none"; });
  $("join").style.display="none"; $("app").style.display="flex"; $("app").classList.add("home"); document.body.classList.remove("in-auth"); { const j=$("join"); j.style.height=""; j.style.transform=""; } document.body.classList.add("in-app"); fitViewport();
  renderTabs(); renderContacts(); updateNotifyUI(); try{ history.replaceState(null,"","/"); }catch(e){} }
// a first visit opens on a short welcome (logo, one sentence, "Create my account"); an invite or group link goes
// straight to the form, since the person already knows why they are here
function firstAuthMode(){ const P=window.__pending||{}; return (P.invite||P.group||P.room) ? "register" : "welcome"; }
function showAuth(mode){
  $("app").style.display="none"; $("join").style.display="flex"; $("join").dataset.mode=mode;
  document.body.classList.remove("in-app","kb"); document.body.classList.add("in-auth"); const ap=$("app"); ap.style.height=""; ap.style.transform=""; try{ window.scrollTo(0,0); }catch(e){}
  $("join").scrollTop=0; fitViewport();
  const reg=mode==="register", login=mode==="login", unlock=mode==="unlock", nw=mode==="newchat", wel=mode==="welcome";
  $("userField").style.display=(reg||login)?"block":"none";
  if($("promises")) $("promises").style.display=wel?"grid":"none";   // the pitch belongs on the first screen only, under its button
  $("pwField").style.display=(reg||login||unlock)?"block":"none";
  $("pw2Field").style.display=reg?"block":"none";
  if($("dispField")) $("dispField").style.display=reg?"block":"none";
  if(reg && !$("dispInput").value) delete $("dispInput").dataset.own;
  try{ $("pwInput").setAttribute("autocomplete", reg?"new-password":"current-password"); }catch(e){}
  $("ncTabs").style.display=nw?"flex":"none";
  $("bioOptWrap").style.display=((reg||login)&&bioSupported()&&!bioSet())?"flex":"none";
  $("bioBtn").hidden=!(unlock&&bioSupported()&&bioSet());
  $("bioLabel").textContent=t("Unlock with {bio}",{bio:bioLabel()});
  if($("lockHead")) $("lockHead").style.display=unlock?"block":"none";
  if($("forgotLink")) $("forgotLink").style.display=(login||unlock)?"block":"none";
  if($("iabNote")){ const iab=(typeof _isInApp==="function") && _isInApp() && (reg||login||wel);
    $("iabNote").style.display=iab?"block":"none";
    if(iab) $("iabNote").textContent=(/iPhone|iPad|iPod/i.test(navigator.userAgent)
      ? t("You're inside WhatsApp's built-in browser. To stay logged in and get notifications, open this page in Safari first: tap ⋯ then “Open in Safari”.")
      : t("You're inside an app's built-in browser. To stay logged in and get notifications, open this page in your browser first (⋯ → Open in browser).")); }
  $("backBtn").style.display=nw?"block":"none";
  if(!nw){ $("roomField").style.display="none"; $("invLinkField").style.display="none"; $("gnameField").style.display="none"; $("invField").style.display="none"; $("shareRow").style.display="none"; }
  $("joinBtn").textContent=wel?t("Create my account"):reg?t("Create account"):login?t("Log in"):unlock?t("Unlock"):t("Connect");
  authMsg(""); if($("userHint")){ $("userHint").textContent=""; $("userHint").className=""; }
  const sl=$("switchLink");
  if(reg){ const inv=window.__pending&&window.__pending.invite&&realName(window.__pending.invite.n)?window.__pending.invite.n:"";
    $("joinHint").textContent=(inv?t("{inviter} invited you to a private chat. Pick a name to reply.",{inviter:inv})+" ":"")+t("Pick any name — no phone number or email needed — and a strong password (8+ characters). There is no password reset: save it in your password manager."); sl.style.display="block"; sl.textContent=t("Already have an account? Log in"); }
  else if(wel){ $("joinHint").textContent=""; sl.style.display="block"; sl.textContent=t("I already have an account"); }
  else if(login){ $("joinHint").textContent=t("Log in to your Gizleme account from any device."); sl.style.display="block"; sl.textContent=t("New here? Create an account"); }
  else if(unlock){ const s=sessLoad(); $("joinHint").textContent=""; if($("lockSub")) $("lockSub").textContent=(s&&s.display)?t("Welcome back, {name}.",{name:s.display}):t("Welcome back."); sl.style.display="block"; sl.textContent=t("Log out / switch account"); }
  else { sl.style.display="none"; $("roomInput").value=""; _pendingInvite=null; $("join").dataset.adv="0";
    try{ $("qrBox").hidden=true; $("invPinOn").checked=false; $("invPinOn").disabled=false; $("invExp").disabled=false; $("invExp").value="86400000"; }catch(e){}
    ncSet("direct"); }   // a fresh link (and fresh options) each time New chat is opened
  if(login){ const s=sessLoad(); if(s&&s.display) $("userInput").value=s.display; }
}
function ncSet(nc){
  $("join").dataset.nc=nc;
  const direct=nc==="direct", group=nc==="group", join=nc==="join";
  const adv=$("join").dataset.adv==="1";                 // "room code" is the advanced form of a direct chat
  $("invLinkField").style.display=(direct&&!adv)?"block":"none";
  $("roomField").style.display=(direct&&adv)?"block":"none";
  $("shareRow").style.display=direct?"flex":"none";
  $("gnameField").style.display=group?"block":"none";
  $("invField").style.display=join?"block":"none";
  $("joinBtn").textContent=direct?(adv?t("Connect"):t("Open chat")):group?t("Create group"):t("Join");
  $("joinHint").textContent = direct
    ? (adv ? t("Share this room code with one person. You both need to open it at the same time.")
           : t("Send this link to one person. When they open it you're connected — even if you're not online at the same time. It stops working after the time you choose; add a 4-digit code (said by voice) and the link alone opens nothing."))
    : group ? t("Create a named, encrypted group. Only people you invite with the link can join — the name alone gives no access.")
    : t("Paste a link a friend sent you — an invite or a group link.");
  [...document.querySelectorAll(".nctab")].forEach(b=>b.classList.toggle("on",b.dataset.nc===nc));
  if(direct && !adv && !_pendingInvite) newPendingInvite();
  if(direct && adv && !$("roomInput").value.trim()) $("roomInput").value=roomCode();   // keep a code the user may already have shared
}
function switchTo(code){
  const R=rooms.get(code); if(!R) return;
  if(code!==active) typingTick("");                       // leaving a chat: "stopped typing" there
  closeExpMenu(); if(code!==active){ closePanel(false); closeFind(); } setTimeout(jumpUpdate,0);
  if(!_reply || _reply.code!==code) cancelReply(); closePicker(); if(rec && code!==active) stopRec(false);
  active=code; $("app").classList.remove("home"); showCallBanner(R); updateCallUI();
  rooms.forEach(r=>{ if(r.logEl) r.logEl.style.display=(r.code===code)?"flex":"none"; });
  { const hk=histKeyOf(R), n=(_meta.unread&&+_meta.unread[hk])||0; markNew(R, n); }
  clearUnread(R);
  $("peerName").textContent=dn(R.peerName); $("peerAvatar").textContent=R.avatar; paintPeerAvatar(); paintExpBtn();
  applyStatus(R);
  // Composer is usable whenever there's somewhere to deliver: a live pairing, a group,
  // or a saved contact (message goes to the encrypted mailbox and is delivered when they reconnect).
  const canSend = R.paired || R.group || !!R.fromContact;
  $("msgInput").disabled=!canSend; $("sendBtn").disabled=!canSend; setAttach(!canSend);
  renderTabs(); renderContacts(); updateNotifyUI(); updateVerifyUI();
}
// Reconciliation just closed: this chat's rendezvous room moves from the link room to the contact-key room.
// An open chat follows by itself (both sides do, so they keep meeting); without this, a side that stays in
// the old room while the other reconnects into the new one would see "offline" until it reopened the chat.
function moveRoomSoon(R){
  if(!R || R.group || !R.fromContact || R.moving) return; R.moving=true;
  setTimeout(async()=>{ try{
    const ck=R.fromContact; const c=contactFind(ck); if(!c || c.recon){ R.moving=false; return; }
    const want=await rvCodeFromCK(rendezvousCKOf(c)||ck); if(want===R.code || !rooms.has(R.code) || rooms.get(R.code)!==R){ R.moving=false; return; }
    const wasActive=(active===R.code), title=R.title;
    const notes=R.logEl ? [...R.logEl.querySelectorAll(".sys")] : [];   // what was said about this chat so far stays on screen
    try{ R.channel && R.channel.unsubscribe(); }catch(e){} if(R.logEl) R.logEl.remove(); rooms.delete(R.code); if(active===R.code) active=null;
    renderTabs(); if(wasActive){ await doJoin(want,{fromContact:ck,title}); const R2=rooms.get(want); if(R2 && R2.logEl){ notes.forEach(n=>R2.logEl.appendChild(n)); R2.connLineShown=R.connLineShown; scrollEl(R2.logEl); } }
  }catch(e){} }, 1500);
}
function leaveRoom(code){
  const R=rooms.get(code); if(!R) return;
  clearTimeout(R.rejoinT); R.rejoinT=null; R.bind=null;
  try{ R.channel && R.channel.unsubscribe(); }catch(e){}
  if(R.logEl) R.logEl.remove();
  rooms.delete(code);
  if(active===code){
    const n=rooms.keys().next();
    if(!n.done){ switchTo(n.value); }
    else { goHome(); }
  }
  renderTabs();
}
function renderTabs(){
  const tabsEl=$("tabs"); if(!tabsEl) return; tabsEl.innerHTML="";
  tabsEl.style.display = rooms.size>1 ? "flex" : "none";   // only show the switcher with multiple open chats
  rooms.forEach(R=>{
    const chip=document.createElement("div"); chip.className="tab"+(R.code===active?" active":"");
    { const age=pulseAge(R._pulseAt); if(age>=0 && R.code!==active){ chip.classList.add("pulse"); chip.style.setProperty("--pd","-"+age+"ms"); } }
    const nm=document.createElement("span"); nm.className="tname"; nm.textContent=R.title?dn(R.title):("#"+R.code); chip.appendChild(nm);
    if(R.unread){ const b=document.createElement("span"); b.className="badge"; b.textContent=R.unread>9?"9+":R.unread; chip.appendChild(b); }
    const x=document.createElement("button"); x.className="tx"; x.textContent="×"; x.title=t("Leave room"); x.setAttribute("aria-label",t("Leave room"));
    x.addEventListener("click",ev=>{ ev.stopPropagation(); leaveRoom(R.code); });
    chip.appendChild(x);
    chip.addEventListener("click",()=>switchTo(R.code));
    tabsEl.appendChild(chip);
  });
  const add=document.createElement("button"); add.className="tabadd"; add.textContent="+"; add.title=t("New room"); add.setAttribute("aria-label",t("New room"));
  add.addEventListener("click",showAddRoom);
  tabsEl.appendChild(add);
}
function showAddRoom(){ closeSidebar(); showAuth("newchat"); }

// ----- entry handlers (contacts-first) -----
async function openByNotifyKey(n){
  for(const c of contactsLoad()){ try{ if(await notifyKeyFor(c.ck)===n){ await openContact(c.ck,c.name); return true; } }catch(e){} }
  return false;
}
async function applyDeepLink(){
  const p=window.__pending||{}; window.__pending=null;
  if(p.group && p.group.rid && p.group.gk){ try{
    const known=groupsLoad().some(g=>g.rid===p.group.rid);
    if(known || confirm(t("Join the group “{name}”?\n\nIts members will see your display name. Only join groups from people you know.",{name:String(p.group.name||"Group").slice(0,40)}))) { await doJoinGroup(p.group.rid, unb64(p.group.gk), p.group.name, p.group.adm, p.group.rot); return; }
    else { try{ history.replaceState(null,"","/"); }catch(e){} goHome(); return; } }catch(e){} }
  if(p.invite && p.invite.s){ try{ await acceptInvite(p.invite); return; }catch(e){} }
  if(p.room){ if(rooms.has(p.room)) switchTo(p.room); else await doJoin(p.room); return; }
  if(p.n){ const ok=await openByNotifyKey(p.n); if(ok) return; _pendingNotify=p.n; }   // contacts may still be restoring — retried after sync
  goHome();
}
async function connectRoom(){
  initAudio();
  if($("join").dataset.adv!=="1"){                 // invite mode: open the chat now; a first message will wait for them
    if(!_pendingInvite) await newPendingInvite();
    persistPendingInvite(); const pi=_pendingInvite; _pendingInvite=null;
    hideJoin(); await openContact(pi.ck, INV_PLACEHOLDER); return;
  }
  const code=($("roomInput").value.trim()||roomCode()).toUpperCase();
  if(rooms.has(code)){ hideJoin(); switchTo(code); return; }
  await doJoin(code);
}

// ---------- accounts: unique username + password / passkey, permanent login ----------
const AUTH_FN="gizleme-auth", LS_SESS="gz-session";
const USERRE=/^[a-z0-9_.]{3,20}$/;
function sessLoad(){ try{ return JSON.parse(localStorage.getItem(LS_SESS)||"null"); }catch(e){ return null; } }
function sessSave(s){ try{ localStorage.setItem(LS_SESS,JSON.stringify(s)); }catch(e){} }
function sessClear(){ try{ localStorage.removeItem(LS_SESS); }catch(e){} }
async function authFn(action,extra){ return client.functions.invoke(AUTH_FN,{body:Object.assign({action},extra||{})}); }
async function sha256b64(bytes){ return b64(await crypto.subtle.digest("SHA-256",bytes)); }
async function pbkdf2bits(pw,saltBytes){ const base=await crypto.subtle.importKey("raw",enc.encode(pw),"PBKDF2",false,["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({name:"PBKDF2",salt:saltBytes,iterations:200000,hash:"SHA-256"},base,256)); }
function authMsg(t,ok){ const m=$("authMsg"); if(m){ m.textContent=t||""; m.classList.toggle("ok",!!ok); } }
const RL_MSG_EN="Too many attempts — please wait a few minutes and try again"; const RL_MSG={ toString(){ return t(RL_MSG_EN); } };
function isRateLimited(r){ return !!(r && r.error && r.error.context && r.error.context.status===429); }
function authBusy(on){ const b=$("joinBtn"); if(b){ b.disabled=on; b.style.opacity=on?".6":"1"; } }
function clearAuthInputs(){ ["pwInput","pw2Input"].forEach(id=>{ if($(id)) $(id).value=""; }); }

// ---------- encrypted account vault: your contacts + groups follow your account across devices ----------
// The server only ever holds ciphertext: an Account Backup Key (ABK) wrapped by a key derived from your
// password, and the contact/group list encrypted under the ABK. A new device recovers everything with
// your password; the same device recovers it via Face ID / PIN from a locally cached copy of the ABK.
const VAULT_FN="gizleme-vault", LS_ABK="gz-abk", LS_VAULTOWNER="gz-vaultowner";
async function vaultFn(action,extra){ return client.functions.invoke(VAULT_FN,{body:Object.assign({action,token:(sessLoad()||{}).token},extra||{})}); }
async function abkWrapKeyFromAK(AK){ return aesKey(await hkdf(AK,"gz-abk-wrap/v1")); }
async function setABK(abkBytes){ gABK=abkBytes; gContactsKey=await aesKey(await hkdf(abkBytes,"gz-contacts/v1"));
  _acct=b64url(new Uint8Array(await hkdf(abkBytes,"gz-acct/v1",16)));
  retrackAll(); if(pushOn()&&gPushSub) registerAllContacts(); }
async function abkCacheSave(){ try{ if(!gABK||!gHistKey) return; const iv=crypto.getRandomValues(new Uint8Array(12));
    const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},gHistKey,gABK); localStorage.setItem(LS_ABK,JSON.stringify({iv:b64(iv),ct:b64(ct)})); }catch(e){} }
async function abkCacheLoad(){ try{ const r=JSON.parse(localStorage.getItem(LS_ABK)||"null"); if(!r||!gHistKey) return false;
    const mk=new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(r.iv)},gHistKey,unb64(r.ct))); await setABK(mk); return true; }catch(e){ return false; } }
function abkCacheClear(){ try{ localStorage.removeItem(LS_ABK); }catch(e){} }
// Recover the ABK: local cache first (Face ID / PIN, no round-trip), else the password-wrapped copy on the server.
async function recoverABK(AK){
  if(gABK) return true;
  const ep=gEpoch;
  if(await abkCacheLoad()) return true;
  if(!AK) return false;
  try{
    const wrapKey=await abkWrapKeyFromAK(AK);
    const {data}=await vaultFn("pull"); if(ep!==gEpoch) return false; if(!data||!data.ok) return false;
    gVaultCver=data.cver||0;
    const unwrap=async a=>new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(a.iv)},wrapKey,unb64(a.ct)));
    if(data.abk && data.abk.ct){
      await setABK(await unwrap(data.abk));
    } else {
      // First device for this account: mint an ABK, but only adopt it once the server confirms it stored it,
      // otherwise two devices could end up encrypting the vault under different keys.
      const abk=crypto.getRandomValues(new Uint8Array(32));
      const iv=crypto.getRandomValues(new Uint8Array(12));
      const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},wrapKey,abk);
      const res=await vaultFn("pushAbk",{abk:{iv:b64(iv),ct:b64(ct)}}); if(ep!==gEpoch) return false;
      if(!res.data || !res.data.ok) return false;
      if(res.data.already){                       // another device won the race — use the one the server holds
        const again=await vaultFn("pull"); if(ep!==gEpoch) return false;
        const a=again.data&&again.data.abk; if(!a||!a.ct) return false;
        await setABK(await unwrap(a));
      } else { await setABK(abk); }
    }
    if(ep!==gEpoch){ gABK=null; gContactsKey=null; return false; }
    await abkCacheSave();
    return true;
  }catch(e){ return false; }
}
// Before any account's data is shown: if this browser last synced a *different* account, drop its local
// contacts/groups so they are never displayed to, or merged into the vault of, the account logging in now.
function vaultOwnerCheck(me){
  let owner=null; try{ owner=localStorage.getItem(LS_VAULTOWNER); }catch(e){}
  if(owner && me && owner!==me){
    localWipe(); try{ [LS_NOTIFIED,LS_MBTS].forEach(k=>localStorage.removeItem(k)); }catch(e){}
    renderContacts();
  }
  if(me){ try{ localStorage.setItem(LS_VAULTOWNER,me); }catch(e){} }
}
// First login on a device: derive AK from the password + account salt, then recover the ABK.
async function recoverABKWithPassword(pw){
  if(gABK) return true;
  if(await abkCacheLoad()) return true;
  try{ const u=(sessLoad()||{}).username; if(!u) return false;
    const s=await authFn("salt",{username:u}); if(!s.data||!s.data.salt) return false;
    const AK=await pbkdf2bits(pw,unb64(s.data.salt));
    return await recoverABK(AK);
  }catch(e){ return false; }
}
function mergeContacts(remote){ let _chainChanged=false;
  const gone=_meta.gone=Object.assign({},_meta.gone||{},remote.gone||{});   // removals known on any device
  const lc=contactsLoad(), byCk={}; lc.forEach(c=>byCk[c.ck]=Object.assign({},c));
  (remote.contacts||[]).forEach(rc=>{ if(!rc||!rc.ck) return;
    if((gone[rc.ck]||0)>(rc.ts||0)) return;                            // removed after it was last saved: stays removed
    // the other device rotated this contact's key: its record replaces our pre-rotation one
    if(rc.prev && byCk[rc.prev] && !byCk[rc.ck]){ const o=byCk[rc.prev]; delete byCk[rc.prev]; byCk[rc.ck]=Object.assign({},rc,{v:(o.v||rc.v)?1:undefined, name:realName(o.name)&&!realName(rc.name)?o.name:rc.name}); if(!byCk[rc.ck].v) delete byCk[rc.ck].v; return; }
    // we rotated already and the other device still has the old record: ours wins, its flags are kept
    const rotLocal=Object.values(byCk).find(c=>c.prev===rc.ck);
    if(rotLocal){ if(rc.v) rotLocal.v=1; if(realName(rc.name) && !realName(rotLocal.name)) rotLocal.name=rc.name;
      if(rc.mts&&(rc.mts>(rotLocal.mts||0))){ rotLocal.mu=rc.mu; rotLocal.mts=rc.mts; if(!rotLocal.mu) delete rotLocal.mu; }
      if(rc.cts&&(rc.cts>(rotLocal.cts||0))){ rotLocal.cl=rc.cl; rotLocal.cts=rc.cts; if(!rotLocal.cl) delete rotLocal.cl; }
      if(rc.into && !rotLocal.into){ rotLocal.into=rc.into; rotLocal.hk=rc.into; } return; }
    const e=byCk[rc.ck];
    if(!e){ byCk[rc.ck]=Object.assign({},rc); }
    else { if((rc.ts||0)>(e.ts||0)){ e.name=rc.name||e.name; e.ts=rc.ts; } if(e.v||rc.v) e.v=1;
           if(rc.inv) e.inv=1; if(rc.is&&!e.is&&!e.rot) e.is=rc.is; if(rc.sv&&!e.sv) e.sv=rc.sv;
           if(rc.hk&&!e.hk) e.hk=rc.hk; if(rc.prev&&!e.prev) e.prev=rc.prev; if(rc.rot&&!e.rot){ e.rot=rc.rot; delete e.is; }
           // the chain only moves forward: whichever device has thrown more away is right. Same epoch but a different
           // root (two device pairs seeded one at the same moment): both accounts keep the smaller root — the same
           // rule on both sides, so they converge instead of each holding a chain the other cannot read.
           if(rc.kc && typeof rc.kce==="number" && (!e.kc || typeof e.kce!=="number" || rc.kce>e.kce || (rc.kce===e.kce && rc.kc<e.kc))){ if(e.kc!==rc.kc) _chainChanged=true; e.kc=rc.kc; e.kce=rc.kce; }
           // recon (the reconciliation window) is per-device state — what THIS device has confirmed with the
           // peer — so it is never carried across a user's devices via the vault.
           if(rc.ats&&(rc.ats>(e.ats||0))){ e.alias=rc.alias; e.ats=rc.ats; if(!e.alias) delete e.alias; }
           if(rc.mts&&(rc.mts>(e.mts||0))){ e.mu=rc.mu; e.mts=rc.mts; if(!e.mu) delete e.mu; }
           if(rc.cts&&(rc.cts>(e.cts||0))){ e.cl=rc.cl; e.cts=rc.cts; if(!e.cl) delete e.cl; }
           if(rc.into && !e.into){ e.into=rc.into; e.hk=rc.into; if(rc.its) e.its=rc.its; }   // merged on another device: one-way, never undone
           if(e.name===INV_PLACEHOLDER && realName(rc.name) && rc.name!==INV_PLACEHOLDER) e.name=rc.name; } });
  const lg=groupsLoad(), byRid={}; lg.forEach(g=>byRid[g.rid]=Object.assign({},g));
  (remote.groups||[]).forEach(rg=>{ if(!rg||!rg.rid) return; if((gone["g:"+rg.rid]||0)>(rg.ts||0)) return; const e=byRid[rg.rid];
    if(!e){ byRid[rg.rid]=Object.assign({},rg); }
    else { if((rg.ts||0)>(e.ts||0)){ e.name=rg.name||e.name; e.ts=rg.ts; if(rg.gk && rg.gk!==e.gk){ e.gk=rg.gk; e.rot=rg.rot||e.rot; e.rotFp=rg.rotFp; e.prevGk=rg.prevGk; e.rotAt=rg.rotAt; if(rg.left) e.left=1; else delete e.left; } }
           if(rg.adm && !e.adm) e.adm=rg.adm;
           if(rg.ats&&(rg.ats>(e.ats||0))){ e.alias=rg.alias; e.ats=rg.ats; if(!e.alias) delete e.alias; }
           if(rg.mts&&(rg.mts>(e.mts||0))){ e.mu=rg.mu; e.mts=rg.mts; if(!e.mu) delete e.mu; }
           if(rg.cts&&(rg.cts>(e.cts||0))){ e.cl=rg.cl; e.cts=rg.cts; if(!e.cl) delete e.cl; }
           if(rg.mem){ const mem=Object.assign({},e.mem||{}); for(const pk in rg.mem){ if(!mem[pk] || (rg.mem[pk].ts||0)<(mem[pk].ts||0)) mem[pk]=rg.mem[pk]; } e.mem=mem; } } });
  if(_chainChanged) _chainCache.clear();   // keys derived from a root this merge replaced must not be reused
  for(const k in byCk) if((gone[k]||0)>(byCk[k].ts||0)) delete byCk[k];
  for(const k in byRid) if((gone["g:"+k]||0)>(byRid[k].ts||0)) delete byRid[k];
  return { contacts:Object.values(byCk), groups:Object.values(byRid) };
}
async function vaultDecrypt(cipher){ if(!gContactsKey||!cipher||!cipher.ct) return null;
  try{ const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(cipher.iv)},gContactsKey,unb64(cipher.ct)); return JSON.parse(dec.decode(pt)); }catch(e){ return null; } }
async function vaultEncrypt(blob){ const iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},gContactsKey,enc.encode(JSON.stringify(blob))); return {iv:b64(iv),ct:b64(ct)}; }
async function pullMerge(){
  const ep=gEpoch;
  const {data}=await vaultFn("pull"); if(ep!==gEpoch) return false; if(!data||!data.ok) return false; gVaultCver=data.cver||0;
  if(data.contacts){ const remote=await vaultDecrypt(data.contacts); if(ep!==gEpoch) return false;
    if(remote){ const m=mergeContacts(remote);
      _contacts=m.contacts; _groups=m.groups; localSaveSoon();
      if(remote.ident && identAdopt(remote.ident)) syncPushSoon();
      await ensureHistKeys();                                   // records that came from another device get their opaque ids
      try{ await advanceChains(); }catch(e){}
      renderContacts();
      if(pushOn()) registerAllContacts();                       // restored contacts must be reachable by push too
    } }
  // A notification tap that arrived before contacts were restored can be honoured now.
  if(_pendingNotify){ const n=_pendingNotify; _pendingNotify=null; openByNotifyKey(n).catch(()=>{}); }
  inboxPull(true);
  return true;
}
async function pushBlob(){
  if(!gContactsKey) return false;
  const ep=gEpoch;
  const cipher=await vaultEncrypt({ contacts:contactsForVault(), groups:groupsLoad(), ident:identLoad()||undefined, gone:_meta.gone||undefined, ts:Date.now() });
  let res=await vaultFn("pushContacts",{contacts:cipher, cver:gVaultCver}); if(ep!==gEpoch) return false;
  if(res.data && res.data.conflict){            // another device advanced it — merge then retry once
    gVaultCver=res.data.cver||gVaultCver; try{ await pullMerge(); }catch(e){} if(ep!==gEpoch) return false;
    const c2=await vaultEncrypt({ contacts:contactsForVault(), groups:groupsLoad(), ident:identLoad()||undefined, gone:_meta.gone||undefined, ts:Date.now() });
    res=await vaultFn("pushContacts",{contacts:c2, cver:gVaultCver}); if(ep!==gEpoch) return false;
  }
  if(res.data && res.data.ok){ gVaultCver=res.data.cver||gVaultCver; return true; }
  return false;
}
async function syncPull(){ if(!gContactsKey) return; try{
    vaultOwnerCheck((sessLoad()||{}).username||"");   // fallback; the main check runs synchronously at login
    const empty=!contactsLoad().length && !groupsLoad().length;
    if(empty){ gRestoring=true; renderContacts(); }
    try{ await pullMerge(); } finally { gRestoring=false; renderContacts(); }
    await pushBlob();
  }catch(e){ gRestoring=false; renderContacts(); } }
let _syncT=null;
function syncPushSoon(){ if(!gContactsKey) return; clearTimeout(_syncT); _syncT=setTimeout(()=>{ pushBlob().catch(()=>{}); }, 1500); }
function vaultClear(){ gEpoch++; gABK=null; gContactsKey=null; _acct=""; gVaultCver=0; gRestoring=false; _pendingNotify=null; abkCacheClear(); clearPreviews(); }
function clearPreviews(){ for(const k in _prev) delete _prev[k]; }

async function checkUsername(){
  const u=$("userInput").value.trim().toLowerCase(), h=$("userHint"); if(!h) return;
  if(!u){ h.textContent=""; h.className=""; return; }
  if(!USERRE.test(u)){ h.textContent=t("3–20 chars · a–z 0–9 . _"); h.className="bad"; return; }
  h.textContent=t("checking…"); h.className="";
  try{ const {data}=await authFn("check",{username:u}); if(data&&data.available){ h.textContent=t("available ✓"); h.className="ok"; } else { h.textContent=t("already taken"); h.className="bad"; } }
  catch(e){ h.textContent=""; h.className=""; }
}
async function doRegister(){
  initAudio(); const raw=$("userInput").value.trim(), u=raw.toLowerCase(), pw=$("pwInput").value, pw2=$("pw2Input").value;
  const disp=(($("dispInput")&&$("dispInput").value.trim())||raw).slice(0,24);
  if(!USERRE.test(u)){ authMsg(t("Username: 3–20 chars (a–z, 0–9, . or _)")); return; }
  if(pw.length<8){ authMsg(t("Password must be at least 8 characters")); return; }
  if(pw!==pw2){ authMsg(t("Passwords don't match")); return; }
  authBusy(true); authMsg("");
  try{
    const saltB=crypto.getRandomValues(new Uint8Array(16)), salt=b64(saltB);
    const AK=await pbkdf2bits(pw,saltB), av=await sha256b64(AK), verifier=await sha256b64(unb64(av));
    const rr=await authFn("register",{username:u,display:disp,salt,verifier}); const data=rr.data;
    if(isRateLimited(rr)){ authMsg(String(RL_MSG)); authBusy(false); return; }
    if(!data||!data.ok){ const st=rr.error&&rr.error.context&&rr.error.context.status; authMsg(st===409||(data&&data.error==="taken")?t("That username is already taken"):t("Couldn't create account — try again")); authBusy(false); return; }
    sessSave({token:data.token,username:data.username,display:data.display}); myName=data.display;
    vaultOwnerCheck(data.username);
    privateDefaults();
    const mk=await setupPin(pw);
    if($("bioOptIn")&&$("bioOptIn").checked&&bioSupported()&&!bioSet()){ try{ await bioEnrollWrap(mk); }catch(e){ setTimeout(()=>toast(t("{bio} isn't available in this browser — you'll unlock with your password",{bio:bioLabel()})),600); } }
    gHistKey=await histKeyFromMK(mk); await localLoad();
    clearAuthInputs(); enterApp(); applyDeepLink();
    recoverABK(AK).then(ok=>{ if(ok) syncPull(); }).catch(()=>{});
  }catch(e){ authMsg(t("Network error — try again")); }
  authBusy(false);
}
async function doLoginAccount(){
  initAudio(); const u=$("userInput").value.trim().toLowerCase(), pw=$("pwInput").value;
  if(!u||!pw){ authMsg(t("Enter your username and password")); return; }
  authBusy(true); authMsg("");
  try{
    const s=await authFn("salt",{username:u});
    if(isRateLimited(s)){ authMsg(String(RL_MSG)); authBusy(false); return; }
    if(!s.data||!s.data.salt){ authMsg(t("Network error — try again")); authBusy(false); return; }
    const AK=await pbkdf2bits(pw,unb64(s.data.salt)), av=await sha256b64(AK);
    const lr=await authFn("login",{username:u,av}); const data=lr.data;
    if(isRateLimited(lr)){ authMsg(String(RL_MSG)); authBusy(false); return; }
    if(!data||!data.ok){ authMsg(t("Wrong username or password")); authBusy(false); return; }
    sessSave({token:data.token,username:data.username,display:data.display}); myName=data.display;
    vaultOwnerCheck(data.username);
    privateDefaults();
    let mk; try{ mk= pinSet()? await unlockPin(pw) : await setupPin(pw); }catch(e){ mk=await setupPin(pw); }
    if($("bioOptIn")&&$("bioOptIn").checked&&bioSupported()&&!bioSet()){ try{ await bioEnrollWrap(mk); }catch(e){ setTimeout(()=>toast(t("{bio} isn't available in this browser — you'll unlock with your password",{bio:bioLabel()})),600); } }
    gHistKey=await histKeyFromMK(mk); await localLoad();
    clearAuthInputs(); enterApp(); applyDeepLink();
    recoverABK(AK).then(ok=>{ if(ok) syncPull(); }).catch(()=>{});
  }catch(e){ authMsg(t("Network error — try again")); }
  authBusy(false);
}
async function doUnlockPw(){
  initAudio(); const pw=$("pwInput").value; if(!pw){ authMsg(t("Enter your password")); return; }
  authBusy(true); authMsg("");
  try{ const mk=await unlockPin(pw); gHistKey=await histKeyFromMK(mk); await localLoad(); const s=sessLoad(); myName=(s&&s.display)||myName; clearAuthInputs(); enterApp(); applyDeepLink();
    recoverABKWithPassword(pw).then(ok=>{ if(ok) syncPull(); }).catch(()=>{}); }
  catch(e){ authMsg(t("Wrong password")); }
  authBusy(false);
}
async function doUnlockBio(){
  initAudio(); authMsg("");
  try{ const mk=await bioUnlock(); gHistKey=await histKeyFromMK(mk); await localLoad(); const s=sessLoad(); myName=(s&&s.display)||myName; clearAuthInputs(); enterApp(); applyDeepLink();
    recoverABK(null).then(ok=>{ if(ok) syncPull(); }).catch(()=>{}); }
  catch(e){ authMsg(t("{bio} didn't work — use your password",{bio:bioLabel()})); }
}
async function logoutAccount(){
  if(call) endCall("ended"); stopRec(false); voiceStop();
  const s=sessLoad();
  let flushed=false;
  try{ clearTimeout(_syncT); if(gContactsKey) flushed=await pushBlob(); }catch(e){}   // flush pending changes before the token dies
  if(!flushed && (contactsLoad().length||groupsLoad().length) &&
     !confirm(t("Your contacts couldn't be backed up to your account just now (offline?).\n\nIf you log out, the contacts on this device that aren't backed up yet will be lost. Log out anyway?"))) return false;
  // This device's push subscriptions belong to the outgoing account — drop them so its contacts can't wake the next user.
  try{ if(pushOn() && gPushSub) await fn("unregister",{owner:deviceId()}); }catch(e){}
  if(s&&s.token){ try{ await authFn("logout",{token:s.token}); }catch(e){} }
  // Always record who last used this browser, so a *different* account logging in later starts clean
  // even if the flush above failed (vaultOwnerCheck at login does the clearing).
  if(s&&s.username){ try{ localStorage.setItem(LS_VAULTOWNER,s.username); }catch(e){} }
  sessClear(); gHistKey=null; vaultClear();
  // No trace on this device: keys, contacts, mailbox cursors and the encrypted history database all go.
  localWipe(); swNames(true).catch(()=>{});
  try{ [LS_MKPIN,LS_MKBIO,LS_NOTIFIED,LS_MBTS,LS_ABK,EXP_R].forEach(k=>localStorage.removeItem(k)); }catch(e){}
  try{ _dbClosed=true; if(_db){ _db.close(); _db=null; } indexedDB.deleteDatabase("vesper"); }catch(e){}
  renderContacts();
  [...rooms.keys()].forEach(c=>{ const R=rooms.get(c); try{ R&&R.channel&&R.channel.unsubscribe(); }catch(e){} if(R&&R.logEl) R.logEl.remove(); });
  rooms.clear(); active=null;
  showAuth("login");
  return true;
}
// ---------- lock: stays signed in, but wipes keys and open chats from memory until Face ID / password ----------
const LS_AUTOLOCK="gz-autolock", LS_HIDEPREV="gz-hideprev", LS_SHIELD="gz-shield";
function shieldOn(){ try{ const v=localStorage.getItem(LS_SHIELD); return v===null ? true : v==="1"; }catch(e){ return true; } }   // on by default
function setShieldOn(on){ try{ localStorage.setItem(LS_SHIELD,on?"1":"0"); }catch(e){} if(!on) showShield(false); }
function showShield(on){ const s=$("privacyShield"); if(s) s.hidden=!on; }
function previewsHidden(){ try{ return localStorage.getItem(LS_HIDEPREV)==="1"; }catch(e){ return false; } }
function setPreviewsHidden(on){ try{ localStorage.setItem(LS_HIDEPREV,on?"1":"0"); }catch(e){} renderContacts(); }
function autoLockMs(){ try{ return +localStorage.getItem(LS_AUTOLOCK)||0; }catch(e){ return 0; } }
// Private by default on every device: messages disappear after 24 h and the app auto-locks after 15 min
// unless this device already chose otherwise (one tap to change in Settings).
function privateDefaults(){ try{ if(localStorage.getItem(EXP_G)===null) localStorage.setItem(EXP_G,"86400000"); if(localStorage.getItem(LS_AUTOLOCK)===null) localStorage.setItem(LS_AUTOLOCK,"900000"); }catch(e){} }
function setAutoLock(ms){ try{ localStorage.setItem(LS_AUTOLOCK,String(ms||0)); }catch(e){} armAutoLock(); }
let _lockT=null, _hiddenAt=0;
function armAutoLock(){ clearTimeout(_lockT); const ms=autoLockMs(); if(!ms||!gHistKey) return; _lockT=setTimeout(()=>{ if(call){ armAutoLock(); return; } lockApp(); }, ms); }   // never in the middle of a call
function lockApp(){ if(call) endCall("ended"); stopRec(false); voiceStop(); stopScan(); cancelReply(); closePicker();
  const s=sessLoad(); if(!s||!gHistKey) return;                 // not signed in, or already locked
  clearTimeout(_lockT); clearTimeout(_syncT);
  clearTimeout(_muteT);
  if(_syncT){ clearTimeout(_syncT); _syncT=null; pushBlob().catch(()=>{}); }      // a pending vault push (a binding, a mute, a merge) must not be lost
  if(_localT){ clearTimeout(_localT); _localT=null; localSave().catch(()=>{}); }   // nor a pending local save (unread, queued sends, cursors)
  [...rooms.keys()].forEach(c=>{ const R=rooms.get(c); try{ R&&R.channel&&R.channel.unsubscribe(); }catch(e){} if(R&&R.logEl) R.logEl.remove(); });
  rooms.clear(); active=null;
  gHistKey=null; gEpoch++; gABK=null; gContactsKey=null; _acct=""; gRestoring=false; clearPreviews(); localClear();   // keys leave memory; the cached ABK stays for a quick unlock
  try{ $("wireCt").textContent="—"; $("msgInput").value=""; const m=$("barMenu"); if(m) m.hidden=true; $("invLinkOut").value=""; $("qrBox").hidden=true; const cv=$("qrCanvas"); if(cv) cv.getContext("2d").clearRect(0,0,cv.width,cv.height); $("peerMeta").title=""; }catch(e){}
  document.querySelectorAll(".modal.show").forEach(m=>m.classList.remove("show"));          // every dialog, whatever it was
  try{ document.querySelectorAll(".lightbox").forEach(l=>l.remove()); }catch(e){}
  _ginvPending=null; _pendingInvite=null; _pendingNotify=null;
  try{ _sq=""; _sCache=null; if($("listSearch")) $("listSearch").value=""; if($("listSearchX")) $("listSearchX").hidden=true; if(_sRes){ _sRes.hidden=true; _sRes.innerHTML=""; } closeFind(); }catch(e){}
  try{ $("logs").innerHTML=""; const sb=document.querySelector(".sb-list"); if(sb) sb.innerHTML=""; renderTabs(); ["pwCur","pwNew","pwNew2","delPw","dispInput"].forEach(id=>{ const e=$(id); if(e) e.value=""; }); }catch(e){}
  showAuth("unlock");
}
async function createGroupFromInput(){ initAudio(); await createGroup($("gnameInput").value.trim()); if($("gnameInput")) $("gnameInput").value=""; }
// QR scanning with the browser's own detector (Chrome/Android/desktop). Elsewhere the phone camera app does
// it natively and opens the link here, so the button is simply hidden.
let _scan=null;
function scanSupported(){ return typeof BarcodeDetector==="function" && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia); }
async function startScan(){
  if(!scanSupported()||_scan) return; const m=$("scanModal"), v=$("scanVideo"), msg=$("scanMsg"); msg.textContent="";
  let stream; try{ stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:"environment"}}, audio:false}); }catch(e){ toast(mediaErr(e)); return; }
  let det; try{ det=new BarcodeDetector({formats:["qr_code"]}); }catch(e){ det=new BarcodeDetector(); }
  v.srcObject=stream; try{ await v.play(); }catch(e){}
  _scan={stream, det, timer:null}; m.classList.add("show");
  const tick=async()=>{ if(!_scan) return; try{ if(v.readyState>=2){ const codes=await det.detect(v); const hit=(codes||[]).map(c=>c.rawValue||"").find(x=>/#i=|#g=/.test(x)); if(hit){ stopScan(); await openScanned(hit); return; } } }catch(e){}
    if(_scan) _scan.timer=setTimeout(tick, 200); };
  tick();
}
function stopScan(){ const sc=_scan; _scan=null; if(!sc) return; clearTimeout(sc.timer); try{ sc.stream.getTracks().forEach(tr=>tr.stop()); }catch(e){} const v=$("scanVideo"); if(v) v.srcObject=null; $("scanModal").classList.remove("show"); }
async function openScanned(text){
  const pi=parseInviteLink(text); if(pi){ try{ hideJoin(); await acceptInvite(pi); }catch(e){ toast(t("Couldn't open that invite — try again")); } return; }
  const inv=parseInvite(text); if(inv){ if(groupsLoad().some(g=>g.rid===inv.rid) || confirm(t("Join the group “{name}”?\n\nIts members will see your display name. Only join groups from people you know.",{name:String(inv.name||"Group").slice(0,40)}))){ try{ hideJoin(); await doJoinGroup(inv.rid, unb64(inv.gk), inv.name, inv.adm, inv.rot); }catch(e){ toast(t("Couldn't join — try again")); } } return; }
  toast(t("That's not a Gizleme code"));
}
async function joinFromInviteInput(){ initAudio(); const raw=$("invInput").value;
  const pi=parseInviteLink(raw);
  if(pi){ try{ $("invInput").value=""; hideJoin(); await acceptInvite(pi); }catch(e){ authMsg(t("Couldn't open that invite — try again")); } return; }
  const inv=parseInvite(raw);
  if(!inv){ authMsg(t("That link doesn't look like a Gizleme invite")); return; }
  try{ $("invInput").value=""; await doJoinGroup(inv.rid, unb64(inv.gk), inv.name, inv.adm, inv.rot); }catch(e){ authMsg(t("Couldn't join — try again")); } }
async function join(){ const m=($("join").dataset.mode)||"register";
  if(m==="welcome"){ showAuth("register"); if(!TOUCH_UI) try{ $("userInput").focus(); }catch(e){} return; }   // step 2: the form alone (focused at once, never later: a late focus would steal the next field)
  if(m==="register") return doRegister();
  if(m==="login") return doLoginAccount();
  if(m==="unlock") return doUnlockPw();
  if(m==="newchat"){ const nc=($("join").dataset.nc)||"direct";
    if(nc==="group") return createGroupFromInput();
    if(nc==="join") return joinFromInviteInput();
    return connectRoom(); }
}
// Rename a contact or a group for yourself only: the nickname lives in your own (encrypted, account-synced)
// list; the other side never sees it. An empty name restores the name they chose.
// "Merge with another chat…": pick the earlier chat with the same person (same name first, then most recent)
function openMerge(){
  const R=A(), list=$("mergeList"); if(!R || !list) return; list.innerHTML="";
  const cur=contactFind(R.fromContact), curName=(cur && realName(cur.name)) || "";
  const last=c=>((_prev[ckHistKey(c.ck)]||{}).ts || c.ts || 0);
  mergeCandidates(R).sort((a,b)=>((b.name===curName)-(a.name===curName)) || (last(b)-last(a))).forEach(c=>{
    const nm=c.alias||dn(c.name)||t("Contact"), pv=_prev[ckHistKey(c.ck)];
    const b=document.createElement("button"); b.type="button"; b.className="merge-row";
    const av=document.createElement("span"); av.className="ava"; av.textContent=up((nm||"?")[0]);
    const tx=document.createElement("span"); tx.className="mr-t"; const n=document.createElement("b"); n.textContent=nm;
    const sub=document.createElement("small"); sub.textContent=pv ? (fmtListTime(pv.ts)+" · "+pv.text) : t("No messages on this device");
    tx.appendChild(n); tx.appendChild(sub); b.appendChild(av); b.appendChild(tx);
    b.addEventListener("click",async()=>{
      if(!confirm(t("Merge your chat with “{old}” into this one?\n\nIts messages will show here, in order, and it leaves your chats list. If they still write in that chat, it arrives here too. Only on your devices — nothing is sent.",{old:nm}))) return;
      $("mergeModal").classList.remove("show"); const ok=await mergeChatInto(A(), c.ck); toast(ok ? t("Chats merged") : t("Couldn't merge these chats")); });
    list.appendChild(b); });
  $("mergeModal").classList.add("show");
}
function renameChat(){
  const R=A(); if(!R) return;
  if(R.group){ const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g) return;
    const v=prompt(t("Nickname for this chat (only on your devices):"), g.alias||g.name||""); if(v===null) return;
    const nv=v.trim().slice(0,32); if(nv && nv!==g.name) g.alias=nv; else delete g.alias; g.ats=Date.now(); groupsSave(l);
    R.title=g.alias||g.name; R.peerName=R.title; }
  else if(R.fromContact){ const l=contactsLoad(); const c=l.find(x=>x.ck===R.fromContact); if(!c) return;
    const v=prompt(t("Nickname for this chat (only on your devices):"), c.alias||dn(c.name)||""); if(v===null) return;
    const nv=v.trim().slice(0,32); if(nv && nv!==c.name) c.alias=nv; else delete c.alias; c.ats=Date.now(); contactsSave(l);
    R.title=c.alias||c.name; R.peerName=c.alias||dn(c.name); R.avatar=up((R.peerName||"?")[0]); }
  else return;
  if(R.code===active){ $("peerName").textContent=R.peerName; $("peerAvatar").textContent=R.avatar; } renderTabs(); renderContacts(); updateVerifyUI(); toast(t("Name updated"));
}
async function rekey(){
  const R=A(); if(!R||!R.channel) return;
  R.kp=await genKP(); R.pubB64=b64(await pubRaw(R.kp)); R.rootFp=""; await ensureTag(R);
  await R.channel.track(presencePayload(R));
  if(R.peer) await establish(R,R.peer,R.authOk);
  sysline(R.logEl,t("↻ new keys — channel re-secured")); toast(t("New keys generated"));
}

// Re-wrap the existing device master key under a new password (history and the cached account key stay readable).
async function rewrapPin(newPw, mk){
  const salt=crypto.getRandomValues(new Uint8Array(16)), iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv}, await pinWrapKey(newPw,salt), mk);
  try{ localStorage.setItem(LS_MKPIN, JSON.stringify({salt:b64(salt), iv:b64(iv), ct:b64(ct)})); }catch(e){}
}
async function avFor(pw){ const u=(sessLoad()||{}).username; const s=await authFn("salt",{username:u}); if(!s.data||!s.data.salt) throw new Error("net");
  const AK=await pbkdf2bits(pw,unb64(s.data.salt)); return {AK, av:await sha256b64(AK)}; }
async function changePassword(cur, nw){
  const s=sessLoad(); if(!s||!s.token) throw new Error(t("Not logged in"));
  let mk; try{ mk=await unlockPin(cur); }catch(e){ throw new Error(t("Current password is wrong")); }
  const {AK:AKold, av:avOld}=await avFor(cur);
  if(!gABK){ const ok=await recoverABK(AKold); if(!ok) throw new Error(t("Couldn't reach your account backup — try again when online")); }
  const saltB=crypto.getRandomValues(new Uint8Array(16)), AKnew=await pbkdf2bits(nw,saltB), avNew=await sha256b64(AKnew), verifier=await sha256b64(unb64(avNew));
  // the account backup key re-wrapped under the new password travels in the same request as the new verifier:
  // the server writes both in one transaction, so no device can end up able to log in but unable to open the backup
  const wrapKey=await abkWrapKeyFromAK(AKnew); const iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},wrapKey,gABK);
  const r=await authFn("changepw",{token:s.token, av:avOld, salt:b64(saltB), verifier, abk:{iv:b64(iv),ct:b64(ct)}});
  if(isRateLimited(r)) throw new Error(String(RL_MSG));
  if(!r.data||!r.data.ok){ const st=r.error&&r.error.context&&r.error.context.status; throw new Error(st===401?t("Current password is wrong"):t("Couldn't change the password — try again")); }
  await rewrapPin(nw, mk);
}
async function deleteAccount(pw){
  const s=sessLoad(); if(!s||!s.token) throw new Error(t("Not logged in"));
  const {av}=await avFor(pw);
  const r=await authFn("delete",{token:s.token, av, owners:[deviceId()], acct:_acct||undefined});
  if(isRateLimited(r)) throw new Error(String(RL_MSG));
  if(!r.data||!r.data.ok){ const st=r.error&&r.error.context&&r.error.context.status; throw new Error(st===401?t("Wrong password"):t("Couldn't delete the account — try again")); }
  try{ if(gPushSub){ await gPushSub.unsubscribe(); } }catch(e){}
  try{ localStorage.setItem(LS_PUSH,"0"); }catch(e){}
  sessClear(); gHistKey=null; vaultClear(); localWipe(); swNames(true).catch(()=>{});
  try{ [LS_MKPIN,LS_MKBIO,LS_NOTIFIED,LS_MBTS,LS_ABK,LS_VAULTOWNER,LS_DEVID,EXP_R].forEach(k=>localStorage.removeItem(k)); }catch(e){}
  try{ if(_db){ _db.close(); _db=null; } indexedDB.deleteDatabase("vesper"); }catch(e){}
  [...rooms.keys()].forEach(c=>{ const R=rooms.get(c); try{ R&&R.channel&&R.channel.unsubscribe(); }catch(e){} if(R&&R.logEl) R.logEl.remove(); });
  rooms.clear(); active=null; renderContacts();
}
const LOGOUT_MSG_EN="Log out of this device?\n\nYour contacts stay safe in your account. Saved message history on this device will be erased."; const LOGOUT_MSG={ toString(){ return t(LOGOUT_MSG_EN); } };
// ---------- wire-up ----------
(function init(){
  const params=new URLSearchParams(location.search);
  // #n= (notification tap) and #room= (manual room) live in the fragment, which browsers never send to a
  // server; the ?n= / ?room= query forms are still read for links created by older builds.
  const hp={}; try{ const h=(location.hash||"").replace(/^#/,""); const m=/^(n|room)=(.*)$/.exec(h); if(m) hp[m[1]]=decodeURIComponent(m[2]); }catch(e){}
  try{ const t=localStorage.getItem("vesper-theme"); if(t) document.documentElement.setAttribute("data-theme",t); }catch(e){}
  const deepRoom=(hp.room||params.get("room")||"").toUpperCase();
  let pendGroup=null; try{ const h=location.hash||""; if(h.indexOf("#g=")===0){ pendGroup=JSON.parse(dec.decode(unb64url(h.slice(3)))); } }catch(e){}
  const pendInvite=parseInviteLink(location.hash||"");
  window.__pending={ n:hp.n||params.get("n")||"", room:deepRoom, group:(pendGroup&&pendGroup.rid&&pendGroup.gk)?pendGroup:null, invite:pendInvite };
  // The #g= fragment is left in place until doJoinGroup consumes it (it strips it then): an in-app
  // browser's "Open in Safari/browser" and a reload before login both need it to still be there.

  $("bioBtn").addEventListener("click",doUnlockBio);
  $("switchLink").addEventListener("click",()=>{ const m=$("join").dataset.mode;
    if(m==="register" || m==="welcome") showAuth("login"); else if(m==="login") showAuth("register");
    else if(m==="unlock"){ if(confirm(String(LOGOUT_MSG))) logoutAccount(); } });
  $("backBtn").addEventListener("click",()=>{ enterApp(); if(active) switchTo(active); else goHome(); });
  $("homeNew").addEventListener("click",showAddRoom);

  $("genRoom").addEventListener("click",()=>$("roomInput").value=roomCode());
  $("genInvite").addEventListener("click",()=>{ newPendingInvite(); toast(t("New link")); });
  $("invExp").addEventListener("change",refreshInviteUrl); $("invPinOn").addEventListener("change",refreshInviteUrl);
  $("qrShow").addEventListener("click",toggleQr);
  $("qrScan").addEventListener("click",startScan); $("scanCancel").addEventListener("click",stopScan);
  if(!scanSupported()){ $("qrScan").hidden=true; } else { $("qrScanHint").textContent=t("You can also point your phone's camera at the code: the link opens here."); }
  $("invLinkOut").addEventListener("focus",e=>{ try{ e.target.select(); }catch(x){} });
  ["copy","cut"].forEach(ev=>$("invLinkOut").addEventListener(ev,()=>{ try{ persistPendingInvite(); }catch(x){} }));   // a link copied by hand is a link sent
  $("advRoom").addEventListener("click",()=>{ $("join").dataset.adv="1"; ncSet("direct"); });
  $("joinBtn").addEventListener("click",join);
  let _ucT=null;
  $("dispInput").addEventListener("input",()=>{ $("dispInput").dataset.own="1"; });
  $("userInput").addEventListener("input",()=>{ if($("join").dataset.mode!=="register") return;
    if($("dispInput").dataset.own!=="1") $("dispInput").value=$("userInput").value.trim();   // the first name starts as the username until they change it
    clearTimeout(_ucT); _ucT=setTimeout(checkUsername,350); });
  ["userInput","pwInput","pw2Input","roomInput","gnameInput","invInput"].forEach(id=>{ const el=$(id); if(el) el.addEventListener("keydown",e=>{ if(e.key==="Enter") join(); }); });
  [...document.querySelectorAll(".nctab")].forEach(b=>b.addEventListener("click",()=>ncSet(b.dataset.nc)));
  $("copyLink").addEventListener("click",shareInvite);
  $("waShare").addEventListener("click",shareWhatsApp);

  $("sendBtn").addEventListener("click",sendText);
  // The message menu (reactions, reply, edit, copy): long press or double tap (phone), double or right click
  // (computer). Replies: also a swipe to the right. Taps on a quote jump to the original.
  (function(){
    const logs=$("logs"); let lastTap=null, sw=null;
    const interactive=el=>!!(el && el.closest && (el.closest("button,a,input,textarea,select,.tapview,.vbar,.quote,.reacts,video") || (el.closest("img") && !el.closest("img.keep"))));
    logs.addEventListener("dblclick",e=>{ const b=e.target.closest && e.target.closest(".bubble"); if(!rxTargetOk(b) || interactive(e.target)) return;
      try{ window.getSelection().removeAllRanges(); }catch(_){} openPicker(b); });
    // a long press (about half a second, finger still) opens the same menu: react, reply, edit, copy
    logs.addEventListener("contextmenu",e=>{ const b=e.target.closest && e.target.closest(".bubble"); if(!rxTargetOk(b) || interactive(e.target)) return;
      e.preventDefault(); openPicker(b); });
    logs.addEventListener("touchstart",e=>{ if(e.touches.length!==1){ sw=null; return; } const b=e.target.closest && e.target.closest(".bubble"); if(!rxTargetOk(b)){ sw=null; return; }
      const p=e.touches[0]; sw={b, x:p.clientX, y:p.clientY, t:Date.now(), on:false, ready:false, moved:false, inter:interactive(e.target), lock:!!(e.target.closest && e.target.closest(".vbar"))};
      const me=sw; if(!me.inter) me.lp=setTimeout(()=>{ if(sw!==me || me.moved || me.on) return; me.long=true; try{ navigator.vibrate && navigator.vibrate(10); }catch(_){} openPicker(me.b); }, 480); },{passive:true});
    logs.addEventListener("touchmove",e=>{ if(!sw || sw.lock) return; const p=e.touches[0]; const dx=p.clientX-sw.x, dy=p.clientY-sw.y;
      if(Math.abs(dx)>10 || Math.abs(dy)>10){ sw.moved=true; clearTimeout(sw.lp); }
      if(!sw.on){ if(Math.abs(dy)>12 && Math.abs(dy)>=Math.abs(dx)){ sw.lock=true; return; }          // a vertical scroll: leave it alone
        if(dx>14 && dx>Math.abs(dy)*1.4){ sw.on=true; sw.b.classList.add("swiping"); closePicker(); } else return; }
      const x=Math.max(0, Math.min(dx-14, 84)); sw.b.style.transform="translateX("+x+"px)";
      const ready=x>=56; if(ready!==sw.ready){ sw.ready=ready; sw.b.classList.toggle("swipe-ready",ready); if(ready){ try{ navigator.vibrate && navigator.vibrate(8); }catch(_){} } } },{passive:true});
    const endSwipe=s=>{ const b=s.b; b.style.transition="transform .18s ease"; b.style.transform="";
      setTimeout(()=>{ b.style.transition=""; b.classList.remove("swiping","swipe-ready"); },200); if(s.ready) startReply(b); };
    logs.addEventListener("touchend",e=>{ const s=sw; sw=null; if(!s) return; clearTimeout(s.lp);
      if(s.long){ lastTap=null; e.preventDefault(); return; }               // the long press already opened the menu
      if(s.on){ endSwipe(s); lastTap=null; return; }
      if(s.moved || s.inter || Date.now()-s.t>350){ lastTap=null; return; }
      const now=Date.now(); if(lastTap && lastTap.b===s.b && now-lastTap.t<330){ lastTap=null; e.preventDefault(); openPicker(s.b); return; }
      lastTap={b:s.b, t:now}; },{passive:false});
    logs.addEventListener("touchcancel",()=>{ const s=sw; sw=null; if(s) clearTimeout(s.lp); if(s && s.on){ s.ready=false; endSwipe(s); } },{passive:true});
    logs.addEventListener("click",e=>{ const jb=e.target.closest && e.target.closest(".bubble.jumbo"); if(jb) jumboPlay(jb);   // a tap replays it
      const q=e.target.closest && e.target.closest(".quote"); if(q){ const R=A(); if(R) jumpToQuoted(R, q.dataset.ref); return; }
      const po=e.target.closest && e.target.closest(".voteb .po"); if(po){ voteTap(po); return; }
      const c=e.target.closest && e.target.closest(".rx"); if(c){ const b=c.closest(".bubble"); const R=A(); if(R && b && b.dataset.mid) sendReaction(R, b.dataset.mid, c.dataset.e); } });
    logs.addEventListener("scroll",()=>closePicker(),{capture:true,passive:true});
    $("rxPick").addEventListener("click",e=>{ const x=e.target.closest && e.target.closest("button"); if(!x) return; const R=A(); const f=_rxFor;
      if(x.id==="rxMore"){ const g=$("rxGrid"); g.hidden=!g.hidden; $("rxPick").classList.toggle("open-grid",!g.hidden); const b=(f&&R)?bubbleOf(R,f.m):null; if(b) placePicker(b); return; }
      if(x.id==="rxReply"){ const b=(f&&R)?bubbleOf(R,f.m):null; closePicker(); if(b) startReply(b); return; }
      if(x.id==="rxEdit"){ const b=(f&&R)?bubbleOf(R,f.m):null; closePicker(); if(b) startEdit(b); return; }
      if(x.id==="rxSave"){ const b=(f&&R)?bubbleOf(R,f.m):null; closePicker(); if(b) savePhoto(b); return; }
      if(x.id==="rxFwd"){ const b=(f&&R)?bubbleOf(R,f.m):null; closePicker(); if(b) openForward(b); return; }
      if(x.id==="rxDel"){ const b=(f&&R)?bubbleOf(R,f.m):null; closePicker(); if(b) askDelete(b); return; }
      if(x.id==="rxCopy"){ const b=(f&&R)?bubbleOf(R,f.m):null; closePicker(); const tx=b && b.querySelector(":scope > .txt");
        if(tx){ (navigator.clipboard ? navigator.clipboard.writeText(tx.textContent) : Promise.reject()).then(()=>toast(t("Copied"))).catch(()=>{}); } return; }
      if(x.dataset.e && f && R && R.code===f.code){ closePicker(); sendReaction(R, f.m, x.dataset.e); } });
    document.addEventListener("pointerdown",e=>{ const pk=$("rxPick"); if(pk && !pk.hidden && !pk.contains(e.target)) closePicker();
      const cp=$("colPick"); if(cp && !cp.hidden && !cp.contains(e.target)) closeColorPick(); },true);
    // the chats list: a long press (or right click) on a chat opens its colour palette
    { const cl=$("contactList"); let lp=null;
      const isRow=t=>{ const row=t && t.closest && t.closest(".ct"); return row && !(t.closest && t.closest(".cx")) ? row : null; };
      cl.addEventListener("contextmenu",e=>{ const row=isRow(e.target); if(!row) return; e.preventDefault(); openColorPick(row); });
      cl.addEventListener("touchstart",e=>{ clearTimeout(lp&&lp.t); lp=null; if(e.touches.length!==1) return; const row=isRow(e.target); if(!row) return;
        const p=e.touches[0]; const me={row, x:p.clientX, y:p.clientY, long:false}; lp=me;
        me.t=setTimeout(()=>{ if(lp!==me) return; me.long=true; row._lp=true; try{ navigator.vibrate && navigator.vibrate(10); }catch(_){} openColorPick(row); }, 480); },{passive:true});
      cl.addEventListener("touchmove",e=>{ if(!lp) return; const p=e.touches[0]; if(Math.abs(p.clientX-lp.x)>10 || Math.abs(p.clientY-lp.y)>10){ clearTimeout(lp.t); lp=null; } },{passive:true});
      cl.addEventListener("touchend",e=>{ const s=lp; lp=null; if(!s) return; clearTimeout(s.t); if(s.long){ e.preventDefault(); setTimeout(()=>{ s.row._lp=false; }, 400); } },{passive:false});
      cl.addEventListener("touchcancel",()=>{ if(lp){ clearTimeout(lp.t); lp=null; } },{passive:true});
      cl.addEventListener("scroll",()=>closeColorPick(),{passive:true});
      $("colGrid").addEventListener("click",e=>{ const b=e.target.closest && e.target.closest("button"); if(!b || !_colFor) return; const id=_colFor; closeColorPick(); setAvaColor(id, b.dataset.c||""); }); }
    document.addEventListener("keydown",e=>{ if(e.key==="Escape"){ closePicker(); closeColorPick(); } });
    window.addEventListener("resize",()=>closePicker());
    $("rbCancel").addEventListener("mousedown",e=>e.preventDefault());
    $("rbCancel").addEventListener("click",()=>{ cancelReply(); try{ $("msgInput").focus(); }catch(_){} });
  })();
  $("callBtn").addEventListener("click",()=>startCall(false)); $("videoBtn").addEventListener("click",()=>startCall(true));
  $("jumpBtn").addEventListener("click",()=>{ const R=A(); if(R && R.logEl){ R._below=0; R.logEl._stick=true; scrollEl(R.logEl, true); } setTimeout(jumpUpdate,60); });
  $("callEnd").addEventListener("click",hangup); $("callAccept").addEventListener("click",()=>acceptCall(false)); $("callNoCam").addEventListener("click",()=>acceptCall(true)); $("callDecline").addEventListener("click",declineCall);
  $("callMute").addEventListener("click",toggleMute); $("callCam").addEventListener("click",toggleCam); $("callFlip").addEventListener("click",flipCam);
  // during a video call the buttons and the name step aside after a few seconds; a tap on the picture brings them
  // back (and another tap hides them again)
  $("callStage").addEventListener("click",()=>{ if(!call || !call.t1 || !$("callIncoming").hidden) return;
    if(!$("callStage").querySelector(".peer:not(.audio)")) return;
    if($("callUI").classList.toggle("bare")) clearTimeout(_bareT); else callChrome(); });
  $("callFs").addEventListener("click",()=>{ if(fsActive()) fsExit(); else fsEnter(); callChrome(); });
  $("callCtl").addEventListener("click",()=>{ if(call && call.t1) callChrome(); });   // using a button keeps them on screen a little longer
  document.addEventListener("fullscreenchange",()=>{ $("callFs").classList.toggle("on", fsActive()); });
  $("callBannerJoin").addEventListener("click",joinGroupCall);
  window.addEventListener("pagehide",()=>{ if(call) endCall("ended"); });
  const ginvLink=()=>{ const g=_ginvPending; if(!g) return ""; const o={rid:g.rid,gk:g.gk,name:g.name}; if(g.adm) o.adm=g.adm; return CANONICAL+"/#g="+b64url(enc.encode(JSON.stringify(o))); };
  $("ginvShare").addEventListener("click",async()=>{ const g=_ginvPending; if(!g) return; const url=ginvLink(); const msg=t("Join my Gizleme group “{name}” 🔒\n{url}",{name:g.name,url});
    if(navigator.share){ try{ await navigator.share({text:msg}); $("ginvModal").classList.remove("show"); return; }catch(e){ if(e&&e.name==="AbortError") return; } }
    try{ await navigator.clipboard.writeText(url); toast(t("Invite link copied")); }catch(e){ prompt(t("Copy this invite link:"),url); } $("ginvModal").classList.remove("show"); });
  $("ginvCopy").addEventListener("click",async()=>{ const url=ginvLink(); if(!url) return; try{ await navigator.clipboard.writeText(url); toast(t("Invite link copied")); }catch(e){ prompt(t("Copy this invite link:"),url); } $("ginvModal").classList.remove("show"); });
  $("ginvLater").addEventListener("click",()=>$("ginvModal").classList.remove("show"));
  $("peerMeta").addEventListener("click",openInfo);       // the name (and the avatar) open Chat info, as in any messenger
  $("peerAvatar").addEventListener("click",openInfo);
  $("peerMeta").addEventListener("keydown",e=>{ if(e.key==="Enter"||e.key===" "){ e.preventDefault(); openInfo(); } });
  wireInfo();
  // search: the chats list, and inside a chat
  $("listSearch").addEventListener("input",e=>setSearch(e.target.value));
  $("listSearch").addEventListener("keydown",e=>{ if(e.key==="Escape"){ e.target.value=""; setSearch(""); e.target.blur(); } });
  $("listSearchX").addEventListener("click",()=>{ $("listSearch").value=""; setSearch(""); try{ $("listSearch").focus(); }catch(e){} });
  { let fT=null; $("findInput").addEventListener("input",()=>{ clearTimeout(fT); fT=setTimeout(runFind,150); }); }
  $("findInput").addEventListener("keydown",e=>{ if(e.key==="Enter"){ e.preventDefault(); findStep(e.shiftKey?1:-1); } else if(e.key==="Escape"){ e.preventDefault(); closeFind(); } });
  document.addEventListener("keydown",e=>{ if(e.key==="Escape" && !$("findBar").hidden && !document.querySelector(".modal.show")) closeFind(); });
  $("findUp").addEventListener("click",()=>findStep(-1)); $("findDown").addEventListener("click",()=>findStep(1)); $("findClose").addEventListener("click",closeFind);
  // deleting a message
  $("delMe").addEventListener("click",deleteForMe); $("delAll").addEventListener("click",deleteForAll);
  $("delCancel").addEventListener("click",()=>{ _delFor=null; $("delMsgModal").classList.remove("show"); });
  $("delMsgModal").addEventListener("click",e=>{ if(e.target.id==="delMsgModal"){ _delFor=null; $("delMsgModal").classList.remove("show"); } });
  // iOS only lets audio start inside a user gesture: unlock at the first tap so the connection / message sounds
  // that follow (which are not user-initiated) can be heard.
  document.addEventListener("pointerdown",()=>{ if(soundMode()!=="none") initAudio(); },{passive:true});
  $("sendBtn").addEventListener("mousedown",e=>e.preventDefault());        // keep the keyboard open while sending
  $("attachBtn").addEventListener("mousedown",e=>e.preventDefault());
  $("msgInput").addEventListener("focus",()=>{ [120,350,700].forEach(ms=>setTimeout(()=>{ fitViewport(); stickLog(); },ms)); });
  $("msgInput").addEventListener("blur",()=>{ setTimeout(healViewport,160); setTimeout(fitViewport,400); });
  $("join").addEventListener("focusin",e=>{ const el=e.target; if(!el||!/^(INPUT|TEXTAREA)$/.test(el.tagName)) return;
    [150,400,750].forEach(ms=>setTimeout(()=>{ fitViewport(); try{ el.scrollIntoView({block:"center",behavior:ms===150?"auto":"smooth"}); }catch(_e){} },ms)); });
  $("join").addEventListener("focusout",()=>{ setTimeout(healViewport,160); setTimeout(fitViewport,400); });
  // Enter sends (the mobile keyboard shows "send" via enterkeyhint); Shift+Enter makes a new line. The box grows up to ~5 lines.
  $("msgInput").addEventListener("keydown",e=>{ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); sendText(); } });
  const growBox=()=>{ const el=$("msgInput"); el.style.height="auto"; el.style.height=Math.min(120, el.scrollHeight)+"px"; };
  $("msgInput").addEventListener("input",growBox);
  $("msgInput").addEventListener("input",e=>{ if(!e.isTrusted || _edit) return; typingTick($("msgInput").value.trim() ? "t" : ""); });   // "typing…" for the others
  $("attachBtn").addEventListener("click",()=>{ closePanel(false); $("camInput").click(); });       // the camera, straight away
  $("camInput").addEventListener("change",e=>{ const f=e.target.files[0]; e.target.value=""; if(f) sendImage(f); });
  $("docInput").addEventListener("change",e=>{ const f=e.target.files[0]; e.target.value=""; if(f) sendDoc(f); });
  $("plusBtn").addEventListener("mousedown",e=>e.preventDefault());
  $("plusBtn").addEventListener("click",()=>{ if(_panel) closePanel(true); else openPanel("plus"); });
  $("msgInput").addEventListener("focus",()=>{ if(_panel) openPanel(""); });   // back to the keyboard
  $("plusPanel").addEventListener("click",e=>{ const b=e.target.closest && e.target.closest("[data-act]"); if(!b) return; const a=b.dataset.act; closePanel(false);
    if(a==="photos") $("fileInput").click(); else if(a==="camera") $("camInput").click(); else if(a==="loc") sendLocation(); else if(a==="doc") $("docInput").click();
    else if(a==="poll") openPollModal(); else if(a==="event") openEvtModal(); });
  $("pollAdd").addEventListener("click",addPollOpt); $("pollSend").addEventListener("click",sendPoll); $("pollCancel").addEventListener("click",()=>$("pollModal").classList.remove("show"));
  $("evtSend").addEventListener("click",sendEvt); $("evtCancel").addEventListener("click",()=>$("evtModal").classList.remove("show"));
  { const ta=$("msgInput"), dsc=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value");   // any change of the text, typed or not, switches mic ↔ send
    try{ Object.defineProperty(ta,"value",{configurable:true, get(){ return dsc.get.call(this); }, set(v){ dsc.set.call(this,v); syncComposer(); }}); }catch(e){}
    ta.addEventListener("input",syncComposer); syncComposer(); }
  $("micBtn").addEventListener("mousedown",e=>e.preventDefault());
  $("micBtn").addEventListener("click",()=>startRec());
  $("recCancel").addEventListener("click",()=>stopRec(false));
  $("recSend").addEventListener("click",()=>stopRec(true));
  $("fileInput").addEventListener("change",e=>{ const fs=[...e.target.files]; e.target.value=""; sendFiles(fs); });
  // ----- theme + sound (surfaced in Settings) -----
  function currentDark(){ const c=document.documentElement.getAttribute("data-theme"); return c?c==="dark":matchMedia("(prefers-color-scheme:dark)").matches; }
  function refreshThemeUI(){ const d=currentDark(); if($("themeState")) $("themeState").textContent=d?t("Dark"):t("Light"); if($("themeToggle")){ const b=$("themeToggle"); b.textContent=""; b.append(icoEl(d?"i-sun":"i-moon",""), d?t("Light"):t("Dark")); } }
  function toggleTheme(){ const next=currentDark()?"light":"dark"; document.documentElement.setAttribute("data-theme",next); try{ localStorage.setItem("vesper-theme",next); }catch(e){} refreshThemeUI(); }
  function refreshSoundUI(){ const sel=$("soundSel"); if(sel) sel.value=soundMode();
    const cur=toneName(); document.querySelectorAll("#toneSel .tone").forEach(x=>x.setAttribute("aria-checked", x.dataset.tone===cur ? "true":"false")); }
  document.querySelectorAll("#toneSel .tone").forEach(btn=>btn.addEventListener("click",()=>{
    if(soundMode()!=="all") setSoundMode("all");      // picking a message sound means wanting to hear it
    btn.classList.remove("playing"); void btn.offsetWidth; btn.classList.add("playing");
    previewTone(btn.dataset.tone); refreshSoundUI(); }));
  function refreshLangUI(){ const s=$("langSel"); if(s) s.value=LANG; }
  $("langSel").addEventListener("change",e=>{ const v=e.target.value; if(LANGS.includes(v)) setLang(v); });
  // iPhone display (see sb.js): shown on iPhone / iPad only, with the numbers that tell what the screen does
  { const IOSDEV=/iphone|ipad|ipod/i.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints>1);
    if(IOSDEV && $("sbRow")){ $("sbRow").hidden=false; $("sbNote").hidden=false; $("sbInfo").hidden=false;
      const mode=document.documentElement.classList.contains("sb-compat") ? "compat" : "std"; $("sbSel").value=mode;   // in force now (chosen, or the default)
      const diag=()=>{ const v=(/OS (\d+)[._](\d+)/.exec(navigator.userAgent)||[]).slice(1).join("."), si=safeInsets(), sw=Math.min(screen.width,screen.height), sh=Math.max(screen.width,screen.height);
        $("sbInfo").textContent="iOS "+(v||"?")+" · "+(STANDALONE?"app":"Safari")+" · "+t("screen")+" "+sw+"×"+sh+" · "+t("view")+" "+window.innerWidth+"×"+viewH()+" · safe "+si.top+"/"+si.bottom+" · "+(document.documentElement.classList.contains("ios-gap")?"gap":"no gap")+" · "+mode; };
      diag(); $("sbRow").closest(".modal") && $("sbRow").closest(".modal").addEventListener("transitionend",diag);
      $("sbSel").addEventListener("change",e=>{ const v=e.target.value; try{ localStorage.setItem("gz-sbmode", v==="compat" ? "compat" : "std"); }catch(_){}
        toast(t("Close the app completely, then open it again")); setTimeout(()=>location.reload(), 1800); }); } }
  { const ts=$("textSize"); if(ts){ ts.value=String(textScale());
    ts.addEventListener("change",e=>{ const v=+e.target.value; if(!TEXT_SIZES.includes(v)) return; try{ localStorage.setItem(LS_TEXT,String(v)); }catch(_){} applyTextScale(v); stickLog(); toast(t("Text size updated")); }); } }
  refreshLangUI();   // the selector shows the language in use from the start (detected or saved)
  _refreshSettingsUI=()=>{ refreshThemeUI(); refreshSoundUI(); refreshLangUI(); refreshPrevUI(); updateNotifyUI(); };
  $("soundSel").addEventListener("change",e=>{ setSoundMode(e.target.value); if(soundMode()==="all"){ initAudio(); soundRecv(); } refreshSoundUI(); });
  $("themeToggle").addEventListener("click",toggleTheme);

  // ----- Settings modal -----
  function setPage(pg){ const m=$("settingsModal"); let shown=null;
    m.querySelectorAll(".set-page").forEach(x=>{ const on=x.dataset.page===pg; x.hidden=!on; if(on) shown=x; });
    if(!shown){ m.querySelector('.set-page[data-page="root"]').hidden=false; pg="root"; }
    m.dataset.page=pg; const c=m.querySelector(".card"); if(c) c.scrollTop=0;
    const f=shown && (shown.querySelector(".set-back") || shown.querySelector(".set-me")); if(f && !TOUCH_UI) try{ f.focus({preventScroll:true}); }catch(e){} }
  function openSettings(pg){
    setPage(typeof pg==="string" ? pg : "root");
    { const s=sessLoad(), nm=(s&&(s.display||s.username))||"—";
      $("setMeName").textContent=nm; $("setMeSub").textContent=s&&s.username ? "@"+s.username : t("Display name");
      $("setAva").textContent=up((nm||"?")[0]); $("setAva").style.background=s&&s.username ? autoColor(s.username) : ""; }
    $("expGlobal").value=String(expGlobal());
    const hasRoom=!!active;
    $("expRoomRow").style.display=hasRoom?"flex":"none";
    if(hasRoom){ const m=expRoomsMap(), k=histKeyOf(A()); $("expRoom").value=Object.prototype.hasOwnProperty.call(m,k)?String(m[k]===null?0:m[k]):""; }
    refreshThemeUI(); refreshSoundUI(); refreshLangUI(); updateNotifyUI();
    if($("autoLock")) $("autoLock").value=String(autoLockMs());
    refreshPrevUI();
    const s=sessLoad(); if($("acctUser")) $("acctUser").textContent=(s&&(s.display||s.username))||"—";
    if($("dispNow")) $("dispNow").textContent=(s&&s.display)||"—";
    $("settingsModal").classList.add("show");
  }
  $("logoutBtn").addEventListener("click",()=>{ if(!confirm(String(LOGOUT_MSG))) return; $("settingsModal").classList.remove("show"); logoutAccount(); });
  // forgot / change / delete password & account
  const openModal=id=>$(id).classList.add("show"), closeModal=id=>$(id).classList.remove("show");
  $("memClose").addEventListener("click",()=>closeModal("memModal"));
  $("forgotLink").addEventListener("click",()=>openModal("forgotModal"));
  $("forgotClose").addEventListener("click",()=>closeModal("forgotModal"));
  $("forgotNew").addEventListener("click",()=>{ closeModal("forgotModal"); if($("join").dataset.mode==="unlock"){ if(confirm(String(LOGOUT_MSG))) logoutAccount().then(()=>showAuth("register")); } else showAuth("register"); });
  $("chpwBtn").addEventListener("click",()=>{ closeModal("settingsModal"); ["pwCur","pwNew","pwNew2"].forEach(i=>$(i).value=""); $("pwMsg").textContent=""; openModal("pwModal"); });
  $("pwCancel").addEventListener("click",()=>closeModal("pwModal"));
  $("pwSave").addEventListener("click",async()=>{
    const cur=$("pwCur").value, nw=$("pwNew").value, nw2=$("pwNew2").value; const m=$("pwMsg"); m.className="authmsg";
    if(nw.length<8){ m.textContent=t("New password must be at least 8 characters"); return; }
    if(nw!==nw2){ m.textContent=t("New passwords don't match"); return; }
    $("pwSave").disabled=true; m.textContent=t("Changing…");
    try{ await changePassword(cur,nw); m.textContent=""; closeModal("pwModal"); toast(t("Password changed — other devices must log in again")); }
    catch(e){ m.textContent=(e&&e.message)||t("Couldn't change the password"); }
    $("pwSave").disabled=false;
  });
  $("delAcctBtn").addEventListener("click",()=>{ closeModal("settingsModal"); $("delPw").value=""; $("delMsg").textContent=""; openModal("delModal"); });
  $("delCancel").addEventListener("click",()=>closeModal("delModal"));
  $("delConfirm").addEventListener("click",async()=>{
    const pw=$("delPw").value; const m=$("delMsg"); if(!pw){ m.textContent=t("Enter your password"); return; }
    if(!confirm(t("Delete your account now? This cannot be undone."))) return;
    $("delConfirm").disabled=true; m.textContent=t("Deleting…");
    try{ await deleteAccount(pw); closeModal("delModal"); showAuth("welcome"); toast(t("Your account has been deleted")); }
    catch(e){ m.textContent=(e&&e.message)||t("Couldn't delete the account"); }
    $("delConfirm").disabled=false;
  });
  ["forgotModal","pwModal","delModal"].forEach(id=>$(id).addEventListener("click",e=>{ if(e.target.id===id) closeModal(id); }));
  $("settingsClose").addEventListener("click",()=>$("settingsModal").classList.remove("show"));
  $("settingsModal").addEventListener("click",e=>{ const g=e.target.closest && e.target.closest("[data-go]"); if(g){ setPage(g.dataset.go); return; }
    if(e.target.closest && e.target.closest(".set-back")) setPage("root"); });
  document.addEventListener("keydown",e=>{ if(e.key!=="Escape") return; const m=$("settingsModal");
    if(m.classList.contains("show")){ if(m.dataset.page && m.dataset.page!=="root") setPage("root"); else m.classList.remove("show"); } });
  $("settingsModal").addEventListener("click",e=>{ if(e.target.id==="settingsModal") $("settingsModal").classList.remove("show"); });
  // ----- privacy & lock, and the "why Gizleme" comparison -----
  $("autoLock").addEventListener("change",e=>{ setAutoLock(+e.target.value||0); toast(+e.target.value?t("Auto-lock on"):t("Auto-lock off")); });
  function refreshPrevUI(){ const h=previewsHidden(); if($("prevState")) $("prevState").textContent=h?t("Hidden"):t("Shown"); if($("prevToggle")) $("prevToggle").textContent=h?t("Show"):t("Hide");
    const s=shieldOn(); if($("shieldState")) $("shieldState").textContent=s?t("On"):t("Off"); if($("shieldToggle")){ $("shieldToggle").textContent=s?t("On"):t("Off"); $("shieldToggle").classList.toggle("off",!s); } }
  $("prevToggle").addEventListener("click",()=>{ const h=!previewsHidden(); setPreviewsHidden(h); refreshPrevUI(); toast(h?t("Previews hidden"):t("Previews shown")); });
  function refreshTypUI(){ const on=typingOn(); if($("typState")) $("typState").textContent=on?t("On"):t("Off"); if($("typToggle")){ $("typToggle").textContent=on?t("On"):t("Off"); $("typToggle").classList.toggle("off",!on); } }
  refreshTypUI();
  $("typToggle").addEventListener("click",()=>{ const on=!typingOn(); if(!on) typingTick("");
    try{ localStorage.setItem(LS_TYPING, on?"1":"0"); }catch(e){}
    if(!on) rooms.forEach(R=>{ if(R.typing){ R.typing.clear(); typingShow(R); } });
    refreshTypUI(); toast(on?t("Typing indicators on"):t("Typing indicators off")); });
  $("shieldToggle").addEventListener("click",()=>{ const s=!shieldOn(); setShieldOn(s); refreshPrevUI(); toast(s?t("Privacy screen on"):t("Privacy screen off")); });
  // display name (what friends see): free text, changed server-side and re-announced
  $("dispEdit").addEventListener("click",async()=>{ const s=sessLoad(); if(!s||!s.token) return; const v=prompt(t("New display name:"), s.display||""); if(v===null) return; const nv=v.trim().slice(0,24); if(!nv) return;
    try{ const r=await authFn("rename",{token:s.token, display:nv}); if(!r.data||!r.data.ok) throw new Error(); sessSave(Object.assign({},s,{display:nv})); myName=nv; retrackAll(); if($("acctUser")) $("acctUser").textContent=nv; if($("dispNow")) $("dispNow").textContent=nv; toast(t("Name updated")); }
    catch(e){ toast(t("Couldn't update the name — try again")); } });
  // Cover the content the instant the page goes to the background (synchronously, so the app-switcher
  // snapshot is of the shield), uncover when it returns.
  document.addEventListener("visibilitychange",()=>{ if(document.hidden){ if(shieldOn()) showShield(true); } else showShield(false); });
  window.addEventListener("pagehide",()=>{ if(shieldOn()) showShield(true); });
  window.addEventListener("pageshow",()=>showShield(false));
  $("lockNowBtn").addEventListener("click",()=>{ $("settingsModal").classList.remove("show"); lockApp(); });
  $("sbLock").addEventListener("click",lockApp);
  $("sbSettings").addEventListener("click",openSettings);
  const openWhy=()=>{ $("settingsModal").classList.remove("show"); $("whyModal").classList.add("show"); };
  $("whyLink").addEventListener("click",openWhy);
  $("whyBtn").addEventListener("click",openWhy);
  $("whyClose").addEventListener("click",()=>$("whyModal").classList.remove("show"));
  $("whyModal").addEventListener("click",e=>{ if(e.target.id==="whyModal") $("whyModal").classList.remove("show"); });
  // any activity postpones the auto-lock; a long time in the background locks on return
  ["pointerdown","keydown","touchstart"].forEach(ev=>document.addEventListener(ev,()=>{ if(gHistKey) armAutoLock(); },{passive:true}));
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){ _hiddenAt=Date.now(); return; }
    const ms=autoLockMs(); if(ms && gHistKey && _hiddenAt && !call && Date.now()-_hiddenAt>=ms) lockApp(); else if(gHistKey) armAutoLock();
    _hiddenAt=0;
  });
  $("expGlobal").addEventListener("change",e=>{ setExpGlobal(+e.target.value||0); toast(t("Default updated")); });
  $("expRoom").addEventListener("change",e=>{ const R=A(); if(!R) return; const v=e.target.value;
    if(v===""){ setExpRoom(histKeyOf(R),""); paintExpBtn(); } else chooseExp(+v);   // a chosen time applies to the chat for both sides
    toast(t("Updated for this chat")); });
  $("expGlobal").addEventListener("change",()=>paintExpBtn());
  $("expBtn").addEventListener("click",e=>{ e.stopPropagation(); if($("expMenu").hidden) openExpMenu(); else closeExpMenu(); });
  $("expMenu").addEventListener("click",e=>{ const b=e.target.closest && e.target.closest("button[data-v]"); if(b) chooseExp(+b.dataset.v); });
  document.addEventListener("pointerdown",e=>{ const m=$("expMenu"); if(m && !m.hidden && !m.contains(e.target) && !$("expBtn").contains(e.target)) closeExpMenu(); },true);
  document.addEventListener("keydown",e=>{ if(e.key==="Escape") closeExpMenu(); });
  setInterval(sweepEphemeral, 15000);
  setInterval(()=>{ if(gHistKey) advanceChains().catch(()=>{}); }, 6*3600*1000);   // weekly chains: check a few times a day
  // poll the encrypted mailbox for every open chat so offline-sent messages arrive (and count as unread) even without a push
  setInterval(()=>{ inboxPull(false); }, 20000);
  // when the app comes back to the foreground (e.g. tapped a push), pull right away
  document.addEventListener("visibilitychange",()=>{ if(!document.hidden){ inboxPull(true); } });
  // offline banner: sending is attempted anyway (and marked failed → tap to retry), but say why
  const updateNet=()=>{ const nb=$("netBar"); if(nb) nb.hidden=(navigator.onLine!==false); };
  window.addEventListener("online",()=>{ updateNet(); inboxPull(true); }); window.addEventListener("offline",updateNet); updateNet();
  // Presence hygiene: leave every room's presence the moment the page is going away (a reload otherwise leaves
  // a ghost the relay keeps for a while, which the other side could pair with), and re-announce on return.
  const untrackAll=()=>rooms.forEach(R=>{ try{ R.channel&&R.channel.untrack&&R.channel.untrack(); }catch(e){} });
  window.addEventListener("pagehide",untrackAll);
  window.addEventListener("pageshow",e=>{ if(e.persisted) retrackAll(); });
  document.addEventListener("visibilitychange",()=>{ if(!document.hidden) retrackAll(); });

  // ----- PWA install (surfaced in Settings) -----
  let deferredPrompt=null;
  const isStandalone = matchMedia("(display-mode: standalone)").matches || window.navigator.standalone===true;
  const isIOS = (/iphone|ipad|ipod/i.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints>1)) && !window.MSStream;   // (an iPad says "Macintosh")
  const isAndroid = /android/i.test(navigator.userAgent);
  const isMacSafari = !isIOS && /Macintosh/.test(navigator.userAgent) && /Safari\//.test(navigator.userAgent) && !/Chrome|Chromium|CriOS|Edg|Firefox|OPR/.test(navigator.userAgent);
  if(isStandalone){ try{ localStorage.setItem("gz-installed", String(Date.now())); }catch(e){} }   // opened as the installed app
  if(isIOS && $("toneHint")) $("toneHint").hidden=false;
  function showInstall(on){ if($("installGroup")) $("installGroup").style.display=on?"block":"none"; if($("installNav")) $("installNav").hidden=!on; }
  window.addEventListener("beforeinstallprompt",e=>{ e.preventDefault(); deferredPrompt=e; if(!isStandalone) showInstall(true);
    if(installModalPending){ installModalPending=false; clearTimeout(_instWait); openInstallModal(); } });
  window.addEventListener("appinstalled",()=>{ showInstall(false); deferredPrompt=null; closeInstallModal(); try{ localStorage.setItem("gz-installed", String(Date.now())); }catch(e){} toast(t("Gizleme installed 🎉")); });
  if((isIOS || isAndroid || isMacSafari) && !isStandalone) showInstall(true);
  $("installPill").addEventListener("click",async()=>{
    if(deferredPrompt){ deferredPrompt.prompt(); try{ await deferredPrompt.userChoice; }catch(e){} deferredPrompt=null; showInstall(false); return; }
    openInstallModal(true);
  });

  // ----- install invitation -----
  // While Gizleme isn't installed on this device, a window offers to add it (one button where the browser can
  // install it itself, illustrated steps on iPhone / iPad, Android browsers without that button and Safari on a
  // Mac). It comes back spaced out — the next day, then every three days, at most six times — and never once
  // "Don't show this again" was chosen, or the installed app was opened on this device in the last two weeks.
  const LS_INST="gz-install", INST_MAX=6, DAY=86400000;
  let installModalPending=false, _instWait=null;
  function instState(){ let o=null; try{ o=JSON.parse(localStorage.getItem(LS_INST)||"null"); }catch(e){}
    if(!o || typeof o!=="object"){ o={n:0, next:0}; try{ if(localStorage.getItem("gz-installPrompted")==="1") o.n=1; }catch(e){} }   // (the old one-time flag: shown once)
    return o; }
  function instSave(o){ try{ localStorage.setItem(LS_INST, JSON.stringify(o)); }catch(e){} }
  function recentlyInstalled(){ try{ const ts=+localStorage.getItem("gz-installed")||0; return ts && Date.now()-ts < 14*DAY; }catch(e){ return false; } }
  function installDue(){ if(isStandalone || recentlyInstalled()) return false; const o=instState(); return !o.never && (o.n||0)<INST_MAX && Date.now()>=(o.next||0); }
  function markInstallShown(){ const o=instState(); o.n=(o.n||0)+1; o.next=Date.now()+(o.n<=1?1:3)*DAY; instSave(o); }
  function closeInstallModal(){ const m=$("installModal"); if(m) m.classList.remove("show"); }
  const I_SHARE='<svg class="iico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 10H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2h-2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
  const I_ADD='<svg class="iico" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="3.5" width="17" height="17" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 8v8M8 12h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
  const I_MENU='<svg class="iico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="2" fill="currentColor"/><circle cx="12" cy="12" r="2" fill="currentColor"/><circle cx="12" cy="19" r="2" fill="currentColor"/></svg>';
  function instSteps(list){ return list.map(x=>"<li>"+x+"</li>").join(""); }
  // manual: opened from Settings → Install (shown whatever the schedule says, and not counted)
  function openInstallModal(manual){
    if(isStandalone) return false;
    const steps=$("installSteps"), body=$("installBody"), now=$("installNow"), sub=$("installSub");
    if(deferredPrompt){
      sub.textContent=t("Add it to your device");
      body.textContent=t("Open Gizleme straight from your home screen, full-screen, and get notified of new messages even when your browser is closed.");
      steps.style.display="none"; now.style.display="block";
    } else if(isIOS || isAndroid || isMacSafari){
      sub.textContent= isMacSafari ? t("Add it to your Dock") : t("Add it to your Home Screen");
      body.textContent=t("Install Gizleme for a full-screen app and message notifications:");
      steps.innerHTML = isIOS ? instSteps([ t("Tap {icon} <b>Share</b> in Safari (at the bottom of the screen — or under <b>⋯</b>)").replace("{icon}",I_SHARE),
                                            t("Choose {icon} <b>Add to Home Screen</b> (scroll down the list if needed)").replace("{icon}",I_ADD),
                                            t("Tap <b>Add</b>: the Gizleme icon appears on your home screen") ])
                      : isAndroid ? instSteps([ t("Open the browser menu {icon} (top right, or ≡ at the bottom)").replace("{icon}",I_MENU),
                                                t("Choose {icon} <b>Install app</b> or <b>Add to Home screen</b>").replace("{icon}",I_ADD),
                                                t("Confirm: the Gizleme icon appears on your home screen") ])
                      : instSteps([ t("In the menu bar, choose <b>File</b> → {icon} <b>Add to Dock…</b>").replace("{icon}",I_ADD),
                                    t("Click <b>Add</b>: Gizleme opens like an app, from your Dock") ]);
      steps.style.display="block"; now.style.display="none";
    } else { if(manual) toast(t("Open the browser menu → Install Gizleme")); return false; }   // no known install path on this browser
    $("installNever").hidden=!!manual;
    if(!manual) markInstallShown();
    $("installModal").classList.add("show"); return true;
  }
  async function maybeShowInstallModal(){
    if(!installDue()) return;
    if(isInAppBrowser()) return;       // can't install from inside WhatsApp/Messenger — don't show it there
    if(document.querySelector(".modal.show") || !$("callUI").hidden) { setTimeout(maybeShowInstallModal, 4000); return; }   // don't stack on an open dialog or a call
    try{ if(navigator.getInstalledRelatedApps){ const apps=await navigator.getInstalledRelatedApps(); if(apps && apps.length){ try{ localStorage.setItem("gz-installed", String(Date.now())); }catch(e){} return; } } }catch(e){}
    if(deferredPrompt || isIOS || isMacSafari){ openInstallModal(); return; }
    // the browser's own install button may still be coming: wait for it a little, then show the steps (Android)
    installModalPending=true; clearTimeout(_instWait);
    _instWait=setTimeout(()=>{ if(!installModalPending) return; installModalPending=false; if(isAndroid && installDue() && !document.querySelector(".modal.show")) openInstallModal(); }, 6000);
  }
  _showInstallInvite = maybeShowInstallModal;   // expose to enterApp (top-level scope)
  $("installNow").addEventListener("click",async()=>{
    closeInstallModal();
    if(deferredPrompt){ deferredPrompt.prompt(); try{ await deferredPrompt.userChoice; }catch(e){} deferredPrompt=null; showInstall(false); }
  });
  $("installLater").addEventListener("click",closeInstallModal);
  $("fwdCancel").addEventListener("click",()=>$("fwdModal").classList.remove("show"));
  $("fwdModal").addEventListener("click",e=>{ if(e.target.id==="fwdModal") $("fwdModal").classList.remove("show"); });
  $("installNever").addEventListener("click",()=>{ const o=instState(); o.never=true; instSave(o); closeInstallModal(); });
  $("installModal").addEventListener("click",e=>{ if(e.target.id==="installModal") closeInstallModal(); });

  if("serviceWorker" in navigator){ window.addEventListener("load",()=>{ navigator.serviceWorker.register("/sw.js").catch(()=>{}); });
    navigator.serviceWorker.addEventListener("message", e=>{ const m=e.data||{}; if(m.type!=="open") return;   // a notification tapped while a window is open
      let n=""; try{ const mm=/^n=(.*)$/.exec((new URL(m.url,location.origin).hash||"").replace(/^#/,"")); if(mm) n=decodeURIComponent(mm[1]); }catch(x){}
      if(!n) return; if(gHistKey) openByNotifyKey(n).then(ok=>{ if(!ok) _pendingNotify=n; }).catch(()=>{}); else _pendingNotify=n; }); }
  // ----- a newer version is out -----
  // An app left open (a phone keeps it in memory for days) goes on running the code it started with. When it
  // comes back to the foreground (and every 30 minutes) it reads the version of the service worker on the
  // server; a higher one shows a small pill: tap to update. On the lock / login screen with nothing typed,
  // nothing can be lost, so it simply reloads there.
  document.addEventListener("visibilitychange",()=>{ if(!document.hidden) checkUpdate(false); });
  setInterval(()=>checkUpdate(false), 1800000);
  $("updGo").addEventListener("click",()=>{ if(call && !confirm(t("Updating will end the call. Update now?"))) return; location.reload(); });
  $("updX").addEventListener("click",()=>{ $("updPill").hidden=true; _updLater=true; });

  // ----- in-app browser nudge -----
  // A link tapped inside WhatsApp/Messenger/Instagram opens in their embedded webview, which cannot
  // hand off to the installed Gizleme app. We detect that and offer a way out: one tap on Android
  // (an Android intent that opens the installed app if set, otherwise the default browser), and a short
  // instruction on iPhone (where tapping "Open in Safari" from the in-app menu is the only route).
  function isInAppBrowser(){ const ua=navigator.userAgent||""; if(isStandalone) return false;
    return /(FBAN|FBAV|FB_IAB|Instagram|WhatsApp|Line\/|Messenger|MicroMessenger|Snapchat|TikTok|Twitter|Pinterest)/i.test(ua)
        || (/Android/i.test(ua) && /; wv\)/.test(ua))
        || (/iPhone|iPad|iPod/i.test(ua) && !/Safari\//i.test(ua) && !/CriOS|FxiOS|EdgiOS/i.test(ua)); }   // WKWebView without Safari's token
  _isInApp=isInAppBrowser;
  function iabIntentUrl(){
    // Query + path only — a #g= group invite carries the group key in its fragment, which must never be
    // placed where it could be sent to a server, so those links fall back to the manual "open in browser" route.
    const host=location.host, pq=location.pathname+location.search;
    const fallback=encodeURIComponent(location.origin+pq);     // never includes a fragment
    return "intent://"+host+pq+"#Intent;scheme=https;S.browser_fallback_url="+fallback+";end";
  }
  function showIabBar(){
    if(isStandalone || !isInAppBrowser()) return;
    try{ if(sessionStorage.getItem("gz-iab-dismiss")==="1") return; }catch(e){}
    const bar=$("iabBar"); if(!bar) return;
    const ua=navigator.userAgent||"", isAndroid=/Android/i.test(ua), iOS=/iPhone|iPad|iPod/i.test(ua);
    const hasGroupFrag=/^#(g|i|n|room)=/.test(location.hash||"");   // the secret / target rides in the fragment
    if(isAndroid && !hasGroupFrag){
      $("iabHint").textContent=t("Gizleme works best in your browser or app.");
      $("iabOpen").style.display="inline-block";
      $("iabOpen").onclick=()=>{ try{ location.href=iabIntentUrl(); }catch(e){} };
    } else {
      $("iabHint").textContent = iOS
        ? t("Open this link in Safari for the full app: tap the ⋯ menu, then “Open in Safari”.")
        : t("Open this link in your browser for the full app: use this page’s ⋯ menu, then “Open in browser”.");
      $("iabOpen").style.display="none";
    }
    document.body.classList.add("has-iab"); bar.hidden=false;
  }
  $("iabClose").addEventListener("click",()=>{ $("iabBar").hidden=true; document.body.classList.remove("has-iab"); try{ sessionStorage.setItem("gz-iab-dismiss","1"); }catch(e){} });
  showIabBar();

  // ----- overflow menu (⋮) -----
  function closeMenu(){ $("barMenu").hidden=true; }
  function toggleMenu(){ const m=$("barMenu");
    if(m.hidden){ const R=A(); const grp=!!(R&&R.group);
      $("mi-invite").hidden=!grp; $("mi-info").hidden=!R; $("mi-find").hidden=!(R && R.logEl);
      $("mi-loc").hidden=!(R&&(grp||R.fromContact||R.paired));
      { const rec=muteRecOf(R), mu=mutedUntil(rec);
        $("mi-mute").hidden=!rec || !!mu; $("mi-unmute").hidden=!mu; $("mi-mute-opts").hidden=true;
        $("mi-mute-until").textContent = mu && mu<MUTE_ALWAYS ? t("until {time}",{time:fmtUntil(mu)}) : ""; }
      m.hidden=false;
    } else m.hidden=true;
  }
  $("menuBtn").addEventListener("click",e=>{ e.stopPropagation(); toggleMenu(); });
  document.addEventListener("click",e=>{ if(!$("barMenu").hidden && !$("barMenu").contains(e.target) && e.target!==$("menuBtn")) closeMenu(); });
  $("barMenu").addEventListener("click",e=>{ const b=e.target.closest(".menu-item"); if(!b) return;
    if(b.dataset.act==="mute"){ $("mi-mute-opts").hidden=!$("mi-mute-opts").hidden; return; }   // pick how long: the menu stays open
    closeMenu();
    const act=b.dataset.act;
    if(act==="invite") inviteToGroup();
    else if(act==="info") openInfo();
    else if(act==="find") openFind();
    else if(act==="loc") sendLocation();
    else if(act==="mute1h") setMute(A(), 3600000);
    else if(act==="mute8h") setMute(A(), 28800000);
    else if(act==="muteall") setMute(A(), MUTE_ALWAYS);
    else if(act==="unmute") setMute(A(), 0);
  });

  $("mergeCancel").addEventListener("click",()=>$("mergeModal").classList.remove("show"));
  $("mergeModal").addEventListener("click",e=>{ if(e.target.id==="mergeModal") $("mergeModal").classList.remove("show"); });
  // ----- contacts / navigation -----
  renderContacts();
  $("sbNew").addEventListener("click",()=>{ closeSidebar(); showAddRoom(); });
  $("fabNew").addEventListener("click",()=>{ closeSidebar(); showAddRoom(); });
  $("backHome").addEventListener("click",goHome);
  $("sbBackdrop").addEventListener("click",closeSidebar);

  // ----- notifications + identity verification -----
  $("notifyToggle").addEventListener("click",async()=>{ if(pushOn()) await disablePush(); else await enablePush(); });
  $("verifyBtn").addEventListener("click",openVerify);
  $("verifyMark").addEventListener("click",markVerifiedNow);
  $("verifyClose").addEventListener("click",()=>$("verifyModal").classList.remove("show"));
  $("verifyModal").addEventListener("click",e=>{ if(e.target.id==="verifyModal") $("verifyModal").classList.remove("show"); });
  if("serviceWorker" in navigator){ navigator.serviceWorker.ready.then(()=>pushInit()).catch(()=>updateNotifyUI()); }
  else updateNotifyUI();

  // ----- the logo comes alive on first open (and on tap) -----
  const la=$("logoAnim");
  if(la){ const play=()=>{ la.classList.remove("play"); void la.offsetWidth; la.classList.add("play"); };
    la.addEventListener("click",play); setTimeout(play, 150); }
  // ----- boot: account-based, permanent login -----
  applyI18n();
  const sess=sessLoad();
  if(sess && sess.username){
    myName=sess.display||sess.username;
    if(pinSet()){ showAuth("unlock"); }                 // logged in → unlock history (Face ID / password)
    else { showAuth("login"); }                           // session without a local lock (shouldn't happen): log in again
  }
  else if(pinSet()){ showAuth("login"); }               // account exists on device, session cleared → log in
  else { showAuth(firstAuthMode()); }                   // brand new → the welcome screen (or the form, when a link brought them)
})();
})();
