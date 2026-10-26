import {writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {transform} from '/Users/sclarke/github/oteleq-qualification/2026-10-22/current-source-1f47c46/otelc-pr157-review/source-c9a9429/adapters/node/src/compiler/transform.mjs';
const root='/Users/sclarke/github/oteleq-qualification/2026-10-22/current-source-1f47c46/otelc-pr157-review/name-before-c9/';
const source=`class Item { close() { function Item() { return value; } const value=7; this.value=Item(); this.helperName=Item.name; } }
const item=new Item(); item.close(); console.log(JSON.stringify({value:item.value,name:item.helperName}));`;
const plan={annotations:{read_existing:false,inject_generated:false},function_matchers:{include:[],exclude:[]},lifetime_matchers:{include:['*Item'],exclude:[]},lifetimes:{enabled:true,release_methods:['close']},traces:{enabled:false}};
writeFileSync(root+'plain.cjs',source);
writeFileSync(root+'instrumented.cjs',transform(source,root+'plain.cjs','app',plan,{register:()=>false}).code);
const results={};
for(const lane of ['plain','instrumented']){
 const result=spawnSync(process.execPath,[root+lane+'.cjs'],{encoding:'utf8',env:{...process.env,NODE_OPTIONS:'',NODE_PATH:''}});
 results[lane]={status:result.status,stdout:result.stdout,stderr:result.stderr};
}
writeFileSync(root+'reproducer.json',JSON.stringify({head:'c9a9429e196ae456eb8c04343bd63deb19c59bb0',scope:'isolated actual transform execution, no SDK admission',results},null,2)+'\n');
console.log(JSON.stringify(results));
