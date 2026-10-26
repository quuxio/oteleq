let state=2;
function selected_match(value){state+=value;process.stdout.write(Buffer.from([0,255,10]));process.stderr.write(Buffer.from([1,255,10]));return state+value;}
function selected_difference(value){state+=value;const active=process.execArgv.join(" ").includes("/node-bootstrap.cjs");process.stdout.write(Buffer.from([0,active?254:255,10]));process.stderr.write(Buffer.from([1,255,10]));return state+value;}
