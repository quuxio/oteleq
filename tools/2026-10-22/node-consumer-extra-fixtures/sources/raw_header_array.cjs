const fs=require('node:fs');const http=require('node:http');
function selected(n){return n+1;}
const headers=['Host','fixture','X-Dup','one','X-Dup','two','X-Fixed','three'];let seen=[];
const server=http.createServer((request,response)=>{for(let i=0;i<request.rawHeaders.length;i+=2){if(/^x-(dup|fixed)$/i.test(request.rawHeaders[i]))seen.push(request.rawHeaders[i],request.rawHeaders[i+1]);}response.end('ok');});
server.listen(0,'127.0.0.1',()=>{const request=http.request({hostname:'127.0.0.1',port:server.address().port,path:'/',headers,agent:false},response=>{response.resume();response.on('end',()=>server.close(()=>{fs.writeSync(1,'result:'+selected(7)+'\nkeys:'+JSON.stringify(Reflect.ownKeys(headers))+'\nvalues:'+JSON.stringify(headers)+'\nseen:'+JSON.stringify(seen)+'\n');}));});request.on('error',()=>{process.exitCode=2;server.close();});request.end();});
