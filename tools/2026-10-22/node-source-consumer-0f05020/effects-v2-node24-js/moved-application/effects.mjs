import fs from "node:fs";
let state=3;
async function perform(bad){
 const root=process.env.APP_DATA_DIR;
 const body=Buffer.from(bad?"bad":"good");
 fs.writeFileSync(root+"/out.bin",Buffer.concat([fs.readFileSync(root+"/seed.bin"),body]),{mode:0o600});
 const response=await fetch(process.env.APP_SERVICE_URL+"/effect",{method:"POST",body});
 const received=new Uint8Array(await response.arrayBuffer());
 if(response.status!==201||received.length!==2||received[0]!==0||received[1]!==255)throw new Error("response differs");
}
async function selected_match(value){await perform(false);state+=value;return state+value;}
async function selected_difference(value){await perform(value>0&&process.execArgv.join(" ").includes("/node-bootstrap.cjs"));state+=value;return state+value;}
async function selected_added(value){await perform(false);state+=value;return state+value;}
