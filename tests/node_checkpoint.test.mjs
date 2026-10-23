import assert from 'node:assert/strict';
import {after,afterEach,test} from 'node:test';
import {mkdtemp,readFile,writeFile,lstat,readdir,rm,mkdir,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as pause} from 'node:timers/promises';

const root=await mkdtemp(join(tmpdir(),'oteleq-node-checkpoint-'));
const token='test-checkpoint-token';
process.env.OTELEQ_NODE_CONTROL_ROOT=root;
process.env.OTELEQ_NODE_CONTROL_TOKEN=token;
const {checkpoint}=await import('../adapters/generation/node_checkpoint.mjs');
const {runSequence}=await import('../adapters/generation/node_sequence.mjs');
const {captureClass}=await import('../adapters/generation/node_observe.mjs');

afterEach(async()=>{
  for(const name of await readdir(root)) await rm(join(root,name),{recursive:true,force:true});
});
after(async()=>{await rm(root,{recursive:true});});

async function ready(phase) {
  const deadline=Date.now()+5000;
  while(Date.now()<deadline) {
    try {await lstat(join(root,phase+'.ready'));return;}
    catch(error) {if(error.code!=='ENOENT') throw error;}
    await pause(1);
  }
  throw new Error('checkpoint did not become ready');
}

test('a checkpoint publishes complete private bytes and yields until the matching host acknowledgement',async()=>{
  let completed=false;
  const pending=checkpoint('before-0').then(()=>{completed=true;});
  await ready('before-0');
  const filename=join(root,'before-0.ready');
  assert.equal(await readFile(filename,'utf8'),token+' before-0\n');
  assert.equal((await lstat(filename)).mode&0o777,0o600);
  await pause(2);
  assert.equal(completed,false);
  await writeFile(join(root,'before-0.resume'),token+' before-0\n',{mode:0o600});
  await pending;
  assert.equal(completed,true);
});

test('wrong acknowledgement bytes, permissions, directories and links fail',async()=>{
  for(const kind of ['contents','permissions','directory','link']) {
    const phase='bad-'+kind;
    const filename=join(root,phase+'.resume');
    if(kind==='directory') await mkdir(filename,{mode:0o700});
    else if(kind==='link') await symlink(join(root,'missing'),filename);
    else await writeFile(filename,kind==='contents'?'wrong':token+' '+phase+'\n',{mode:kind==='permissions'?0o644:0o600});
    await assert.rejects(checkpoint(phase),/invalid host control acknowledgement/);
  }
});

test('one real receiver runs each declared state in order and completes final restoration',async()=>{
  class Counter {constructor(start){this.value=start;this.self=this;}add(value){this.value+=value;return this;}}
  const record=captureClass(Counter,{owner:'Counter',label:'fixture.Counter',methods:['add'],statics:[]});
  const states=[{collection:true,emission:true},{collection:false,emission:true},
    {collection:true,emission:false},{collection:false,emission:false}];
  const sequence=states.map((metrics,index)=>({id:'step-'+index,action:'call',arguments:[index?index+1:7],metrics}));
  const phases=states.flatMap((_,index)=>['before-'+index,'after-'+index]).concat('finish');
  const observed=[];
  async function host() {
    for(const phase of phases) {
      await ready(phase); // NOSONAR: host transitions must follow the caller's serial schedule.
      assert.equal(await readFile(join(root,phase+'.ready'),'utf8'),token+' '+phase+'\n');
      observed.push(phase);
      await writeFile(join(root,phase+'.resume'),token+' '+phase+'\n',{mode:0o600}); // NOSONAR: release only the current phase.
    }
  }
  const output=join(root,'observation');
  process.env.OTELEQ_OBSERVATION=output;
  await Promise.all([host(),runSequence(record,{fixture:{kind:'constructor',arguments:[10]},
    method:'add',arguments:[7],asynchronous:false,sequence},()=>({arguments:[7]}),()=>true)]);
  assert.deepEqual(observed,phases);
  const result=JSON.parse(await readFile(output,'utf8'));
  assert.equal(result.steps.length,4);
  assert.ok(result.steps.every(step=>step.gaps.length===0));
});
