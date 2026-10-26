const fs=require('node:fs');let finalized=0;
const registry=new FinalizationRegistry(()=>{finalized++;});
class Payload{constructor(amount){this.amount=amount;}}
function selected(n){const value=new Payload(n);registry.register(value,1);return Promise.resolve(value);}
async function main(){await selected(7);for(let i=0;i<64&&finalized===0;i++){await new Promise(resolve=>setImmediate(resolve));global.gc();await new Promise(resolve=>setImmediate(resolve));}fs.writeSync(1,finalized>0?'collected\n':'not-observed\n');}
main().catch(()=>{process.exitCode=2;});
