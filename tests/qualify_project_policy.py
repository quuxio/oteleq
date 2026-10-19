"""Qualify configured domains, repeat budgets and lossless scalar fixtures on real otelc."""
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import struct

from qualify_generation import command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, default=Path(__file__).resolve().parents[1] / "target/debug/quux-oteleq")
    args = parser.parse_args()
    cli, root = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True)
    destination = args.report_dir.resolve()
    if destination.is_relative_to(root) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and external")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"] = sys.executable
    source = destination / "application"
    shutil.copytree(Path(__file__).with_name("generation-fixtures"), source)
    (source / "wide.c").write_text("unsigned long long echo(unsigned long long value){return value;}\nfloat decimal(float value){return value;}\n")
    (source / "wide.cpp").write_text("long long echo(long long value){return value;}\nfloat decimal(float value){return value;}\n")
    (source / "wide.rs").write_text("fn echo(value:u128)->u128{value}\nfn decimal(value:f32)->f32{value}\n")
    (source / "wide.go").write_text("package main\nfunc echo(value uint64) uint64 {return value}\nfunc decimal(value float32) float32 {return value}\n")
    (source / "unicode").mkdir()
    (source / "unicode/UnicodeCases.java").write_text('''package unicode;
public class UnicodeCases {
 static String seen="";
 public static String text(String value){seen=value;return value+"\\ud800";}
 public static long wide(long value){return value;}
 public static char unit(int value){return (char)value;}
 public static float decimal(float value){return value;}
}
''')
    policy = destination / "equivalence.toml"
    text = '''schema_version=1
[generation]
seed=7
cases_per_function=8
[limits]
baseline_repeats=3
instrumented_repeats=3
'''
    for language in ("c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"):
        values = [[7], [41], [2**100]] if language == "python" else [[7], [41]]
        if language in ("javascript", "typescript"):
            values.extend([[1.3], [-0.0]])
        text += f'\n[[fixtures]]\nlanguage={json.dumps(language)}\nfunction="*add*"\ncases={json.dumps(values)}\n'
    for language, filename, value in (("c", "wide.c", 2**64 - 1), ("cpp", "wide.cpp", -(2**63)),
                                      ("rust", "wide.rs", 2**128 - 1), ("go", "wide.go", 2**64 - 1)):
        text += f'\n[[fixtures]]\nlanguage={json.dumps(language)}\nsource={json.dumps(filename)}\nfunction="*echo*"\ncases=[[{value}]]\n'
    for language in ("c", "cpp", "rust", "go", "java"):
        text += f'\n[[fixtures]]\nlanguage={json.dumps(language)}\nfunction="*decimal*"\ncases=[[1.3],[-0.0]]\n'
    text += '''
[[fixtures]]
language="java"
function="unicode.UnicodeCases.text(java.lang.String)"
cases=[["\u00e9\\u0000\U0001f600"]]
[[fixtures]]
language="java"
function="unicode.UnicodeCases.wide(long)"
cases=[[-9223372036854775808]]
[[fixtures]]
language="java"
function="unicode.UnicodeCases.unit(int)"
cases=[[55296]]
'''
    policy.write_text(text, encoding="utf-8")
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", root,
                              "--workspace-parent", destination, "--config", policy], destination, "plan"))
    data = json.loads((workspace / "plan.json").read_text())
    assert not any(entry["status"] == "blocked" for entry in data["inventory"])
    command([cli, "generate", "--workspace", workspace], destination, "generate")
    command([cli, "run", "--workspace", workspace, "--report-dir", destination / "comparison"], destination, "run", timeout=1800)
    report = json.loads((destination / "comparison/report.json").read_text())
    assert len(report["cases"]) == 38 and report["source_preserved"]
    assert report["configuration"]["limits"]["baseline_repeats"] == 3
    languages = {entry["language"] for entry in report["inventory"] if entry["status"] == "ready"}
    assert len(languages) == 8
    by_id = {entry["id"]: entry for entry in data["inventory"]}
    corpus = {case["id"]: case for case in json.loads((workspace / "tests/corpus.json").read_text())}
    tokens = {"wide.c": b"return:unsigned long long:ffffffffffffffff",
              "wide.cpp": b"return:long long:" + (-(2**63)).to_bytes(8, sys.byteorder, signed=True).hex().encode(),
              "wide.rs": b"return:u128:" + str(2**128 - 1).encode(),
              "wide.go": hex(2**64 - 1).encode()}
    for case in report["cases"]:
        bundle = json.loads((destination / "comparison" / case["case"] / "bundle.json").read_text())["cases"][0]
        assert len(bundle["baseline"]) == len(bundle["instrumented_on"]) == 3
        assert case["exit_code"] == 0
        entry = by_id[corpus[case["case"]]["function_id"]]
        expected_token = tokens.get(entry["path"]) if "echo" in entry["name"] else None
        if case["function"] == "unicode.UnicodeCases.wide(long)":
            expected_token = b"java.lang.Long:" + base64.b64encode(str(-(2**63)).encode())
        if case["function"] == "unicode.UnicodeCases.unit(int)":
            expected_token = b"return:char:d800"
        if "decimal" in entry["name"]:
            packed = struct.pack(">f", case["arguments"][0])
            prefix = {"rust": "return:f32:", "go": "return:float32:", "java": "return:float:"}
            expected_token = (prefix[entry["language"]] + packed.hex()).encode() if entry["language"] in prefix else b"return:float:" + struct.pack("=f", case["arguments"][0]).hex().encode()
        for lane in ("baseline", "instrumented_on"):
            for attempt in bundle[lane]:
                raw = bytes(attempt["channels"]["state-and-outcome"])
                if expected_token is not None:
                    assert expected_token in raw, (entry["path"], raw)
                if entry["language"] == "python" and case["arguments"] == [2**100]:
                    assert json.loads(raw)["outcome"]["value"]["roots"]["result"]["value"] == str(2**100 + 1)
                if entry["language"] in ("javascript", "typescript") and math.copysign(1, case["arguments"][0]) < 0:
                    graph = json.loads(raw)["before"]
                    arguments = graph["nodes"][graph["roots"]["arguments"]["ref"]]["fields"]
                    assert next(field[1] for field in arguments if field[0] == "0")["bits"] == "8000000000000000"
    unicode_case = next(case for case in report["cases"] if "UnicodeCases.text" in case["function"])
    bundle = json.loads((destination / "comparison" / unicode_case["case"] / "bundle.json").read_text())
    expected = "00e90000d83dde00d800"
    for lane in ("baseline", "instrumented_on"):
        for attempt in bundle["cases"][0][lane]:
            assert expected.encode() in bytes(attempt["channels"]["state-and-outcome"])
    control = destination / "altered-unicode-observation"
    control.mkdir()
    for attempt in bundle["cases"][0]["instrumented_on"]:
        raw = bytes(attempt["channels"]["state-and-outcome"])
        attempt["channels"]["state-and-outcome"] = list(raw.replace(expected.encode(), expected[:-1].encode() + b"1"))
    (control / "bundle.json").write_text(json.dumps(bundle))
    command([cli, "compare-workload", control / "bundle.json"], control, "compare", expected=1)
    (control / "KIND.txt").write_text("Deliberately altered retained observation; not another target execution.\n")
    typed = json.loads((destination / "comparison" / unicode_case["case"] / "typed-bundle.json").read_text())
    for attempt in typed["cases"][0]["instrumented_on"]:
        value = attempt["observation"]["outcome"]["graph"]["roots"]["result"]
        assert value["value"] == expected and value["encoding"] == "utf16_be"
        value["value"] = expected[:-1] + "1"
    (control / "typed-bundle.json").write_text(json.dumps(typed))
    command([cli, "compare-observations", control / "typed-bundle.json"], control, "compare-typed", expected=1)
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "languages": sorted(languages),
               "configured_cases": 38, "matching_attempts": 228, "repeats_per_lane": 3,
               "unicode_utf16_and_signed_unsigned_extremes": True, "altered_unicode_control_rejected": True,
               "altered_typed_unicode_control_rejected": True,
               "source_preserved": report["source_preserved"], "configuration_sha256": data["configuration_sha256"]}
    (destination / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
