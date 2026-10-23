"""Context-v2 startup builds retain their real compiler positions and bindings."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples'), str(ROOT / 'tests')]
import generation
import java_build
import java_startup_builds as builds

JAVA = Path(os.environ.get('OTELC_JAVA') or shutil.which('java')).resolve()


class JavaStartupBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='java-startup-builds-')
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        cls.folder = cls.root / 'attempt';cls.folder.mkdir()
        project = cls.folder / 'project';project.mkdir()
        source = project / 'Counter.java';source.write_text('class Counter {int run(int n){return n;}}\n')
        driver = project / 'OteleqDriver.java'
        driver.write_text('class OteleqDriver {public static void main(String[] args){}}\nclass OteleqGraph {}\n')
        inputs = java_build.compiler_inputs(JAVA)
        del inputs[str(java_build.FRONTEND)]
        context = {'schema_version': 2, 'profile': 'source-classpath-archives-v1',
            'source_roots': [str(project)], 'source_units': [str(source)], 'entries': [],
            'archive_feature': 21, 'archive_jdk': inputs}
        (cls.folder / 'java-build-context.json').write_text(json.dumps(context))
        java_build.build(project, [source, driver], 'OteleqDriver', JAVA,
            cls.folder / 'scratch/classes', cls.folder, os.environ.copy(), generation.execute, context=context)

    def test_archive_context_uses_real_context_v2_positions_and_all_three_bindings(self):
        self.assertEqual(builds.verify(self.folder, 'archive-methods-v1'),
            {'retained_manifests': 1, 'unique_manifest_identities': 1, 'retained_class_bindings': 3})

    def copied(self):
        temporary = tempfile.TemporaryDirectory(prefix='java-startup-build-copy-')
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name).resolve() / 'attempt'
        shutil.copytree(self.folder, folder)
        return folder

    def reseal(self, folder, name, key):
        record = json.loads((folder / 'build-identities.json').read_text())
        record[key] = java_build.digest(folder / name)
        (folder / 'build-identities.json').write_text(json.dumps(record))

    def test_copied_build_uses_retained_original_positions_without_original_files(self):
        copied = self.copied();detached = self.root / 'original-detached'
        self.folder.rename(detached)
        try:
            self.assertEqual(builds.verify(copied, 'archive-methods-v1')['retained_class_bindings'], 3)
        finally:
            detached.rename(self.folder)

    def test_profile_selection_preserves_standalone_checker_and_refuses_unknown(self):
        for profile in ('stock-methods-v1', 'safe-methods-v1'):
            with patch.object(builds.receivers, 'verify_builds', return_value={'checked': True}) as verify:
                self.assertEqual(builds.verify(Path('/fixture'), profile), {'checked': True})
                verify.assert_called_once_with(Path('/fixture'))
        with self.assertRaisesRegex(ValueError, 'unknown'):
            builds.verify(Path('/fixture'), 'foreign')

    def test_rehashed_context_cannot_change_roots_sources_dependencies_or_jdk(self):
        for fault in ('schema', 'profile', 'roots', 'units', 'entries', 'feature', 'jdk', 'extra'):
            with self.subTest(fault=fault):
                folder = self.copied();path = folder / 'java-build-context.json'
                data = json.loads(path.read_text())
                if fault == 'schema':data['schema_version'] = True
                elif fault == 'profile':data['profile'] = 'source-classpath-v1'
                elif fault == 'roots':data['source_roots'] = []
                elif fault == 'units':data['source_units'].append('/foreign.java')
                elif fault == 'entries':data['entries'] = [{'path': '/foreign.jar'}]
                elif fault == 'feature':data['archive_feature'] = 22
                elif fault == 'jdk':data['archive_jdk'] = {}
                else:data['unknown'] = 'ignored'
                path.write_text(json.dumps(data));self.reseal(folder, path.name, 'java_context_sha256')
                with self.assertRaises(AssertionError):builds.verify(folder, 'archive-methods-v1')

    def test_rehashed_compiler_arguments_and_options_cannot_change_the_recipe(self):
        for fault in ('argv', 'options', 'reads', 'jdk-version', 'outputs'):
            with self.subTest(fault=fault):
                folder = self.copied();name = 'java-compiler-identity.json' if fault == 'argv' else 'java-compiler.json'
                path = folder / name;data = json.loads(path.read_text())
                if fault == 'argv':data['argv'][9] = '1'
                elif fault == 'options':data['options'].append('-g')
                elif fault == 'reads':data['class_reads_sha256'] = {'file:/foreign.class': '0' * 64}
                elif fault == 'jdk-version':data['java_version'] = '22.0.1'
                else:data['outputs'][0]['origins'] = ['/foreign.java']
                path.write_text(json.dumps(data))
                if fault != 'argv':
                    (folder / 'build/stdout').write_text(json.dumps(data))
                    identity = json.loads((folder / 'java-compiler-identity.json').read_text())
                    identity['compiler_metadata_sha256'] = java_build.digest(path)
                    (folder / 'java-compiler-identity.json').write_text(json.dumps(identity))
                    self.reseal(folder, path.name, 'compiler_metadata_sha256')
                self.reseal(folder, 'java-compiler-identity.json', 'compiler_identity_sha256')
                with self.assertRaises(AssertionError):builds.verify(folder, 'archive-methods-v1')

    def test_rehashed_manifest_cannot_change_classpath_binding_origin_or_provenance(self):
        for fault in ('classpath', 'origin', 'provenance', 'class', 'source', 'main'):
            with self.subTest(fault=fault):
                folder = self.copied();path = folder / 'prepared-application.json';data = json.loads(path.read_text())
                if fault == 'classpath':data['classpath'].append('/foreign.jar')
                elif fault == 'main':data['main_class'] = 'Counter'
                else:
                    binding = data['bindings']['Counter']
                    field = {'origin': 'source', 'provenance': 'provenance', 'class': 'class_sha256', 'source': 'source_sha256'}[fault]
                    binding[field] = '/foreign.java' if fault == 'origin' else '0' * 64
                path.write_text(json.dumps(data));self.reseal(folder, path.name, 'prepared_application_sha256')
                with self.assertRaises(AssertionError):builds.verify(folder, 'archive-methods-v1')

    def test_changed_source_product_and_compiler_frontend_cannot_pass(self):
        for relative in ('project/Counter.java', 'scratch/classes/Counter.class', 'compiler-tool/OteleqCompile.java'):
            with self.subTest(path=relative):
                folder = self.copied();path = folder / relative;path.write_bytes(path.read_bytes() + b'changed')
                with self.assertRaises(AssertionError):builds.verify(folder, 'archive-methods-v1')


if __name__ == '__main__':
    unittest.main()
