"""Plain-JDK fixture preparation; this does not qualify an otelc producer."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
JAVA = Path('/opt/homebrew/opt/openjdk@21/bin/java').resolve()
JAVAC = JAVA.with_name('javac')
SOURCE_REPO = Path('/Users/sclarke/github/oteleq')
CASES = (
    ('inactive', None, (9, 17, 21, 22), 8, 8, None),
    ('active', 'true', (9, 17, 21, 22), 21, 21, 21),
    ('false', 'false', (9, 17, 21), 8, 8, None),
    ('intermediate', 'true', (9, 17, 22), 17, 17, 17),
    ('future-only', 'true', (22,), 8, 8, None),
    ('first-version', 'true', (9,), 9, 9, 9),
    ('folded', 'folded', (21,), 21, 21, 21),
    ('identical-bytes', 'true', (21,), 8, 21, 21),
)
APP = '''import dep.Flags;
public class App {
 public static void main(String[] args)throws Exception {
  var properties=new java.util.Properties();
  try(var input=App.class.getResourceAsStream("/fixture.properties")){properties.load(input);}
  System.out.println(Flags.INLINE+":"+Flags.value()+":"+properties.getProperty("value"));
 }
}
'''.replace('var properties', 'java.util.Properties properties').replace('var input', 'java.io.InputStream input')
PROBE = r'''import java.io.File;
import java.util.jar.JarFile;
import java.util.zip.ZipFile;
import java.security.MessageDigest;
import java.util.HexFormat;
public class JarProbe {
 static String quote(String value){return "\""+value.replace("\\","\\\\").replace("\"","\\\"")+"\"";}
 public static void main(String[] args)throws Exception {
  int maximum=Integer.parseInt(args[1]);
  try(var jar=new JarFile(new File(args[0]),false,ZipFile.OPEN_READ,Runtime.Version.parse(args[1]))){
   var rows=new java.util.ArrayList<String>();
   for(String name:new String[]{"dep/Flags.class","fixture.properties"}){
    var entry=jar.getJarEntry(name);
    try(var input=jar.getInputStream(entry)){
     String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input.readAllBytes()));
     rows.add(quote(name)+":{\"entry\":"+quote(entry.getRealName())+",\"sha256\":"+quote(hash)+"}");
    }
   }
   System.out.print("{\"jdk_feature\":"+Runtime.version().feature()+",\"maximum\":"+maximum
    +",\"jar_version\":"+jar.getVersion().feature()+",\"multi_release\":"+jar.isMultiRelease()
    +",\"members\":{"+String.join(",",rows)+"}}");
  }
 }
}
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, name):
    environment = {'PATH': os.environ['PATH'], 'HOME': str(ROOT / 'home'),
                   'TMPDIR': str(ROOT / 'scratch'), 'LANG': 'C.UTF-8'}
    result = subprocess.run(list(map(str, args)), env=environment, capture_output=True, check=False, timeout=120)
    (ROOT / (name + '.stdout')).write_bytes(result.stdout)
    (ROOT / (name + '.stderr')).write_bytes(result.stderr)
    assert result.returncode == 0, (name, result.returncode)
    return result.stdout.decode()


def main():
    for name in ('home', 'scratch', 'compiled', 'sources', 'archives', 'tools', 'applications'):
        (ROOT / name).mkdir()
    versions = {}
    for value in (8, 9, 17, 21, 22):
        folder = ROOT / 'sources' / str(value)
        folder.mkdir()
        source = folder / 'Flags.java'
        source.write_text('package dep;public final class Flags {public static final int INLINE='
                          + str(value) + ';public static int value(){return ' + str(value) + ';}}\n')
        classes = ROOT / 'compiled' / str(value)
        command([JAVAC, '--release', str(min(value, 21)), '-d', classes, source], 'dependency-' + str(value))
        versions[value] = classes / 'dep/Flags.class'
    frontend = (SOURCE_REPO / 'adapters/generation/OteleqCompile.java').read_text()
    original = 'List.of("-encoding", "UTF-8", "-proc:none", "-implicit:class")'
    assert frontend.count(original) == 1
    tools = {}
    for label in ('default', 'release8'):
        folder = ROOT / 'tools' / label
        folder.mkdir()
        source = folder / 'OteleqCompile.java'
        source.write_text(frontend if label == 'default' else frontend.replace(original,
            'List.of("-encoding", "UTF-8", "-proc:none", "-implicit:class", "--release", "8")'))
        classes = folder / 'classes'
        command([JAVAC, '-d', classes, source], 'frontend-' + label)
        tools[label] = classes
    probe_source = ROOT / 'tools/JarProbe.java'
    probe_source.write_text(PROBE)
    command([JAVAC, '-d', ROOT / 'tools/probe', probe_source], 'probe-build')
    consumer = ROOT / 'tools/java_classpath.py'
    shutil.copyfile(SOURCE_REPO / 'adapters/generation/java_classpath.py', consumer)
    sys.path.insert(0, str(consumer.parent))
    import java_classpath
    results = []
    for name, flag, selected, runtime_value, resource_value, member_version in CASES:
        archive = ROOT / 'archives' / (name + '.jar')
        manifest = 'Manifest-Version: 1.0\r\n'
        if flag is not None:
            manifest += 'Multi-Release: tr\r\n ue\r\n' if flag == 'folded' else 'Multi-Release: ' + flag + '\r\n'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as jar:
            jar.writestr('META-INF/MANIFEST.MF', manifest + '\r\n')
            jar.writestr('dep/Flags.class', versions[8].read_bytes())
            jar.writestr('fixture.properties', 'value=8\n')
            for version in selected:
                prefix = 'META-INF/versions/' + str(version) + '/'
                byte_source = 8 if name == 'identical-bytes' else version
                jar.writestr(prefix + 'dep/Flags.class', versions[byte_source].read_bytes())
                jar.writestr(prefix + 'fixture.properties', 'value=' + str(version) + '\n')
        before = digest(archive)
        try:
            java_classpath.inspect(archive)
        except ValueError as error:
            assert 'multi-release JARs require a qualified producer profile' in str(error)
            refusal = str(error)
        else:
            raise AssertionError('current consumer unexpectedly accepted an unqualified archive')
        application = ROOT / 'applications' / name
        application.mkdir()
        source = application / 'App.java'
        source.write_text(APP)
        source_hash = digest(source)
        lanes = []
        for label, maximum in (('default', 21), ('release8', 8)):
            classes = application / label
            metadata = json.loads(command([JAVA, '-cp', tools[label], 'OteleqCompile', '--context-v2',
                application, classes, '1', application, '1', archive, source], name + '-' + label + '-compile'))
            assert metadata['success'] and metadata['schema_version'] == 2
            view = json.loads(command([JAVA, '-cp', ROOT / 'tools/probe', 'JarProbe', archive, maximum],
                                      name + '-' + label + '-view'))
            assert view['jdk_feature'] == 21 and view['maximum'] == maximum
            version = member_version if maximum == 21 else None
            prefix = 'META-INF/versions/' + str(version) + '/' if version else ''
            assert view['members']['dep/Flags.class']['entry'] == prefix + 'dep/Flags.class'
            assert view['members']['fixture.properties']['entry'] == prefix + 'fixture.properties'
            expected_hash = digest(versions[8 if name == 'identical-bytes' else runtime_value if maximum == 21 else 8])
            assert view['members']['dep/Flags.class']['sha256'] == expected_hash
            reads = metadata['class_reads_sha256']
            assert len(reads) == 1 and set(reads.values()) == {expected_hash}
            actual = command([JAVA, '-cp', str(classes) + os.pathsep + str(archive), 'App'], name + '-' + label + '-application')
            inline = runtime_value if maximum == 21 else 8
            assert actual == str(inline) + ':' + str(runtime_value) + ':' + str(resource_value) + '\n'
            lanes.append({'compiler_recipe': label, 'compiler_options': metadata['options'],
                'literal_compiler_reads': reads, 'derived_compiler_view': view,
                'stdout': actual, 'app_class_sha256': digest(classes / 'App.class')})
        assert digest(archive) == before and digest(source) == source_hash
        results.append({'name': name, 'archive': str(archive), 'archive_sha256': before,
                        'runtime_class_value': runtime_value, 'runtime_resource_value': resource_value,
                        'consumer_refusal': refusal, 'compiler_recipes': lanes})
        (ROOT / 'progress.json').write_text(json.dumps(results, indent=2) + '\n')
    record = {'status': 'plain-JDK characterization; no instrumented producer qualification',
              'source_consumer_commit': subprocess.check_output(['git', '-C', SOURCE_REPO, 'rev-parse', 'HEAD'], text=True).strip(),
              'consumer_sha256': digest(consumer), 'jdk': str(JAVA), 'java_sha256': digest(JAVA),
              'probe_sha256': digest(probe_source), 'cases': results, 'application_jvms': len(results) * 2,
              'derivation_limit': 'Compiler entry identity is derived from the selected-JDK view at the recorded recipe; literal compiler URI and byte digest remain separate. Equal bytes alone do not establish a member.',
              'references': ['https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/jar/JarFile.html',
                             'https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/jar/JarEntry.html']}
    (ROOT / 'results.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'cases': len(results), 'application_jvms': record['application_jvms'], 'status': record['status']}))


if __name__ == '__main__':
    main()
