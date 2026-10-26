const fs=require('node:fs');let total=0;
function selected(n){total+=n;return total;}
process.on('exit',code=>fs.writeSync(1,'exit:'+code+':'+selected(7)+'\n'));
fs.writeSync(1,'main:'+selected(1)+'\n');
