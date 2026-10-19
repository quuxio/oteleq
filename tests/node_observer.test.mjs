import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {__oteleqGraph,run} from '../adapters/generation/node_observe.mjs';

test('primitive values retain exact bits and absence tags',()=>{
  const graph=__oteleqGraph({nil:null,missing:undefined,number:-0,integer:2n,text:'\ud800',flag:true});
  assert.equal(graph.roots.nil.type,'null');
  assert.equal(graph.roots.missing.type,'undefined');
  assert.equal(graph.roots.number.bits,'8000000000000000');
  assert.equal(graph.roots.integer.value,'2');
  assert.equal(graph.roots.text.value,'\ud800');
  assert.equal(graph.roots.flag.value,true);
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
