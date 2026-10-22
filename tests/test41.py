# Turkish: detected from the browser, every string translated (placeholders intact), switchable in Settings,
# Turkish dates and initials (i → İ), notification texts, and the Turkish section of the privacy page.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site41"); site.mkdir(exist_ok=True)
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
html=html.replace("/app.min.js?v=","/app.js?v=")   # the page loads the readable app.js here (hooked below), not the minified build
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); }; window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),up:(s)=>up(s),fmtList:(ts)=>fmtListTime(ts),swTmpl:()=>({msg:t("New message from {name}"),call:t("{name} is calling you"),anyMsg:t("New message")}),lang:()=>LANG};\n})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"vendor").mkdir(exist_ok=True)
for _v in _os.listdir(SRC+"vendor"):
    if _v.endswith(".js") and not _v.startswith("supabase") and not _v[0].isdigit(): (site/"vendor"/_v).write_bytes(_pl.Path(SRC+"vendor/"+_v).read_bytes())
for _f in ("privacy.html","privacy.js"): (site/_f).write_bytes(_pl.Path(SRC+_f).read_bytes())
(site/"sw.js").write_text(pathlib.Path(SRC+"sw.js").read_text().replace("/app.min.js?v=","/app.js?v="))   # the worker precaches what the page loads
os.chdir(site)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=socketserver.ThreadingTCPServer(("127.0.0.1",0),Q); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
inv=base64.urlsafe_b64encode(json.dumps({"s":base64.b64encode(os.urandom(32)).decode(),"n":"Camille"}).encode()).decode().rstrip("=")

r={}
import re, subprocess
# dictionary completeness: every French key has a Turkish one, with the same placeholders, line breaks and tags
NODE=r"""global.window={}; require(process.argv[1]); const d=window.GZ_I18N; const ph=s=>(s.match(/\{[a-z]+\}/g)||[]).sort().join(","), tg=s=>(s.match(/<\/?[a-z]+>/g)||[]).join(",");
const fr=Object.keys(d.fr), tr=d.tr||{}; const miss=fr.filter(k=>!(k in tr)), bad=Object.keys(tr).filter(k=>ph(k)!==ph(tr[k])||tg(k)!==tg(tr[k])||(k.split("\n").length!==tr[k].split("\n").length)||!tr[k].trim());
console.log(JSON.stringify({n:Object.keys(tr).length, miss:miss.slice(0,5), missN:miss.length, bad:bad.slice(0,5), badN:bad.length}));"""
out=subprocess.run(["node","-e",NODE,SRC+"i18n.js"],capture_output=True,text=True)
try: d=json.loads(out.stdout.strip())
except Exception: d={"err":(out.stdout+out.stderr)[:300]}
r["dict"]=d
r["dict_complete"]= d.get("missN")==0 and d.get("badN")==0 and d.get("n",0)>=500
with sync_playwright() as pw:
    b=pw.chromium.launch()
    ctx=b.new_context(viewport={"width":414,"height":820}, locale="tr-TR"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept("Ilık")); ctx.add_init_script("window.__promptValue='Ilık';")
    p.goto(f"http://127.0.0.1:{port}/#i={inv}"); p.wait_for_timeout(500)
    r["tr_htmlLang"]= p.evaluate("()=>document.documentElement.lang")=="tr"
    r["tr_button"]= p.eval_on_selector("#joinBtn","e=>e.textContent")
    r["tr_buttonOk"]= r["tr_button"] in ("Hesap oluştur","Devam","Bağlan")
    r["tr_inviteHeadline"]= "Camille seni özel bir sohbete davet etti" in p.evaluate("()=>document.body.innerText")
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","ilker"); p.fill("#dispInput","ilker"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(2500)
    p.click("#backHome"); p.wait_for_timeout(300)
    r["tr_listHeader"]= p.eval_on_selector(".sb-head > span:first-child","e=>e.textContent.trim()")=="Sohbetler"
    r["tr_initialDotted"]= p.evaluate("()=>window.__gz.up('i')")=="İ" and p.evaluate("()=>window.__gz.up('ı')")=="I"
    # dates: Turkish weekday names in the list for a date a few days ago
    wd=p.evaluate("()=>window.__gz.fmtList(Date.now()-3*86400000)")
    r["tr_weekday"]= wd in ("Pzt","Sal","Çar","Per","Cum","Cmt","Paz")
    r["tr_weekday_v"]= wd
    r["tr_notifTmpl"]= p.evaluate("()=>window.__gz.swTmpl()")=={"msg":"Yeni mesaj — {name}","call":"{name} seni arıyor","anyMsg":"Yeni mesaj"}
    # chat: status and day separator in Turkish
    p.click(".ct"); p.wait_for_timeout(800)
    p.fill("#msgInput","merhaba"); p.press("#msgInput","Enter"); p.wait_for_timeout(700)
    r["tr_daySep"]= p.eval_on_selector(".log .daysep","e=>e.textContent")=="Bugün"
    # Settings: the selector shows Türkçe; switching to French then English then back to Turkish works live
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.wait_for_timeout(100)
    r["tr_settingsTitle"]= p.eval_on_selector("#settingsModal h1","e=>e.textContent")=="Ayarlar"
    r["sel_showsTr"]= p.evaluate("()=>document.getElementById('langSel').value")=="tr"
    p.evaluate("()=>document.querySelector('#settingsModal [data-go=chats]').click()"); p.wait_for_timeout(100)
    r["sel_options"]= p.evaluate("()=>[...document.getElementById('langSel').options].map(o=>o.value+':'+o.textContent).join('|')")=="en:English|fr:Français|tr:Türkçe"
    p.select_option("#langSel","fr"); p.wait_for_timeout(250)
    r["switch_fr"]= p.eval_on_selector("#settingsModal h1","e=>e.textContent")=="Réglages" and p.evaluate("()=>document.documentElement.lang")=="fr"
    p.select_option("#langSel","en"); p.wait_for_timeout(250)
    r["switch_en"]= p.eval_on_selector("#settingsModal h1","e=>e.textContent")=="Settings"
    p.select_option("#langSel","tr"); p.wait_for_timeout(250)
    r["switch_backTr"]= p.eval_on_selector("#settingsModal h1","e=>e.textContent")=="Ayarlar" and p.evaluate("()=>localStorage.getItem('gz-lang')")=="tr"
    # the saved choice wins over the browser locale
    c2=b.new_context(viewport={"width":414,"height":820}, locale="en-US"); p2=c2.new_page(); p2.goto(f"http://127.0.0.1:{port}/"); p2.wait_for_timeout(200)
    p2.evaluate("()=>localStorage.setItem('gz-lang','tr')"); p2.reload(); p2.wait_for_timeout(400)
    r["saved_beats_locale"]= p2.evaluate("()=>window.__gz.lang()")=="tr"
    c2.close()
    # a browser whose first language is German but second Turkish → Turkish
    c3=b.new_context(viewport={"width":414,"height":820}, locale="de-DE", extra_http_headers={"Accept-Language":"de-DE,tr;q=0.8"}); p3=c3.new_page()
    p3.add_init_script("Object.defineProperty(navigator,'languages',{get:()=>['de-DE','tr-TR','en']})")
    p3.goto(f"http://127.0.0.1:{port}/"); p3.wait_for_timeout(300)
    r["second_language_tr"]= p3.evaluate("()=>window.__gz.lang()")=="tr" and p3.eval_on_selector("#joinBtn","e=>e.textContent")!="Create account"
    c3.close()
    # privacy page: a Turkish reader lands on the Turkish section
    c4=b.new_context(viewport={"width":414,"height":820}, locale="tr-TR"); p4=c4.new_page()
    p4.goto(f"http://127.0.0.1:{port}/privacy.html"); p4.wait_for_timeout(300)
    r["privacy_tr"]= p4.evaluate("()=>location.hash")=="#tr" and p4.eval_on_selector("#tr h1","e=>getComputedStyle(e).display!=='none' && e.textContent")=="Gizlilik"
    c4.close()
    r["errors"]= errs[:3]
    b.close()
srv.shutdown()
print("RESULTS")
for k,v in r.items(): print(f"  {k}: {v}")
