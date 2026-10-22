// Inspect the actual loader result, then replace the target before evaluation.
import {createHash} from 'node:crypto';
import {existsSync, readFileSync, realpathSync} from 'node:fs';
import {registerHooks} from 'node:module';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {installCompiler} from './node_source_context.mjs';

const input = JSON.parse(readFileSync(0, 'utf8'));
const root = realpathSync(input.root);
const selected = realpathSync(input.filename);
const relative = path.relative(root, selected);
if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) throw new Error('Node context target is outside the private snapshot');
const digest = value => createHash('sha256').update(value).digest('hex');
const before = digest(readFileSync(selected));
if (before !== input.source_sha256) throw new Error('Node context source changed before inspection');
const compiler = input.source_provider ? await installCompiler(input.source_provider, root, selected) : undefined;
// Retain the nearest package bytes, including an ambient package outside the snapshot.
// Module format itself always comes from the actual loader below.
let packageFile;
for (let directory = path.dirname(selected);;) {
  const candidate = path.join(directory, 'package.json');
  if (existsSync(candidate)) {packageFile = candidate; break;}
  const parent = path.dirname(directory);
  if (parent === directory || path.basename(directory) === 'node_modules') break;
  directory = parent;
}
let packageContext = null;
if (packageFile) {
  const packagePath = realpathSync(packageFile);
  const packageRelative = path.relative(root, packagePath);
  if (packageRelative === '..' || packageRelative.startsWith('..' + path.sep) || path.isAbsolute(packageRelative)) throw new Error('Node package context escapes the private snapshot');
  packageContext = {path: packageRelative.split(path.sep).join('/'), sha256: digest(readFileSync(packagePath))};
}
let receipt;
const hook = registerHooks({load(url, context, nextLoad) {
  if (!url.startsWith('file:') || fileURLToPath(url) !== selected) return nextLoad(url, context);
  if (realpathSync(selected) !== selected || digest(readFileSync(selected)) !== before) throw new Error('Node context source changed before loading');
  const result = nextLoad(url, context);
  if (receipt || !['module', 'commonjs'].includes(result.format)) throw new Error('Node loader returned an unsupported or duplicate selected format');
  receipt = {schema_version: 1, format: result.format, loader_hint: context.format ?? null,
    source_sha256: before, package: packageContext, node_version: process.version};
  // The original source is compiled/read by the selected loader but never evaluated.
  return {...result, source: ''};
}});
try {
  await import(pathToFileURL(selected).href);
  if (!receipt || digest(readFileSync(selected)) !== before) throw new Error('Node context source changed or was not inspected');
  if (compiler) receipt.source_compiler = compiler.receipt();
  process.stdout.write(JSON.stringify(receipt));
} finally {
  hook.deregister();
  compiler?.close();
}
