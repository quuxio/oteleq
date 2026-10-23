"""Independent build checks for the closed Java startup qualification fixture."""

from pathlib import Path

import java_project_oracle as project
import qualify_java_receivers as receivers


def check_context(folder: Path) -> int:
    """Require the fixture's empty archive context and real compiler products."""
    record = project.document(folder / 'build-identities.json')
    identity = project.document(folder / 'java-compiler-identity.json')
    metadata = project.document(folder / 'java-compiler.json')
    context = project.document(folder / 'java-build-context.json')
    application = project.document(folder / 'prepared-application.json')
    argv = identity['argv']
    assert argv[4] == '--context-v2'
    original_project, original_classes = map(Path, argv[5:7])
    original = original_project.parent
    assert original_project == original / 'project' and original_classes == original / 'scratch/classes'
    source, driver = original_project / 'Counter.java', original_project / 'OteleqDriver.java'
    assert set(context) == {'schema_version', 'profile', 'source_roots', 'source_units',
        'entries', 'archive_feature', 'archive_jdk'}
    assert type(context['schema_version']) is int and context['schema_version'] == 2
    assert context['profile'] == 'source-classpath-archives-v1'
    assert context['source_roots'] == [str(original_project)] and context['source_units'] == [str(source)]
    assert context['entries'] == [] and type(context['archive_feature']) is int and context['archive_feature'] == 21
    assert type(record['schema_version']) is int and record['schema_version'] == 1
    assert type(metadata['schema_version']) is int and metadata['schema_version'] == 2
    assert metadata['success'] is True and type(metadata['java_version']) is str and metadata['java_version'].split('.')[0] == '21'
    assert project.inventory(folder / 'project') == record['source_sha256']
    assert project.inventory(folder / 'scratch/classes') == record['classes_sha256']
    for name, key in (('java-compiler.json', 'compiler_metadata_sha256'),
            ('java-compiler-identity.json', 'compiler_identity_sha256'),
            ('prepared-application.json', 'prepared_application_sha256'),
            ('java-build-context.json', 'java_context_sha256')):
        assert project.sha(folder / name) == record[key]
    assert metadata == project.document(folder / 'build/stdout')
    assert identity['compiler_metadata_sha256'] == record['compiler_metadata_sha256']
    project.check_compiler_tooling(folder, identity, original)
    assert context['archive_jdk'] == {name: value for name, value in identity['inputs_sha256'].items()
        if name != str(original / 'compiler-tool/OteleqCompile.java')}
    assert argv[4:] == ['--context-v2', str(original_project), str(original_classes),
        '1', str(original_project), '0', str(source), str(driver)]
    assert metadata['options'] == ['-encoding', 'UTF-8', '-proc:none', '-implicit:class',
        '-sourcepath', str(original_project), '-classpath', str(original_classes), '-d', str(original_classes)]
    assert metadata['class_reads_sha256'] == {} and set(metadata['source_reads_sha256']) == {str(source), str(driver)}
    for name, value in metadata['source_reads_sha256'].items():
        assert project.sha(project.local(name, original, folder)) == value
    assert type(application['schema_version']) is int and application['schema_version'] == 1
    assert application['classpath'] == [str(original_classes)]
    assert application['main_class'] == record['main_class'] == 'OteleqDriver'
    origins = {'Counter': str(source), 'OteleqDriver': str(driver), 'OteleqGraph': str(driver)}
    assert set(application['bindings']) == set(origins)
    assert {row['class'] for row in metadata['outputs']} == set(origins)
    assert len(metadata['outputs']) == len(record['classes_sha256']) == 3
    for output in metadata['outputs']:
        name = output['class'];origin = origins[name];relative = name + '.class'
        binding = application['bindings'][name]
        assert output['origins'] == [origin] and output['output'] == str(original_classes / relative)
        assert binding['source'] == origin and binding['source_sha256'] == metadata['source_reads_sha256'][origin]
        assert binding['class_sha256'] == project.sha(folder / 'scratch/classes' / relative)
        assert binding['policy_path'] == ('Counter.java' if name == 'Counter' else '_oteleq_generated/OteleqDriver.java')
        assert binding['provenance'] == 'oteleq.jdk-file-manager-v1:' + record['compiler_identity_sha256']
    assert set(record['classes_sha256']) == {name + '.class' for name in origins}
    return 3


def verify(folder: Path, profile: str) -> dict:
    """Select the declared profile without relaxing standalone build checks."""
    if profile in ('stock-methods-v1', 'safe-methods-v1'):
        return receivers.verify_builds(folder)
    if profile != 'archive-methods-v1':
        raise ValueError('unknown Java startup build profile')
    manifests = sorted(folder.rglob('prepared-application.json'))
    assert manifests
    counts = [check_context(path.parent) for path in manifests]
    return {'retained_manifests': len(manifests),
        'unique_manifest_identities': len({project.sha(path) for path in manifests}),
        'retained_class_bindings': sum(counts)}
