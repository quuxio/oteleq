const fs=require('node:fs');
function selected(n){return n+1;}
process.on('exit',code=>fs.writeSync(1,'exit_event:'+code+'\n'));
fs.writeSync(1,'main:'+selected(1)+'\n');process.emit('exit',73);
fs.writeSync(1,'after:'+selected(7)+'\n');setImmediate(()=>fs.writeSync(1,'late:'+selected(9)+'\n'));
