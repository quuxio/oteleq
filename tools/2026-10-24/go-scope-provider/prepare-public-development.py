"""Retain a development experiment with the previous independent live oracle."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
text = (ROOT.parent / 'go-live-controls/qualify-b2eebdb.py').read_text()
replacements = {
    'source-b2eebdb.json': 'source-development-01.json',
    'SDK = ROOT.parent / "go-reuse-review-d2ec6bf/source"': 'SDK = ROOT / "sdk-eda9fcc"',
    'SDK_INDEX = json.loads((SDK.parent / "inputs-before.json").read_text())': 'SDK_INDEX = json.loads((ROOT / "sdk-source.json").read_text())',
    'target-b2eebdb-public': 'target-development-01',
    'public-b2eebdb-01': 'public-development-01',
    'backend="source-v1"': 'backend="source-scope-v1"',
    'build/go-upstream/': 'build/go-upstream-scope/',
    '"head": INDEX["head"]': '"head": INDEX["parent_head"]',
    '"dirty_development_snapshot": False': '"dirty_development_snapshot": True',
    'committed diagnostic direct workflow only; retained routes and full Go remain open': 'frozen uncommitted source-scope-v1 development direct workflow with builtin shadows; retained routes and full Go remain open',
}
for before, after in replacements.items():
    assert before in text, before
    text = text.replace(before, after)
text = text.replace('(APPLICATION / "counter/api.go").write_text(text)', '''text = text.replace('package counter\\n', 'package counter\\nimport "example.test/live/domain"\\n')
text = text.replace(' int', ' domain.Number').replace('(seed int)', '(seed domain.Number)').replace('(amount int)', '(amount domain.Number)').replace(')int', ')domain.Number')
text = text.replace('panic("known")', 'domain.Fail()')
text += "\\nvar nil, any, int, bool, panic, true, false domain.Number\\n"
(APPLICATION / "domain").mkdir()
(APPLICATION / "domain/types.go").write_text('package domain\\ntype Number = int\\nfunc Fail(){panic("known")}\\n')
(APPLICATION / "counter/api.go").write_text(text)''')
text = text.replace('(\"go.mod\", \"counter/api.go\")', '("go.mod", "counter/api.go", "domain/types.go")')
text = text.replace('"cli": facts(CLI)}', '''"weaver_source": {name: facts(SDK / "build/go-upstream-scope/source" / name) for name in
                json.loads((SDK / "build/go-upstream-scope/scope-source.json").read_text())["files"]},
            "weaver_manifest": facts(SDK / "build/go-upstream-scope/scope-source.json"), "cli": facts(CLI)}''')
text = text.replace('start = json.loads((folder / "go-runtime/oteleq-go-start.json").read_text())', '''build = json.loads((folder / "go-build/build.json").read_text())
                assert build["schema_version"] == 6 and build["helper_profile"] == "private-bootstrap-v1"
                assert len(build["command_evidence"]) == 31 and build["toolchain"]["schema_version"] == 2
                retained_tools = json.loads((folder / "go-toolchain.json").read_text())
                assert len(retained_tools["state"]["queries"]) == 3
                assert isinstance(retained_tools["state"]["source"], str) and len(retained_tools["state"]["source"]) == 64
                start = json.loads((folder / "go-runtime/oteleq-go-start.json").read_text())''')
path = ROOT / 'qualify-development-01.py'
with path.open('x') as output:
    output.write(text)
print(path)
