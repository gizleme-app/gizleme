// Gizleme — end-to-end encrypted messaging in the browser. https://gizleme.com
// Copyright (C) 2026 Oğuz Seran
// SPDX-License-Identifier: AGPL-3.0-only
// This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
// General Public License as published by the Free Software Foundation, version 3. It is distributed WITHOUT
// ANY WARRANTY; see the LICENSE file for details.
// Show the reader's language first (the sections are :target-driven; this just picks the default anchor).
(function(){
  if(location.hash==="#fr"||location.hash==="#en") return;
  var saved=null; try{ saved=localStorage.getItem("gz-lang"); }catch(e){}
  var fr = saved ? saved==="fr" : /^fr\b/i.test(navigator.language||"");
  location.replace("#"+(fr?"fr":"en"));
})();
