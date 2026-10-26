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


def check_report(path: Path, initial: float, count: int) -> set[tuple[str, int]]:
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
        assert len(bindings) == 1
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
    identities = check_report(root / "comparison/report.json", 2, 2)
    (root / "PREFLIGHT.json").write_text(json.dumps({"applications": len(identities), "all_oracles_passed": True}, indent=2) + "\n")
    print(json.dumps({"preflight_applications": len(identities), "root": str(root)}), flush=True)


if __name__ == "__main__":
    main()
