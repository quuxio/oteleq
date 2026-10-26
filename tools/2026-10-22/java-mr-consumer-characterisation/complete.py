"""Complete the matrix after the folded-header oracle was disproved by the JDK."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

import characterise as fixture

ROOT = Path(__file__).resolve().parent
RECEIPTS = []


def step(arguments, name, role='tool'):
    env = {'PATH': os.environ['PATH'], 'HOME': str(ROOT / 'home'),
           'TMPDIR': str(ROOT / 'scratch'), 'LANG': 'C.UTF-8'}
    with subprocess.Popen(list(map(str, arguments)), env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as process:
        stdout, stderr = process.communicate(timeout=120)
        receipt = {'pid': process.pid, 'argv': list(map(str, arguments)), 'cwd': str(ROOT),
                   'exit_code': process.returncode, 'role': role}
    (ROOT / (name + '.stdout')).write_bytes(stdout)
    (ROOT / (name + '.stderr')).write_bytes(stderr)
    (ROOT / (name + '.process.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    RECEIPTS.append(receipt)
    assert receipt['exit_code'] == 0, name
    return stdout.decode()


def main():
    results = json.loads((ROOT / 'progress.json').read_text())
    assert [r['name'] for r in results] == ['inactive', 'active', 'false', 'intermediate', 'future-only', 'first-version']
    for case in results:
        runtime_view = case['compiler_recipes'][0]['derived_compiler_view']
        for lane in case['compiler_recipes']:
            lane['jarfile_recipe_view'] = lane.pop('derived_compiler_view')
            lane['runtime_jarfile_view'] = runtime_view
    identical = ROOT / 'archives/identical-bytes.jar'
    with zipfile.ZipFile(identical, 'w', compression=zipfile.ZIP_DEFLATED) as jar:
        jar.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\r\nMulti-Release: true\r\n\r\n')
        binary = (ROOT / 'compiled/8/dep/Flags.class').read_bytes()
        for prefix, value in (('', 8), ('META-INF/versions/21/', 21)):
            jar.writestr(prefix + 'dep/Flags.class', binary)
            jar.writestr(prefix + 'fixture.properties', 'value=' + str(value) + '\n')
    for name, runtime_prefix, resource in (('folded', '', 8), ('identical-bytes', 'META-INF/versions/21/', 21)):
        archive = ROOT / 'archives' / (name + '.jar')
        original = fixture.digest(archive)
        application = ROOT / 'applications' / name
        application.mkdir(exist_ok=True)
        source = application / 'App.java'
        if not source.exists():
            source.write_text(fixture.APP)
        source_hash = fixture.digest(source)
        runtime = json.loads(step([fixture.JAVA, '-cp', ROOT / 'tools/probe', 'JarProbe', archive, 21], 'v2-' + name + '-runtime-view'))
        assert runtime['members']['dep/Flags.class']['entry'] == runtime_prefix + 'dep/Flags.class'
        assert runtime['members']['fixture.properties']['entry'] == runtime_prefix + 'fixture.properties'
        assert runtime['multi_release'] is (name == 'identical-bytes')
        assert runtime['members']['dep/Flags.class']['sha256'] == fixture.digest(ROOT / 'compiled/8/dep/Flags.class')
        lanes = []
        for label in ('default', 'release8'):
            classes = application / ('v2-' + label)
            metadata = json.loads(step([fixture.JAVA, '-cp', ROOT / 'tools' / label / 'classes',
                'OteleqCompile', '--context-v2', application, classes, '1', application, '1', archive, source],
                'v2-' + name + '-' + label + '-compile'))
            compiler_member = ('META-INF/versions/21/' if label == 'default' else '') + 'dep/Flags.class'
            compiler_value = 21 if name == 'folded' and label == 'default' else 8
            byte_source = 21 if compiler_value == 21 else 8
            expected_uri = 'jar:' + archive.as_uri() + '!/' + compiler_member
            assert metadata['success'] and metadata['class_reads_sha256'] == {
                expected_uri: fixture.digest(ROOT / 'compiled' / str(byte_source) / 'dep/Flags.class')}
            output = step([fixture.JAVA, '-cp', str(classes) + os.pathsep + str(archive), 'App'],
                          'v2-' + name + '-' + label + '-application', 'application')
            assert output == str(compiler_value) + ':8:' + str(resource) + '\n'
            lanes.append({'compiler_recipe': label, 'compiler_options': metadata['options'],
                          'literal_compiler_reads': metadata['class_reads_sha256'],
                          'runtime_jarfile_view': runtime, 'stdout': output,
                          'app_class_sha256': fixture.digest(classes / 'App.class')})
        assert fixture.digest(archive) == original and fixture.digest(source) == source_hash
        results.append({'name': name, 'archive': str(archive), 'archive_sha256': original,
                        'runtime_class_value': 8, 'runtime_resource_value': resource,
                        'compiler_recipes': lanes})
    assert len(results) == 8 and len([r for r in RECEIPTS if r['role'] == 'application']) == 4
    record = {'status': 'plain-JDK characterization; no instrumented producer qualification',
              'cases': results, 'characterisation_application_jvms': 16,
              'additional_folded_calibration_application_jvms': 1,
              'folded_header_finding': {'manifest_attribute': 'true', 'JarFile_multi_release': False,
                  'default_compiler_stdout': '21:8:8\n', 'javap_feature21_constant': 21,
                  'literal_compiler_uri_is_versioned': True},
              'scope': 'Literal compiler URI/bytes and runtime JarFile entry resolution are independent. Initial folded-header assumptions were rejected; no current consumer MR support is claimed.',
              'java_sha256': fixture.digest(fixture.JAVA), 'consumer_sha256': fixture.digest(ROOT / 'tools/java_classpath.py')}
    (ROOT / 'results-v2.json').write_text(json.dumps(record, indent=2) + '\n')
    files = {p.relative_to(ROOT).as_posix(): fixture.digest(p) for p in ROOT.rglob('*') if p.is_file() and p.name not in ('seal.json', 'complete.log')}
    (ROOT / 'seal.json').write_text(json.dumps(files, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'cases': 8, 'characterisation_application_jvms': 16, 'status': record['status']}))


if __name__ == '__main__':
    main()
