"""Actual source SDK filesystem/HTTP and fresh current-source suite qualification."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "reviewed-source-3e9614e/tests"))
from node_collection_oracle import canonical_observation, number
from node_receiver_oracle import array
import node_source_oracle
from qualify_project_tests import command

SOURCE = '''import fs from "node:fs";
let state=2;
async function perform(bad){
 const root=process.env.APP_DATA_DIR;
 const body=Buffer.from(bad?"bad":"good");
 fs.writeFileSync(root+"/out.bin",Buffer.concat([fs.readFileSync(root+"/seed.bin"),body]),{mode:0o600});
 const response=await fetch(process.env.APP_SERVICE_URL+"/effect",{method:"POST",body});
 const received=new Uint8Array(await response.arrayBuffer());
 if(response.status!==201||received.length!==2||received[0]!==0||received[1]!==255)throw new Error("response differs");
}
async function selected_match(value){await perform(false);state+=value;return state+value;}
async function selected_difference(value){await perform(value>0&&process.execArgv.join(" ").includes("/node-bootstrap.cjs"));state+=value;return state+value;}
'''


def policy(language: str, compiler: str) -> str:
    return ('schema_version=1\nlanguages=' + json.dumps([language]) + '\n'
            '[generation]\ncases_per_function=1\n[functions]\ninclude=["effects.selected_*"]\n'
            '[adapters.node]\nbackend="source-v1"\ntypescript_compiler=' + json.dumps(compiler) + '\n'
            '[[effects.filesystem]]\nname="data"\nenvironment="APP_DATA_DIR"\npath_mode="relative"\n'
            'files=[{path="seed.bin",hex="00ff",mode=0o600}]\ndirectories=["empty"]\n'
            '[[effects.http]]\nname="service"\nenvironment="APP_SERVICE_URL"\nheaders=[]\n'
            'responses=[{status=201,hex="00ff"}]\nmin_requests=1\nmax_requests=1\n'
            '[[fixtures]]\nfunction="effects.selected_match"\ncases=[[7]]\n'
            '[[fixtures]]\nfunction="effects.selected_difference"\ncases=[[7]]\n')


def graph(argument: float, state: float, result=None) -> dict:
    roots = {"arguments": {"ref": 0}, "global:state": number(state)}
    if result is not None:
        roots["result"] = number(result)
    return {"roots": roots, "nodes": [array([argument])]}


def check_report(path: Path, initial: float, count: int, language: str) -> set[tuple[str, int]]:
    report = json.loads(path.read_bytes())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    identities = set()
    for case in report["cases"]:
        argument = case["arguments"][0]
        different = case["function"].endswith("selected_difference") and argument > 0
        assert case["exit_code"] == int(different)
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_bytes())["cases"][0]
        expected = {"before": graph(argument, initial), "after": graph(argument, initial + argument),
                    "outcome": {"kind": "return", "value": graph(argument, initial + argument, initial + 2 * argument)}}
        bindings = set()
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            bad = different and lane == "instrumented_on"
            payload = b"bad" if bad else b"good"
            for index, attempt in enumerate(bundle[lane]):
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                raw = json.loads((folder / "observation").read_bytes())
                assert json.dumps(canonical_observation(raw), sort_keys=True) == json.dumps(expected, sort_keys=True)
                execution = attempt["execution"]
                assert execution["capture_complete"] is True and execution["channels"]["stdout"] == execution["channels"]["stderr"] == []
                files = json.loads(bytes(execution["channels"]["filesystem:data"]))
                for phase in ("before", "after"):
                    state = files[phase]
                    assert state["complete"] is True and not state["gaps"]
                    entries = {bytes.fromhex(row["path_hex"]): row for row in state["entries"]}
                    assert set(entries) == ({b"", b"empty", b"seed.bin"} | ({b"out.bin"} if phase == "after" else set()))
                    for directory in (b"", b"empty"):
                        assert entries[directory] == {"path_hex": directory.hex(), "kind": "directory", "mode": 0o700}
                    assert entries[b"seed.bin"] == {"path_hex": b"seed.bin".hex(), "kind": "file", "mode": 0o600, "hex": "00ff"}
                    if phase == "after":
                        assert entries[b"out.bin"] == {"path_hex": b"out.bin".hex(), "kind": "file", "mode": 0o600, "hex": (b"\0\xff" + payload).hex()}
                http = json.loads(bytes(execution["channels"]["http:service"]))
                assert http["complete"] is True and not http["gaps"] and len(http["requests"]) == 1
                request = http["requests"][0]
                assert request == {"method": "POST", "target_hex": b"/effect".hex(), "version": "HTTP/1.1", "header_lines_hex": [],
                    "body_hex": payload.hex(), "response_index": 0,
                    "response_hex": b"HTTP/1.1 201 Fixture\r\nConnection: close\r\nContent-Length: 2\r\n\r\n\0\xff".hex()}
                binding = json.loads((folder / "http-controls.json").read_bytes())["environment"]["APP_SERVICE_URL"]
                bindings.add(binding)
                launch = json.loads((folder / "node-source-request.json").read_bytes())
                app = json.loads((folder / "node-source-application.json").read_bytes())
                identities.add((launch["runtime"], app["pid"]))
                if lane == "instrumented_on":
                    assert execution["witness"]["functions"] == {case["function"]: 1}
                    assert not any(execution["witness"]["losses"].values())
                    capture = json.loads((folder / "http-capture.json").read_bytes())
                    node_source_oracle.check_attempt(folder, {"function": case["function"], "language": language}, capture)
        assert len(bindings) == 1
    return identities


def framework(bundle: Path, root: Path, name: str, initial: int, count: int, language: str,
              *, promoted: bool = False) -> set[tuple[str, int]]:
    text = command([sys.executable, "-I", "-B", bundle / "test_equivalence.py" if promoted else bundle / "tests/test_equivalence.py"], root, name, 1)
    rows = [json.loads(line) for line in text.splitlines()]
    if promoted:
        preparation = rows.pop(0)
        current = Path(preparation["workspace"])
        plan = json.loads((current / "plan.json").read_bytes())
        assert plan["source_manifest"] == {file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                                           for file in bundle.parent.iterdir() if file.is_file()}
    assert len(rows) == count
    identities = set()
    for row in rows:
        identities |= check_report(Path(row["report"]), initial, 1, language)
    return identities


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--language", choices=("javascript", "typescript"), required=True)
    parser.add_argument("--compiler", choices=("native", "api"), required=True)
    args = parser.parse_args()
    root = args.root.resolve(); root.mkdir(mode=0o700)
    proof = Path(__file__).parent
    cli = proof / "quux-oteleq-3e9614e"
    provider = Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-0f05020/provider')
    os.environ.update(OTELEQ_CLI=str(cli), OTELEQ_PYTHON=sys.executable, OTELEQ_WORKSPACE_PARENT=str(root))

    def run(name, argv, expected=0):
        return command(argv, root, name, expected)

    application = root / "application"; application.mkdir()
    source = SOURCE
    if args.language == "typescript":
        source = source.replace("perform(bad)", "perform(bad:boolean)").replace("(value)", "(value:number)")
    filename = application / ("effects.mjs" if args.language == "javascript" else "effects.mts")
    filename.write_text(source)
    config = root / "policy.toml"; config.write_text(policy(args.language, args.compiler))
    workspace = Path(run("plan", [cli, "plan", "--source", application, "--otelc-root", provider, "--workspace-parent", root, "--config", config]))
    run("generate", [cli, "generate", "--workspace", workspace])
    run("run", [cli, "run", "--workspace", workspace, "--report-dir", root / "comparison"], 1)
    identities = check_report(root / "comparison/report.json", 2, 2, args.language)
    identities |= framework(workspace, root, "framework", 2, 2, args.language)
    corpus = json.loads((workspace / "tests/corpus.json").read_bytes())
    for case in corpus:
        different = case["function_id"].endswith("selected_difference")
        replay = json.loads(run("replay-" + case["id"], [cli, "replay", "--workspace", workspace, "--case", case["id"]], int(different)))
        identities |= check_report(Path(replay["report"]), 2, 1, args.language)
    exported = root / "exported"
    run("export-dry", [cli, "export-tests", "--workspace", workspace, "--destination", exported])
    assert not exported.exists()
    run("export", [cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"])
    detached = root / "detached-application"
    application.rename(detached)
    try:
        identities |= framework(exported, root, "detached-framework", 2, 2, args.language)
    finally:
        detached.rename(application)
    assert filename.read_text() == source
    promoted = application / "equivalence-tests"
    run("promote-dry", [cli, "promote", "--workspace", workspace, "--source", application, "--destination", promoted])
    assert not promoted.exists()
    run("promote", [cli, "promote", "--workspace", workspace, "--source", application, "--destination", promoted, "--apply"])
    identities |= framework(promoted, root, "promoted-original", 2, 2, args.language, promoted=True)
    changed = source.replace("let state=2;", "let state=3;")
    annotation = ":number" if args.language == "typescript" else ""
    changed += "async function selected_added(value" + annotation + "){await perform(false);state+=value;return state+value;}\n"
    filename.write_text(changed)
    identities |= framework(promoted, root, "promoted-changed", 3, 3, args.language, promoted=True)
    assert filename.read_text() == changed
    moved = root / "moved-application"
    application.rename(moved)
    identities |= framework(moved / "equivalence-tests", root, "promoted-moved", 3, 3, args.language, promoted=True)
    assert (moved / filename.name).read_text() == changed
    assert len(identities) == 64
    record = {"claim": "equivalence over these tests and observations", "applications": len(identities),
              "language": args.language, "compiler": args.compiler, "actual_application_identities": sorted(identities),
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "Declared filesystem/HTTP effects, retained replay/framework/detached routes, current-source promotion, changed bodies, added functions and moved checkout."}
    (root / "QUALIFICATION.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
