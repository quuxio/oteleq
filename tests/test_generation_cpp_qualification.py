"""Independent C++ qualification oracles reject matching wrong observations."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import qualify_cpp_receivers as qualification
import test_generation_cpp_workers as workers
import typed_capture


class CppQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Real plain workers supply codec graphs; synthetic lanes exercise the
        # independent checker, not an actual instrumentation qualification.
        worker = workers.CppWorkerTests()
        worker.setUp()
        cls.addClassCleanup(worker.doCleanups)
        cls.bundles, cls.cases = {}, []
        for method in qualification.METHODS:
            _, capture, _, _ = worker.captured(qualification.SOURCE, method="sample::Counter::" + method)
            capture["gaps"] = []
            baseline = {"observation": capture, "execution": {"witness": {"functions": {qualification.function(method): 1}}}}
            instrumented = copy.deepcopy(baseline)
            for graph in (instrumented["observation"]["after"], instrumented["observation"]["outcome"]["graph"]):
                fields = qualification.node(graph, graph["roots"]["receiver"])["fields"]
                if method == "instance":
                    qualification.node(graph, fields["field:value_"])["fields"]["value"]["value"] = "14"
                elif method == "static_only":
                    qualification.node(graph, graph["roots"]["global:sample::Counter::total_"])["fields"]["value"]["value"] = "4"
                elif method == "alias":
                    qualification.node(graph, fields["field:pointer_"])["fields"]["value"] = fields["field:other_"]
            cls.bundles[method] = {"cases": [{"contract": {"required_roots": ["receiver", "argument:0", "global:sample::Counter::total_"]},
                                              "baseline": [baseline, baseline], "instrumented_on": [instrumented, instrumented]}]}
            cls.cases.append({"case": method, "function": qualification.function(method), "arguments": [3],
                              "exit_code": int(method in qualification.DIFFERENCES), "receiver_fixture": {"arguments": [10]}})
        cls.binding_bundles, cls.binding_cases = {}, []
        for index, name in enumerate(qualification.BINDING_FUNCTIONS):
            receiver = name in qualification.BINDING_FACTORIES
            entry, result, raw, _ = worker.worker(qualification.BINDING_SOURCE,
                method=name.split('(')[0] if receiver else name, factory=qualification.BINDING_FACTORIES.get(name))
            worker.assertEqual(result.returncode, 0, result.stderr)
            capture = typed_capture.observation(raw, entry, {"case_id": str(index), "function_id": name, "fixture_sha256": "a"*64})
            attempt = {"observation": capture, "execution": {"witness": {"functions": {name: 1}}}}
            cls.binding_bundles[str(index)] = {"cases": [{"contract": {"required_roots": typed_capture.required_roots(entry)},
                "baseline": [attempt, attempt], "instrumented_on": [attempt, attempt]}]}
            cls.binding_cases.append({"case": str(index), "function": name, "arguments": [3], "exit_code": 0,
                                      "receiver_fixture": {"arguments": [10]} if receiver else None})

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.report = self.folder / "report.json"
        self.report.write_text(json.dumps({"source_preserved": True, "blocked": [], "cases": self.cases}))
        for name, bundle in self.bundles.items():
            target = self.folder / name
            target.mkdir()
            (target / "typed-bundle.json").write_text(json.dumps(bundle))

    def test_every_method_and_both_lanes_have_complete_independent_value_oracles(self):
        self.assertEqual(qualification.check_report(self.report, len(self.cases))[0], 36)

    def test_binding_oracles_check_global_record_and_all_c_linkage_returns(self):
        self.report.write_text(json.dumps({"source_preserved": True, "blocked": [], "cases": self.binding_cases}))
        for name, bundle in self.binding_bundles.items():
            folder = self.folder / name
            folder.mkdir()
            (folder / "typed-bundle.json").write_text(json.dumps(bundle))
        self.assertEqual(qualification.check_bindings(self.report, len(qualification.BINDING_FUNCTIONS)), 20)
        for name in ("1", "2", "3"):
            bundle = copy.deepcopy(self.binding_bundles[name])
            for lane in ("baseline", "instrumented_on"):
                for attempt in bundle["cases"][0][lane]:
                    attempt["observation"]["outcome"]["graph"]["roots"]["result"]["value"] = "40"
            target = self.folder / name / "typed-bundle.json"
            target.write_text(json.dumps(bundle))
            with self.subTest(case=name), self.assertRaises(AssertionError):
                qualification.check_bindings(self.report, len(qualification.BINDING_FUNCTIONS))
            target.write_text(json.dumps(self.binding_bundles[name]))

    def test_original_shrink_copies_do_not_inflate_unique_launch_count(self):
        for index in range(4):
            for phase in ("actual", "copied-original"):
                folder = self.folder / phase / ("baseline-" + str(index))
                folder.mkdir(parents=True)
                (folder / "command.json").write_text(json.dumps(["application-" + str(index)]))
        self.assertEqual(qualification.verify_launches(self.folder, 4), {"unique_application_launches": 4, "raw_attempt_folders": 8})
        with self.assertRaises(AssertionError):
            qualification.verify_launches(self.folder, 8)

    def test_unicode_getter_count_reference_and_return_copy_have_independent_oracles(self):
        name = str(qualification.BINDING_FUNCTIONS.index('UnicodeCounter::add(int)'))
        case = self.binding_cases[int(name)]
        original = self.binding_bundles[name]['cases'][0]['baseline'][0]['observation']
        qualification.check_binding_receiver(original, case)
        for change in ('getter', 'reference', 'return-copy'):
            observed = copy.deepcopy(original)
            graph = observed['outcome']['graph']
            fields = qualification.node(graph, graph['roots']['receiver'])['fields']
            if change == 'getter':
                qualification.node(graph, graph['roots'][qualification.BINDING_STATIC])['fields']['value']['value'] = '1'
            elif change == 'reference':
                qualification.node(graph, fields['field:\u6570\u636e'])['fields']['value'] = graph['roots']['result']
            else:
                location = qualification.node(graph, fields['field:value_'])['fields']['location']
                qualification.node(graph, graph['roots']['result'])['fields']['location'] = location
            with self.subTest(change=change), self.assertRaises(AssertionError):
                qualification.check_binding_receiver(observed, case)

    def test_equal_wrong_fields_widths_arguments_float_bits_and_aliases_are_rejected(self):
        original = self.bundles["identity"]
        target = self.folder / "identity/typed-bundle.json"
        for alteration in ("value", "width", "signed", "argument", "float", "child", "array", "alias", "location", "result", "witness", "construction"):
            bundle = copy.deepcopy(original)
            for lane in ("baseline", "instrumented_on"):
                for attempt in bundle["cases"][0][lane]:
                    graph = attempt["observation"]["outcome"]["graph"]
                    fields = qualification.node(graph, graph["roots"]["receiver"])["fields"]
                    value = qualification.node(graph, fields["field:value_"])["fields"]["value"]
                    if alteration == "value":
                        value["value"] = "130"
                    elif alteration == "width":
                        value["bits"] = 32
                    elif alteration == "signed":
                        value["signed"] = False
                    elif alteration == "argument":
                        qualification.node(graph, graph["roots"]["argument:0"])["fields"]["value"]["value"] = "4"
                    elif alteration == "float":
                        qualification.node(graph, fields["field:small_"])["fields"]["value"]["bits"] = "7fc00017"
                    elif alteration == "child":
                        child = qualification.node(graph, fields["field:child_"])
                        qualification.node(graph, child["fields"]["field:value"])["fields"]["value"]["value"] = "20"
                    elif alteration == "array":
                        array = qualification.node(graph, fields["field:array_"])
                        qualification.node(graph, array["fields"]["item:1"])["fields"]["value"]["value"] = "120"
                    elif alteration == "alias":
                        qualification.node(graph, fields["field:pointer_"])["fields"]["value"] = fields["field:other_"]
                    elif alteration == "location":
                        qualification.node(graph, fields["field:value_"])["fields"]["location"] = {"kind": "reference", "node_id": "different"}
                    elif alteration == "result":
                        qualification.node(graph, graph["roots"]["result"])["fields"]["value"] = fields["field:other_"]
                    elif alteration == "witness":
                        attempt["execution"]["witness"]["functions"] = {}
            target.write_text(json.dumps(bundle))
            report = {"source_preserved": True, "blocked": [], "cases": copy.deepcopy(self.cases)}
            if alteration == "construction":
                report["cases"][0]["receiver_fixture"]["arguments"] = [11]
            self.report.write_text(json.dumps(report))
            with self.subTest(alteration=alteration), self.assertRaises(AssertionError):
                qualification.check_report(self.report, len(self.cases))
