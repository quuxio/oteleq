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

test('native lifetime qualification uses the reviewed SDK and explicit independent fixture jobs', () => {
  const workflow = yaml.load(readFileSync(new URL('../.github/workflows/native-lifetimes.yml', import.meta.url), 'utf8'));
  assert.equal(workflow.permissions.contents, 'read');
  for (const module of ['native_lifetime_audit', 'native_lifetime_cases', 'native_lifetime_otlp', 'native_lifetime_refusals', 'native_prepared_otlp']) {
    assert.ok(workflow.on.pull_request.paths.includes(`tests/${module}.py`));
  }
  const job = workflow.jobs['native-lifetimes'];
  assert.equal(job.strategy['fail-fast'], false);
  assert.equal(job.strategy['max-parallel'], 2);
  assert.deepEqual(job.strategy.matrix.case, ['cpp-target-error', 'c-completed', 'cpp-completed', 'c-state', 'c-zero',
    'cpp-zero', 'c-censored', 'cpp-censored', 'cpp-unwind', 'cpp-throwing-destructor']);
  assert.equal(job['runs-on'], 'ubuntu-24.04');
  const checkouts = job.steps.filter(step => step.uses?.startsWith('actions/checkout@'));
  assert.equal(checkouts.length, 2);
  assert.ok(checkouts.every(step => step.with['persist-credentials'] === false));
  assert.equal(checkouts[1].with.repository, 'quuxio/otelc');
  assert.equal(checkouts[1].with.ref, 'acb13d7735526448209df37b7e6b98e5717befdb');
  const execute = job.steps.find(step => step.name === 'Build original SDK and exercise public lifetime workflows');
  assert.match(execute.run, /tests\/qualify_native_lifetimes\.py/);
  assert.match(execute.run, /--case '\$\{\{ matrix\.case \}\}'/);
  assert.doesNotMatch(execute.run, /--coverage/);
  const retain = job.steps.find(step => step.name === 'Retain original qualification evidence and SDK build failures');
  assert.equal(retain.if, 'always()');
  assert.equal(retain.with['retention-days'], 7);
  assert.match(retain.with.name, /native-lifetimes-\$\{\{ matrix\.case \}\}/);
  const sources = job.steps.find(step => step.name === 'Retain exact source archives and source status');
  assert.match(sources.run, /cp consumer\/target\/debug\/quux-oteleq .*consumer-cli/);
  assert.ok(!Object.hasOwn(job, 'secrets'));
});

test('pip binary-only arguments require quoting in a YAML command scalar', () => {
  const command = 'python -m pip install --only-binary=:all: -r ci/requirements.txt';
  assert.throws(() => yaml.load(`run: ${command}\n`));
  assert.equal(yaml.load(`run: '${command}'\n`).run, command);
});

test('native metric workflows cover both languages and every startup state with retained evidence', () => {
  const workflow = yaml.load(readFileSync(new URL('../.github/workflows/native-metrics.yml', import.meta.url), 'utf8'));
  assert.equal(workflow.permissions.contents, 'read');
  const job = workflow.jobs['native-metrics'];
  assert.equal(job['runs-on'], 'ubuntu-24.04');
  assert.equal(job.strategy['fail-fast'], false);
  assert.equal(job.strategy['max-parallel'], 2);
  assert.deepEqual(job.strategy.matrix.language, ['c', 'cpp']);
  assert.deepEqual(job.strategy.matrix.start, ['11', '01', '10', '00']);
  const checkouts = job.steps.filter(step => step.uses?.startsWith('actions/checkout@'));
  assert.equal(checkouts.length, 2);
  assert.ok(checkouts.every(step => step.with['persist-credentials'] === false));
  assert.equal(checkouts[1].with.repository, 'quuxio/otelc');
  assert.equal(checkouts[1].with.ref, 'acb13d7735526448209df37b7e6b98e5717befdb');
  const execute = job.steps.find(step => step.name === 'Build original SDK and exercise public metric workflows');
  assert.match(execute.run, /tests\/qualify_native_metrics\.py/);
  assert.match(execute.run, /--language/);
  assert.match(execute.run, /--start/);
  assert.doesNotMatch(execute.run, /--coverage/);
  const retain = job.steps.find(step => step.name === 'Retain original qualification and SDK build failures');
  assert.equal(retain.if, 'always()');
  assert.equal(retain.with['retention-days'], 7);
  assert.match(retain.with.path, /native-metric-evidence/);
  assert.match(retain.with.path, /native-sdk-build.json/);
  assert.ok(!Object.hasOwn(job, 'secrets'));
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
