// Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
import {types} from 'node:util';
import {Buffer} from 'node:buffer';
import {writeFileSync} from 'node:fs';
import process from 'node:process';
const {Map,Object,Array,Reflect,Error,TypeError,RangeError,SyntaxError,ReferenceError,URIError,EvalError,AggregateError,JSON}=globalThis;
const __oteleqIsProxy=types.isProxy;
// Labels come from known prototype identities, never application getters.
const __oteleqErrorPrototypes=new Map([
  [Error.prototype,'Error'],[TypeError.prototype,'TypeError'],
  [RangeError.prototype,'RangeError'],[SyntaxError.prototype,'SyntaxError'],
  [ReferenceError.prototype,'ReferenceError'],[URIError.prototype,'URIError'],
  [EvalError.prototype,'EvalError'],[AggregateError.prototype,'AggregateError']
]);
/** Capture supported own state without invoking application property accessors. */
function __oteleqGraph(roots) {
  const seen = new Map(), nodes = [];
  function value(v, depth=0) {
    if(depth>32 || nodes.length>=512) throw new Error('observation graph limit');
    if(v===null) return {type:'null'};
    if(typeof v==='number') { const b=Buffer.alloc(8); b.writeDoubleBE(v); return {type:'float64',bits:b.toString('hex')}; }
    if(['boolean','string','undefined','bigint'].includes(typeof v)) return {type:typeof v,value:typeof v==='bigint'?v.toString():v};
    if(typeof v!=='object') throw new Error('opaque value: '+typeof v);
    if(__oteleqIsProxy(v)) throw new Error('proxy state requires a fixture');
    if(seen.has(v)) return {ref:seen.get(v)};
    const id=nodes.length; seen.set(v,id);
    const prototype=Object.getPrototypeOf(v);
    const errorType=__oteleqErrorPrototypes.get(prototype);
    const isError=errorType!==undefined;
    if(![Object.prototype,Array.prototype,null].includes(prototype) && !isError) throw new Error('opaque object prototype');
    const n={type:isError?errorType:Array.isArray(v)?'array':'object',fields:[],prototype:prototype===null?'null':prototype===Array.prototype?'Array':isError?errorType:'Object',extensible:Object.isExtensible(v)}; nodes.push(n);
    for(const key of Reflect.ownKeys(v)) {
      if(isError && key==='stack') continue;
      if(typeof key!=='string') throw new Error('symbol state requires a fixture');
      const d=Object.getOwnPropertyDescriptor(v,key);
      if(!Object.hasOwn(d,'value')) throw new Error('accessor state requires a fixture');
      n.fields.push([key,value(d.value,depth+1),d.writable,d.enumerable,d.configurable]);
    }
    return {ref:id};
  }
  return {roots:Object.fromEntries(Object.keys(roots).sort().map(k=>[k,value(roots[k])])),nodes};
}

export {__oteleqGraph};
/** Observe one selected call; capture errors remain outside its application catch. */
export async function run(target,arguments_,roots,asynchronous,validBinding) {
  if(!validBinding()) throw new Error('selected function binding differs from its frozen declaration');
  const before=__oteleqGraph(roots());
  let result,error,failed=false;
  try { if(asynchronous) result=await target(...arguments_); else result=target(...arguments_); }
  catch(caught) {failed=true;error=caught;}
  const outcome={kind:failed?'error':'return',value:__oteleqGraph({...roots(),[failed?'error':'result']:failed?error:result})};
  const after=__oteleqGraph(roots());
  writeFileSync(process.env.OTELEQ_OBSERVATION,JSON.stringify({before,outcome,after}));
}
