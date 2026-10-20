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
  JSON: NativeJSON, String: NativeString, Function: NativeFunction
}=globalThis;
const isProxy=types.isProxy;
const isError=NativeError.isError;
// Prototype changes do not remove native internal slots. Refuse these brands
// before accepting an otherwise plain or declared prototype.
const opaqueBrands=[types.isAnyArrayBuffer,types.isArrayBufferView,types.isArgumentsObject,
  types.isBoxedPrimitive,types.isDate,types.isExternal,types.isGeneratorObject,
  types.isMap,types.isMapIterator,types.isModuleNamespaceObject,types.isPromise,
  types.isRegExp,types.isSet,types.isSetIterator,types.isWeakMap,types.isWeakSet,
  types.isKeyObject,types.isCryptoKey];
const ownDescriptor=NativeObject.getOwnPropertyDescriptor;
const hasOwn=NativeObject.hasOwn;
const intrinsicSlots=[
  [NativeObject,'getOwnPropertyDescriptor'],[NativeObject,'getPrototypeOf'],[NativeObject,'isExtensible'],
  [NativeObject,'hasOwn'],[NativeObject,'entries'],[NativeObject,'fromEntries'],[NativeArray,'isArray'],[NativeError,'isError'],
  [NativeReflect,'ownKeys'],[NativeReflect,'apply'],[NativeReflect,'construct'],[NativeJSON,'stringify'],
  [NativeMap.prototype,'get'],[NativeMap.prototype,'set'],[NativeMap.prototype,'has'],
  [Buffer.prototype,'writeDoubleBE'],[Buffer.prototype,'toString'],
  [NativeArray.prototype,'push'],[NativeArray.prototype,'map'],[NativeArray.prototype,'some'],
  [NativeArray.prototype,'every'],[NativeArray.prototype,'includes'],[NativeArray.prototype,Symbol.iterator]
].map(([object,key])=>[object,key,ownDescriptor(object,key).value]);

function stableIntrinsics() {
  // Do not use the application's Array iterator before validating that slot.
  let index=0;
  while(index<intrinsicSlots.length) {
    const slot=intrinsicSlots[index++];
    const object=slot[0],key=slot[1],expected=slot[2];
    const actual=ownDescriptor(object,key);
    if(!actual||!hasOwn(actual,'value')||actual.value!==expected) throw new NativeError('changed observer intrinsic requires a fixture');
  }
  if(ownDescriptor(NativeObject.prototype,'toJSON')||ownDescriptor(NativeArray.prototype,'toJSON')) throw new NativeError('observer JSON hooks require a fixture');
}
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

function prototypeInfo(value,declared) {
  const prototype=NativeObject.getPrototypeOf(value);
  const errorType=errorPrototypes.get(prototype);
  const type=NativeArray.isArray(value)?'array':'object';
  if(opaqueBrands.some(check=>check(value))) throw new NativeError('native internal storage requires a fixture');
  if(isError(value)!==(errorType!==undefined)) throw new NativeError('native error prototype differs from its supported brand');
  if(errorType!==undefined) return {type:errorType,prototype:errorType,error:true};
  if(prototype===null) return {type,prototype:'null',error:false};
  if(prototype===NativeArray.prototype) return {type,prototype:'Array',error:false};
  if(prototype===NativeObject.prototype) return {type,prototype:'Object',error:false};
  if(declared?.has(prototype)) return {type,prototype:declared.get(prototype),error:false};
  throw new NativeError('opaque object prototype');
}

class GraphEncoder {
  seen=new NativeMap();
  nodes=[];
  constructor(declared) {this.declared=declared;}

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
    const info=prototypeInfo(value,this.declared);
    this.seen.set(value,id);
    const node={type:info.type,fields:[],prototype:info.prototype,extensible:NativeObject.isExtensible(value)};
    this.nodes.push(node);
    node.fields=this.fields(value,depth,info.error);
    return {ref:id};
  }
}

/** Capture supported own state without invoking application property accessors. */
export function __oteleqGraph(roots,declared) {
  stableIntrinsics();
  const encoder=new GraphEncoder(declared);
  const captured=NativeObject.fromEntries(NativeObject.entries(roots).map(([key,value])=>[key,encoder.value(value)]));
  return {roots:captured,nodes:encoder.nodes};
}

/** Observe one selected call; capture errors remain outside its application catch. */
export async function run(target,arguments_,roots,asynchronous,validBinding,declared) {
  if(!validBinding()) throw new NativeError('selected function binding differs from its frozen declaration');
  const before=__oteleqGraph(roots(),declared);
  let result,error,failed=false;
  try { if(asynchronous) result=await target(...arguments_); else result=target(...arguments_); }
  catch(error_) {failed=true;error=error_;}
  const outcome={kind:failed?'error':'return',value:__oteleqGraph({...roots(),[failed?'error':'result']:failed?error:result},declared)};
  const after=__oteleqGraph(roots(),declared);
  writeFileSync(process.env.OTELEQ_OBSERVATION,NativeJSON.stringify({before,outcome,after}));
}

function dataDescriptor(object,name) {
  const descriptor=ownDescriptor(object,name);
  if(!descriptor||!hasOwn(descriptor,'value')) throw new NativeError('source class binding requires an own data descriptor');
  return descriptor;
}
function sameDescriptor(left,right) {
  return left.value===right.value&&left.writable===right.writable&&left.enumerable===right.enumerable&&left.configurable===right.configurable;
}
function validateClass(record) {
  stableIntrinsics();
  if(typeof record.constructor!=='function'||isProxy(record.constructor)) throw new NativeError('receiver class requires an ordinary constructor');
  if(NativeObject.getPrototypeOf(record.constructor)!==NativeFunction.prototype) throw new NativeError('receiver class inheritance requires a fixture');
  if(dataDescriptor(record.constructor,'prototype').value!==record.prototype||isProxy(record.prototype)||NativeObject.getPrototypeOf(record.prototype)!==NativeObject.prototype) throw new NativeError('receiver prototype differs from its declared class');
  const keys=NativeReflect.ownKeys(record.prototype);
  if(keys.length!==record.members.length||NativeObject.isExtensible(record.prototype)!==record.extensible) throw new NativeError('receiver prototype shape changed');
  for(const [name,expected] of record.members) {
    const actual=dataDescriptor(record.prototype,name);
    if(!sameDescriptor(actual,expected)) throw new NativeError('receiver method binding changed');
  }
}

/** Capture source method bindings from a private first class static block. */
export function captureClass(constructor,metadata) {
  stableIntrinsics();
  if(typeof constructor!=='function'||isProxy(constructor)) throw new NativeError('receiver requires a source class');
  const prototype=dataDescriptor(constructor,'prototype').value;
  if(typeof prototype!=='object'||prototype===null||isProxy(prototype)) throw new NativeError('receiver requires a plain prototype');
  const names=['constructor',...metadata.methods];
  const members=names.map(name=>[name,dataDescriptor(prototype,name)]);
  if(members.some(([,descriptor])=>typeof descriptor.value!=='function'||isProxy(descriptor.value))) throw new NativeError('source method requires an ordinary function');
  const record={constructor,prototype,members,extensible:NativeObject.isExtensible(prototype),metadata};
  validateClass(record);
  return record;
}

function staticRoots(record) {
  return NativeObject.fromEntries(record.metadata.statics.map(name=>{
    const descriptor=ownDescriptor(record.constructor,name);
    if(!descriptor) return ['static:'+record.metadata.owner+'.'+name,{present:false}];
    if(!hasOwn(descriptor,'value')) throw new NativeError('class static accessor requires a fixture');
    return ['static:'+record.metadata.owner+'.'+name,{present:true,value:descriptor.value,writable:descriptor.writable,enumerable:descriptor.enumerable,configurable:descriptor.configurable}];
  }));
}

/** Construct a fresh receiver and observe one source-bound instance method. */
export async function runReceiver(record,call,roots,validBinding) {
  const {factory,fixture,method,arguments:arguments_,asynchronous}=call;
  validateClass(record);
  if(!validBinding()) throw new NativeError('source class or factory binding changed');
  let receiver;
  if(fixture.kind==='constructor') receiver=NativeReflect.construct(record.constructor,fixture.arguments);
  else {
    if(typeof factory!=='function'||isProxy(factory)) throw new NativeError('source factory requires an ordinary function');
    receiver=NativeReflect.apply(factory,undefined,fixture.arguments);
  }
  validateClass(record);
  if(!validBinding()) throw new NativeError('source class or factory binding changed');
  if(typeof receiver!=='object'||receiver===null||isProxy(receiver)||NativeArray.isArray(receiver)||NativeObject.getPrototypeOf(receiver)!==record.prototype) throw new NativeError('factory returned a different receiver class');
  if(ownDescriptor(receiver,method)) throw new NativeError('receiver shadows the selected source method');
  const target=dataDescriptor(record.prototype,method).value;
  const declared=new NativeMap([[record.prototype,'declared:'+record.metadata.label]]);
  const observedRoots=()=>{
    validateClass(record);
    if(!validBinding()) throw new NativeError('source class or factory binding changed');
    return {...roots(),receiver,...staticRoots(record)};
  };
  await run((...values)=>NativeReflect.apply(target,receiver,values),arguments_,observedRoots,asynchronous,validBinding,declared);
}
