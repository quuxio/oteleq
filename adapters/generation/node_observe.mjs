// Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
import {types} from 'node:util';
import {Buffer} from 'node:buffer';
import {writeFileSync} from 'node:fs';
import process from 'node:process';
const {
  Map: NativeMap, Object: NativeObject, Array: NativeArray, Reflect: NativeReflect,
  Error: NativeError, TypeError: NativeTypeError, RangeError: NativeRangeError,
  SyntaxError: NativeSyntaxError, ReferenceError: NativeReferenceError,
  URIError: NativeURIError, EvalError: NativeEvalError, AggregateError: NativeAggregateError,
  JSON: NativeJSON, String: NativeString
}=globalThis;
const isProxy=types.isProxy;
// Labels come from known prototype identities, never application getters.
const errorPrototypes=new NativeMap([
  [NativeError.prototype,'Error'],[NativeTypeError.prototype,'TypeError'],
  [NativeRangeError.prototype,'RangeError'],[NativeSyntaxError.prototype,'SyntaxError'],
  [NativeReferenceError.prototype,'ReferenceError'],[NativeURIError.prototype,'URIError'],
  [NativeEvalError.prototype,'EvalError'],[NativeAggregateError.prototype,'AggregateError']
]);

function primitiveValue(value) {
  if(value===null) return {type:'null'};
  const kind=typeof value;
  if(kind==='number') {
    const bytes=Buffer.alloc(8); bytes.writeDoubleBE(value);
    return {type:'float64',bits:bytes.toString('hex')};
  }
  if(kind==='undefined') return {type:kind};
  if(kind==='bigint') return {type:kind,value:NativeString(value)};
  if(kind==='boolean' || kind==='string') return {type:kind,value};
  return undefined;
}

function prototypeInfo(value) {
  const prototype=NativeObject.getPrototypeOf(value);
  const errorType=errorPrototypes.get(prototype);
  const type=NativeArray.isArray(value)?'array':'object';
  if(errorType!==undefined) return {type:errorType,prototype:errorType,error:true};
  if(prototype===null) return {type,prototype:'null',error:false};
  if(prototype===NativeArray.prototype) return {type,prototype:'Array',error:false};
  if(prototype===NativeObject.prototype) return {type,prototype:'Object',error:false};
  throw new NativeError('opaque object prototype');
}

class GraphEncoder {
  seen=new NativeMap();
  nodes=[];

  fields(value,depth,error) {
    const fields=[];
    for(const key of NativeReflect.ownKeys(value)) {
      if(error && key==='stack') continue;
      if(typeof key!=='string') throw new NativeError('symbol state requires a fixture');
      const descriptor=NativeObject.getOwnPropertyDescriptor(value,key);
      if(!NativeObject.hasOwn(descriptor,'value')) throw new NativeError('accessor state requires a fixture');
      fields.push([key,this.value(descriptor.value,depth+1),descriptor.writable,descriptor.enumerable,descriptor.configurable]);
    }
    return fields;
  }

  value(value,depth=0) {
    if(depth>32 || this.nodes.length>=512) throw new NativeError('observation graph limit');
    const primitive=primitiveValue(value);
    if(primitive!==undefined) return primitive;
    if(typeof value!=='object') throw new NativeError('opaque value: '+typeof value);
    if(isProxy(value)) throw new NativeError('proxy state requires a fixture');
    if(this.seen.has(value)) return {ref:this.seen.get(value)};
    const id=this.nodes.length;
    const info=prototypeInfo(value);
    this.seen.set(value,id);
    const node={type:info.type,fields:[],prototype:info.prototype,extensible:NativeObject.isExtensible(value)};
    this.nodes.push(node);
    node.fields=this.fields(value,depth,info.error);
    return {ref:id};
  }
}

/** Capture supported own state without invoking application property accessors. */
export function __oteleqGraph(roots) {
  const encoder=new GraphEncoder();
  const captured=NativeObject.fromEntries(NativeObject.entries(roots).map(([key,value])=>[key,encoder.value(value)]));
  return {roots:captured,nodes:encoder.nodes};
}

/** Observe one selected call; capture errors remain outside its application catch. */
export async function run(target,arguments_,roots,asynchronous,validBinding) {
  if(!validBinding()) throw new NativeError('selected function binding differs from its frozen declaration');
  const before=__oteleqGraph(roots());
  let result,error,failed=false;
  try { if(asynchronous) result=await target(...arguments_); else result=target(...arguments_); }
  catch(error_) {failed=true;error=error_;}
  const outcome={kind:failed?'error':'return',value:__oteleqGraph({...roots(),[failed?'error':'result']:failed?error:result})};
  const after=__oteleqGraph(roots());
  writeFileSync(process.env.OTELEQ_OBSERVATION,NativeJSON.stringify({before,outcome,after}));
}
