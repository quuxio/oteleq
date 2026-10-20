import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {captureClass} from '../adapters/generation/node_observe.mjs';
import {runSequence} from '../adapters/generation/node_sequence.mjs';

function fixture(held=false,asynchronous=false) {
  class Counter {
    static held=null;
    constructor(start){this.value=start;this.self=this;if(held)Counter.held=this;}
    add(value){this.value+=value;return this;}
    async later(value){await Promise.resolve();return this.add(value);}
  }
  const record=captureClass(Counter,{owner:'Counter',label:'fixture.Counter',methods:['add','later'],statics:['held']});
  const sequence=[{id:'first',action:'call',arguments:[7]},{id:'second',action:'call',arguments:[2]},
    {id:'release',action:'release'},{id:'collection',action:'collect',gc_rounds:held?2:64,settle_turns:4}];
  return {Counter,record,call:{fixture:{kind:'constructor',arguments:[10]},method:asynchronous?'later':'add',arguments:[7],asynchronous,sequence}};
}

async function observe(value) {
  const folder=mkdtempSync(join(tmpdir(),'oteleq-sequence-'));
  const previous=process.env.OTELEQ_OBSERVATION;
  process.env.OTELEQ_OBSERVATION=join(folder,'observed.json');
  try {
    await runSequence(value.record,value.call,()=>({arguments:[7]}),()=>true);
    return JSON.parse(readFileSync(process.env.OTELEQ_OBSERVATION,'utf8'));
  } finally {
    if(previous===undefined)delete process.env.OTELEQ_OBSERVATION;else process.env.OTELEQ_OBSERVATION=previous;
    rmSync(folder,{recursive:true});
  }
}

test('actual collection releases returned receiver aliases after ordered calls',async()=>{
  for(const asynchronous of [false,true]) {
    const observed=await observe(fixture(false,asynchronous));
    assert.equal(observed.steps.length,4);
    assert.deepEqual(observed.steps.map(step=>step.action),['call','call','release','collect']);
    assert.equal(observed.steps[3].collection.completed,true);
    assert.ok(observed.steps[3].collection.rounds>=1&&observed.steps[3].collection.rounds<=64);
    assert.deepEqual(observed.steps[3].gaps,[]);
    assert.deepEqual(observed.steps[2].after.roots.receiver,{type:'null'});
  }
});

test('retained application objects yield an explicit bounded observation gap',async()=>{
  const value=fixture(true);
  const observed=await observe(value);
  assert.equal(observed.steps[3].collection.completed,false);
  assert.equal(observed.steps[3].collection.rounds,2);
  assert.match(observed.steps[3].gaps[0].reason,/not observed.*no leak inference/);
  value.Counter.held=null;
});

test('call-only and release-only tails do not require collection',async()=>{
  for(const tail of [1,2,3]) {
    const value=fixture();
    value.call.sequence=value.call.sequence.slice(0,tail);
    const observed=await observe(value);
    assert.equal(observed.steps.length,tail);
    assert.ok(observed.steps.every(step=>step.collection===undefined));
  }
});

test('a shadowing method introduced by a prior action cannot replace the next call',async()=>{
  class Counter {constructor(){this.value=0;}add(){this.add=()=>99;return 7;}}
  const record=captureClass(Counter,{owner:'Counter',label:'fixture.Counter',methods:['add'],statics:[]});
  const call={fixture:{kind:'constructor',arguments:[]},method:'add',arguments:[],asynchronous:false,
    sequence:[{id:'first',action:'call',arguments:[]},{id:'second',action:'call',arguments:[]}]};
  await assert.rejects(observe({record,call}),/opaque|source method|observation/);
});
