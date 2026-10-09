"""Contract and failure regressions for the external generation workflow."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import discovery
import generation as gen
import harness
import observe


def args(command, **kwargs):
    return argparse.Namespace(command=command, **kwargs)


class DiscoveryTests(unittest.TestCase):
    def test_python_retains_all_callable_kinds_and_state_roots(self):
        source = '''a = b = []
x: int = 1
y,z = (1,2)
def plain(x: int, /, y: bool)->float:return 1.0
@decorator
def decorated(*args, **kwargs):pass
def outer():
    def inner():pass
    return lambda: 1
class Example:
    def method(self):pass
async def asynchronous():pass
def yielded():yield 1
def kwonly(*, x:int):pass
'''
        data = discovery.python_inventory(source)
        entries = {e["name"]: e for e in data["functions"]}
        self.assertEqual(entries["plain"]["parameters"], ["int", "bool"])
        self.assertEqual(entries["plain"]["output"], "float")
        self.assertEqual(entries["plain"]["reason"], "")
        for name in ("decorated", "outer.inner", "outer.<lambda>", "Example.method", "asynchronous", "yielded", "kwonly"):
            self.assertTrue(entries[name]["reason"], name)
        self.assertEqual([g["name"] for g in data["globals"]], ["a", "b", "x", "<destructured>"])
        with self.assertRaises(SyntaxError):
            discovery.python_inventory("def bad(")
        conditional=discovery.python_inventory("if True:\n state=0\nfor index in []:\n conditional=1\ndef outer():\n def generated():yield 1\n return 1\n")
        self.assertEqual({g["name"] for g in conditional["globals"]},{"state","index","conditional"})
        self.assertEqual(next(e for e in conditional["functions"] if e["name"]=="outer")["reason"],"")

    def test_native_inventory_filters_headers_and_retains_methods_and_templates(self):
        path = Path("/tmp/test.cpp")
        def function(name, kind="FunctionDecl", **extras):
            return {"kind": kind, "name": name, "loc": {"offset": 1, "line": 2},
                    "type": {"qualType": "int (int)"}, "inner": [{"kind": "ParmVarDecl", "type": {"qualType": "int"}}, {"kind": "CompoundStmt"}], **extras}
        data = {"kind": "TranslationUnitDecl", "inner": [function("good"), function("variadic", variadic=True),
                function("external", inner=[]), function("header", loc={"offset": 1, "file": "/elsewhere/header.h"}),
                function("included", loc={"offset": 1, "includedFrom": {"file": "header.h"}}),
                {"kind": "NamespaceDecl", "name": "N", "inner": [function("nested")]},
                {"kind": "CXXRecordDecl", "name": "Class", "inner": [function("method", "CXXMethodDecl")]},
                {"kind": "FunctionTemplateDecl", "inner": [function("generic")]},
                {"kind": "VarDecl", "name": "global", "loc": {"offset": 5}, "type": {"qualType": "int"}}]}
        result = discovery.native_inventory(data, path)
        entries = {e["name"]: e for e in result["functions"]}
        self.assertEqual(entries["good"]["reason"], "")
        self.assertEqual(entries["N::nested"]["parameters"], ["int"])
        for name in ("variadic", "external", "Class::method", "generic"):
            self.assertTrue(entries[name]["reason"])
        self.assertNotIn("header", entries)
        self.assertNotIn("included", entries)
        self.assertEqual(result["globals"][0]["name"], "global")

    def test_every_compiler_route_uses_argument_vectors_and_propagates_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "target.py"
            source.write_text("def sample():return 1")
            base = {"functions": [], "globals": []}
            calls = []
            def execute(command, cwd, input_data=None):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, json.dumps(base).encode(), b"")
            with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": "/chosen/cli"}):
                for language in set(discovery.LANGUAGES.values()):
                    tools = {language: Path("/selected/tool"), "clang": Path("/selected/clang"), "clang++": Path("/selected/clang++")}
                    discovery.discover(source, language, Path(folder), tools, execute)
                self.assertEqual(len(calls), 7)
                self.assertEqual(calls[0][0] if calls[0][1] == "inventory-rust" else "/chosen/cli", "/chosen/cli")
                with self.assertRaisesRegex(ValueError, "inventory tool failed"):
                    discovery.discover(source, "go", Path(folder), {"go": Path("/go")}, lambda c,w: subprocess.CompletedProcess(c,1,b"",b"bad compiler"))


class GraphTests(unittest.TestCase):
    def test_bits_large_integers_cycles_aliases_and_object_fields(self):
        class Example:
            pass
        item = Example()
        shared = [None, True, 2**100, -0.0, "text", b"bytes"]
        item.values = shared
        shared.append(item)
        first = observe.graph({"a": item, "b": shared, "alias": shared})
        self.assertEqual(first["roots"]["alias"], first["roots"]["b"])
        self.assertIn("8000000000000000", json.dumps(first))
        self.assertIn(str(2**100), json.dumps(first))
        item.new = 1
        self.assertNotEqual(first, observe.graph({"a": item, "b": shared, "alias": shared}))
        for value in ({1,2}, object(), lambda: 1):
            with self.assertRaises((ValueError, AttributeError)):
                observe.graph({"opaque": value})
        error=ValueError("original")
        error.extra=shared
        error.__cause__=error
        captured=observe.graph({"error":error,"unbound":observe.MISSING,"tuple":(1,2)})
        self.assertEqual(captured["roots"]["unbound"],{"type":"unbound"})
        error.extra=[]
        self.assertNotEqual(captured,observe.graph({"error":error,"unbound":observe.MISSING,"tuple":(1,2)}))
        deep = []
        for _ in range(40):deep = [deep]
        with self.assertRaisesRegex(ValueError, "limit"):
            observe.graph({"deep": deep})


class HarnessTests(unittest.TestCase):
    def entry(self, language, **kw):
        return {"language": language, "name": "sample", "parameters": ["int"], "output": "int", "path": "source.py", "globals": [], "file_functions": [], "package": "", "package_end": 12, **kw}

    def test_corpus_is_frozen_bounded_typed_and_does_not_guess_opaque_values(self):
        for type_ in harness.INTEGERS | harness.FLOATS | harness.BOOLS:
            self.assertIsNotNone(harness.values(type_, "python"), type_)
        for type_ in harness.STRINGS:
            self.assertEqual(harness.values(type_, "java")[0], "")
        self.assertIsNone(harness.values("Database", "python"))
        self.assertEqual(harness.corpus(self.entry("python"),3), [[0],[1],[-1]])
        self.assertEqual(harness.corpus(self.entry("python"),16), [[0],[1],[-1]])
        self.assertEqual(harness.corpus(self.entry("python",parameters=["bool"]),3), [[False],[True]])
        self.assertEqual(harness.corpus(self.entry("python",parameters=[]),3), [[]])
        opaque_entry=self.entry("python",parameters=["Database"])
        with self.assertRaisesRegex(ValueError,"fixture"):
            harness.corpus(opaque_entry,3)
        self.assertEqual(harness.literal(True,"bool","rust"),"true")
        self.assertEqual(harness.literal(1,"f32","rust"),"1.0f32")
        self.assertEqual(harness.literal(1,"int","go"),"int(1)")
        self.assertEqual(harness.literal(1,"byte","java"),"(byte)1")
        self.assertEqual(harness.literal(True,"bool","c"),"1")
        self.assertEqual(harness.literal("s","String","java"),'"s"')
        self.assertEqual(harness.values("unknown","javascript")[0],0)

    def test_all_eight_materialise_separate_harnesses_and_visible_state_gaps(self):
        suffixes = {"c":".c","cpp":".cpp","python":".py","rust":".rs","go":".go","java":".java","javascript":".mjs","typescript":".mts"}
        for language,suffix in suffixes.items():
            with tempfile.TemporaryDirectory() as temporary:
                project=Path(temporary)
                entry=self.entry(language,path="source"+suffix,parameters=["i32"] if language=="rust" else ["int"],output="i32" if language=="rust" else "int",
                                 globals=[{"name":"state","type":"int"}], async_=True)
                source=project/entry["path"]
                source.write_text("package main\n" if language=="go" else "// original\n" if language!="python" else "# original\n")
                driver=harness.materialise(project,entry,[0])
                self.assertTrue(driver.is_file())
                self.assertIn("OTELEQ_OBSERVATION",driver.read_text())
                if language in ("c","cpp","java","python"):
                    self.assertTrue(source.read_text().endswith("original\n") or language=="java")
                entry["globals"]=[{"name":"opaque","type":"Database"}]
                if language not in ("python","javascript","typescript"):
                    self.assertEqual(harness.global_gaps(entry),["opaque"])
                entry["globals"]=[{"name":"<destructured>","type":"unknown"}]
                self.assertEqual(harness.global_gaps(entry),["<destructured>"])
        self.assertIn("await sample",harness.js_driver(self.entry("javascript",**{"async":True}),[],""))
        self.assertIn("return:void",harness.native_driver(self.entry("c",output="void"),[]))
        self.assertIn("return:void",harness.go_driver(self.entry("go",output="void"),[],"package main\n"))
        self.assertIn("return:void",harness.java_driver(self.entry("java",output="void",package="example"),[]))
        self.assertIn("to_bits",harness.rust_driver(self.entry("rust",output="f64"),[],""))
        self.assertIn("to_bits",harness.rust_driver(self.entry("rust",globals=[{"name":"S","type":"f64"}]),[],""))
        with tempfile.TemporaryDirectory() as temporary:
            project=Path(temporary);(project/"source.java").write_text("class Source {}")
            (project/"OteleqDriver.java").write_text("user file")
            java_entry=self.entry("java",path="source.java")
            with self.assertRaisesRegex(ValueError,"overwrite"):
                harness.materialise(project,java_entry,[])

    def test_main_renaming_is_checked_against_ast_ranges(self):
        self.assertEqual(harness.rename_main("fn main(){}",[{"name":"main","line":1,"column":3}],"rust"),"fn __oteleq_original_main(){}")
        self.assertEqual(harness.rename_main("func main(){}",[{"name":"main","name_offset":5}],"go"),"func __oteleq_original_main(){}")
        with self.assertRaisesRegex(ValueError,"range"):
            harness.rename_main("fn changed(){}",[{"name":"main","line":1,"column":3}],"rust")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.base=Path(self.temporary.name)
        self.source=self.base/"application";self.source.mkdir()
        (self.source/"source.py").write_text("state=[]\ndef sample(x:int)->int:\n state.append(x)\n return x+1\ndef main():pass\n")
        self.root=self.base/"otelc";self.root.mkdir()
        self.cli=self.base/"cli";self.cli.write_text("chosen CLI")
        self.environment=patch.dict(os.environ,{"OTELEQ_EXECUTABLE":str(self.cli)})
        self.environment.start()
        self.tools=patch.object(gen.capture,"selected_tools",return_value={"python":Path(sys.executable)})
        self.artifacts=patch.object(gen.capture,"artefacts",return_value={"pinned":"sha"})
        self.tools.start();self.artifacts.start()
        self.decoder=patch.object(gen,"decoder",return_value=None);self.decoder.start()
        output=io.StringIO()
        with redirect_stdout(output):
            gen.plan(args("plan",source=self.source,otelc_root=self.root,workspace_parent=self.base,language=None,exclude=[],cases=3))
        self.workspace=Path(output.getvalue().strip())

    def tearDown(self):
        self.decoder.stop();self.artifacts.stop();self.tools.stop();self.environment.stop();self.temporary.cleanup()

    def generate(self):
        with redirect_stdout(io.StringIO()):gen.generate(args("generate",workspace=self.workspace))

    def test_nested_and_instance_main_remain_blockers_and_entrypoint_metadata_is_small(self):
        for language in ("rust", "go", "javascript", "python"):
            nested={"name":"main", "parameters":[], "output":"void", "reason":"needs access fixture", "entrypoint":False}
            self.assertFalse(gen.is_entrypoint(nested,language))
        instance={"name":"Example.main", "parameters":["String[]"], "output":"void", "reason":"instance method needs a fixture"}
        self.assertFalse(gen.is_entrypoint(instance,"java"))
        self.assertTrue(gen.is_entrypoint(dict(instance,reason=""),"java"))
        self.assertFalse(gen.is_entrypoint(dict(instance,reason="",parameters=["int"]),"java"))
        (self.source/"source.py").write_text("def outer():\n def main():pass\n return 1\ndef main():pass\n")
        output=io.StringIO()
        with redirect_stdout(output):
            gen.plan(args("plan",source=self.source,otelc_root=self.root,workspace_parent=self.base,language=None,exclude=[],cases=3))
        inventory=gen.read(Path(output.getvalue().strip())/"plan.json")["inventory"]
        self.assertEqual(next(e for e in inventory if e["name"]=="outer.main")["status"],"blocked")
        for entry in inventory:
            self.assertEqual([f["name"] for f in entry["file_functions"]],["main"])

    def test_native_builds_only_the_selected_lane_and_retains_actual_binary_identity(self):
        for language,compiler in (("c","clang"),("cpp","clang++")):
            for lane in ("baseline","instrumented_on"):
                folder=self.base/(language+lane);folder.mkdir();scratch=folder/"scratch";scratch.mkdir()
                binary=scratch/"application"
                binary.write_bytes((language+lane).encode())
                driver=self.source/("driver.c" if language=="c" else "driver.cpp")
                tools={compiler:Path("/selected")/compiler}
                with patch.object(gen,"execute",return_value=subprocess.CompletedProcess([],0,b"",b"")) as execute:
                    command=gen.build_command(self.root,self.source,{"language":language},driver,self.base/"policy",tools,{},folder,scratch,lane)
                execute.assert_called_once()
                built=execute.call_args.args[0]
                self.assertEqual(built[0],tools[compiler] if lane=="baseline" else self.root/"target/debug/quux-otelc")
                self.assertIn("-O2" if language=="cpp" else "-O1",built)
                self.assertEqual(command[-1],binary)
                self.assertEqual(gen.read(folder/"build-identities.json"),{"application":gen.capture.file_digest(binary)})
                gen.validate_private_sources(self.source,gen.manifest(self.source),folder)
                self.assertEqual(gen.read(folder/"build-identities.json"),{"application":gen.capture.file_digest(binary)})
        with patch.object(gen,"execute",return_value=subprocess.CompletedProcess([],1,b"",b"compiler failure")):
            with self.assertRaisesRegex(ValueError,"native build failed"):
                gen.native_command([],self.source,"c",driver,{"clang":"/selected/clang"},{},folder,scratch,"baseline")

    def reseal(self,data):
        gen.write(self.workspace/"plan.json",data)
        marker=gen.read(self.workspace/".oteleq-owned.json");marker["plan_sha256"]=gen.identity(data)
        gen.write(self.workspace/".oteleq-owned.json",marker)

    def test_generation_is_external_source_preserving_and_exports_portably(self):
        original=gen.manifest(self.source)
        self.generate()
        self.assertEqual(gen.manifest(self.source),original)
        self.assertEqual(len(gen.read(self.workspace/"tests/corpus.json")),3)
        self.assertTrue((self.workspace/"tests/test_equivalence.py").is_file())
        self.assertTrue((self.workspace/"tests/GENERATED-LICENSE.txt").is_file())
        destination=self.base/"export"
        with redirect_stdout(io.StringIO()):
            gen.export_tests(args("export-tests",workspace=self.workspace,destination=destination,apply=False))
            self.assertFalse(destination.exists())
            gen.export_tests(args("export-tests",workspace=self.workspace,destination=destination,apply=True))
        exported,data=gen.load_workspace(destination,generated=True)
        self.assertEqual(data["source"],str(exported/"snapshot"))
        conflicting=args("export-tests",workspace=self.workspace,destination=destination,apply=True)
        recursive=args("export-tests",workspace=self.workspace,destination=self.workspace/"copy",apply=True)
        with self.assertRaises(ValueError):gen.export_tests(conflicting)
        with self.assertRaises(ValueError):gen.export_tests(recursive)
        (destination/"unrelated.txt").write_text("user work")
        cleanup=args("clean",workspace=destination)
        with self.assertRaisesRegex(ValueError,"unowned"):gen.clean(cleanup)
        (destination/"unrelated.txt").unlink()
        gen.clean(args("clean",workspace=destination));self.assertFalse(destination.exists())

    def test_changed_source_snapshot_corpus_plan_or_generator_never_passes(self):
        self.generate()
        source=self.source/"source.py";original=source.read_bytes();source.write_text("changed")
        with self.assertRaisesRegex(ValueError,"source"):gen.load_workspace(self.workspace)
        source.write_bytes(original)
        snapshot=self.workspace/"snapshot/source.py";snapshot.write_text("changed")
        with self.assertRaisesRegex(ValueError,"snapshot"):gen.load_workspace(self.workspace)
        snapshot.write_bytes(original)
        corpus=self.workspace/"tests/corpus.json";saved=corpus.read_bytes();corpus.write_text("[]")
        with self.assertRaisesRegex(ValueError,"suite"):gen.load_workspace(self.workspace,generated=True)
        corpus.write_bytes(saved)
        plan=gen.read(self.workspace/"plan.json");plan["inventory"]=[];gen.write(self.workspace/"plan.json",plan)
        with self.assertRaisesRegex(ValueError,"plan identity"):gen.load_workspace(self.workspace)
        self.reseal(plan)
        with patch.object(gen,"generator_identity",return_value="changed"):
            with self.assertRaisesRegex(ValueError,"generator"):gen.load_workspace(self.workspace)

    def test_baseline_captures_real_global_and_input_state_and_missing_instrumentation_fails(self):
        self.generate()
        _,data=gen.load_workspace(self.workspace,generated=True)
        entry=next(e for e in data["inventory"] if e["status"]=="ready")
        case=gen.read(self.workspace/"tests/corpus.json")[1]
        with patch.object(gen.capture,"stable"),patch.object(gen.capture,"commands",side_effect=lambda root,project,lang,driver,*rest:([sys.executable,driver],[sys.executable,driver])):
            result=gen.attempt(self.workspace,data,entry,case,"baseline",self.base/"baseline",None)
            self.assertEqual(result["termination"],{"kind":"exit","code":0})
            self.assertIsNone(result["witness"])
            state=json.loads(bytes(result["channels"]["state-and-outcome"]))
            self.assertNotEqual(state["before"],state["after"])
            with self.assertRaises(OSError):gen.attempt(self.workspace,data,entry,case,"instrumented_on",self.base/"on",None)
        self.assertEqual(gen.manifest(self.source),data["source_manifest"])

    def test_run_retains_mixed_results_and_blockers_are_failures(self):
        self.generate()
        _,data=gen.load_workspace(self.workspace,generated=True)
        entry=dict(data["inventory"][0],status="blocked",reason="fixture required",id="other")
        data["inventory"].append(entry);self.reseal(data)
        results=[{"case":"a","exit_code":0},{"case":"b","exit_code":1},{"case":"c","exit_code":4}]
        destination=self.base/"report"
        with patch.object(gen,"compare_case",side_effect=results),redirect_stdout(io.StringIO()):
            self.assertEqual(gen.run(args("run",workspace=self.workspace,report_dir=destination)),4)
        report=gen.read(destination/"report.json")
        self.assertEqual(len(report["cases"]),3);self.assertEqual(len(report["blocked"]),1)
        with patch.object(gen,"compare_case",return_value={"exit_code":0}),redirect_stdout(io.StringIO()):
            self.assertEqual(gen.run(args("run",workspace=self.workspace,report_dir=self.base/"blocked")),3)
        with patch.object(gen,"compare_case",side_effect=ValueError("tool failed")),redirect_stdout(io.StringIO()):
            self.assertEqual(gen.run(args("run",workspace=self.workspace,report_dir=self.base/"fail")),4)
        case=gen.read(self.workspace/"tests/corpus.json")[0]
        with patch.object(gen,"compare_case",return_value={"exit_code":0}),redirect_stdout(io.StringIO()):
            self.assertEqual(gen.run(args("replay",workspace=self.workspace,case=case["id"])),0)
        missing=args("replay",workspace=self.workspace,case="missing")
        internal_report=args("run",workspace=self.workspace,report_dir=self.source/"report")
        with self.assertRaisesRegex(ValueError,"unknown case"):
            gen.run(missing)
        with self.assertRaisesRegex(ValueError,"outside"):
            gen.run(internal_report)

    def test_bounds_symlinks_inventory_errors_and_zero_cases_are_explicit(self):
        with patch.object(gen,"MAX_FILE",1):
            with self.assertRaisesRegex(ValueError,"limit"):gen.manifest(self.source)
        link=self.source/"link";link.symlink_to(self.cli)
        with self.assertRaisesRegex(ValueError,"symlink"):gen.manifest(self.source)
        link.unlink()
        with patch.object(gen.discovery,"discover",side_effect=ValueError("bad syntax")),redirect_stdout(io.StringIO()) as output:
            gen.plan(args("plan",source=self.source,otelc_root=self.root,workspace_parent=self.base,language=["python"],exclude=[],cases=3))
            second=Path(output.getvalue().strip())
        data=gen.read(second/"plan.json");self.assertEqual(data["inventory"][0]["status"],"blocked")
        internal_workspace=args("plan",source=self.source,otelc_root=self.root,workspace_parent=self.source,language=None,exclude=[],cases=3)
        with self.assertRaisesRegex(ValueError,"outside"):
            gen.plan(internal_workspace)
        _,data=gen.load_workspace(self.workspace);data["inventory"]=[];self.reseal(data)
        self.generate()
        with patch.object(gen,"compare_case"),redirect_stdout(io.StringIO()):
            self.assertEqual(gen.run(args("run",workspace=self.workspace,report_dir=self.base/"empty")),3)
        env=dict(os.environ,OTELEQ_CLI="/unused")
        result=subprocess.run([sys.executable,self.workspace/"tests/test_equivalence.py"],capture_output=True,env=env)
        self.assertNotEqual(result.returncode,0);self.assertIn(b"no selected executable cases",result.stderr)

    def test_telemetry_requires_exact_selected_name_one_root_and_runtime_health(self):
        entry={"otelc_function":"f","language":"python"}
        with patch.object(gen.capture,"decode",return_value=({"f":3},[],1,2)),patch.object(gen.capture,"witness",return_value={"spans":3}) as witness:
            self.assertEqual(gen.telemetry([],{},entry,"service",None),{"spans":3})
            self.assertEqual(witness.call_args.args[2]["trees"],1)
        for decoded in (({"other":1},[],1,0),({"f":1},[],2,0),({"f":0},[],1,0)):
            with patch.object(gen.capture,"decode",return_value=decoded):
                with self.assertRaisesRegex(ValueError,"witnessed"):gen.telemetry([],{},entry,"service",None)
        self.assertIn('backend = "compile"',gen.policy({"language":"go","otelc_function":"p.f"},"receiver"))
        self.assertEqual(gen.entry_identity({"language":"cpp","name":"N::f","parameters":["int"],"path":"x.cpp"}),"N::f(int)")
        self.assertEqual(gen.entry_identity({"language":"java","name":"X.f","parameters":["String"],"package":"p","path":"X.java"}),"p.X.f(java.lang.String)")

    def test_process_timeout_and_output_limit_retains_bytes_and_kills_group(self):
        with self.assertRaisesRegex(ValueError,"timeout"):
            gen.execute([sys.executable,"-c","import time;print('started',flush=True);time.sleep(10)"],self.base,folder=self.base/"timeout",timeout=0.05)
        self.assertIn(b"started",(self.base/"timeout/stdout").read_bytes())
        with patch.object(gen,"MAX_OUTPUT",32):
            with self.assertRaisesRegex(ValueError,"output limit"):
                gen.execute([sys.executable,"-c","print('x'*1000)"],self.base,folder=self.base/"output")
        self.assertEqual(gen.execute([sys.executable,"-c","print('ok')"],self.base).stdout,b"ok\n")
        with patch.object(gen,"MAX_TREE",1):
            with self.assertRaisesRegex(ValueError,"document"):gen.read(self.workspace/"plan.json")

    def test_cli_routes_use_actual_flags_and_fail_closed(self):
        with redirect_stdout(io.StringIO()),self.assertRaises(SystemExit) as help_result:
            gen.main(["plan","--help"])
        self.assertEqual(help_result.exception.code,0)
        with patch.object(gen,"plan",return_value=0) as planning:
            self.assertEqual(gen.main(["plan","--source",str(self.source),"--otelc-root",str(self.root),"--language","python","--exclude","*.main","--cases","2"]),0)
            self.assertEqual(planning.call_args.args[0].cases,2)
        for command,method,extra in (("generate","generate",[]),("run","run",["--report-dir",str(self.base/"out")]),
                                     ("replay","run",["--case","case"]),("export-tests","export_tests",["--destination",str(self.base/"copy"),"--apply"]),
                                     ("clean","clean",[])):
            with patch.object(gen,method,return_value=3):
                self.assertEqual(gen.main([command,"--workspace",str(self.workspace),*extra]),3)
        with patch.object(gen,"clean",side_effect=ValueError("blocked")),patch.object(sys,"stderr",io.StringIO()):
            self.assertEqual(gen.main(["clean","--workspace",str(self.workspace)]),4)

    def test_comparison_bundle_keeps_channels_corpus_and_observation_limits(self):
        self.generate()
        _,data=gen.load_workspace(self.workspace,generated=True)
        entry=next(e for e in data["inventory"] if e["status"]=="ready")
        case=gen.read(self.workspace/"tests/corpus.json")[0]
        destination=self.base/"compare";destination.mkdir()
        attempt={"witness":{"functions":{"source.sample":1}},"channels":{"stdout":[],"stderr":[],"state-and-outcome":[1]}}
        with patch.object(gen,"attempt",return_value=attempt),patch.object(gen,"execute",return_value=subprocess.CompletedProcess([],1,b'{"verdict":"different_observed"}',b"")):
            result=gen.compare_case(self.workspace,data,entry,case,destination,None)
        self.assertEqual(result["exit_code"],1)
        self.assertEqual(gen.read(destination/"corpus.json"),case)
        bundle=gen.read(destination/"bundle.json")
        self.assertEqual(bundle["scope"]["artefact_class"],"diagnostic")
        self.assertEqual(len(bundle["cases"][0]["baseline"]),2)
        self.assertIn("state-and-outcome",bundle["scope"]["channels"])
        with patch.object(gen.capture,"stable"),patch.object(gen.capture,"commands",side_effect=lambda root,project,lang,driver,*rest:([sys.executable,driver],[sys.executable,driver])),patch.object(gen,"MAX_CHANNEL_BYTES",1):
            with self.assertRaisesRegex(ValueError,"channel budget"):
                gen.attempt(self.workspace,data,entry,case,"baseline",self.base/"overflow",None)


if __name__=="__main__":unittest.main()
