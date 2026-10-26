;const __oteleqSelected=calculate;
const __oteleqObserver=await import("./_oteleq_generated/node_observe.mjs");
const os=require("node:os");
let state=2;
function calculate(n){state+=n;return n+state+Number(os.platform()==="darwin");}

const __oteleqArguments=[7];
const __oteleqRoots=()=>({"global:state":state,arguments:__oteleqArguments});
await __oteleqObserver.run(__oteleqSelected,__oteleqArguments,__oteleqRoots,false,()=>typeof __oteleqSelected==='function' && calculate===__oteleqSelected);
