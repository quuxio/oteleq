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
    def test_build_budget_is_frozen_for_standalone_and_package_entries(self):
        configuration = gen.project_policy.validate({"adapters": {"go": {"build_timeout_ms": 600000}}})
        for context in (None, {"module_root": ".", "shadowed_recovery": False}):
            with self.subTest(context=context):
                entry = {"path": "app.go", "name": "selected"}
                discovered = {"functions": []}
                if context is not None:
                    discovered["go_context"] = context
                gen.configure_go_context(entry, discovered, configuration)
                self.assertEqual(entry["go_build_timeout_ms"], 600000)

    def test_failed_build_retains_command_budget_and_restores_capture_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original_execute = gen.capture.execute
            def commands(*_):
                gen.capture.execute(["/selected/go", "build"], folder, {})
            with patch.object(gen.capture, "go_commands", side_effect=commands), \
                    patch.object(gen, "execute", side_effect=ValueError("process timeout")):
                with self.assertRaisesRegex(ValueError, "process timeout"):
                    gen.build_command(folder, folder, {"language": "go", "go_build_timeout_ms": 600000},
                        folder / "app.go", folder / "policy", {}, {}, folder, folder, "baseline")
            self.assertIs(gen.capture.execute, original_execute)
            receipt, = folder.glob("build-*/build-command.json")
            self.assertEqual(gen.read(receipt)["timeout_ms"], 600000)

    def test_invalid_retained_build_budget_never_starts_a_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for milliseconds in (True, 0, 900001, float("inf")):
                entry = {"language": "go", "go_build_timeout_ms": milliseconds}
                with self.subTest(milliseconds=milliseconds), patch.object(gen, "execute") as execute:
                    with self.assertRaisesRegex(ValueError, "build_timeout_ms"):
                        gen.build_command(folder, folder, entry, folder / "app.go", folder / "policy", {}, {},
                                          folder, folder, "baseline")
                    execute.assert_not_called()

    def test_declared_build_budget_is_applied_and_recorded_without_changing_launch_budget(self):
        for milliseconds in (180000, 600000):
            with self.subTest(milliseconds=milliseconds), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                entry = {"language": "go", "go_build_timeout_ms": milliseconds}
                def commands(*_):
                    gen.capture.execute(["/selected/go", "build"], folder, {})
                    gen.write(folder / "go-build-identities.json", {"application": "fixed"})
                    return ["plain"], ["on"]
                with patch.object(gen.capture, "go_commands", side_effect=commands), patch.object(gen, "execute") as execute:
                    self.assertEqual(gen.build_command(folder, folder, entry, folder / "app.go", folder / "policy",
                        {}, {}, folder, folder, "baseline"), ["plain"])
                self.assertEqual(execute.call_args.kwargs["timeout"], milliseconds / 1000)
                receipt, = folder.glob("build-*/build-command.json")
                self.assertEqual(gen.read(receipt), {"schema_version": 1, "argv": ["/selected/go", "build"],
                    "cwd": str(folder), "timeout_ms": milliseconds})
                self.assertEqual(gen.project_policy.validate({})["limits"]["case_timeout_ms"], 60000)

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
