// Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
import {setImmediate as nextTurn} from 'node:timers/promises';
import {prepareReceiver,writeObservation} from './node_observe.mjs';
const NativeWeakRef=globalThis.WeakRef;
const dereference=NativeWeakRef.prototype.deref;
const apply=Reflect.apply;
const collect=Object.getOwnPropertyDescriptor(globalThis,'gc')?.value;
const NativeError=Error;
const turn=nextTurn;

/** GC and WeakRef results are bounded observations, never leak or timing proofs. */
async function collection(weak,step) {
  let completed=false,rounds=0;
  for(;rounds<step.gc_rounds;rounds++) {
    // A successful dereference keeps its target alive for the current job.
    await turn();
    collect();
    await turn();
    if(apply(dereference,weak,[])===undefined) {completed=true;rounds++;break;}
  }
  for(let index=0;index<step.settle_turns;index++) await turn();
  return {completed,rounds};
}

/** Execute the exact frozen call/release schedule with independent state at each step. */
export async function runSequence(record,call,roots,validBinding) {
  const selected=call.sequence;
  const receiver=prepareReceiver(record,call,roots,validBinding);
  if(selected.some(step=>step.action==='collect')&&typeof collect!=='function') throw new NativeError('collection requires the explicitly selected --expose-gc test mode');
  const steps=[];
  let weak,lastCall;
  for(const step of selected) {
    if(step.action==='call') {
      const observed=await receiver.observe(step.arguments);
      lastCall=observed.outcome;
      steps.push({id:step.id,action:step.action,gaps:[],...observed});
      continue;
    }
    const before=receiver.snapshot();
    let value;
    const gaps=[];
    let collectionObservation;
    if(step.action==='release') weak=receiver.release(value=>new NativeWeakRef(value));
    else {
      const observed=await collection(weak,step);
      collectionObservation=observed;
      value=observed.completed;
      if(!value) gaps.push({phase:'after',path:'/collection',reason:'collection was not observed within the declared bound; no leak inference'});
    }
    const outcome=receiver.outcome(value);
    const after=receiver.snapshot();
    steps.push({id:step.id,action:step.action,gaps,before,outcome,after,...(collectionObservation?{collection:collectionObservation}:{})});
  }
  writeObservation({before:steps[0].before,outcome:lastCall,after:steps[steps.length-1].after,steps});
}
