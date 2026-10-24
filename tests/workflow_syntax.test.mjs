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

test('Python validation installs enforce wheel and dependency hashes', () => {
  const workflow = yaml.load(readFileSync(new URL('../.github/workflows/ci.yml', import.meta.url), 'utf8'));
  const install = workflow.jobs.design.steps.find(step => step.name === 'Install pinned Python validation tools');
  assert.ok(install);
  assert.match(install.run, /--require-hashes\b/);
  assert.match(install.run, /--only-binary=:all:/);
  assert.match(install.run, /-r ci\/requirements\.txt/);
});

test('required documentation CI and the weekly job retain complete dependency audit evidence', () => {
  for (const [filename, jobName] of [['ci.yml', 'design'], ['dependency-audit.yml', 'audit']]) {
    const workflow = yaml.load(readFileSync(new URL(`../.github/workflows/${filename}`, import.meta.url), 'utf8'));
    assert.equal(workflow.permissions.contents, 'read');
    const steps = workflow.jobs[jobName].steps;
    assert.equal(steps.find(step => step.name === 'Audit locked repository dependencies').run, 'make dependency-audit PYTHON=python');
    const evidence = steps.find(step => step.name === 'Retain dependency audit evidence');
    assert.equal(evidence.if, 'always()');
    assert.match(evidence.uses, /^actions\/upload-artifact@[a-f0-9]{40}$/);
    assert.equal(evidence.with.path, 'build/dependency-audit/');
    assert.equal(evidence.with['retention-days'], 7);
    if (filename === 'dependency-audit.yml') {
      assert.equal(workflow.on.schedule[0].cron, '17 6 * * 1');
      assert.equal(workflow.jobs.audit['timeout-minutes'], 10);
    }
  }
});

test('dependency updates cover every repository lock ecosystem and GitHub Actions', () => {
  const policy = yaml.load(readFileSync(new URL('../.github/dependabot.yml', import.meta.url), 'utf8'));
  assert.equal(policy.version, 2);
  assert.deepEqual(policy.updates.map(row => [row['package-ecosystem'], row.directory]), [
    ['cargo', '/'], ['pip', '/ci'], ['npm', '/ci/markdownlint'], ['github-actions', '/'],
  ]);
  assert.ok(policy.updates.every(row => row.schedule.interval === 'weekly'));
});
