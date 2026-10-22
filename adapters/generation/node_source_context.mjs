// Metadata-only compiler hook. It never starts the SDK or evaluates application code.
import {createHash} from 'node:crypto';
import {existsSync, readFileSync, realpathSync, writeFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const digest = value => createHash('sha256').update(value).digest('hex');

function readConfiguration(filename, state) {
  const requested = path.resolve(filename);
  let record, result;
  if (!existsSync(filename)) record = {requested_path: requested, kind: 'absent_config'};
  else {
    const resolved = realpathSync(filename), bytes = state.readStableFile(resolved);
    result = bytes.toString('utf8');
    record = {requested_path: requested, resolved_path: resolved, kind: 'compiler_config',
      sha256: digest(bytes), size: bytes.length};
  }
  if (state.reads.has(requested) && JSON.stringify(state.reads.get(requested)) !== JSON.stringify(record)) {
    throw new Error('compiler configuration changed during inspection');
  }
  state.reads.set(requested, record);
  return result;
}

function retainCompiler(evidence, directory) {
  const {files, ...metadata} = evidence;
  const retained = {};
  for (const [name, value] of Object.entries(files)) {
    const bytes = Buffer.from(value.text), sha256 = digest(bytes), filename = sha256 + '.txt';
    const destination = path.join(directory, filename);
    if (existsSync(destination)) {
      if (!readFileSync(destination).equals(bytes)) throw new Error('compiler inspection artifact changed');
    } else writeFileSync(destination, bytes, {flag: 'wx', mode: 0o600});
    retained[name] = {file: filename, sha256, size: bytes.length, ...(value.path ? {path: value.path} : {})};
  }
  return {...metadata, files: retained};
}

/** Use the frozen SDK compiler behind the ordinary empty-module inspector. */
export async function installCompiler(request, root, selected) {
  if (!request || Object.keys(request).sort().join(',') !== 'backend,directory,root'
      || !['native', 'api'].includes(request.backend)
      || typeof request.root !== 'string' || typeof request.directory !== 'string'
      || !path.isAbsolute(request.root) || !path.isAbsolute(request.directory)) {
    throw new Error('invalid source compiler inspection request');
  }
  const provider = realpathSync(request.root), directory = realpathSync(request.directory);
  const inside = base => directory === base || directory.startsWith(base + path.sep);
  if (inside(root) || inside(provider)) throw new Error('compiler inspection output must be outside source and provider');
  const {transpile} = await import(pathToFileURL(path.join(provider, 'adapters/node/src/compiler/typescript.mjs')).href);
  const {readStableFile} = await import(pathToFileURL(path.join(provider, 'adapters/node/src/source-file.ts')).href);
  const state = {reads: new Map(), readStableFile};
  let compiler;

  const hook = registerHooks({load(url, context, nextLoad) {
    if (!url.startsWith('file:') || fileURLToPath(url) !== selected) return nextLoad(url, context);
    if (compiler || !/\.(?:ts|mts|cts)$/.test(selected)) throw new Error('unsupported or repeated source compiler inspection');
    const source = readStableFile(selected).toString('utf8');
    // This is compiler intent, not a fabricated source4 launch plan or manifest.
    const intent = {backend: request.backend, plain: true, lifetimes: {enabled: false}};
    const output = transpile(source, selected, path.relative(root, selected).split(path.sep).join('/'),
      intent, root, context.format?.replace('-typescript', ''), filename => readConfiguration(filename, state));
    compiler = retainCompiler(output.compilation, directory);
    const emitted = output.code + '\n//# sourceMappingURL=data:application/json;base64,'
      + Buffer.from(JSON.stringify(output.map)).toString('base64');
    return {format: output.format ?? 'module', shortCircuit: true, source: emitted};
  }});
  return {
    close() { hook.deregister(); },
    receipt() {
      if (!compiler) throw new Error('source compiler was not inspected');
      const original = JSON.stringify([...state.reads.values()]);
      for (const filename of [...state.reads.keys()]) readConfiguration(filename, state);
      if (JSON.stringify([...state.reads.values()]) !== original) throw new Error('compiler configuration changed after inspection');
      return {profile: 'module-format-only-v1', compiler, configuration_reads: [...state.reads.values()]};
    }
  };
}
