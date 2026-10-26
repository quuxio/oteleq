import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {transform} from '/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-01fa267/provider/adapters/node/src/compiler/transform.mjs';
const root=path.dirname(new URL(import.meta.url).pathname);
const plan={function_matchers:{include:[],exclude:[]},lifetime_matchers:{include:['*'],exclude:[]}, annotations:{read_existing:false,inject_generated:false},traces:{enabled:false},lifetimes:{enabled:true,release_methods:['close']}};
const samples={constructor:'class Item { constructor(){ function read(){return value;} const value=7; this.value=read(); } } console.log(new Item().value);',release:'class Item { close(){ function read(){return value;} const value=7; this.value=read(); } } const item=new Item(); item.close();console.log(item.value);'};
const results=[];
for(const [name,source] of Object.entries(samples)) {
 const baseline=path.join(root,name+'-plain.mjs');fs.writeFileSync(baseline,source);
 const changed=path.join(root,name+'-instrumented.mjs');
 const transformed=transform(source,baseline,'app.mjs',plan,{register:()=>false});fs.writeFileSync(changed,transformed.code);
 const run=file=>{const r=spawnSync(process.execPath,[file],{encoding:'utf8',timeout:10000});return {status:r.status,stdout:r.stdout,stderr:r.stderr,error:r.error?.message};};
 results.push({name,baseline:run(baseline),instrumented:run(changed)});
}
fs.writeFileSync(path.join(root,'lifetime-closure-reproducer.json'),JSON.stringify({head:'01fa2678f24d23ce23086393b284676a092430a0',scope:'isolated transform execution, no SDK admission',results},null,2)+'\n');
console.log(JSON.stringify(results));
