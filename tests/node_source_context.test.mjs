// Component fixtures exercise our hook contract; they are not an SDK qualification.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import test from 'node:test';
import {installCompiler} from '../adapters/generation/node_source_context.mjs';

const SOURCE = 'throw Error("APPLICATION_INITIALISER_MUST_NOT_RUN");\n';
const digest = value => createHash('sha256').update(value).digest('hex');

function fixture(t, suffix = '.mts') {
  const base = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'oteleq-compiler-context-')));
  t.after(() => rmSync(base, {recursive: true, force: true}));
  const root = path.join(base, 'application'), provider = path.join(base, 'provider'), directory = path.join(base, 'evidence');
  for (const folder of [root, directory, path.join(provider, 'adapters/node/src/compiler')]) mkdirSync(folder, {recursive: true});
  writeFileSync(path.join(provider, 'package.json'), '{"type":"module"}');
  writeFileSync(path.join(root, 'tsconfig.json'), '{"compilerOptions":{"target":"ES2022"}}');
  writeFileSync(path.join(provider, 'adapters/node/src/source-file.ts'),
    'import {readFileSync} from "node:fs";export const readStableFile = filename => readFileSync(filename);');
  writeFileSync(path.join(provider, 'adapters/node/src/compiler/typescript.mjs'), `
import path from 'node:path';
import {fileURLToPath} from 'node:url';
export function transpile(source, filename, logical, intent, root, hint, read) {
  read(path.join(root, 'tsconfig.json'));read(path.join(root, 'tsconfig.json'));read(path.join(root, 'missing.json'));
  const files = {input:{text:source,path:filename},options:{text:JSON.stringify(intent)},output:{text:source},map:{text:'{}'}};
  if (intent.backend === 'native') files.preparation_map = {text:'{}'};
  const compiler = fileURLToPath(import.meta.url);
  return {code:source,map:{version:3,sources:[logical],mappings:''},format:hint,
    compilation:{backend:intent.backend,version:intent.backend==='native'?'7.0.2':'6.0.3',compiler_path:compiler,
    cwd:root,transformer_profile:'none',...(intent.backend==='native'?{argv:[compiler,'--project',filename+'.config']}:{method:'transpileModule'}),files}};
}
`);
  const selected = path.join(root, 'app' + suffix);
  writeFileSync(selected, SOURCE);
  return {root, provider, directory, selected};
}

async function inspect(value, backend = 'native') {
  const compiler = await installCompiler({backend, root: value.provider, directory: value.directory}, value.root, value.selected);
  const empty = registerHooks({load(url, context, nextLoad) {
    const result = nextLoad(url, context);
    return url.startsWith('file:') && fileURLToPath(url) === value.selected ? {...result, source: ''} : result;
  }});
  try { await import(pathToFileURL(value.selected).href); }
  catch (error) { compiler.close(); throw error; }
  finally { empty.deregister(); }
  return compiler;
}

test('both compiler contracts retain raw files and inspect without evaluating the application', async t => {
  for (const backend of ['native', 'api']) {
    const value = fixture(t);
    const compiler = await inspect(value, backend);
    try {
      const receipt = compiler.receipt();
      assert.equal(receipt.profile, 'module-format-only-v1');
      assert.equal(receipt.compiler.transformer_profile, 'none');
      assert.equal(receipt.compiler.files.input.sha256, digest(SOURCE));
      assert.equal(readFileSync(path.join(value.directory, receipt.compiler.files.input.file), 'utf8'), SOURCE);
      assert.equal(receipt.configuration_reads.length, 2);
      assert.equal(receipt.configuration_reads[1].kind, 'absent_config');
      const intent = JSON.parse(readFileSync(path.join(value.directory, receipt.compiler.files.options.file)));
      assert.deepEqual(intent, {backend, plain: true, lifetimes: {enabled: false}});
      assert.equal(existsSync(path.join(value.directory, 'node-launch.json')), false);
    } finally { compiler.close(); }
  }
});

test('unknown controls and evidence inside the source or provider refuse', async t => {
  const value = fixture(t);
  const valid = {backend: 'native', root: value.provider, directory: value.directory};
  for (const request of [null, {...valid, extra: true}, {...valid, backend: 'unknown'}, {...valid, root: 0},
    {...valid, root: 'relative'}, {...valid, directory: value.root}, {...valid, directory: value.provider}]) {
    await assert.rejects(installCompiler(request, value.root, value.selected));
  }
});

test('an uninspected or repeated compiler operation cannot produce a valid receipt', async t => {
  const value = fixture(t);
  const request = {backend: 'native', root: value.provider, directory: value.directory};
  const unused = await installCompiler(request, value.root, value.selected);
  try { assert.throws(() => unused.receipt(), /not inspected/); }
  finally { unused.close(); }
  const compiler = await inspect(value);
  try { await assert.rejects(import(pathToFileURL(value.selected).href + '?second'), /repeated/); }
  finally { compiler.close(); }
  const unsupported = fixture(t, '.js');
  await assert.rejects(inspect(unsupported), /unsupported/);
});

test('changed configuration, newly present config and changed retained bytes refuse', async t => {
  const changed = fixture(t);
  const compiler = await inspect(changed);
  try {
    writeFileSync(path.join(changed.root, 'tsconfig.json'), '{}');
    assert.throws(() => compiler.receipt(), /configuration changed/);
  } finally { compiler.close(); }
  const appeared = fixture(t);
  const absent = await inspect(appeared);
  try {
    writeFileSync(path.join(appeared.root, 'missing.json'), '{}');
    assert.throws(() => absent.receipt(), /configuration changed/);
  } finally { absent.close(); }
  const artifact = fixture(t);
  writeFileSync(path.join(artifact.directory, digest(SOURCE) + '.txt'), 'changed evidence');
  await assert.rejects(inspect(artifact), /artifact changed/);
});
