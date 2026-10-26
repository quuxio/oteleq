const fs=require('node:fs');const http=require('node:http');let reads=0;function selected(){return reads;}
const server=http.createServer((request,response)=>response.end('unused'));
server.listen(0,'127.0.0.1',()=>{const request=http.request({hostname:'127.0.0.1',port:server.address().port,path:'/',agent:false});request.on('error',()=>{});const error=new Error();Object.defineProperty(error,'message',{get(){reads++;return 'fixture';},configurable:true});request.emit('error',error);fs.writeSync(1,'reads:'+selected()+'\n');request.destroy();server.close();});
