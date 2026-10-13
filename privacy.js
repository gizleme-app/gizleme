// Show the reader's language first (the sections are :target-driven; this just picks the default anchor).
(function(){
  if(location.hash==="#fr"||location.hash==="#en") return;
  var saved=null; try{ saved=localStorage.getItem("gz-lang"); }catch(e){}
  var fr = saved ? saved==="fr" : /^fr\b/i.test(navigator.language||"");
  location.replace("#"+(fr?"fr":"en"));
})();
