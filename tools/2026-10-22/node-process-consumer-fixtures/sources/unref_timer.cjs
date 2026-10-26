const fs=require('node:fs');
function selected(n){return n+1;}
setTimeout(()=>fs.writeSync(1,'UNREF_TIMER\n'),0).unref();
fs.writeSync(1,'main:'+selected(7)+'\n');
