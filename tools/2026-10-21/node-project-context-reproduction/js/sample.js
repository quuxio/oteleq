const os=require("node:os");
let state=2;
function calculate(n){state+=n;return n+state+Number(os.platform()==="darwin");}
