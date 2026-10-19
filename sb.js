// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// iPhone display mode, read before the page is drawn. iOS 26 installed web apps (WebKit bug 301994) can paint a
// band over the bottom of the screen when the page is laid out under the status bar (viewport-fit=cover with a
// translucent status bar). "Compatibility" lays the page out inside the safe area instead, under an opaque status
// bar. Chosen in Settings (iPhone only), or with ?sbtest=1 / ?sbtest=0 in the address.
(function(){ try{
  var m=/[?&]sbtest=(0|1)(?:&|$)/.exec(location.search);
  if(m){ if(m[1]==="1") localStorage.setItem("gz-sbmode","compat"); else localStorage.removeItem("gz-sbmode"); }
  if(localStorage.getItem("gz-sbmode")!=="compat") return;
  document.documentElement.classList.add("sb-compat");
  var v=document.querySelector('meta[name="viewport"]'); if(v) v.setAttribute("content","width=device-width, initial-scale=1, interactive-widget=resizes-content");
  var th=localStorage.getItem("vesper-theme"), dark= th ? th==="dark" : !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  var s=document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]'); if(s) s.setAttribute("content", dark ? "black" : "default");
}catch(e){} })();
