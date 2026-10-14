// Gizleme — application code (served same-origin; no third-party scripts, see _headers for the CSP)
(function(){
"use strict";
const SB_URL = "https://jypgewvqoifvorxgbvcs.supabase.co";
const SB_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp5cGdld3Zxb2lmdm9yeGdidmNzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM2MTI2ODksImV4cCI6MjA5OTE4ODY4OX0.2BpVGp5Rq2QXhfHWKKphSIKRQU9hzhhBu_R8E-hv1Eg";
const BUCKET = "vesper-media";
const client = supabase.createClient(SB_URL, SB_KEY, { realtime:{ params:{ eventsPerSecond: 25 } } });

const $ = id => document.getElementById(id);
// ---------- language ----------
const LS_LANG="gz-lang";
let LANG=(()=>{ try{ const v=localStorage.getItem(LS_LANG); if(v==="fr"||v==="en") return v; }catch(e){} return /^fr\b/i.test(navigator.language||"") ? "fr" : "en"; })();
const DICT=(window.GZ_I18N||{});
function t(key, vars){ let v=(LANG!=="en" && DICT[LANG] && DICT[LANG][key]) || key; if(vars) for(const k in vars) v=v.split("{"+k+"}").join(vars[k]); return v; }
function LOC(){ return LANG==="fr" ? "fr-FR" : []; }
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
const enc = new TextEncoder(), dec = new TextDecoder();
const SALT = enc.encode("vesper/v1");
const hex = b => [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,"0")).join("");
const b64 = b => btoa(String.fromCharCode(...new Uint8Array(b)));
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
function newRoom(code){ return { code, id:rid(), kp:null, pubB64:"", tag:null, authOk:false, channel:null, peer:null, root:null, rootFp:"", sendI:0, paired:false, logEl:null, unread:0, statusText:"connecting…", secure:false, peerName:"Waiting for peer…", avatar:"?", fromContact:null, title:null, group:false, rid:null, gk:null, gkMsg:null, seen:null, multiSig:"", recvI:-1 }; }
// (peerName starts as the English placeholder; dn() translates it wherever it is displayed)
// ---------- automatic identity check at every connection ----------
// Two contacts share a secret key (ck) from their first connection or invite link; the relay never has it.
// Each side signs the day's public key with it. A pairing is accepted only if the other side's signature
// verifies, so someone who merely reached the room (a relay, an intercepted room code) can't be paired with.
async function authKeyFor(ckB64){ return crypto.subtle.importKey("raw", await hkdf(unb64(ckB64),"gz-auth/v1"), {name:"HMAC",hash:"SHA-256"}, false, ["sign","verify"]); }
async function authTag(ckB64, pubB64){ return b64(await crypto.subtle.sign("HMAC", await authKeyFor(ckB64), unb64(pubB64))); }
async function authVerify(ckB64, pubB64, tagB64){ try{ return await crypto.subtle.verify("HMAC", await authKeyFor(ckB64), unb64(tagB64), unb64(pubB64)); }catch(e){ return false; } }
async function ensureTag(R){ try{ R.tag = (R.fromContact && R.pubB64) ? await authTag(R.fromContact, R.pubB64) : null; }catch(e){ R.tag=null; } }
// ---------- single-use invite links (protocol v2) ----------
// A link-derived contact key is a bearer secret: anyone who kept the link could use it. So at the first
// live pairing that is authenticated with it, both sides derive a NEW contact key from the session's ECDH
// secret — something only these two devices can compute — and retire the link key. Rendezvous rooms,
// mailbox and push keys move to the new key; history, previews and unread counts stay attached to the
// conversation through a stable history key (hk). Other devices of each account learn the new key from the
// vault (contact {ck:new, prev:old, hk, rot}).
async function rotatedCKFromSecret(secret){ return b64(await hkdf(secret,"gz-contact/v2")); }
async function rotatedCKFor(R, peerPubB64){ const pk=await importPub(unb64(peerPubB64)); return rotatedCKFromSecret(await sharedSecret(R.kp.privateKey,pk)); }
function ckHistKey(ck){ const c=contactFind(ck); return (c&&c.hk)||("c:"+ck); }
function contactByPrev(ckOld){ return contactsLoad().find(c=>c.prev===ckOld)||null; }
// "ok" | "bad" | "missing" | "stale" | "n/a" (no shared key yet in this room: first-ever connection via a room code)
async function verifyPeerTag(R, other){
  if(!R.fromContact) return "n/a";
  if(!other || !other.tag) return "missing";
  if(await authVerify(R.fromContact, other.pub, other.tag)) return "ok";
  const c=contactFind(R.fromContact);
  // They already switched to the key we're about to derive from this very session (rotation in progress).
  if(c && c.inv && !c.rot && R.kp){ try{ const cand=await rotatedCKFor(R, other.pub); if(await authVerify(cand, other.pub, other.tag)) return "ok"; }catch(e){} }
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
let _meta={unread:{},rcpt:{},viewed:{}};   // per-chat unread counts, received-receipts by message id, viewed view-once photos
function contactsLoad(){ return _contacts.map(c=>Object.assign({},c)); }
function contactsSave(list){ _contacts=(list||[]).filter(c=>c&&c.ck).map(c=>Object.assign({},c)); localSaveSoon(); renderContacts(); syncPushSoon(); }
function localSaveSoon(){ clearTimeout(_localT); _localT=setTimeout(()=>{ localSave().catch(()=>{}); swNamesSoon(); },250); }
// The service worker composes notification text itself ("New message from Baba"), so it needs the names
// you use for your contacts — nickname first — and the sentence templates in your language. Only names
// (never keys) leave the encrypted list; they are cleared on lock-out and account deletion.
let _swNamesT=null;
function swNamesSoon(){ clearTimeout(_swNamesT); _swNamesT=setTimeout(()=>{ swNames().catch(()=>{}); },400); }
async function swNames(clear){
  if(!("serviceWorker" in navigator)) return;
  const names={};
  if(!clear) for(const c of contactsLoad()){ try{ const nm=c.alias||(DN_KEYS[c.name]?"":realName(c.name)); if(nm) names[await notifyKeyFor(c.ck)]=nm; }catch(e){} }
  const msg={type:"names", names, tmpl:{ msg:t("New message from {name}"), chat:t("{name} wants to chat on Gizleme"), anyMsg:t("New message"), anyChat:t("A contact wants to chat") }};
  try{ const reg=await navigator.serviceWorker.ready; (reg.active||navigator.serviceWorker.controller)?.postMessage(msg); }catch(e){}
}
async function localSave(){ if(!gHistKey) return; const {iv,ct}=await aesEnc(gHistKey, enc.encode(JSON.stringify({contacts:_contacts,groups:_groups,meta:_meta})));
  try{ localStorage.setItem(LS_LOCAL,JSON.stringify({iv,ct})); }catch(e){} }
async function localLoad(){   // at unlock: decrypt the local copy, and import (then delete) any plaintext left by older builds
  let c=[], g=[];
  let meta=null;
  try{ const r=JSON.parse(localStorage.getItem(LS_LOCAL)||"null"); if(r&&r.ct&&gHistKey){ const o=JSON.parse(dec.decode(await aesDec(gHistKey,r.iv,r.ct))); c=o.contacts||[]; g=o.groups||[]; meta=o.meta||null; } }catch(e){}
  _meta={unread:(meta&&meta.unread)||{}, rcpt:(meta&&meta.rcpt)||{}, viewed:(meta&&meta.viewed)||{}};
  let legacy=false;
  try{ const lc=JSON.parse(localStorage.getItem(LS_CONTACTS)||"[]")||[], lg=JSON.parse(localStorage.getItem(LS_GROUPS)||"[]")||[];
    lc.forEach(x=>{ if(x&&x.ck&&!c.find(y=>y.ck===x.ck)){ c.push(x); legacy=true; } });
    lg.forEach(x=>{ if(x&&x.rid&&!g.find(y=>y.rid===x.rid)){ g.push(x); legacy=true; } }); }catch(e){}
  try{ localStorage.removeItem(LS_CONTACTS); localStorage.removeItem(LS_GROUPS); }catch(e){}
  _contacts=c; _groups=g; if(legacy) localSaveSoon();
  renderContacts(); if(pushOn()&&gPushSub) registerAllContacts(); swNamesSoon();
  inboxPull(true);                                   // deliver what arrived while the app was closed, for every chat
}
function localClear(){ clearTimeout(_localT); _contacts=[]; _groups=[]; _meta={unread:{},rcpt:{},viewed:{}}; }                       // lock: out of memory, ciphertext stays on disk
function localWipe(){ localClear(); try{ localStorage.removeItem(LS_LOCAL); localStorage.removeItem(LS_CONTACTS); localStorage.removeItem(LS_GROUPS); }catch(e){} }
function realName(n){ return n && n!=="Peer" && n!=="Contact" && n!=="Anon" && n!=="Waiting for peer…" ? n : ""; }
function contactUpsert(name, ckB64){
  const list=contactsLoad(); const i=list.findIndex(c=>c.ck===ckB64); const nm=realName(name);
  if(i>=0){ if(nm) list[i].name=nm; list[i].ts=Date.now(); }
  else list.push({name:nm||name||"Contact", ck:ckB64, ts:Date.now()});
  contactsSave(list);
}
function contactRemove(ckB64){
  [...rooms.values()].filter(R=>R.fromContact===ckB64).forEach(R=>leaveRoom(R.code));   // or the next presence sync re-saves them
  contactsSave(contactsLoad().filter(c=>c.ck!==ckB64)); }
async function ckFromSecret(secret){ return b64(await hkdf(secret,"gz-contact/v1")); }  // ECDH secret -> stable contact key
async function rvCodeFromCK(ckB64){         // secret room code for today's window
  const day=Math.floor(Date.now()/86400000);
  const u=new Uint8Array(await hkdf(unb64(ckB64),"gz-rv/v1|"+day, 10));
  let s=""; for(let i=0;i<7;i++) s+=B32[u[i]%B32.length]; return s;
}
async function openContact(ckB64, name){
  closeSidebar();
  const code=await rvCodeFromCK(ckB64);
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
function inviteLinkFromSecret(sB64){ return CANONICAL+"/#i="+b64url(enc.encode(JSON.stringify({s:sB64,n:realName(myName)?myName:""}))); }
function parseInviteLink(text){ try{ const s=(text||"").trim(); const i=s.indexOf("#i="); if(i<0) return null;
  const o=JSON.parse(dec.decode(unb64url(s.slice(i+3)))); if(o&&typeof o.s==="string"&&o.s.length>20) return o; }catch(e){} return null; }
function contactFind(ck){ return contactsLoad().find(c=>c.ck===ck)||null; }
function contactPatch(ck, fields){ const l=contactsLoad(); const c=l.find(x=>x.ck===ck); if(c){ Object.assign(c,fields); contactsSave(l); } }
async function newPendingInvite(){
  const s=b64(crypto.getRandomValues(new Uint8Array(32)));
  _pendingInvite={ s, ck:await ckFromInviteSecret(s), url:inviteLinkFromSecret(s), saved:false };
  const o=$("invLinkOut"); if(o) o.value=_pendingInvite.url;
}
function persistPendingInvite(){   // the inviter keeps a placeholder contact that becomes the person once they open the link
  const pi=_pendingInvite; if(!pi||pi.saved) return;
  if(!contactFind(pi.ck)){ const l=contactsLoad(); l.push({name:INV_PLACEHOLDER, ck:pi.ck, inv:1, is:pi.s, ts:Date.now()}); contactsSave(l); }
  pi.saved=true; if(pushOn()) registerAllContacts();
}
function isPendingInvite(c){ return !!(c && c.inv && c.is && c.name===INV_PLACEHOLDER); }
async function acceptInvite(inv){   // someone opened a link: become their contact and open the chat
  const ck0=await ckFromInviteSecret(inv.s);
  const rotated=contactByPrev(ck0);                      // this link's contact already moved to a rotated key
  const ck=rotated?rotated.ck:ck0;
  const mine=contactFind(ck);
  try{ history.replaceState(null,"","/"); }catch(e){}
  if(mine && mine.is===inv.s){ toast(t("That's your own invite link — send it to a friend")); goHome(); return; }
  const nm=realName(inv.n)?inv.n:"Friend";   // stored in English, shown translated (dn)
  if(!mine){ const l=contactsLoad(); l.push({name:nm, ck, inv:1, ts:Date.now()}); contactsSave(l); if(pushOn()) registerAllContacts(); }
  else if(!realName(mine.name)||mine.name==="Friend"){ contactPatch(ck,{name:nm,ts:Date.now()}); }
  await openContact(ck, nm);
}
// A contact who has written to us reveals their name inside the encrypted envelope — adopt it for placeholders.
function adoptNameFromMessage(R, n){
  if(!R||R.group||!R.fromContact||!realName(n)) return;
  const c=contactFind(R.fromContact); if(!c || (c.name!==INV_PLACEHOLDER && c.name!=="Friend")) return;
  contactPatch(R.fromContact,{name:n}); if(c.alias) return; R.title=n; R.peerName=dn(n); R.avatar=(n[0]||"?").toUpperCase();
  if(R.code===active){ $("peerName").textContent=n; $("peerAvatar").textContent=R.avatar; } renderTabs();
}
function activeCK(){ const R=A(); return R&&R.fromContact||null; }
function renderContacts(fromPreview){
  const el=$("contactList"); if(!el) return; el.innerHTML="";
  const lastTs=it=>Math.max(it.ts||0, (_prev[previewKeyOf(it)]||{}).ts||0);
  const items=groupsLoad().map(g=>({t:"g",id:"g:"+g.rid,rid:g.rid,gk:g.gk,name:g.name,alias:g.alias,ts:g.ts||0}))
    .concat(contactsLoad().map(c=>({t:"c",id:"c:"+c.ck,ck:c.ck,hk:c.hk,name:c.name,alias:c.alias,v:c.v,ts:c.ts||0})))
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
  items.forEach(it=>{
    const row=document.createElement("div"); row.className="ct"+(it.id===activeId?" active":"");
    const ava=document.createElement("div"); ava.className="ava"+(it.t==="g"?" grp":""); ava.textContent=it.t==="g"?"👥":(((it.alias||it.name)&&(it.alias||it.name)[0]||"?").toUpperCase());
    const ci=document.createElement("div"); ci.className="ci";
    // line 1: name (+ verified) ……… time of the last message
    const r1=document.createElement("div"); r1.className="crow";
    const cn=document.createElement("div"); cn.className="cn"; cn.textContent=it.alias||dn(it.name)||(it.t==="g"?t("Group"):t("Contact"));
    if(it.t==="c"&&it.v){ const vb=document.createElement("span"); vb.className="vbadge"; vb.textContent="✓"; vb.title=t("Verified"); cn.appendChild(vb); }
    const pv=_prev[previewKeyOf(it)]||null;
    const ct=document.createElement("span"); ct.className="ctime"; ct.textContent=pv?fmtListTime(pv.ts):"";
    r1.appendChild(cn); r1.appendChild(ct);
    // line 2: last message ……… unread count
    const r2=document.createElement("div"); r2.className="crow";
    const unread=(it.id===activeId) ? 0 : (_meta.unread[previewKeyOf(it)]||0);
    const cm=document.createElement("div"); cm.className="cm";
    const pendingInv = it.t==="c" && it.name===INV_PLACEHOLDER;
    const placeholder = pendingInv ? t("Invite sent · waiting for them to open it") : (it.t==="g" ? t("Group · say hello") : t("Tap to start chatting"));
    // "Hide previews": nothing readable over your shoulder — only whether there's something new
    cm.textContent= previewsHidden()
      ? (unread ? t(unread>1?"{n} new messages":"{n} new message",{n:unread}) : (pv ? t("🔒 Encrypted message") : placeholder))
      : (pv ? pv.text : placeholder);
    if(unread) cm.classList.add("unread");
    r2.appendChild(cm);
    if(unread && it.id!==activeId){ const ub=document.createElement("span"); ub.className="ubadge"; ub.textContent=unread>99?"99+":String(unread); ub.title=t("{n} unread",{n:unread}); r2.appendChild(ub); ct.classList.add("unread"); }
    ci.appendChild(r1); ci.appendChild(r2);
    const x=document.createElement("button"); x.className="cx"; x.textContent="×"; x.title=it.t==="g"?t("Leave group"):t("Remove contact"); x.setAttribute("aria-label",x.title);
    x.addEventListener("click",ev=>{ ev.stopPropagation();
      if(it.t==="g"){ if(confirm(t("Leave the group “{name}”?\n\nYou'll need a new invite link to come back.",{name:dn(it.name)||t("Group")}))) groupRemove(it.rid); }
      else { if(confirm(t("Remove {name} from your chats?\n\nTo talk again you'll need to exchange a new invite link.",{name:dn(it.name)||t("this contact")}))) contactRemove(it.ck); } });
    row.appendChild(ava); row.appendChild(ci); row.appendChild(x);
    row.addEventListener("click",()=> it.t==="g" ? openGroup(it.rid,it.gk,it.name) : openContact(it.ck,it.alias||it.name));
    el.appendChild(row);
  });
}

// ---------- group chats (named, invite-only, shared group key) ----------
const LS_GROUPS="gz-groups";              // legacy plaintext key (older builds): imported once, then removed
function groupsLoad(){ return _groups.map(g=>Object.assign({},g)); }
function groupsSave(l){ _groups=(l||[]).filter(g=>g&&g.rid).map(g=>Object.assign({},g)); localSaveSoon(); renderContacts(); syncPushSoon(); }
function groupUpsert(rid,gkB64,name){ const l=groupsLoad(); const i=l.findIndex(g=>g.rid===rid);
  if(i>=0){ if(name) l[i].name=name; l[i].ts=Date.now(); } else l.push({rid,gk:gkB64,name:name||"Group",ts:Date.now()}); groupsSave(l); }
function groupRemove(rid){ const R=rooms.get(rid); if(R){ try{ R.channel&&R.channel.unsubscribe(); }catch(e){} if(R.logEl) R.logEl.remove(); rooms.delete(rid); if(active===rid) goHome(); }
  groupsSave(groupsLoad().filter(g=>g.rid!==rid)); }
function newRid(){ const A="0123456789abcdefghijklmnopqrstuvwxyz"; return [...crypto.getRandomValues(new Uint8Array(16))].map(b=>A[b%36]).join(""); }
async function gkMsgKey(gkBytes){ return aesKey(await hkdf(gkBytes,"gz-group-msg/v1")); }
function openGroup(rid,gkB64,name){ closeSidebar(); doJoinGroup(rid, unb64(gkB64), name); }
async function createGroup(name){ const rid=newRid(); const gk=crypto.getRandomValues(new Uint8Array(32));
  await doJoinGroup(rid, gk, (name||"").trim()||"New group");
  const R=A(); if(R&&R.logEl){ sysline(R.logEl,t("🔒 Group created. Tap the menu ⋮ → “Invite people” to add members.")); } }
async function doJoinGroup(rid, gkBytes, name){
  const code=rid;
  groupUpsert(rid, b64(gkBytes), name);
  if(rooms.has(code)){ hideJoin(); switchTo(code); return; }
  if(_joining.has(code)) return; _joining.add(code);
  const R=newRoom(code);
  R.group=true; R.rid=rid; R.gk=gkBytes; R.title=name||"Group"; R.peerName=dn(name||"Group"); R.avatar="👥"; R.paired=true;
  { const g=groupsLoad().find(x=>x.rid===rid); if(g&&g.alias){ R.title=g.alias; R.peerName=g.alias; } }
  try{ R.gkMsg=await gkMsgKey(gkBytes); } finally { _joining.delete(code); }
  if(rooms.has(code)){ switchTo(code); return; }
  const logEl=document.createElement("div"); logEl.className="log"; logEl.style.display="none"; $("logs").appendChild(logEl); R.logEl=logEl;
  rooms.set(code,R); hideJoin(); switchTo(code);
  if(gHistKey){ renderHistory(R, await histLoad(code)); }
  if(!R.seen) R.seen=new Set();
  const ch=client.channel("ratchet-"+rid,{config:{private:true,presence:{key:R.id},broadcast:{self:false}}});
  R.channel=ch;
  ch.on("presence",{event:"sync"},()=>onSyncGroup(R));
  ch.on("broadcast",{event:"msg"},(payload)=>onMsgGroup(R,payload));
  ch.subscribe(async st=>{ if(st==="SUBSCRIBED"){ await ch.track(presencePayload(R)); setStatus(R,t("🔒 encrypted group"),true);
      if(R.code===active){ $("msgInput").disabled=false; $("sendBtn").disabled=false; $("attachBtn").disabled=false; } fetchMailbox(R); }
    else if(st==="CHANNEL_ERROR"||st==="TIMED_OUT"){ setStatus(R,t("connection problem — retrying…"),false); } });
  fetchMailbox(R);
  try{ history.replaceState(null,"","/"); }catch(e){}
  renderContacts(); updateVerifyUI();
}
function onSyncGroup(R){
  const st=R.channel.presenceState(); const ids=new Set(); const names=[];
  for(const k in st) for(const m of st[k]){ if(!m.id) continue; ids.add(m.id); if(m.id!==R.id && m.name) names.push(m.name); }
  const n=ids.size;
  const extra=names.length?(" · "+names.slice(0,3).join(", ")+(names.length>3?" +"+(names.length-3):"")):"";
  setStatus(R,(n>1?t("🔒 group · {n} online",{n}):t("🔒 group · 1 (just you)"))+extra,true);
}
async function broadcastGroup(R, env, mid){
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const ctBuf=await crypto.subtle.encrypt({name:"AES-GCM",iv}, R.gkMsg, enc.encode(JSON.stringify(Object.assign({},env,{mid,n:myName}))));
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
    onInbound(R, env, who, now, p.mid, false, true);
    if(R.code===active) blinkEyes();
    soundRecv();
  }catch(e){ if(p.mid && R.seen) R.seen.delete(p.mid); addText(R.logEl,"fail",t("⚠ could not decrypt this message"),""); }
}
function groupInviteLink(R){ const g=groupsLoad().find(x=>x.rid===R.rid); const payload=b64url(enc.encode(JSON.stringify({rid:R.rid,gk:b64(R.gk),name:(g&&g.name)||R.title}))); return CANONICAL+"/#g="+payload; }
async function inviteToGroup(){ const R=A(); if(!R||!R.group) return;
  const url=groupInviteLink(R); const msg=t("Join my Gizleme group “{name}” 🔒\n{url}",{name:R.title,url});
  if(navigator.share){ try{ await navigator.share({text:msg}); return; }catch(e){ if(e&&e.name==="AbortError") return; } }
  try{ await navigator.clipboard.writeText(url); toast(t("Invite link copied")); }catch(e){ prompt(t("Copy this invite link:"),url); }
}
function parseInvite(text){ // accepts a full link or raw payload
  try{ const s=(text||"").trim(); const i=s.indexOf("#g="); const payload= i>=0 ? s.slice(i+3) : s;
    const obj=JSON.parse(dec.decode(unb64url(payload))); if(obj&&obj.rid&&obj.gk) return obj; }catch(e){} return null; }

// ---------- offline delivery: encrypted store-and-forward mailbox ----------
const MBOX_FN="gizleme-mbox", LS_MBTS="gz-mboxts";
function myUsername(){ const s=sessLoad(); return (s&&s.username)||""; }
async function mboxFn(action,extra){ return client.functions.invoke(MBOX_FN,{body:Object.assign({action},extra||{})}); }
function roomSecretB64(R){ return R.group ? (R.gk?b64(R.gk):null) : (R.fromContact||null); }
async function mboxIdFor(R){ const sec=roomSecretB64(R); if(!sec) return null; return b64url(new Uint8Array(await hkdf(unb64(sec),"gz-mbox/v1",16))); }
async function mboxKeyFor(R){ if(R.group) return R.gkMsg; const sec=roomSecretB64(R); if(!sec) return null; return aesKey(await hkdf(unb64(sec),"gz-mbox-key/v1")); }
function mbtsLoad(){ try{ return JSON.parse(localStorage.getItem(LS_MBTS)||"{}")||{}; }catch(e){ return {}; } }
function mbtsGet(id){ return mbtsLoad()[id]||0; }
function mbtsSet(id,ts){ const m=mbtsLoad(); if(ts>(m[id]||0)){ m[id]=ts; try{ localStorage.setItem(LS_MBTS,JSON.stringify(m)); }catch(e){} } }
async function depositMailbox(R, mid, env){
  try{ const id=await mboxIdFor(R), key=await mboxKeyFor(R); if(!id||!key) return false;
    const iv=crypto.getRandomValues(new Uint8Array(12));
    // the sender's display name travels inside the ciphertext, not beside it
    const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,enc.encode(JSON.stringify(Object.assign({},env,{n:myName,mid}))));
    const r=await mboxFn("put",{mbox:id, mid, from:_acct||undefined, data:{iv:b64(iv),ct:b64(ct)}});
    return !!(r && r.data && r.data.ok);
  }catch(e){ return false; }
}
async function fetchMailbox(R){
  if(!R) return 0;
  if(R.fetching) return R.fetching;          // coalesce overlapping fetches (open + subscribe + poll)
  R.fetching=(async()=>{
    let delivered=0;
    try{ const id=await mboxIdFor(R), key=await mboxKeyFor(R); if(!id||!key) return 0;
      const since=mbtsGet(id);
      const {data}=await mboxFn("get",{mbox:id, since: since?new Date(since).toISOString():0});
      const items=(data&&data.items)||[]; if(!items.length) return 0;
      if(!R.seen) R.seen=new Set();
      let maxTs=since; const mine=_acct;
      const dur=expFor(histKeyOf(R)); const cut=dur?Date.now()-dur:0;
      for(const it of items){ const ts=Date.parse(it.ts)||Date.now(); if(ts>maxTs) maxTs=ts;
        const own=!!(mine && it.from_user===mine);               // written by our own account's other device
        if(it.mid && R.seen.has(it.mid)) continue;
        if(dur && ts<=cut) continue;                             // already past this chat's disappearing window
        if(it.mid) R.seen.add(it.mid);                           // claim it before awaiting so a parallel pass can't show it too
        try{ const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(it.data.iv)},key,unb64(it.data.ct));
          const env=JSON.parse(dec.decode(pt));
          if(env.t==="rcpt"){ if(!own) markReceived(histKeyOf(R), env.mids||[]); continue; }   // the other side got our messages
          if(env.mid && it.mid && env.mid!==it.mid) throw new Error("id mismatch");
          const who=realName(env.n)||(R.group?t("Member"):"");
          if(!own) adoptNameFromMessage(R, env.n);
          onInbound(R, env, who, ts, it.mid, own, false);
          if(!own) delivered++;
        }catch(e){ if(it.mid) R.seen.delete(it.mid); }
      }
      mbtsSet(id,maxTs);
      if(delivered && !R.shadow){ soundRecv(); if(R.code===active) blinkEyes(); }
    }catch(e){}
    return delivered;
  })();
  try{ return await R.fetching; } finally { R.fetching=null; }
}
// One place where every inbound message lands (live, mailbox, background): render if the chat is open,
// always save, count as unread when not being looked at, and tell the sender it arrived.
function onInbound(R, env, who, ts, mid, own, animate){
  const hk=histKeyOf(R); const open=!!R.logEl;
  if(own){   // sent from another of our devices: appears on this one as our own message, no sound, no badge
    if(open){ if(env.t==="img") addText(R.logEl,"sent",t("📷 Photo"),"",false,ts,{mid,st:stateFor(mid)}); else addText(R.logEl,"sent",env.body,"",false,ts,{mid,st:stateFor(mid)}); }
    histSave(hk,{dir:"sent",env,ts,mid}); return;
  }
  const tag=R.group?(who||""):"";
  if(env.t==="img"){ if(open) addImageRecvOnce(R.logEl,env,tag,ts,mid); }
  else if(open) addText(R.logEl,"recv",env.body,tag,!!animate,ts,{mid});
  histSave(hk,{dir:"recv",env,ts,who,mid});
  if(!open || R.code!==active) bumpUnread(R);
  if(!R.group && R.fromContact && mid) queueRcpt(R.fromContact, mid);
}
function bumpUnread(R){ const k=histKeyOf(R); _meta.unread[k]=(_meta.unread[k]||0)+1; R.unread=(R.unread||0)+1; localSaveSoon(); renderTabs(); renderContacts(); }
function clearUnread(R){ const k=histKeyOf(R); if(_meta.unread[k]){ delete _meta.unread[k]; localSaveSoon(); } R.unread=0; }
function stateFor(mid){ return mid && _meta.rcpt[mid] ? "rcvd" : "sent"; }
// ----- receipts: "your message reached their device". Encrypted under the contact's mailbox key, so the
// relay sees neither which messages nor that it is a receipt. Sent live when paired, and always left in the
// mailbox for the sender's other devices / later polls. 1:1 chats only.
const _rcptQ={}; let _rcptT=null;
function queueRcpt(ck, mid){ (_rcptQ[ck]=_rcptQ[ck]||[]).push(mid); clearTimeout(_rcptT); _rcptT=setTimeout(()=>{ for(const k in _rcptQ){ const mids=_rcptQ[k]; delete _rcptQ[k]; flushRcpt(k,mids).catch(()=>{}); } },800); }
async function flushRcpt(ck, mids){
  const S={fromContact:ck,group:false}; const id=await mboxIdFor(S), key=await mboxKeyFor(S); if(!id||!key) return;
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,enc.encode(JSON.stringify({t:"rcpt",mids})));
  const data={iv:b64(iv),ct:b64(ct)};
  rooms.forEach(R=>{ if(R.fromContact===ck && R.paired && R.channel){ try{ R.channel.send({type:"broadcast",event:"rcpt",payload:{from:R.id,iv:data.iv,ct:data.ct}}); }catch(e){} } });
  try{ await mboxFn("put",{mbox:id, mid:"r"+rid(), from:_acct||undefined, data}); }catch(e){}
}
async function onRcpt(R,{payload:p}){
  if(!p||p.from===R.id||!R.fromContact) return;
  try{ const key=await mboxKeyFor(R); const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(p.iv)},key,unb64(p.ct));
    const env=JSON.parse(dec.decode(pt)); if(env.t==="rcpt") markReceived(histKeyOf(R), env.mids||[]); }catch(e){}
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
  const R=newRoom(it.t==="g"?it.rid:""); R.shadow=true; R.logEl=null; R.seen=new Set();
  if(it.t==="g"){ R.group=true; R.rid=it.rid; R.gk=unb64(it.gk); R.gkMsg=await gkMsgKey(R.gk); R.title=it.name||"Group"; }
  else { R.fromContact=it.ck; R.title=it.name||""; }
  return R;
}
let _inboxBusy=false, _inboxLast=0;
async function inboxPull(force){
  if(!gHistKey||_inboxBusy) return; if(!force && Date.now()-_inboxLast<15000) return;
  _inboxBusy=true; _inboxLast=Date.now();
  try{
    const items=groupsLoad().map(g=>({t:"g",rid:g.rid,gk:g.gk,name:g.name})).concat(contactsLoad().map(c=>({t:"c",ck:c.ck,name:c.name})));
    let bg=0;
    for(const it of items){
      let R=null; rooms.forEach(x=>{ if(it.t==="g" ? x.rid===it.rid : x.fromContact===it.ck) R=x; });
      if(R){ await fetchMailbox(R); continue; }
      try{ const S=await shadowRoom(it); bg+=(await fetchMailbox(S))||0; }catch(e){}
    }
    if(bg){ soundRecv(); renderContacts(); }
  } finally { _inboxBusy=false; }
}
function seedSeen(R, past){ R.seen=new Set(); (past||[]).forEach(r=>{ if(r && r.mid) R.seen.add(r.mid); }); }

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
  const nks=[]; for(const c of contactsLoad()){ try{ nks.push(await notifyKeyFor(c.ck)); }catch(e){} }
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
  const nk=await notifyKeyFor(ckB64);
  let map={}; try{ map=JSON.parse(localStorage.getItem(LS_NOTIFIED)||"{}"); }catch(e){}
  const now=Date.now(); if(map[nk]&&now-map[nk]<90000) return false;   // debounce 90s per contact
  map[nk]=now; try{ localStorage.setItem(LS_NOTIFIED,JSON.stringify(map)); }catch(e){}
  const nm=realName(myName);
  try{ await fn("notify",{notify_key:nk, from:deviceId(), title:"Gizleme",
    body: kind==="msg" ? (nm?t("New message from {name}",{name:nm}):t("New message")) : (nm?t("{name} wants to chat on Gizleme",{name:nm}):t("A contact wants to chat")),
    kind: kind==="msg"?"msg":"chat", url:CANONICAL+"/#n="+encodeURIComponent(nk), from_acct:_acct||undefined}); return true; }catch(e){ return false; }
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

let _db=null;
function idb(){ return new Promise((res,rej)=>{ if(_db) return res(_db);
  const r=indexedDB.open("vesper",1);
  r.onupgradeneeded=()=>{ const db=r.result; if(!db.objectStoreNames.contains("msgs")){ const os=db.createObjectStore("msgs",{keyPath:"id",autoIncrement:true}); os.createIndex("room","room"); } };
  r.onsuccess=()=>{ _db=r.result; res(_db); }; r.onerror=()=>rej(r.error); }); }
// Saved history and per-chat settings are keyed by a stable id: the contact key for 1:1 contact chats
// (their live room code rotates daily and would otherwise hide yesterday's messages), the rid for groups.
function histKeyOf(R){ return R && R.fromContact ? ckHistKey(R.fromContact) : (R?R.code:""); }
async function histSave(room, rec){ // rec = {dir, env, ts}
  if(!gHistKey) return;
  try{
    const {iv,ct}=await aesEnc(gHistKey, enc.encode(JSON.stringify(rec)));
    const db=await idb(); const tx=db.transaction("msgs","readwrite");
    tx.objectStore("msgs").add({room,iv,ct,ts:rec.ts||Date.now()});
    tx.oncomplete=()=>refreshPreviews();          // the chats list shows the latest message
  }catch(e){}
}
function histSweep(room, cutoff){ // delete saved records older than cutoff (ms epoch)
  try{ idb().then(db=>{ const tx=db.transaction("msgs","readwrite"); const idx=tx.objectStore("msgs").index("room");
    const rq=idx.openCursor(IDBKeyRange.only(room)); rq.onsuccess=e=>{ const c=e.target.result; if(!c) return;
      if((c.value.ts||0) && c.value.ts<=cutoff) c.delete(); c.continue(); }; }); }catch(e){}
}
// Last saved message of a chat (one reverse cursor step + one decrypt) — for the conversation list preview.
async function histLast(room){
  if(!gHistKey||!room) return null;
  try{ const db=await idb();
    const rec=await new Promise((res,rej)=>{ const idx=db.transaction("msgs").objectStore("msgs").index("room");
      const rq=idx.openCursor(IDBKeyRange.only(room),"prev"); rq.onsuccess=e=>{ const c=e.target.result; res(c?c.value:null); }; rq.onerror=()=>rej(rq.error); });
    if(!rec) return null;
    const r=JSON.parse(dec.decode(await aesDec(gHistKey,rec.iv,rec.ct))); r.ts=r.ts||rec.ts||0; return r;
  }catch(e){ return null; }
}
// Preview cache for the chats list: key -> {text, ts, dir}. Refreshed in the background after each render.
const _prev={}; let _prevT=null;
function previewKeyOf(it){ return it.t==="g" ? it.rid : (it.hk||("c:"+it.ck)); }
function previewText(r, isGroup){
  if(!r) return "";
  const body = r.env && r.env.t==="img" ? t("📷 Photo") : (r.env && r.env.body) || "";
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
      const nx=r?{text:previewText(r,it.t==="g"),ts:r.ts||0,dir:r.dir}:null; const old=_prev[k];
      if((nx&&!old)||(!nx&&old)||(nx&&old&&(nx.text!==old.text||nx.ts!==old.ts))){ if(nx) _prev[k]=nx; else delete _prev[k]; changed=true; } }
    if(changed) renderContacts(true);
  }, 120);
}
async function histLoad(room){
  if(!gHistKey) return [];
  try{
    const db=await idb();
    const recs=await new Promise((res,rej)=>{ const out=[]; const idx=db.transaction("msgs").objectStore("msgs").index("room");
      const rq=idx.openCursor(IDBKeyRange.only(room)); rq.onsuccess=e=>{ const c=e.target.result; if(c){ out.push(c.value); c.continue(); } else res(out); }; rq.onerror=()=>rej(rq.error); });
    const out=[];
    for(const r of recs){ try{ const pt=await aesDec(gHistKey,r.iv,r.ct); out.push(JSON.parse(dec.decode(pt))); }catch(e){} }
    return out;
  }catch(e){ return []; }
}

// ---------- media (encrypted blobs in Supabase Storage) ----------
async function downscale(file){
  if(file.size < 500000) return file;              // small enough
  try{
    const img = await createImageBitmap(file);
    const max=1600, scale=Math.min(1, max/Math.max(img.width,img.height));
    if(scale>=1) return file;
    const c=document.createElement("canvas"); c.width=Math.round(img.width*scale); c.height=Math.round(img.height*scale);
    c.getContext("2d").drawImage(img,0,0,c.width,c.height);
    const blob=await new Promise(r=>c.toBlob(r,"image/jpeg",0.82));
    return blob||file;
  }catch(e){ return file; }
}
async function uploadImage(file){
  const small = await downscale(file);
  const mime = small.type || "image/jpeg";
  const bytes = new Uint8Array(await small.arrayBuffer());
  const key = crypto.getRandomValues(new Uint8Array(32));
  const ck = await aesKey(key);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ctBuf = await crypto.subtle.encrypt({name:"AES-GCM",iv}, ck, bytes);
  // The relay names the object with a random id (nothing about the chat in the path) and is the only
  // writer of the bucket; the AES key never leaves the message.
  const r = await mboxFn("putblob",{data:b64(ctBuf)});
  const path = r && r.data && r.data.ok && r.data.path;
  if(!path){ const code=(r&&r.data&&r.data.error)||(r&&r.error&&r.error.context&&r.error.context.status)||""; throw new Error(code==="rate_limited"||code===429 ? t("too many photos — wait a minute") : t("upload failed")); }
  return { path, k:b64(key), iv:b64(iv), mime };
}
async function fetchImage(meta){ // meta={path,k,iv,mime}
  const { data } = client.storage.from(BUCKET).getPublicUrl(meta.path);
  const resp = await fetch(data.publicUrl, {cache:"no-store"});
  const ctBuf = await resp.arrayBuffer();
  const ck = await aesKey(unb64(meta.k));
  const plain = await crypto.subtle.decrypt({name:"AES-GCM",iv:unb64(meta.iv)}, ck, ctBuf);
  return URL.createObjectURL(new Blob([plain], {type:meta.mime||"image/jpeg"}));
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
let audioCtx=null, soundOn=true;
try{ soundOn = localStorage.getItem("vesper-sound")!=="off"; }catch(e){}
function initAudio(){ try{ if(!audioCtx) audioCtx=new (window.AudioContext||window.webkitAudioContext)(); if(audioCtx.state==="suspended") audioCtx.resume(); }catch(e){} }
function beep(seq){ if(!soundOn||!audioCtx) return; const now=audioCtx.currentTime;
  seq.forEach(n=>{ const o=audioCtx.createOscillator(), g=audioCtx.createGain(); o.type=n.type||"sine"; o.frequency.value=n.f;
    g.gain.setValueAtTime(0, now+n.t0); g.gain.linearRampToValueAtTime(n.gain||0.06, now+n.t0+0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, now+n.t0+n.dur); o.connect(g).connect(audioCtx.destination);
    o.start(now+n.t0); o.stop(now+n.t0+n.dur+0.03); }); }
// Refined notification tones: soft sine intervals with gentle, overlapping envelopes.
function soundSend(){ beep([
  {f:587.33,t0:0,   dur:0.16,gain:0.045},   // D5
  {f:880.00,t0:0.05,dur:0.20,gain:0.038},   // A5 (fifth)
  {f:1174.66,t0:0.05,dur:0.22,gain:0.015}   // D6 shimmer
]); }
// Message tones, all synthesized (no audio files, works offline). "classic" is the original.
const LS_TONE="gz-tone";
const TONES={
  classic:[{f:783.99,t0:0,dur:0.18,gain:0.042},{f:587.33,t0:0.07,dur:0.26,gain:0.040},{f:392.00,t0:0.07,dur:0.30,gain:0.016}],
  pop:    [{f:659.25,t0:0,dur:0.07,gain:0.05,type:"triangle"},{f:987.77,t0:0.06,dur:0.12,gain:0.045,type:"triangle"}],
  chime:  [{f:1046.50,t0:0,dur:0.55,gain:0.038},{f:2093.00,t0:0,dur:0.30,gain:0.010},{f:1318.51,t0:0.14,dur:0.50,gain:0.030},{f:1567.98,t0:0.28,dur:0.55,gain:0.022}],
  marimba:[{f:523.25,t0:0,dur:0.16,gain:0.034,type:"triangle"},{f:659.25,t0:0.11,dur:0.16,gain:0.034,type:"triangle"},{f:783.99,t0:0.22,dur:0.24,gain:0.034,type:"triangle"}],
  soft:   [{f:392.00,t0:0,dur:0.38,gain:0.030},{f:523.25,t0:0.16,dur:0.42,gain:0.026}]
};
function toneName(){ try{ const v=localStorage.getItem(LS_TONE); return TONES[v]?v:"classic"; }catch(e){ return "classic"; } }
function setTone(n){ if(!TONES[n]) return; try{ localStorage.setItem(LS_TONE,n); }catch(e){} }
function soundRecv(){ beep(TONES[toneName()]); }
// Warm ascending arpeggio when a secure channel opens with a contact.
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
function sweepEphemeral(){
  const now=Date.now();
  rooms.forEach(R=>{ const k=histKeyOf(R); const dur=expFor(k); if(!dur||!R.logEl) return; const cut=now-dur;
    [...R.logEl.children].forEach(el=>{ const ts=+(el.dataset&&el.dataset.ts||0); if(ts&&ts<=cut) el.remove(); });
    histSweep(k,cut);
  });
}
let _toastT=null;
function toast(m){ const t=$("toast"); t.textContent=m; t.classList.add("show"); clearTimeout(_toastT); _toastT=setTimeout(()=>t.classList.remove("show"), Math.max(1700, Math.min(6000, 55*m.length))); }
function scrollEl(el){ try{ el.scrollTop=el.scrollHeight; }catch(e){} }
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
function addText(logEl, cls, body, tag, animate, ts, opts){
  opts=opts||{}; ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble "+cls; d.dataset.ts=ts; if(opts.mid) d.dataset.mid=opts.mid;
  if(tag){ const w=document.createElement("span"); w.className="who"; w.textContent=tag; d.appendChild(w); }
  const t=document.createElement("span"); t.className="txt"; d.appendChild(t);
  if(cls==="sent"||cls==="recv") metaRow(d, ts, cls==="sent" ? (opts.st||"sent") : null);
  if(cls==="sent"){ d.addEventListener("click",()=>{ if(d.classList.contains("failed") && d._retry) d._retry(); }); }
  logEl.appendChild(d); scrollEl(logEl);
  if(animate){ t.classList.add("scrambling"); scramble(t,body,()=>{ t.classList.remove("scrambling"); scrollEl(logEl); }); } else t.textContent=body;
  return d;
}
function openLightbox(url, opts){
  opts=opts||{}; const t_=t;   // the countdown label shadows t below
  const lb=document.createElement("div"); lb.className="lightbox";
  const img=new Image(); img.src=url; lb.appendChild(img);
  const close=document.createElement("button"); close.className="lb-close"; close.textContent="✕"; lb.appendChild(close);
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
  const img=new Image(); img.src=localUrl; img.style.maxWidth="160px"; img.style.cursor="pointer";
  img.addEventListener("click",()=>openLightbox(localUrl,{}));
  d.appendChild(img);
  const o=document.createElement("span"); o.className="once"; o.textContent=t("⦿ view once"); d.appendChild(o);
  metaRow(d, ts, opts.st||"pending");
  d.addEventListener("click",e=>{ if(e.target===img) return; if(d.classList.contains("failed") && d._retry) d._retry(); });
  logEl.appendChild(d); scrollEl(logEl);
  return d;
}
function addImageRecvOnce(logEl, meta, tag, ts, mid){
  ts=ts||Date.now(); ensureDaySep(logEl, ts);
  const d=document.createElement("div"); d.className="bubble recv"; d.dataset.ts=ts; if(mid) d.dataset.mid=mid;
  if(tag){ const w=document.createElement("span"); w.className="who"; w.textContent=tag; d.appendChild(w); }
  const btn=document.createElement("div"); btn.className="tapview"; btn.innerHTML=t("📷 Photo")+"<small>"+t("tap to view — once only")+"</small>";
  d.appendChild(btn);
  metaRow(d, ts, null);
  logEl.appendChild(d); scrollEl(logEl);
  let opened=false;
  btn.addEventListener("click",async()=>{
    if(opened) return; opened=true; const prev=btn.innerHTML; btn.textContent=t("decrypting…");
    try{
      const url=await fetchImage(meta);
      markViewed(mid);                                   // never shown again, even after a reload
      openLightbox(url,{countdown:10,onClose:()=>{ try{URL.revokeObjectURL(url);}catch(e){} deleteBlob(meta.path);
        const x=document.createElement("div"); x.className="imgph"; x.textContent=t("📷 photo viewed"); btn.replaceWith(x); }});
    }catch(e){ opened=false; btn.innerHTML=prev; }
  });
  return d;
}
// Saved history, rendered the same way for contacts and groups: expired records skipped, view-once photos
// shown as "tap to view" until viewed, our own messages with their delivery state.
function renderHistory(R, past){
  const hk=histKeyOf(R); const dur=expFor(hk); const cut=dur?Date.now()-dur:0; if(dur) histSweep(hk,cut);
  for(const r of past){ if(!r||!r.env) continue; if(dur&&(r.ts||0)<=cut) continue;
    if(r.env.t==="img"){
      if(r.dir==="recv"){ if(r.mid && _meta.viewed[r.mid]) continue; addImageRecvOnce(R.logEl,r.env,R.group?(r.who||""):"",r.ts,r.mid); }
      else addText(R.logEl,"sent",t("📷 Photo"),"",false,r.ts,{mid:r.mid,st:stateFor(r.mid)});
      continue; }
    if(r.dir==="sent") addText(R.logEl,"sent",r.env.body,"",false,r.ts,{mid:r.mid,st:stateFor(r.mid)});
    else addText(R.logEl,"recv",r.env.body,R.group?(r.who||""):"",false,r.ts,{mid:r.mid});
  }
  seedSeen(R, past);
}
function sysline(logEl, t, warn){ const d=document.createElement("div"); d.className="sys"+(warn?" warnline":""); d.textContent=t; logEl.appendChild(d); scrollEl(logEl); }
function setStatus(R, t, secure){ R.statusText=t; R.secure=!!secure; if(R.code===active){ $("statusText").textContent=t; $("bar").classList.toggle("secure",!!secure); } }
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
async function shareInvite(){
  const {url,msg}=inviteParts();
  // One combined text field is handled most consistently across targets (WhatsApp included).
  if(navigator.share){ try{ await navigator.share({text:msg}); return; }catch(e){ if(e&&e.name==="AbortError") return; } }
  try{ await navigator.clipboard.writeText(url); toast(t("Link copied")); }catch(e){ prompt(t("Copy this link:"),url); }
}
function shareWhatsApp(){
  const {msg}=inviteParts();
  // wa.me opens WhatsApp directly (foregrounds it) with the message ready; the person
  // still taps Send inside WhatsApp — no app can send on your behalf.
  const wa="https://wa.me/?text="+encodeURIComponent(msg);
  window.open(wa,"_blank","noopener");
}
function enableComposer(on){ $("msgInput").disabled=!on; $("sendBtn").disabled=!on; $("attachBtn").disabled=!on; }

// ---------- session ----------
function idleStatus(R){
  if(!R||!R.fromContact) return t("waiting for peer…");
  if(isPendingInvite(contactFind(R.fromContact))) return t("waiting for them to open your link — anything you write will be waiting for them");
  return t("offline — messages will be delivered when they reconnect"); }
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
  const nm=other.name||"Peer"; R.peerName=dn(nm); R.avatar=(nm[0]||"?").toUpperCase();
  const alias=R.fromContact ? (contactFind(R.fromContact)||{}).alias : "";
  if(alias){ R.title=alias; R.peerName=alias; R.avatar=(alias[0]||"?").toUpperCase(); }
  else if(realName(nm)) R.title=nm;                    // show the person's name in the tab/header
  setStatus(R, authed ? t("🔒 secure · same key as your first connection ✓") : t("🔒 secure · key {fp}",{fp:rootFp}), true);
  if(R.code===active){ $("peerName").textContent=alias||dn(nm); $("peerAvatar").textContent=R.avatar; $("msgInput").disabled=false; $("sendBtn").disabled=false; $("attachBtn").disabled=false; }
  if(changed){
    sysline(R.logEl, authed ? t("✅ {name} verified automatically — same shared key as when you first connected.",{name:alias||dn(nm)}) : t("🔒 secure channel established with {name}",{name:alias||dn(nm)}));
    soundConnect();
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
      if(authed && c && c.inv && !c.rot){
        const old=R.fromContact, nk=await rotatedCKFromSecret(secret);
        const l=contactsLoad(); const i=l.findIndex(x=>x.ck===old);
        if(i>=0 && !l.some(x=>x.ck===nk)){
          const e=l[i]; e.prev=old; e.hk=e.hk||("c:"+old); e.ck=nk; e.rot=Date.now(); delete e.is; e.ts=Date.now();
          contactsSave(l);
          R.fromContact=nk; await ensureTag(R); if(R.tag && R.channel) R.channel.track(presencePayload(R));
          sysline(R.logEl, t("🔐 Invite link retired — this chat now uses a key only your two devices know."));
        } }
    }catch(e){}
    renderTabs(); renderContacts(); updateNotifyUI(); updateVerifyUI();
    if(pushOn()) registerAllContacts();      // make sure we're reachable under this contact
  }
}
function unpair(R){ R.paired=false; R.peer=null; R.root=null; R.rootFp=""; R.authOk=false; R.recvI=-1;
  // A saved contact keeps their name in the header while offline; only an anonymous manual room shows "Waiting for peer…".
  const known=!!(R.fromContact && realName(R.title));
  R.peerName=known?dn(R.title):t("Waiting for peer…"); R.avatar=known?(R.title[0]||"?").toUpperCase():"?";
  setStatus(R,idleStatus(R),false);
  if(R.code===active){ $("peerName").textContent=R.peerName; $("peerAvatar").textContent=R.avatar; const keep=!!R.fromContact; $("msgInput").disabled=!keep; $("sendBtn").disabled=!keep; $("attachBtn").disabled=!keep; updateVerifyUI(); } }
function presencePayload(R){ const p={id:R.id,name:myName,u:_acct}; if(!R.group){ p.pub=R.pubB64; if(R.tag) p.tag=R.tag; } return p; }
function retrackAll(){ rooms.forEach(R=>{ try{ R.channel&&R.channel.track&&R.channel.track(presencePayload(R)); }catch(e){} }); }
async function onSync(R){
  const st=R.channel.presenceState(); const me=_acct; let others=[];
  for(const k in st) for(const m of st[k]) if(m.id&&m.id!==R.id) others.push(m);
  others=others.filter(m=>!(me && m.u===me));          // my own account on another device/tab is not a peer
  if(others.length===0){ R.multiSig=""; if(R.paired) unpair(R); else setStatus(R,idleStatus(R),false); return; }
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
      sysline(R.logEl, t("{name}'s other device still uses the retired invite key — it will catch up when it syncs the account. Not connected live with that device.",{name:nm}), false);
    } else if(others.length>1){
      const names=[...new Set(others.map(m=>realName(m.name)||t("someone")))];
      if(names.length===1) sysline(R.logEl, t("{name} is connected from {n} devices — you're paired with the most recent one; their other device still receives your messages.",{name:names[0],n:others.length}), false);
      else sysline(R.logEl, t("⚠ {n} people are in this chat: {names}. You're paired with {with}. If you weren't expecting anyone else, stop and compare the safety code (🛡) with them in person.",{n:others.length,names:names.join(", "),with:(o&&realName(o.name)||t("the most recent"))}), true);
    }
  }
  if(!o){ if(R.paired) unpair(R); setStatus(R, stale.length && !rejected.length ? idleStatus(R) : t("⚠ not verified — not connected live"), false); return; }
  if(!R.paired||!R.peer||R.peer.id!==o.id||R.peer.pub!==o.pub) establish(R,o,auth[others.indexOf(o)]==="ok");
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
    onInbound(R, env, "", now, p.mid, false, true);
    if(R.code===active) blinkEyes();
    soundRecv();
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
  try{ const r=await R.channel.send({type:"broadcast",event:"msg",payload:{from:R.id,name:myName,dir,i,iv,ct,mid}}); return r==="ok"; }catch(e){ return false; }
}
async function sendText(){
  const R=A(); if(!R) return;
  const text=$("msgInput").value.trim(); if(!text) return;
  if(!R.group && !R.fromContact && !R.paired) return;       // manual room with no one here yet: nothing to send to
  const env={t:"txt",body:text}; const mid=rid(); const now=Date.now();
  if(!R.seen) R.seen=new Set(); R.seen.add(mid);
  $("msgInput").value=""; $("msgInput").style.height="auto"; initAudio();
  const el=addText(R.logEl,"sent",text,"",false,now,{mid,st:"pending"});
  await deliverOut(R, env, mid, el, now);
}
// Delivery: live broadcast when paired, and/or the encrypted mailbox (always for contacts and groups, so
// offline devices get it). The bubble shows pending → sent, or failed with tap-to-retry; nothing is saved
// to history until it has actually left the device.
async function deliverOut(R, env, mid, el, now){
  let ok=false;
  try{
    if(R.group){ const a=await broadcastGroup(R,env,mid); const b=await depositMailbox(R,mid,env); ok=a||b; }
    else if(R.paired){ const a=await broadcast(R,env,mid); const b=R.fromContact ? await depositMailbox(R,mid,env) : false; ok=a||b; }
    else { ok=await depositMailbox(R,mid,env); }
  }catch(e){ ok=false; }
  if(ok){
    setMsgState(el, stateFor(mid)); soundSend(); histSave(histKeyOf(R),{dir:"sent",env,ts:now,mid});
    if(!R.group && R.fromContact && !R.paired) notifyPeer(R.fromContact, "msg");     // they're not here: wake their device
  } else {
    setMsgState(el,"failed"); el._retry=()=>{ el._retry=null; setMsgState(el,"pending"); deliverOut(R,env,mid,el,now); };
  }
}
async function sendImage(file){
  const R=A(); if(!file||!R) return; if(!R.group && !R.fromContact && !R.paired) return; initAudio();
  const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid); const now=Date.now();
  const el=addImageSent(R.logEl, null, URL.createObjectURL(file), now, {mid, st:"pending"});
  try{
    const meta=await uploadImage(file); meta.t="img"; meta.once=true;
    await deliverOut(R, meta, mid, el, now);
  }catch(e){ setMsgState(el,"failed"); el._retry=()=>sendImageRetry(R,file,el,mid,now); toast(t("Photo not sent — ")+(e&&e.message?e.message:t("check your connection"))); }
}
async function sendImageRetry(R,file,el,mid,now){ el._retry=null; setMsgState(el,"pending");
  try{ const meta=await uploadImage(file); meta.t="img"; meta.once=true; await deliverOut(R, meta, mid, el, now); }
  catch(e){ setMsgState(el,"failed"); el._retry=()=>sendImageRetry(R,file,el,mid,now); } }
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
  if(R.fromContact && realName(R.title)){ R.peerName=dn(R.title); R.avatar=(R.title[0]||"?").toUpperCase(); }   // a known contact: show their name right away
  try{ R.kp=await genKP(); R.pubB64=b64(await pubRaw(R.kp)); await ensureTag(R); } finally { _joining.delete(code); }
  if(rooms.has(code)){ switchTo(code); return; }          // someone joined it while we were generating keys
  const logEl=document.createElement("div"); logEl.className="log"; logEl.style.display="none";
  $("logs").appendChild(logEl); R.logEl=logEl;
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
  if(!R.seen) R.seen=new Set();
  const ch=client.channel("ratchet-"+code,{config:{private:true,presence:{key:R.id},broadcast:{self:false}}});
  R.channel=ch;
  ch.on("presence",{event:"sync"},()=>onSync(R));
  ch.on("broadcast",{event:"msg"},(payload)=>onMsg(R,payload));
  ch.on("broadcast",{event:"rcpt"},(payload)=>onRcpt(R,payload));
  ch.subscribe(async st=>{
    if(st==="SUBSCRIBED"){ await ch.track(presencePayload(R)); if(!R.paired) setStatus(R,idleStatus(R),false); fetchMailbox(R); }
    else if(st==="CHANNEL_ERROR"||st==="TIMED_OUT"){ setStatus(R,t("connection problem — retrying…"),false); }
  });
  fetchMailbox(R);   // pull anything that was queued while we were away
  // Keep the shared code in the URL only for manual/invite rooms; contact rooms use a
  // secret daily code that shouldn't linger in history, so reload lands on the chats list.
  try{ history.replaceState(null,"", opts.fromContact ? "/" : localRoomUrl(code)); }catch(e){}
}
let _installChecked=false, _showInstallInvite=null;
function enterApp(){ $("join").style.display="none"; $("app").style.display="flex"; closeSidebar(); renderContacts(); updateNotifyUI(); armAutoLock();
  if(!_installChecked){ _installChecked=true; setTimeout(()=>{ try{ if(_showInstallInvite) _showInstallInvite(); }catch(e){} }, 2500); } }
function hideJoin(){ enterApp(); $("app").classList.remove("home"); }
function goHome(){ active=null; rooms.forEach(r=>{ if(r.logEl) r.logEl.style.display="none"; });
  $("join").style.display="none"; $("app").style.display="flex"; $("app").classList.add("home");
  renderTabs(); renderContacts(); updateNotifyUI(); try{ history.replaceState(null,"","/"); }catch(e){} }
function showAuth(mode){
  $("app").style.display="none"; $("join").style.display="flex"; $("join").dataset.mode=mode;
  const reg=mode==="register", login=mode==="login", unlock=mode==="unlock", nw=mode==="newchat";
  $("userField").style.display=(reg||login)?"block":"none";
  if($("promises")) $("promises").style.display=reg?"grid":"none";   // the pitch belongs on the first screen only
  $("pwField").style.display=(reg||login||unlock)?"block":"none";
  $("pw2Field").style.display=reg?"block":"none";
  if($("dispField")) $("dispField").style.display=reg?"block":"none";
  try{ $("pwInput").setAttribute("autocomplete", reg?"new-password":"current-password"); }catch(e){}
  $("ncTabs").style.display=nw?"flex":"none";
  $("bioOptWrap").style.display=((reg||login)&&bioSupported()&&!bioSet())?"flex":"none";
  $("bioBtn").hidden=!(unlock&&bioSupported()&&bioSet());
  $("bioBtn").textContent=t("🙂 Unlock with {bio}",{bio:bioLabel()});
  if($("lockHead")) $("lockHead").style.display=unlock?"block":"none";
  if($("forgotLink")) $("forgotLink").style.display=(login||unlock)?"block":"none";
  if($("iabNote")){ const iab=(typeof _isInApp==="function") && _isInApp() && (reg||login);
    $("iabNote").style.display=iab?"block":"none";
    if(iab) $("iabNote").textContent=(/iPhone|iPad|iPod/i.test(navigator.userAgent)
      ? t("You're inside WhatsApp's built-in browser. To stay logged in and get notifications, open this page in Safari first: tap ⋯ then “Open in Safari”.")
      : t("You're inside an app's built-in browser. To stay logged in and get notifications, open this page in your browser first (⋯ → Open in browser).")); }
  $("backBtn").style.display=nw?"block":"none";
  if(!nw){ $("roomField").style.display="none"; $("invLinkField").style.display="none"; $("gnameField").style.display="none"; $("invField").style.display="none"; $("shareRow").style.display="none"; }
  $("joinBtn").textContent=reg?t("Create account"):login?t("Log in"):unlock?t("Unlock"):t("Connect");
  authMsg(""); if($("userHint")){ $("userHint").textContent=""; $("userHint").className=""; }
  const sl=$("switchLink");
  if(reg){ const inv=window.__pending&&window.__pending.invite&&realName(window.__pending.invite.n)?window.__pending.invite.n:"";
    $("joinHint").textContent=(inv?t("{inviter} invited you to a private chat. Pick a name to reply.",{inviter:inv})+" ":"")+t("Pick any name — no phone number or email needed — and a strong password (8+ characters). There is no password reset: save it in your password manager."); sl.style.display="block"; sl.textContent=t("Already have an account? Log in"); }
  else if(login){ $("joinHint").textContent=t("Log in to your Gizleme account from any device."); sl.style.display="block"; sl.textContent=t("New here? Create an account"); }
  else if(unlock){ const s=sessLoad(); $("joinHint").textContent=""; if($("lockSub")) $("lockSub").textContent=(s&&s.display)?t("Welcome back, {name}.",{name:s.display}):t("Welcome back."); sl.style.display="block"; sl.textContent=t("Log out / switch account"); }
  else { sl.style.display="none"; $("roomInput").value=""; _pendingInvite=null; $("join").dataset.adv="0"; ncSet("direct"); }   // a fresh link each time New chat is opened
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
           : t("Send this link to one person. When they open it you're connected — even if you're not online at the same time. Anyone with the link can reach you as this contact, so don't post it publicly."))
    : group ? t("Create a named, encrypted group. Only people you invite with the link can join — the name alone gives no access.")
    : t("Paste a link a friend sent you — an invite or a group link.");
  [...document.querySelectorAll(".nctab")].forEach(b=>b.classList.toggle("on",b.dataset.nc===nc));
  if(direct && !adv && !_pendingInvite) newPendingInvite();
  if(direct && adv && !$("roomInput").value.trim()) $("roomInput").value=roomCode();   // keep a code the user may already have shared
}
function switchTo(code){
  const R=rooms.get(code); if(!R) return;
  active=code; $("app").classList.remove("home");
  rooms.forEach(r=>{ if(r.logEl) r.logEl.style.display=(r.code===code)?"flex":"none"; });
  clearUnread(R);
  $("peerName").textContent=dn(R.peerName); $("peerAvatar").textContent=R.avatar;
  $("statusText").textContent=R.statusText; $("bar").classList.toggle("secure",R.secure);
  // Composer is usable whenever there's somewhere to deliver: a live pairing, a group,
  // or a saved contact (message goes to the encrypted mailbox and is delivered when they reconnect).
  const canSend = R.paired || R.group || !!R.fromContact;
  $("msgInput").disabled=!canSend; $("sendBtn").disabled=!canSend; $("attachBtn").disabled=!canSend;
  renderTabs(); renderContacts(); updateNotifyUI(); updateVerifyUI();
}
function leaveRoom(code){
  const R=rooms.get(code); if(!R) return;
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
  if(p.group && p.group.rid && p.group.gk){ try{ await doJoinGroup(p.group.rid, unb64(p.group.gk), p.group.name); return; }catch(e){} }
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
function mergeContacts(remote){
  const lc=contactsLoad(), byCk={}; lc.forEach(c=>byCk[c.ck]=Object.assign({},c));
  (remote.contacts||[]).forEach(rc=>{ if(!rc||!rc.ck) return;
    // the other device rotated this contact's key: its record replaces our pre-rotation one
    if(rc.prev && byCk[rc.prev] && !byCk[rc.ck]){ const o=byCk[rc.prev]; delete byCk[rc.prev]; byCk[rc.ck]=Object.assign({},rc,{v:(o.v||rc.v)?1:undefined, name:realName(o.name)&&!realName(rc.name)?o.name:rc.name}); if(!byCk[rc.ck].v) delete byCk[rc.ck].v; return; }
    // we rotated already and the other device still has the old record: ours wins, its flags are kept
    const rotLocal=Object.values(byCk).find(c=>c.prev===rc.ck);
    if(rotLocal){ if(rc.v) rotLocal.v=1; if(realName(rc.name) && !realName(rotLocal.name)) rotLocal.name=rc.name; return; }
    const e=byCk[rc.ck];
    if(!e){ byCk[rc.ck]=Object.assign({},rc); }
    else { if((rc.ts||0)>(e.ts||0)){ e.name=rc.name||e.name; e.ts=rc.ts; } if(e.v||rc.v) e.v=1;
           if(rc.inv) e.inv=1; if(rc.is&&!e.is&&!e.rot) e.is=rc.is; if(rc.sv&&!e.sv) e.sv=rc.sv;
           if(rc.hk&&!e.hk) e.hk=rc.hk; if(rc.prev&&!e.prev) e.prev=rc.prev; if(rc.rot&&!e.rot){ e.rot=rc.rot; delete e.is; }
           if(rc.ats&&(rc.ats>(e.ats||0))){ e.alias=rc.alias; e.ats=rc.ats; if(!e.alias) delete e.alias; }
           if(e.name===INV_PLACEHOLDER && realName(rc.name) && rc.name!==INV_PLACEHOLDER) e.name=rc.name; } });
  const lg=groupsLoad(), byRid={}; lg.forEach(g=>byRid[g.rid]=Object.assign({},g));
  (remote.groups||[]).forEach(rg=>{ if(!rg||!rg.rid) return; const e=byRid[rg.rid];
    if(!e){ byRid[rg.rid]=Object.assign({},rg); }
    else { if((rg.ts||0)>(e.ts||0)){ e.name=rg.name||e.name; e.ts=rg.ts; if(rg.gk) e.gk=rg.gk; }
           if(rg.ats&&(rg.ats>(e.ats||0))){ e.alias=rg.alias; e.ats=rg.ats; if(!e.alias) delete e.alias; } } });
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
  const cipher=await vaultEncrypt({ contacts:contactsLoad(), groups:groupsLoad(), ts:Date.now() });
  let res=await vaultFn("pushContacts",{contacts:cipher, cver:gVaultCver}); if(ep!==gEpoch) return false;
  if(res.data && res.data.conflict){            // another device advanced it — merge then retry once
    gVaultCver=res.data.cver||gVaultCver; try{ await pullMerge(); }catch(e){} if(ep!==gEpoch) return false;
    const c2=await vaultEncrypt({ contacts:contactsLoad(), groups:groupsLoad(), ts:Date.now() });
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
    // Private by default for a brand-new account on this device: messages disappear after 24h and the app
    // auto-locks after 5 minutes. Both are one tap to change in Settings; an existing device's choices are kept.
    try{ if(localStorage.getItem(EXP_G)===null) localStorage.setItem(EXP_G,"86400000");
         if(localStorage.getItem(LS_AUTOLOCK)===null) localStorage.setItem(LS_AUTOLOCK,"900000"); }catch(e){}
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
  try{ [LS_MKPIN,LS_MKBIO,LS_NOTIFIED,LS_MBTS,LS_ABK].forEach(k=>localStorage.removeItem(k)); }catch(e){}
  try{ if(_db){ _db.close(); _db=null; } indexedDB.deleteDatabase("vesper"); }catch(e){}
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
function setAutoLock(ms){ try{ localStorage.setItem(LS_AUTOLOCK,String(ms||0)); }catch(e){} armAutoLock(); }
let _lockT=null, _hiddenAt=0;
function armAutoLock(){ clearTimeout(_lockT); const ms=autoLockMs(); if(!ms||!gHistKey) return; _lockT=setTimeout(lockApp, ms); }
function lockApp(){
  const s=sessLoad(); if(!s||!gHistKey) return;                 // not signed in, or already locked
  clearTimeout(_lockT); clearTimeout(_syncT);
  [...rooms.keys()].forEach(c=>{ const R=rooms.get(c); try{ R&&R.channel&&R.channel.unsubscribe(); }catch(e){} if(R&&R.logEl) R.logEl.remove(); });
  rooms.clear(); active=null;
  gHistKey=null; gEpoch++; gABK=null; gContactsKey=null; _acct=""; gRestoring=false; clearPreviews(); localClear();   // keys leave memory; the cached ABK stays for a quick unlock
  try{ $("wireCt").textContent="—"; $("msgInput").value=""; const m=$("barMenu"); if(m) m.hidden=true; }catch(e){}
  ["settingsModal","verifyModal","whyModal","installModal"].forEach(id=>{ const m=$(id); if(m) m.classList.remove("show"); });
  showAuth("unlock");
}
async function createGroupFromInput(){ initAudio(); await createGroup($("gnameInput").value.trim()); if($("gnameInput")) $("gnameInput").value=""; }
async function joinFromInviteInput(){ initAudio(); const raw=$("invInput").value;
  const pi=parseInviteLink(raw);
  if(pi){ try{ $("invInput").value=""; hideJoin(); await acceptInvite(pi); }catch(e){ authMsg(t("Couldn't open that invite — try again")); } return; }
  const inv=parseInvite(raw);
  if(!inv){ authMsg(t("That link doesn't look like a Gizleme invite")); return; }
  try{ $("invInput").value=""; await doJoinGroup(inv.rid, unb64(inv.gk), inv.name); }catch(e){ authMsg(t("Couldn't join — try again")); } }
async function join(){ const m=($("join").dataset.mode)||"register";
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
function renameChat(){
  const R=A(); if(!R) return;
  if(R.group){ const l=groupsLoad(); const g=l.find(x=>x.rid===R.rid); if(!g) return;
    const v=prompt(t("Nickname for this chat (only on your devices):"), g.alias||g.name||""); if(v===null) return;
    const nv=v.trim().slice(0,32); if(nv && nv!==g.name) g.alias=nv; else delete g.alias; g.ats=Date.now(); groupsSave(l);
    R.title=g.alias||g.name; R.peerName=R.title; }
  else if(R.fromContact){ const l=contactsLoad(); const c=l.find(x=>x.ck===R.fromContact); if(!c) return;
    const v=prompt(t("Nickname for this chat (only on your devices):"), c.alias||dn(c.name)||""); if(v===null) return;
    const nv=v.trim().slice(0,32); if(nv && nv!==c.name) c.alias=nv; else delete c.alias; c.ats=Date.now(); contactsSave(l);
    R.title=c.alias||c.name; R.peerName=c.alias||dn(c.name); R.avatar=((R.peerName||"?")[0]).toUpperCase(); }
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
  const r=await authFn("changepw",{token:s.token, av:avOld, salt:b64(saltB), verifier});
  if(isRateLimited(r)) throw new Error(String(RL_MSG));
  if(!r.data||!r.data.ok){ const st=r.error&&r.error.context&&r.error.context.status; throw new Error(st===401?t("Current password is wrong"):t("Couldn't change the password — try again")); }
  // the server now expects the new password: re-wrap the account backup key under it, and the local master key too
  const wrapKey=await abkWrapKeyFromAK(AKnew); const iv=crypto.getRandomValues(new Uint8Array(12));
  const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},wrapKey,gABK);
  await vaultFn("rewrapAbk",{abk:{iv:b64(iv),ct:b64(ct)}, av:avNew});
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
  try{ [LS_MKPIN,LS_MKBIO,LS_NOTIFIED,LS_MBTS,LS_ABK,LS_VAULTOWNER,LS_DEVID].forEach(k=>localStorage.removeItem(k)); }catch(e){}
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
    if(m==="register") showAuth("login"); else if(m==="login") showAuth("register");
    else if(m==="unlock"){ if(confirm(String(LOGOUT_MSG))) logoutAccount(); } });
  $("backBtn").addEventListener("click",()=>{ enterApp(); if(active) switchTo(active); else goHome(); });
  $("homeNew").addEventListener("click",showAddRoom);

  $("genRoom").addEventListener("click",()=>$("roomInput").value=roomCode());
  $("genInvite").addEventListener("click",()=>{ newPendingInvite(); toast(t("New link")); });
  $("invLinkOut").addEventListener("focus",e=>{ try{ e.target.select(); }catch(x){} });
  $("advRoom").addEventListener("click",()=>{ $("join").dataset.adv="1"; ncSet("direct"); });
  $("joinBtn").addEventListener("click",join);
  let _ucT=null;
  $("userInput").addEventListener("input",()=>{ if($("join").dataset.mode!=="register") return; clearTimeout(_ucT); _ucT=setTimeout(checkUsername,350); });
  ["userInput","pwInput","pw2Input","roomInput","gnameInput","invInput"].forEach(id=>{ const el=$(id); if(el) el.addEventListener("keydown",e=>{ if(e.key==="Enter") join(); }); });
  [...document.querySelectorAll(".nctab")].forEach(b=>b.addEventListener("click",()=>ncSet(b.dataset.nc)));
  $("copyLink").addEventListener("click",shareInvite);
  $("waShare").addEventListener("click",shareWhatsApp);

  $("sendBtn").addEventListener("click",sendText);
  // Enter sends (the mobile keyboard shows "send" via enterkeyhint); Shift+Enter makes a new line. The box grows up to ~5 lines.
  $("msgInput").addEventListener("keydown",e=>{ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); sendText(); } });
  const growBox=()=>{ const el=$("msgInput"); el.style.height="auto"; el.style.height=Math.min(120, el.scrollHeight)+"px"; };
  $("msgInput").addEventListener("input",growBox);
  $("attachBtn").addEventListener("click",()=>$("fileInput").click());
  $("fileInput").addEventListener("change",e=>{ const f=e.target.files[0]; e.target.value=""; if(f) sendImage(f); });
  // ----- theme + sound (surfaced in Settings) -----
  function currentDark(){ const c=document.documentElement.getAttribute("data-theme"); return c?c==="dark":matchMedia("(prefers-color-scheme:dark)").matches; }
  function refreshThemeUI(){ const d=currentDark(); if($("themeState")) $("themeState").textContent=d?t("Dark"):t("Light"); if($("themeToggle")) $("themeToggle").textContent=d?t("Light ☀"):t("Dark ☾"); }
  function toggleTheme(){ const next=currentDark()?"light":"dark"; document.documentElement.setAttribute("data-theme",next); try{ localStorage.setItem("vesper-theme",next); }catch(e){} refreshThemeUI(); }
  function refreshSoundUI(){ if($("soundState")) $("soundState").textContent=soundOn?t("On"):t("Off"); const b=$("soundToggle"); if(b){ b.textContent=soundOn?t("On"):t("Off"); b.classList.toggle("off",!soundOn); }
    if($("toneSel")) $("toneSel").value=toneName(); }
  $("toneSel").addEventListener("change",e=>{ setTone(e.target.value); initAudio(); if(!soundOn){ soundOn=true; try{ localStorage.setItem("vesper-sound","on"); }catch(x){} refreshSoundUI(); } soundRecv(); });
  function refreshLangUI(){ if($("langState")) $("langState").textContent=LANG==="fr"?"Français":"English"; if($("langToggle")) $("langToggle").textContent=LANG==="fr"?"English":"Français"; }
  $("langToggle").addEventListener("click",()=>{ setLang(LANG==="fr"?"en":"fr"); });
  _refreshSettingsUI=()=>{ refreshThemeUI(); refreshSoundUI(); refreshLangUI(); refreshPrevUI(); updateNotifyUI(); };
  function toggleSound(){ soundOn=!soundOn; try{ localStorage.setItem("vesper-sound",soundOn?"on":"off"); }catch(e){} if(soundOn){ initAudio(); soundRecv(); } refreshSoundUI(); }
  $("themeToggle").addEventListener("click",toggleTheme);
  $("soundToggle").addEventListener("click",toggleSound);

  // ----- Settings modal -----
  function openSettings(){
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
    try{ await deleteAccount(pw); closeModal("delModal"); showAuth("register"); toast(t("Your account has been deleted")); }
    catch(e){ m.textContent=(e&&e.message)||t("Couldn't delete the account"); }
    $("delConfirm").disabled=false;
  });
  ["forgotModal","pwModal","delModal"].forEach(id=>$(id).addEventListener("click",e=>{ if(e.target.id===id) closeModal(id); }));
  $("settingsClose").addEventListener("click",()=>$("settingsModal").classList.remove("show"));
  $("settingsModal").addEventListener("click",e=>{ if(e.target.id==="settingsModal") $("settingsModal").classList.remove("show"); });
  // ----- privacy & lock, and the "why Gizleme" comparison -----
  $("autoLock").addEventListener("change",e=>{ setAutoLock(+e.target.value||0); toast(+e.target.value?t("Auto-lock on"):t("Auto-lock off")); });
  function refreshPrevUI(){ const h=previewsHidden(); if($("prevState")) $("prevState").textContent=h?t("Hidden"):t("Shown"); if($("prevToggle")) $("prevToggle").textContent=h?t("Show"):t("Hide");
    const s=shieldOn(); if($("shieldState")) $("shieldState").textContent=s?t("On"):t("Off"); if($("shieldToggle")){ $("shieldToggle").textContent=s?t("On"):t("Off"); $("shieldToggle").classList.toggle("off",!s); } }
  $("prevToggle").addEventListener("click",()=>{ const h=!previewsHidden(); setPreviewsHidden(h); refreshPrevUI(); toast(h?t("Previews hidden"):t("Previews shown")); });
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
    const ms=autoLockMs(); if(ms && gHistKey && _hiddenAt && Date.now()-_hiddenAt>=ms) lockApp(); else if(gHistKey) armAutoLock();
    _hiddenAt=0;
  });
  $("expGlobal").addEventListener("change",e=>{ setExpGlobal(+e.target.value||0); toast(t("Default updated")); });
  $("expRoom").addEventListener("change",e=>{ const R=A(); if(R){ setExpRoom(histKeyOf(R),e.target.value); toast(t("Updated for this chat")); } });
  setInterval(sweepEphemeral, 15000);
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
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  function showInstall(on){ if($("installGroup")) $("installGroup").style.display=on?"block":"none"; }
  window.addEventListener("beforeinstallprompt",e=>{ e.preventDefault(); deferredPrompt=e; if(!isStandalone) showInstall(true);
    if(installModalPending && !installPrompted()){ installModalPending=false; openInstallModal(); } });
  window.addEventListener("appinstalled",()=>{ showInstall(false); deferredPrompt=null; closeInstallModal(); markInstallPrompted(); toast(t("Gizleme installed 🎉")); });
  if(isIOS && !isStandalone) showInstall(true);
  $("installPill").addEventListener("click",async()=>{
    if(deferredPrompt){ deferredPrompt.prompt(); try{ await deferredPrompt.userChoice; }catch(e){} deferredPrompt=null; showInstall(false); return; }
    if(isIOS){ toast(t("Tap Share then “Add to Home Screen”")); return; }
    toast(t("Open the browser menu → Install Gizleme"));
  });

  // ----- one-time install invitation, after the first time you reach the app on this device -----
  const LS_INSTALL="gz-installPrompted";
  let installModalPending=false;
  function installPrompted(){ try{ return localStorage.getItem(LS_INSTALL)==="1"; }catch(e){ return false; } }
  function markInstallPrompted(){ try{ localStorage.setItem(LS_INSTALL,"1"); }catch(e){} }
  function closeInstallModal(){ const m=$("installModal"); if(m) m.classList.remove("show"); }
  function openInstallModal(){
    if(isStandalone || installPrompted()) return;
    const steps=$("installSteps"), body=$("installBody"), now=$("installNow"), sub=$("installSub");
    if(deferredPrompt){
      sub.textContent=t("Add it to your device");
      body.textContent=t("Open Gizleme straight from your home screen, full-screen, and get notified of new messages even when your browser is closed.");
      steps.style.display="none"; now.style.display="block";
    } else if(isIOS){
      sub.textContent=t("Add it to your Home Screen");
      body.textContent=t("Install Gizleme for a full-screen app and message notifications:");
      steps.innerHTML=t("<li>Tap the <b>Share</b> icon in Safari’s toolbar</li><li>Scroll to <b>Add to Home Screen</b></li><li>Tap <b>Add</b></li>");
      steps.style.display="block"; now.style.display="none";
    } else { return; }     // no install path on this browser yet — try again next session
    markInstallPrompted();
    $("installModal").classList.add("show");
  }
  function maybeShowInstallModal(){
    if(isStandalone || installPrompted()) return;
    if(isInAppBrowser()) return;       // can't install from inside WhatsApp/Messenger — don't show or consume the prompt here
    if(document.querySelector(".modal.show")) { setTimeout(maybeShowInstallModal, 4000); return; }   // don't stack on an open dialog
    if(deferredPrompt || isIOS) openInstallModal();
    else installModalPending=true;     // wait for beforeinstallprompt to fire, then show
  }
  _showInstallInvite = maybeShowInstallModal;   // expose to enterApp (top-level scope)
  $("installNow").addEventListener("click",async()=>{
    closeInstallModal();
    if(deferredPrompt){ deferredPrompt.prompt(); try{ await deferredPrompt.userChoice; }catch(e){} deferredPrompt=null; showInstall(false); }
  });
  $("installLater").addEventListener("click",closeInstallModal);
  $("installModal").addEventListener("click",e=>{ if(e.target.id==="installModal") closeInstallModal(); });

  if("serviceWorker" in navigator){ window.addEventListener("load",()=>{ navigator.serviceWorker.register("/sw.js").catch(()=>{}); }); }

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
      $("mi-invite").hidden=!grp;
      $("mi-verify").hidden=!(R&&((R.fromContact&&R.paired)||grp));
      $("mi-notify").hidden=!(R&&R.fromContact&&!grp);
      $("mi-rekey").hidden=!(R&&R.paired&&!grp);
      $("mi-rename").hidden=!(R&&(R.fromContact||grp));
      m.hidden=false;
    } else m.hidden=true;
  }
  $("menuBtn").addEventListener("click",e=>{ e.stopPropagation(); toggleMenu(); });
  document.addEventListener("click",e=>{ if(!$("barMenu").hidden && !$("barMenu").contains(e.target) && e.target!==$("menuBtn")) closeMenu(); });
  $("barMenu").addEventListener("click",e=>{ const b=e.target.closest(".menu-item"); if(!b) return; closeMenu();
    const act=b.dataset.act;
    if(act==="invite") inviteToGroup();
    else if(act==="verify") openVerify();
    else if(act==="notify") nudgeContact();
    else if(act==="rekey") rekey();
    else if(act==="rename") renameChat();
    else if(act==="wire") $("wire").classList.toggle("show");
    else if(act==="settings") openSettings();
    else if(act==="lock") lockApp();
  });

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
  else { showAuth("register"); }                        // brand new → create account
})();
})();
