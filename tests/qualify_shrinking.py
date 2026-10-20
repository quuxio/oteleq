"""Qualify scalar shrinking through actual eight-language otelc execution."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

from qualify_generation import command


def specifications():
    """Deliberately telemetry-sensitive fixtures exercise real difference preservation."""
    python_active = '"quux.otelc" in (sys.monitoring.get_tool(0),sys.monitoring.get_tool(1),sys.monitoring.get_tool(2),sys.monitoring.get_tool(3),sys.monitoring.get_tool(4),sys.monitoring.get_tool(5))'
    result = {
        "c": ("sample.c", "sample", '#include <stdlib.h>\nint sample(int value){return value>=7 && getenv("OTELC_CONFIG")!=0;}\n'),
        "cpp": ("sample.cpp", "sample(int)", '#include <stdlib.h>\nint sample(int value){return value>=7 && getenv("OTELC_CONFIG")!=nullptr;}\n'),
        "rust": ("sample.rs", "sample.sample", 'fn sample(value:i32)->i32{if value<7{return 0}let bytes=std::fs::read(std::env::current_exe().unwrap()).unwrap();let mut count=0;for part in bytes.windows(15){if part==b"quux_otelc_rust"{count+=1}}(count>1) as i32}\n'),
        "python": ("sample.py", "sample.sample", 'import sys\ndef sample(value:int)->int:return int(value>=7 and (' + python_active + '))\n'),
        "java": ("Sample.java", "Sample.sample(int)", 'class Sample { static int sample(int value){return value>=7 && java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().toString().contains("-javaagent:")?1:0;} }\n'),
        "javascript": ("sample.js", "sample.sample", 'export function sample(value){return value>=7 && process.execArgv.join(" ").includes("/node/register.mjs")?1:0;}\n'),
        "typescript": ("sample.ts", "sample.sample", 'export function sample(value:number):number{return value>=7 && process.execArgv.join(" ").includes("/node/register.mjs")?1:0;}\n'),
        "go": ("sample.go", "sample.sample", 'package main\nimport "runtime"\nfunc sample(value int) int {if value>=7 && runtime.NumGoroutine()>1{return 1};return 0}\n'),
    }
    specs = [{"language": language, "path": path, "function": function, "text": text,
              "start": 32, "domains": [{"kind": "integer", "minimum": 0, "maximum": 32}], "budget": 16}
             for language, (path, function, text) in result.items()]
    python = next(row for row in specs if row["language"] == "python")
    extra = [("floating", "float", "value>=1.25", 8.0, {"kind": "float", "minimum": 0.0, "maximum": 8.0}, 8),
             ("text", "str", '"z" in value', "zzabba", {"kind": "string", "minimum_length": 1, "maximum_length": 6, "alphabet": "abz"}, 16),
             ("logical", "bool", "value", True, {"kind": "boolean"}, 4)]
    for name, type_, condition, start, domain, budget in extra:
        python["text"] += f'def {name}(value:{type_})->int:return int(({condition}) and ({python_active}))\n'
        specs.append({"language": "python", "path": "sample.py", "function": "sample." + name,
                      "start": start, "domains": [domain], "budget": budget})
    return specs


def write_policy(path, specs):
    """Freeze explicit valid domains and exact selected diagnostic functions."""
    text = 'schema_version=1\nlanguages=' + json.dumps(list(dict.fromkeys(row["language"] for row in specs)))
    text += '\n[functions]\ninclude=' + json.dumps(list(dict.fromkeys(row["function"] for row in specs))) + '\n'
    for row in specs:
        domain = '{' + ','.join(key + '=' + json.dumps(value) for key, value in row["domains"][0].items()) + '}'
        text += '\n[[fixtures]]\nlanguage=' + json.dumps(row["language"]) + '\nfunction=' + json.dumps(row["function"])
        text += '\nsource=' + json.dumps(row["path"]) + '\ncases=' + json.dumps([[row["start"]]]) + '\ndomains=[' + domain + ']\n'
    path.write_text(text)


def fixture(destination):
    """Keep one mixed source tree while selected cases have independent domains."""
    source = destination / "application"
    source.mkdir()
    specs = specifications()
    for row in specs:
        if "text" in row:
            (source / row["path"]).write_text(row["text"])
    policy = destination / "equivalence.toml"
    write_policy(policy, specs)
    return source, policy, specs


def spec_for(report, case, specs):
    entry = next(row for row in report["inventory"] if row["id"] == case["case"].rsplit('-', 1)[0])
    return next(row for row in specs if row["language"] == entry["language"] and row["function"] == case["function"])


def expected(spec, argument, lane):
    if spec["function"].endswith(".floating"):
        active = argument >= 1.25
    elif spec["function"].endswith(".text"):
        active = "z" in argument
    elif spec["function"].endswith(".logical"):
        active = argument
    else:
        active = argument >= 7
    return int(active and lane == "instrumented_on")


def check_report(path, specs):
    """Independent value oracles accompany every complete actual execution."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"]
    launches = 0
    for case in report["cases"]:
        spec = spec_for(report, case, specs)
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        assert case["exit_code"] in (0, 1)
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                launches += 1
                observation = attempt["observation"]
                assert not observation["gaps"] and observation["outcome"]["kind"] == "return"
                scalar = observation["outcome"]["graph"]["roots"]["result"]
                if scalar["kind"] == "float":
                    number = struct.unpack('>d', bytes.fromhex(scalar["bits"]))[0]
                    assert number.is_integer()
                    value = int(number)
                else:
                    value = int(scalar["value"])
                oracle = expected(spec, case["arguments"][0], lane)
                assert value == oracle, (spec["language"], case["arguments"], lane, value, oracle)
    return launches


def check_reduction(spec, report):
    value = report["reduced_arguments"][0]
    assert report["exit_code"] == 1 and report["source_preserved"] and report["incomplete_trials"] == 0
    if spec["function"].endswith(".floating"):
        assert 1.25 <= value < spec["start"] and report["status"] == "budget_limited"
    elif spec["function"].endswith(".text"):
        assert value == "z" and report["status"] == "candidate_rule_minimal"
    elif spec["function"].endswith(".logical"):
        assert value is True and report["status"] == "candidate_rule_minimal"
    else:
        assert value == 7 and report["status"] == "candidate_rule_minimal"


def witness_controls(cli, destination, bundle_path):
    """Edited retained evidence must not replace a required actual witness."""
    folder = destination / 'altered-retained-witness'
    folder.mkdir()
    source = json.loads(bundle_path.read_text())
    for name in ('missing', 'pending', 'loss'):
        document = copy.deepcopy(source)
        execution = document['cases'][0]['instrumented_on'][0]['execution']
        if name == 'missing':
            execution['witness'] = None
        elif name == 'pending':
            execution['witness']['pending'] = 1
        else:
            key = next(iter(execution['witness']['losses']))
            execution['witness']['losses'][key] = 1
        path = folder / (name + '.json')
        path.write_text(json.dumps(document))
        command([cli, 'compare-observations', path], folder, name, expected=3)
    (folder / 'KIND.txt').write_text('Deliberately edited retained witness controls; no new application execution.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    root, cli, destination = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True), args.report_dir.resolve()
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"] = sys.executable
    os.environ["OTELEQ_CLI"] = str(cli)
    source, policy, specs = fixture(destination)
    workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', root, '--workspace-parent', destination,
                              '--config', policy], destination, 'plan'))
    command([cli, 'generate', '--workspace', workspace], destination, 'generate')
    command([cli, 'run', '--workspace', workspace, '--report-dir', destination / 'original-run'], destination, 'original-run', expected=1)
    original = json.loads((destination / 'original-run/report.json').read_text())
    assert len(original["cases"]) == len(specs) and all(case["exit_code"] == 1 for case in original["cases"])
    launches = check_report(destination / 'original-run/report.json', specs)
    reduced = []
    exported = False
    for index, case in enumerate(original["cases"]):
        spec = spec_for(original, case, specs)
        folder = destination / ('shrink-' + str(index).zfill(2) + '-' + spec["language"])
        command([cli, 'shrink', '--workspace', workspace, '--case', case["case"], '--report-dir', folder,
                 '--trials', spec["budget"]], destination, 'shrink-' + str(index), expected=1, timeout=1800)
        report = json.loads((folder / 'shrink.json').read_text())
        check_reduction(spec, report)
        launches += check_report(folder / 'original/report.json', specs)
        launches += check_report(folder / 'confirmation/report.json', specs)
        for trial in report["trials"]:
            launches += check_report(Path(trial["report"]), specs)
        retained = Path(report["workspace"])
        retained_case = json.loads((retained / 'tests/corpus.json').read_text())[0]["id"]
        replay = json.loads(command([cli, 'replay', '--workspace', retained, '--case', retained_case],
                                    destination, 'replay-' + str(index), expected=1))
        launches += check_report(Path(replay["report"]), specs)
        framework = json.loads(command([sys.executable, retained / 'tests/test_equivalence.py'],
                                       destination, 'framework-' + str(index), expected=1))
        launches += check_report(Path(framework['report']), specs)
        if spec['language'] == 'python' and not exported:
            export = destination / 'exported-python'
            command([cli, 'export-tests', '--workspace', retained, '--destination', export], destination, 'export-dry-run')
            assert not export.exists()
            command([cli, 'export-tests', '--workspace', retained, '--destination', export, '--apply'], destination, 'export-apply')
            replay_export = json.loads(command([cli, 'replay', '--workspace', export, '--case', retained_case],
                                               destination, 'export-replay', expected=1))
            launches += check_report(Path(replay_export['report']), specs)
            witness_controls(cli, destination, folder / 'confirmation' / retained_case / 'typed-bundle.json')
            exported = True
        reduced.append({"language": spec["language"], "function": spec["function"], "arguments": report["reduced_arguments"],
                        "trials": len(report["trials"]), "status": report["status"]})
    plan = json.loads((workspace / 'plan.json').read_text())
    print(json.dumps({"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
                      "oteleq_cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "languages": sorted(set(row["language"] for row in specs)),
                      "cases": len(specs), "actual_application_launches": launches, "reductions": reduced,
                      "generated_unittest_runs": len(specs), "exported_replays": int(exported),
                      "altered_retained_witness_controls_rejected": 3,
                      "source_sha256": plan["source_sha256"], "source_preserved": True,
                      "scope": "deliberately telemetry-sensitive fixtures, including Rust diagnostic SDK symbol presence; no shipping/object/sequence claim"}), flush=True)


if __name__ == '__main__':
    main()
