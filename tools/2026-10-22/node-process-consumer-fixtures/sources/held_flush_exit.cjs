const fs=require('node:fs');const http=require('node:http');
function selected(n){return n+1;}
fs.writeSync(1,'initial:'+selected(0)+'\n');
const request=http.request(process.env.FIXTURE_URL,{method:'POST'},response=>{response.resume();response.on('end',()=>{fs.writeSync(1,'done:'+selected(7)+'\n');process.exit(0);});});
request.on('error',()=>{process.exitCode=2;});request.end('ready');
