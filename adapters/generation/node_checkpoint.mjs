// Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
import {lstat,open,readFile,rename} from 'node:fs/promises';
import {setTimeout as pause} from 'node:timers/promises';

const root=process.env.OTELEQ_NODE_CONTROL_ROOT;
const token=process.env.OTELEQ_NODE_CONTROL_TOKEN;

/** Yield the event loop so the source SDK's authenticated endpoint can respond. */
export async function checkpoint(phase) {
  const message=token+' '+phase+'\n';
  const temporary=root+'/'+phase+'.tmp';
  const file=await open(temporary,'wx',0o600);
  try {await file.writeFile(message);} finally {await file.close();}
  await rename(temporary,root+'/'+phase+'.ready');
  const resume=root+'/'+phase+'.resume';
  for(;;) {
    try {
      const metadata=await lstat(resume);
      if(!metadata.isFile()||metadata.isSymbolicLink()||(metadata.mode&0o777)!==0o600
          ||await readFile(resume,'utf8')!==message) throw new Error('invalid host control acknowledgement');
      return;
    } catch(error) {
      if(error?.code!=='ENOENT') throw error;
    }
    await pause(1); // NOSONAR: the host releases each checkpoint after its actual SDK operation.
  }
}
