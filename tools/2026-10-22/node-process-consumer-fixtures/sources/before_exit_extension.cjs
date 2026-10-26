const fs=require('node:fs');let turn=0;
function selected(n){return n+1;}
process.on('beforeExit',()=>{++turn;fs.writeSync(1,'beforeExit:'+turn+'\n');if(turn===1)setImmediate(()=>fs.writeSync(1,'extension:'+selected(7)+'\n'));});
process.on('exit',code=>fs.writeSync(1,'exit:'+code+':'+turn+'\n'));
fs.writeSync(1,'main:'+selected(1)+'\n');
