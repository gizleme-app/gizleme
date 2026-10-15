# Lot C: French UI from the browser locale, in-app language switch, translated dynamic strings (placeholders,
# statuses, day separators), invite landing with the inviter's name, free display name at registration,
# SVG controls instead of emoji, textarea composer (Enter sends, Shift+Enter newline).
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site15"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__calls=[]; window.__pstate={};
window.supabase={createClient:()=>({
  channel:()=>{ const c={ _cbs:{}, on(type,opts,cb){ this._cbs[type+":"+(opts&&opts.event)]=cb; return this; }, subscribe(cb){ setTimeout(()=>cb&&cb("SUBSCRIBED"),5); return this; },
    track(p){ this._me=p; return Promise.resolve("ok"); }, untrack(){ return Promise.resolve("ok"); }, send(m){ (window.__sent=window.__sent||[]).push(m); return Promise.resolve("ok"); }, presenceState(){ return window.__pstate; }, unsubscribe(){} };
    window.__chan=c; return c; },
  storage:{from:()=>({upload:async()=>({}),getPublicUrl:(p)=>({data:{publicUrl:"/blob/"+p}}),remove:async()=>({})})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{}; window.__calls.push([n,b]);
    if(n==="gizleme-auth"&&b.action==="register"){ window.__reg=b; return {data:{ok:true,token:"t",username:b.username,display:b.display}}; }
    if(n==="gizleme-auth"&&b.action==="rename"){ window.__renamed=b.display; return {data:{ok:true,display:b.display}}; }
    if(n==="gizleme-vault") return {data:{ok:true,abk:null,contacts:null,cver:0}};
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
'''
(site/"mock.js").write_text(MOCK)
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad()};\n})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"vendor").mkdir(exist_ok=True)
for _v in _os.listdir(SRC+"vendor"):
    if _v.endswith(".js") and not _v.startswith("supabase") and not _v[0].isdigit(): (site/"vendor"/_v).write_bytes(_pl.Path(SRC+"vendor/"+_v).read_bytes())
os.chdir(site)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=socketserver.ThreadingTCPServer(("127.0.0.1",0),Q); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
inv=base64.urlsafe_b64encode(json.dumps({"s":base64.b64encode(os.urandom(32)).decode(),"n":"Camille"}).encode()).decode().rstrip("=")

r={}
with sync_playwright() as pw:
    b=pw.chromium.launch()
    ctx=b.new_context(viewport={"width":414,"height":820}, locale="fr-FR"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept("Élodie Ç"))
    p.goto(f"http://127.0.0.1:{port}/#i={inv}"); p.wait_for_timeout(500)
    r["fr_htmlLang"]= p.evaluate("()=>document.documentElement.lang")
    r["fr_promise"]= p.eval_on_selector(".promise b","e=>e.textContent")
    r["fr_tagline"]= p.eval_on_selector(".hero-tag","e=>e.textContent")
    r["fr_button"]= p.eval_on_selector("#joinBtn","e=>e.textContent")
    r["fr_placeholder"]= p.get_attribute("#userInput","placeholder")
    r["fr_inviteHeadline"]= p.eval_on_selector("#joinHint","e=>e.textContent").startswith("Camille t'invite")
    r["fr_lockTitle"]= p.get_attribute("#sbLock","title")
    r["dispFieldShown"]= p.is_visible("#dispField")
    p.fill("#userInput","oguz"); p.fill("#dispInput","Oğuz İ."); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(2500)
    r["displayNameSent"]= p.evaluate("()=>window.__reg.display")
    r["fr_peerName"]= p.eval_on_selector("#peerName","e=>e.textContent")          # the invite contact: "Camille"
    r["fr_status"]= p.eval_on_selector("#statusText","e=>e.textContent")
    p.click("#backHome"); p.wait_for_timeout(300)
    r["fr_listHeader"]= p.eval_on_selector(".sb-head > span:first-child","e=>e.textContent.trim()")
    r["fr_preview"]= p.eval_on_selector(".ct .cm","e=>e.textContent")
    # SVG controls, no emoji glyphs in the bar/composer
    r["svgControls"]= p.evaluate("()=>['sbLock','sbSettings','sbNew','backHome','menuBtn','attachBtn','sendBtn'].every(id=>document.getElementById(id).querySelector('svg.ico'))")
    r["composerIsTextarea"]= p.evaluate("()=>document.getElementById('msgInput').tagName==='TEXTAREA'")
    # chat: Shift+Enter makes a newline, Enter sends; French day separator
    p.click(".ct"); p.wait_for_timeout(800)
    p.focus("#msgInput"); p.keyboard.type("ligne 1"); p.keyboard.press("Shift+Enter"); p.keyboard.type("ligne 2"); p.wait_for_timeout(100)
    r["shiftEnterNewline"]= p.evaluate("()=>document.getElementById('msgInput').value.includes('\\n')")
    p.keyboard.press("Enter"); p.wait_for_timeout(800)
    r["enterSends"]= p.eval_on_selector_all(".log .bubble.sent .txt","els=>els.map(e=>e.textContent)")==["ligne 1\nligne 2"]
    r["fr_daySep"]= p.eval_on_selector(".log .daysep","e=>e.textContent")
    r["fr_sentTitle"]= p.get_attribute(".log .bubble.sent .st","title")
    # rename from settings (prompt accepted with "Élodie Ç") → server + presence
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.wait_for_timeout(100)
    r["fr_settingsTitle"]= p.eval_on_selector("#settingsModal h1","e=>e.textContent")
    p.click("#dispEdit"); p.wait_for_timeout(800)
    r["renamed"]= p.evaluate("()=>window.__renamed")
    r["presenceUsesNewName"]= p.evaluate("()=>window.__chan._me && window.__chan._me.name")
    # switch to English live
    p.click("#langToggle"); p.wait_for_timeout(300)
    r["en_htmlLang"]= p.evaluate("()=>document.documentElement.lang")
    r["en_settingsTitle"]= p.eval_on_selector("#settingsModal h1","e=>e.textContent")
    r["en_lockTitle"]= p.get_attribute("#sbLock","title")
    r["en_persisted"]= p.evaluate("()=>localStorage.getItem('gz-lang')")
    p.click("#settingsClose"); p.click("#backHome"); p.wait_for_timeout(300)
    r["en_preview"]= p.eval_on_selector(".ct .cm","e=>e.textContent")
    # English-locale browser without a saved choice → English
    c2=b.new_context(viewport={"width":414,"height":820}, locale="en-US"); p2=c2.new_page(); p2.goto(f"http://127.0.0.1:{port}/"); p2.wait_for_timeout(300)
    r["enLocale_button"]= p2.eval_on_selector("#joinBtn","e=>e.textContent"); c2.close()
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
