const fs=require('node:fs');const http=require('node:http');
const count=2000;function selected(n){return n+1;}
const request=http.request(process.env.FIXTURE_URL,{method:'POST'},response=>{response.resume();response.on('end',()=>{let sum=0;for(let i=0;i<count;i++)sum+=selected(i);fs.writeSync(1,'completed:'+count+':'+sum+'\n');process.exit(0);});});
request.on('error',()=>{process.exitCode=2;});request.end('ready');
