"""Generated Go callers retain the common bundle identities for each lane."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'adapters/generation'),str(Path(__file__).resolve().parents[1]/'examples')]
import generation as gen
from qualify_go_project import check_build_context


class GeneratedGoBuildTests(unittest.TestCase):
    def test_copied_shrink_evidence_retains_original_module_build_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();folder=base/'copy/case/baseline-0'
            (folder/'go-bundle').mkdir(parents=True)
            project=base/'original/case/baseline-0/project'
            for module in ('.','services/api'):
                entry={'go_context':{'module_root':module,'files':['services/api/cmd/api.go']}}
                inputs={str(project/'services/api/cmd/api.go'):'a'*64}
                (folder/'working-directory.json').write_text(json.dumps(str(project/module)))
                (folder/'go-bundle/recipe.json').write_text(json.dumps({'source_root':str(project/module)}))
                check_build_context(folder,entry,'case',inputs)
                with self.assertRaises(AssertionError):check_build_context(folder,entry,'other-case',inputs)
                with self.assertRaises(AssertionError):check_build_context(folder,entry,'case',{})
                (folder/'go-bundle/recipe.json').write_text(json.dumps({'source_root':str(folder/'project'/module)}))
                with self.assertRaises(AssertionError):check_build_context(folder,entry,'case',inputs)

    def test_each_lane_retains_the_pair_identity_and_uses_no_build_launch(self):
        for lane,expected in [('baseline','plain'),('instrumented_on','on')]:
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary)
                identity={'baseline':'a'*64,'application':'b'*64,'compiler':{'version':'qualified'}}
                def commands(*_):
                    (folder/'go-build-identities.json').write_text(json.dumps(identity))
                    return ['plain'],['on']
                execute=gen.capture.execute
                with patch.object(gen.capture,'go_commands',side_effect=commands) as build:
                    command=gen.build_command(folder,folder,{'language':'go'},folder/'app.go',folder/'policy',{}, {},folder,folder,lane)
                self.assertEqual(build.call_args.args[1],{'workspace':folder,'target':folder/'app.go','sources':[folder/'app.go'],'project':folder})
                self.assertEqual(command,[expected])
                self.assertEqual(json.loads((folder/gen.BUILD_IDENTITIES).read_text()),identity)
                self.assertIs(gen.capture.execute,execute)


if __name__=='__main__':unittest.main()
