import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {__oteleqGraph,run,captureClass,runReceiver} from '../adapters/generation/node_observe.mjs';

test('primitive values retain exact bits and absence tags',()=>{
  const graph=__oteleqGraph({nil:null,missing:undefined,number:-0,integer:2n,text:'\ud800',flag:true});
  assert.equal(graph.roots.nil.type,'null');
  assert.equal(graph.roots.missing.type,'undefined');
  assert.equal(graph.roots.number.bits,'8000000000000000');
  assert.equal(graph.roots.integer.value,'2');
  assert.equal(graph.roots.text.value,'\ud800');
  assert.equal(graph.roots.flag.value,true);
  const original=Object.getOwnPropertyDescriptor(BigInt.prototype,'toString');
  let calls=0;
  try{
    Object.defineProperty(BigInt.prototype,'toString',{value(){calls++;return 'masked'},configurable:true});
    assert.equal(__oteleqGraph({integer:2n}).roots.integer.value,'2');
    assert.equal(calls,0);
  }finally{Object.defineProperty(BigInt.prototype,'toString',original);}
});

function receiverFixture() {
  class Counter {
    static total=0;
    static shared=[];
    constructor(start){this.value=start;this.alias=this;this.shared=Counter.shared;}
    add(amount){this.value+=amount;Counter.total+=amount;Counter.shared.push(amount);return this;}
    async later(amount){await Promise.resolve();return this.add(amount);}
    fail(){throw new TypeError('expected');}
    remove(){delete Counter.total;return 7;}
  }
  const record=captureClass(Counter,{owner:'Counter',label:'fixture.Counter',methods:['add','later','fail','remove'],statics:['total','shared']});
  return {Counter,record};
}
function observedDirectory() {
  const directory=mkdtempSync(join(tmpdir(),'oteleq-node-receiver-'));
  const previous=process.env.OTELEQ_OBSERVATION;
  process.env.OTELEQ_OBSERVATION=join(directory,'observation.json');
  return {read:()=>JSON.parse(readFileSync(process.env.OTELEQ_OBSERVATION,'utf8')),close(){
    if(previous===undefined)delete process.env.OTELEQ_OBSERVATION;else process.env.OTELEQ_OBSERVATION=previous;
    rmSync(directory,{recursive:true});
  }};
}

test('declared receivers preserve returned and static aliases plus descriptor state',async()=>{
  const {Counter,record}=receiverFixture();
  const capture=observedDirectory();
  try{
    await runReceiver(record,{factory:undefined,fixture:{kind:'constructor',arguments:[10]},method:'add',arguments:[7],asynchronous:false},()=>({arguments:[7]}),()=>true);
    const data=capture.read();
    const roots=data.outcome.value.roots;
    assert.equal(roots.result.ref,roots.receiver.ref);
    const receiver=data.outcome.value.nodes[roots.receiver.ref];
    assert.equal(receiver.prototype,'declared:fixture.Counter');
    assert.equal(receiver.fields.find(field=>field[0]==='alias')[1].ref,roots.receiver.ref);
    const descriptor=data.outcome.value.nodes[roots['static:Counter.shared'].ref];
    assert.equal(receiver.fields.find(field=>field[0]==='shared')[1].ref,descriptor.fields.find(field=>field[0]==='value')[1].ref);
    assert.equal(descriptor.fields.find(field=>field[0]==='present')[1].value,true);
    assert.throws(()=>__oteleqGraph({receiver:new Counter(0)}),/opaque object prototype/);
  }finally{capture.close();}
});

test('receiver factories construct separately and declared async methods complete',async()=>{
  const {Counter,record}=receiverFixture();
  const factory=start=>new Counter(start);
  const capture=observedDirectory();
  try{
    await runReceiver(record,{factory:factory,fixture:{kind:'function',arguments:[10]},method:'later',arguments:[7],asynchronous:true},()=>({}),()=>true);
    const data=capture.read();
    assert.equal(data.outcome.kind,'return');
    assert.equal(data.outcome.value.roots.result.ref,data.outcome.value.roots.receiver.ref);
    await runReceiver(record,{factory:undefined,fixture:{kind:'constructor',arguments:[10]},method:'fail',arguments:[],asynchronous:false},()=>({}),()=>true);
    const error=capture.read();
    assert.equal(error.outcome.kind,'error');
    assert.equal(error.outcome.value.nodes[error.outcome.value.roots.error.ref].type,'TypeError');
  }finally{capture.close();}
});

test('deleted class data stays visibly absent and static accessors are never called',async()=>{
  const {Counter,record}=receiverFixture();
  const capture=observedDirectory();
  try{
    await runReceiver(record,{factory:undefined,fixture:{kind:'constructor',arguments:[10]},method:'remove',arguments:[],asynchronous:false},()=>({}),()=>true);
    const data=capture.read();
    const descriptor=data.after.nodes[data.after.roots['static:Counter.total'].ref];
    assert.equal(descriptor.fields.find(field=>field[0]==='present')[1].value,false);
    let calls=0;
    Object.defineProperty(Counter,'total',{get(){calls++;return 7;},configurable:true});
    await assert.rejects(runReceiver(record,{factory:undefined,fixture:{kind:'constructor',arguments:[10]},method:'remove',arguments:[],asynchronous:false},()=>({}),()=>true),/static accessor/);
    assert.equal(calls,0);
  }finally{capture.close();}
});

test('changed class method shape inheritance and factory bindings refuse execution',async()=>{
  for(const change of [({Counter})=>{Counter.prototype.add=()=>7;},({Counter})=>{Counter.prototype.extra=1;},({Counter})=>Object.preventExtensions(Counter.prototype)]){
    const fixture=receiverFixture();change(fixture);
    await assert.rejects(runReceiver(fixture.record,{factory:undefined,fixture:{kind:'constructor',arguments:[10]},method:'add',arguments:[7],asynchronous:false},()=>({}),()=>true),/changed/);
  }
  const {Counter,record}=receiverFixture();
  await assert.rejects(runReceiver(record,{factory:undefined,fixture:{kind:'constructor',arguments:[]},method:'add',arguments:[],asynchronous:false},()=>({}),()=>false),/class or factory binding changed/);
  await assert.rejects(runReceiver(record,{factory:7,fixture:{kind:'function',arguments:[]},method:'add',arguments:[],asynchronous:false},()=>({}),()=>true),/factory requires/);
  const wrong=()=>({});
  await assert.rejects(runReceiver(record,{factory:wrong,fixture:{kind:'function',arguments:[]},method:'add',arguments:[],asynchronous:false},()=>({}),()=>true),/different receiver/);
  const shadow=()=>Object.assign(new Counter(0),{add:7});
  await assert.rejects(runReceiver(record,{factory:shadow,fixture:{kind:'function',arguments:[]},method:'add',arguments:[],asynchronous:false},()=>({}),()=>true),/shadows/);
  class Derived extends Counter{}
  assert.throws(()=>captureClass(Derived,{methods:[],statics:[],label:'Derived',owner:'Derived'}),/inheritance/);
});

test('proxy constructors receivers and method accessors cannot trigger traps',async()=>{
  const {Counter,record}=receiverFixture();
  let calls=0;
  const constructor=new Proxy(Counter,{get(){calls++;throw new Error('CALLBACK');}});
  assert.throws(()=>captureClass(constructor,{methods:[],statics:[]}),/source class/);
  const factory=()=>new Proxy(new Counter(0),{getPrototypeOf(){calls++;return Counter.prototype;}});
  await assert.rejects(runReceiver(record,{factory:factory,fixture:{kind:'function',arguments:[]},method:'add',arguments:[],asynchronous:false},()=>({}),()=>true),/different receiver/);
  Object.defineProperty(Counter.prototype,'add',{get(){calls++;return ()=>7;},configurable:true});
  await assert.rejects(runReceiver(record,{factory:undefined,fixture:{kind:'constructor',arguments:[]},method:'add',arguments:[],asynchronous:false},()=>({}),()=>true),/own data descriptor/);
  assert.equal(calls,0);
});

test('observer intrinsic replacements and JSON hooks refuse without invoking callbacks',()=>{
  const descriptor=Object.getOwnPropertyDescriptor;
  const define=Object.defineProperty;
  for(const [owner,key] of [[Object,'getPrototypeOf'],[Map.prototype,'get'],[Array.prototype,Symbol.iterator],[Object.prototype,'toJSON']]){
    const original=descriptor(owner,key);let calls=0,error;
    try{
      define(owner,key,{value(){calls++;return undefined;},configurable:true,writable:true});
      try{__oteleqGraph({value:7});}catch(caught){error=caught;}
    }finally{if(original)define(owner,key,original);else delete owner[key];}
    assert.match(error.message,/intrinsic|JSON hooks/);
    assert.equal(calls,0);
  }
});

test('native internal state cannot hide behind a plain or declared prototype',()=>{
  const {Counter,record}=receiverFixture();
  for(const prototype of [Object.prototype,null,record.prototype]){
    for(const value of [new Date(0),new Map([['value',7]]),new Set([7]),new WeakMap(),new WeakSet(),
      new ArrayBuffer(8),new Uint8Array([7]),/pattern/,new Number(7),Promise.resolve(7),new Error('native')]){
      Object.setPrototypeOf(value,prototype);
      assert.throws(()=>__oteleqGraph({value},new Map([[Counter.prototype,'declared:fixture.Counter']])),/native/);
    }
  }
  assert.throws(()=>__oteleqGraph({error:Object.create(Error.prototype)}),/native error prototype/);
});

test('bindings changed during construction or invocation prevent complete evidence',async()=>{
  const capture=observedDirectory();
  try{
    for(const changeDuringConstruction of [true,false]){
      let valid=true;
      class Counter {run(){valid=false;return 7;}}
      const record=captureClass(Counter,{owner:'Counter',label:'fixture.Counter',methods:['run'],statics:[]});
      const factory=()=>{if(changeDuringConstruction)valid=false;return new Counter();};
      await assert.rejects(runReceiver(record,{factory:factory,fixture:{kind:'function',arguments:[]},method:'run',arguments:[],asynchronous:false},()=>({}),()=>valid),/binding changed/);
    }
  }finally{capture.close();}
});

test('aliases cycles sparse arrays descriptors and prototype state survive',()=>{
  const child={};child.owner=child;
  const array=[];array.length=3;array[2]=child;
  Object.defineProperty(child,'fixed',{value:7,writable:false,enumerable:false,configurable:false});
  const graph=__oteleqGraph({a:array,b:child,c:child});
  assert.equal(graph.roots.b.ref,graph.roots.c.ref);
  const node=graph.nodes[graph.roots.b.ref];
  assert.equal(node.fields.find(field=>field[0]==='owner')[1].ref,graph.roots.b.ref);
  assert.deepEqual(node.fields.find(field=>field[0]==='fixed').slice(2),[false,false,false]);
  assert.equal(graph.nodes[graph.roots.a.ref].prototype,'Array');
  const plain=__oteleqGraph({root:{}}).nodes[0];
  const empty=Object.preventExtensions(Object.create(null));
  const other=__oteleqGraph({root:empty}).nodes[0];
  assert.equal(plain.prototype,'Object');assert.equal(plain.extensible,true);
  assert.equal(other.prototype,'null');assert.equal(other.extensible,false);
});

test('error tags never invoke prototype name getters',()=>{
  let calls=0;
  const original=Object.getOwnPropertyDescriptor(Error.prototype,'name');
  try{
    Object.defineProperty(Error.prototype,'name',{get(){calls++;return 'changed'},configurable:true});
    const graph=__oteleqGraph({error:new Error('known'),range:new RangeError('range')});
    assert.equal(calls,0);
    assert.equal(graph.nodes[graph.roots.error.ref].type,'Error');
    assert(!graph.nodes[0].fields.some(field=>field[0]==='stack'));
  }finally{Object.defineProperty(Error.prototype,'name',original);}
});

test('unknown values accessors proxies symbols and bounds cannot qualify',()=>{
  let calls=0;
  const accessor={get value(){calls++;return 7;}};
  const proxy=new Proxy({}, {ownKeys(){calls++;return [];}});
  for(const value of [accessor,proxy,()=>7,new Date(),{[Symbol('key')]:1}]){
    assert.throws(()=>__oteleqGraph({root:value}));
  }
  assert.equal(calls,0);
  let root={};for(let index=0;index<35;index++)root={child:root};
  assert.throws(()=>__oteleqGraph({root}),/graph limit/);
  assert.throws(()=>__oteleqGraph({root:Array.from({length:600},()=>({}))}),/graph limit/);
});

test('runner separates invocation errors from observer errors and awaits only declared async',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'oteleq-node-observer-'));
  const previous=process.env.OTELEQ_OBSERVATION;
  process.env.OTELEQ_OBSERVATION=join(directory,'observation.json');
  try{
    const state={calls:0};
    await run(value=>{state.calls+=value;return state;},[7],()=>({state}),false,()=>true);
    let capture=JSON.parse(readFileSync(process.env.OTELEQ_OBSERVATION,'utf8'));
    assert.equal(capture.outcome.kind,'return');
    assert.equal(capture.outcome.value.roots.result.ref,capture.outcome.value.roots.state.ref);
    await run(async()=>12,[],()=>({}),true,()=>true);
    capture=JSON.parse(readFileSync(process.env.OTELEQ_OBSERVATION,'utf8'));
    assert.equal(capture.outcome.value.roots.result.type,'float64');
    await run(()=>{throw 'known';},[],()=>({}),false,()=>true);
    capture=JSON.parse(readFileSync(process.env.OTELEQ_OBSERVATION,'utf8'));
    assert.equal(capture.outcome.kind,'error');
    await assert.rejects(run(()=>7,[],()=>({}),false,()=>false),/selected function binding differs/);
    let getters=0;
    await assert.rejects(run(()=>({get then(){getters++;return ()=>{};}}),[],()=>({}),false,()=>true),/accessor/);
    assert.equal(getters,0);
  }finally{
    if(previous===undefined)delete process.env.OTELEQ_OBSERVATION;else process.env.OTELEQ_OBSERVATION=previous;
    rmSync(directory,{recursive:true});
  }
});
