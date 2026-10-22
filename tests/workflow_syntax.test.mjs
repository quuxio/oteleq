import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../ci/markdownlint/package.json', import.meta.url));
const yaml = require('js-yaml');

test('all GitHub workflow files have valid YAML syntax', () => {
  const directory = new URL('../.github/workflows/', import.meta.url);
  const names = readdirSync(directory).filter(name => /\.ya?ml$/.test(name)).sort();
  assert.ok(names.length > 0);
  for (const name of names) {
    assert.doesNotThrow(() => yaml.load(readFileSync(new URL(name, directory), 'utf8')), name);
  }
});

test('pip binary-only arguments require quoting in a YAML command scalar', () => {
  const command = 'python -m pip install --only-binary=:all: -r ci/requirements.txt';
  assert.throws(() => yaml.load(`run: ${command}\n`));
  assert.equal(yaml.load(`run: '${command}'\n`).run, command);
});
