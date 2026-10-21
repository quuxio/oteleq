"""Independent literal and retained-build checks for Java dependency qualification."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit
import zipfile

FUNCTIONS = {"app.App.match(int)": "match", "app.App.different(int)": "different",
             "app.App.resources(int)": "resources", "app.Counter.step(int)": "receiver"}
PROFILE = "source-classpath-v1"


def sha(path: Path) -> str:
    """Read fixture bytes without calling application code."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def document(path: Path) -> dict:
    return json.loads(path.read_text())


def inventory(root: Path) -> dict:
    paths = list(root.rglob("*"))
    assert root.is_dir() and all(not path.is_symlink() for path in paths)
    return {path.relative_to(root).as_posix(): sha(path) for path in paths if path.is_file()}


def scalar(value: int, primitive: bool = False) -> dict:
    return {"kind": "integer", "type": "java.int" if primitive else "java.lang.Integer",
            "bits": 32, "signed": True, "value": str(value)}


def expected_state(value: int, total: int, amount: int, receiver: dict | None = None) -> dict:
    """Node labels are local; every declared field and alias must still match."""
    if receiver is None:
        return {"nodes": [], "roots": {"global:App.total": scalar(total)}}
    assert type(receiver) is dict and set(receiver) == {"kind", "node_id"}
    assert receiver["kind"] == "reference" and type(receiver["node_id"]) is str
    return {"roots": {"receiver": receiver, "argument:0": scalar(amount, True),
                       "static:Counter.total": scalar(total, True)},
            "nodes": [{"id": receiver["node_id"], "type": "java.object:app.Counter",
                       "fields": {"value": scalar(value, True)}}]}


def observation(value: dict, function: str, amount: int, instrumented: bool) -> None:
    """Check all boundary values against the fixture, independently of lane equality."""
    method = FUNCTIONS[function]
    assert type(amount) is int and (amount == 7 or method == "different" and 0 <= amount <= 7)
    assert value["function_id"] == function and value["gaps"] == [] and value["fixture"] == {"status": "ready"}
    receiver = receiver_reference(value["before"], method == "receiver")
    extra = int(instrumented and method == "different")
    assert value["before"] == expected_state(10, 2, amount, receiver)
    after = expected_state(10 + amount, 2 + amount + extra, amount, receiver_reference(value["after"], method == "receiver"))
    assert value["after"] == after
    result = {"match": amount + 36, "different": 7, "resources": amount + 32, "receiver": 46 + 2 * amount}[method]
    outcome = expected_state(10 + amount, 2 + amount + extra, amount,
                            receiver_reference(value["outcome"]["graph"], method == "receiver"))
    graph = {"nodes": outcome["nodes"], "roots": {**outcome["roots"], "result": scalar(result, method == "receiver")}}
    assert value["outcome"] == {"kind": "return", "graph": graph}


def receiver_reference(graph: dict, enabled: bool) -> dict | None:
    """Each boundary owns its node labels; no cross-boundary identity is inferred."""
    if not enabled:
        return None
    assert "receiver" in graph["roots"]
    return graph["roots"]["receiver"]


def check_report(path: Path, expected_cases: int | None = None) -> tuple[int, dict]:
    """A stable same-return mutation must differ; all other cases must match."""
    report = document(path)
    assert report["source_preserved"] and not report["blocked"]
    if expected_cases is not None:
        assert len(report["cases"]) == expected_cases
    launches = 0
    for case in report["cases"]:
        function, = [name for name in FUNCTIONS if name == case["function"]]
        assert case["exit_code"] == int(FUNCTIONS[function] == "different")
        bundle = document(path.parent / case["case"] / "typed-bundle.json")
        assert len(bundle["cases"]) == 1
        captured = bundle["cases"][0]
        assert captured["contract"]["function_id"] == function
        amount, = case["arguments"]
        for lane in ("baseline", "instrumented_on"):
            assert len(captured[lane]) == 2
            for attempt in captured[lane]:
                observation(attempt["observation"], function, amount, lane == "instrumented_on")
                execution = attempt["execution"]
                assert execution["channels"]["stdout"] == execution["channels"]["stderr"] == []
                if lane == "instrumented_on":
                    assert execution["witness"]["functions"] == {function: 1}
                    assert not any(execution["witness"]["losses"].values())
                launches += 1
    return launches, report


def local(name: str, original: Path, actual: Path) -> Path:
    path = Path(name)
    assert path.is_absolute() and path.is_relative_to(original)
    return actual / path.relative_to(original)


def dependency(entry: dict, original: Path, folder: Path) -> dict:
    """Recompute the complete raw JAR/resource catalogue, including empty directories."""
    path = local(entry["path"], original, folder)
    if entry["kind"] == "jar":
        assert path.suffix == ".jar" and entry["files"] == {"": sha(path)} and entry["directories"] == []
        with zipfile.ZipFile(path) as archive:
            classes = {name[:-6].replace("/", "."): {"entry": name, "sha256": hashlib.sha256(archive.read(name)).hexdigest()}
                       for name in archive.namelist() if name.endswith(".class")}
    else:
        assert entry["kind"] == "directory" and inventory(path) == entry["files"]
        assert sorted(item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_dir()) == entry["directories"]
        classes = {name[:-6].replace("/", "."): {"entry": name, "sha256": digest}
                   for name, digest in entry["files"].items() if name.endswith(".class")}
    assert classes == entry["classes"]
    return classes


def compiler_reads(reads: dict, entries: list[dict]) -> None:
    expected = {(entry["path"], value["entry"]): (name, value["sha256"])
                for entry in entries for name, value in entry["classes"].items()}
    observed = set()
    for uri, digest in reads.items():
        if uri.startswith("jar:"):
            origin, separator, relative = uri[4:].rpartition("!/")
            assert separator
            parsed = urlsplit(origin)
            assert parsed.scheme == "file" and not parsed.netloc
            key = (unquote(parsed.path), unquote(relative))
        else:
            parsed = urlsplit(uri)
            assert parsed.scheme == "file" and not parsed.netloc
            path = Path(unquote(parsed.path))
            matches = [(entry["path"], path.relative_to(entry["path"]).as_posix()) for entry in entries
                       if entry["kind"] == "directory" and path.is_relative_to(entry["path"])]
            assert len(matches) == 1
            key, = matches
        name, expected_digest = expected[key]
        assert digest == expected_digest
        observed.add(name)
    assert observed == {"dep.Library", "other.More"}


def check_build(folder: Path) -> int:
    """Do not accept a self-consistent manifest without compiler reads and actual products."""
    record = document(folder / "build-identities.json")
    identity = document(folder / "java-compiler-identity.json")
    metadata = document(folder / "java-compiler.json")
    context = document(folder / "java-build-context.json")
    application = document(folder / "prepared-application.json")
    assert record["schema_version"] == 1 and metadata["schema_version"] == 2 and metadata["success"] is True
    argv = identity["argv"]
    assert argv[1] == "-cp" and argv[4] == "--context-v2"
    original_project, original_classes = map(Path, argv[5:7])
    original = original_project.parent
    assert original_project == original / "project" and original_classes == original / "scratch/classes"
    assert context["schema_version"] == 1 and context["profile"] == PROFILE and len(context["entries"]) == 2
    assert inventory(folder / "project") == record["source_sha256"]
    assert inventory(folder / "scratch/classes") == record["classes_sha256"]
    for name, key in (("java-compiler.json", "compiler_metadata_sha256"),
                      ("java-compiler-identity.json", "compiler_identity_sha256"),
                      ("prepared-application.json", "prepared_application_sha256"),
                      ("java-build-context.json", "java_context_sha256")):
        assert sha(folder / name) == record[key]
    assert metadata == document(folder / "build/stdout") and identity["compiler_metadata_sha256"] == record["compiler_metadata_sha256"]
    assert context["source_roots"] == [str(original_project / name) for name in ("src/main/java", "target/generated-sources")]
    paths = [entry["path"] for entry in context["entries"]]
    assert paths == [str(original / "java-classpath/0000.jar"), str(original / "java-classpath/0001")]
    assert metadata["options"] == ["-encoding", "UTF-8", "-proc:none", "-implicit:class", "-sourcepath",
        os.pathsep.join(context["source_roots"]), "-classpath", os.pathsep.join(paths), "-d", str(original_classes)]
    assert application["schema_version"] == 1 and application["classpath"] == [str(original_classes), *paths]
    assert application["main_class"] == record["main_class"] == "app.OteleqDriver"
    check_compiler_tooling(folder, identity, original)
    for entry in context["entries"]:
        dependency(entry, original, folder)
    compiler_reads(metadata["class_reads_sha256"], context["entries"])
    expected_sources = {str(original_project / name) for name in (
        "src/main/java/app/App.java", "src/main/java/app/Counter.java", "src/main/java/app/Helper.java",
        "target/generated-sources/app/Generated.java", "src/main/java/app/OteleqDriver.java")}
    assert set(metadata["source_reads_sha256"]) == expected_sources
    assert set(context["source_units"]) == expected_sources - {str(original_project / "src/main/java/app/OteleqDriver.java")}
    for name, digest in metadata["source_reads_sha256"].items():
        assert sha(local(name, original, folder)) == digest
    assert argv[7:] == ["2", *context["source_roots"], "2", *paths, *context["source_units"],
                        str(original_project / "src/main/java/app/OteleqDriver.java")]
    outputs = metadata["outputs"]
    assert len(outputs) == len(application["bindings"]) == len(record["classes_sha256"])
    assert {row["class"] for row in outputs} == set(application["bindings"])
    expected_origins = {"app." + name: str(original_project / relative) for name, relative in (
        ("App", "src/main/java/app/App.java"), ("Counter", "src/main/java/app/Counter.java"),
        ("Helper", "src/main/java/app/Helper.java"), ("Generated", "target/generated-sources/app/Generated.java"),
        ("OteleqDriver", "src/main/java/app/OteleqDriver.java"), ("OteleqGraph", "src/main/java/app/OteleqDriver.java"))}
    assert {"app.App", "app.Counter", "app.Helper", "app.Generated", "app.OteleqDriver"}.issubset(application["bindings"])
    for output in outputs:
        name = output["class"]
        source, = output["origins"]
        assert source == expected_origins[name.split("$", 1)[0]]
        relative = name.replace(".", "/") + ".class"
        binding = application["bindings"][name]
        assert output["output"] == str(original_classes / relative)
        assert binding["source"] == source and binding["source_sha256"] == metadata["source_reads_sha256"][source]
        assert binding["class_sha256"] == sha(folder / "scratch/classes" / relative)
        policy_path = Path(source).relative_to(original_project).as_posix()
        if policy_path.endswith("/OteleqDriver.java"):
            policy_path = "_oteleq_generated/" + policy_path
        assert binding["policy_path"] == policy_path
        assert binding["provenance"] == "oteleq.jdk-file-manager-v1:" + record["compiler_identity_sha256"]
    assert {name.replace(".", "/") + ".class" for name in application["bindings"]} == set(record["classes_sha256"])
    return len(outputs)


def check_compiler_tooling(folder: Path, identity: dict, original: Path) -> None:
    """Bind the actual JDK, complete module image and fixed frontend independently."""
    java = Path(os.environ.get("OTELC_JAVA") or shutil.which("java")).resolve()
    frontend = original / "compiler-tool/OteleqCompile.java"
    argv = identity["argv"]
    assert Path(argv[0]).resolve() == java
    assert argv[1:4] == ["-cp", str(original / "compiler-classpath"), str(frontend)]
    assert set(identity["inputs_sha256"]) == {str(java), str(java.parent.parent / "lib/modules"), str(frontend)}
    for name, digest in identity["inputs_sha256"].items():
        path = local(name, original, folder) if Path(name).is_relative_to(original) else Path(name)
        assert sha(path) == digest
    expected_frontend = Path(__file__).resolve().parents[1] / "adapters/generation/OteleqCompile.java"
    assert sha(folder / "compiler-tool/OteleqCompile.java") == sha(expected_frontend)


def check_origins(folder: Path, function: str) -> None:
    launch = folder / "prepared-launch.json"
    log = folder / "sdk-runtime/class-load.log" if launch.exists() else folder / "class-load.log"
    identity = document(folder / "java-compiler-identity.json")
    original = Path(identity["argv"][5]).parent
    application = document(folder / "prepared-application.json")
    context = document(folder / "java-build-context.json")
    expected = {name: "file:" + str(original / "scratch/classes") + "/" for name in application["bindings"]}
    for entry in context["entries"]:
        origin = "file:" + entry["path"] + ("/" if entry["kind"] == "directory" else "")
        for name in entry["classes"]:
            assert name not in expected
            expected[name] = origin
    observed = {}
    for line in log.read_text().splitlines():
        match = re.search(r"\] ([^ ]+) source: (.+)$", line)
        if match and match[1] in expected:
            assert match[1] not in observed and unquote(match[2]) == expected[match[1]]
            observed[match[1]] = match[2]
    assert document(folder / "verified-origins.json") == observed
    owner = function.split("(", 1)[0].rsplit(".", 1)[0]
    assert {owner, "app.OteleqDriver", "dep.Library", "other.More"}.issubset(observed)
