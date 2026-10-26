"""Run the same independent reader probes against the exact SDK fixes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
before = ROOT.parent / 'native-prepared-review-3c8269e'
old_head = '3c8269eb62224c4f0bdd69ea3e7b63a19354b841'
new_head = '4a85c180124b0d8dbfe2a4fcda254dc50e270200'
for name in ('probe-exit-reader.py', 'probe-health-reader.py'):
    text = (before / name).read_text().replace(old_head, new_head)
    if name == 'probe-exit-reader.py':
        text = text.replace("'finding': 'No-failure records accept contradictory nonzero/killed child exit with a successful externally observed supervisor'",
                            "'regression': 'Correct control accepted; contradictory nonzero/killed child exits refused'")
        text = text.replace("assert results[0]['accepted'] and all(row['accepted'] for row in results[1:]), 'candidate behavior changed'",
                            "assert results[0]['accepted'] and all(not row['accepted'] for row in results[1:])")
    else:
        text = text.replace("'finding': 'SDK checkpoint language and selection are not joined to the verified native build'",
                            "'regression': 'Correct health accepted; wrong language and selection refused'")
        text = text.replace("assert all(row['accepted'] for row in results), 'candidate behavior changed'",
                            "assert results[0]['accepted'] and all(not row['accepted'] for row in results[1:])")
    with (ROOT / name).open('x') as output:
        output.write(text)
text = (before / 'probe-sdk-record-binding.py').read_text().replace(old_head, new_head)
text = text.replace("        native_build.verify(directory, policy)", '''        results = []
        for target in (sdk_file, directory / 'sdk/native-sdk-build.json'):
            if not target.exists():
                target.write_text('SDK validity is trusted by this isolated path-binding probe.\\n')
            manifest['sdk'] = native_gate.identity(target)
            (directory / native_build.MANIFEST).write_text(json.dumps(manifest))
            accepted = False
            try:
                native_build.verify(directory, policy)
                accepted = True
            except ValueError:
                pass
            results.append({'record': target.name, 'accepted': accepted})''')
text = text.replace("'accepted': True,", "'results': results,")
text += "\nassert results == [{'record': 'unrelated.txt', 'accepted': False}, {'record': 'native-sdk-build.json', 'accepted': True}]\n"
with (ROOT / 'probe-sdk-record-binding.py').open('x') as output:
    output.write(text)
