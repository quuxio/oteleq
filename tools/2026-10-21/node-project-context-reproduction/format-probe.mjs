import {registerHooks} from 'node:module';
import {realpathSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const selected=realpathSync(process.argv[1]);
registerHooks({load(url,context,nextLoad){
 const result=nextLoad(url,context);
 if(url.startsWith('file:')&&realpathSync(fileURLToPath(url))===selected){
  process.stdout.write(JSON.stringify({format:result.format,context:context.format})+'\n');
  return {...result,source:''};
 }
 return result;
}});
