"""Independent literal oracles for the fixed JDK 21 archive qualification corpus."""
import hashlib
from pathlib import Path
from urllib.parse import unquote, urlsplit
import zipfile

import java_project_oracle as project

FUNCTION = "app.App.selected(int)"
VARIANTS = {
    "ordinary": (None, [], True, 5, 5, 13),
    "inactive": (None, [21], True, 5, 5, 13),
    "false": (b"false", [21], True, 5, 5, 13),
    "active": (b"true", [9, 17, 21, 22], True, 21, 21, 29),
    "intermediate": (b"true", [9, 17, 22], True, 17, 17, 25),
    "future": (b"true", [22], True, 5, 5, 13),
    "version-only": (b"true", [9, 22], False, 9, 9, 17),
    "folded": (b"tr\r\n ue", [21], True, 21, 5, 13),
    "identical": (b"true", [21], True, 5, 5, 29),
    "collision": (b"true", [21], True, 21, 21, 29),
    "mutation": (b"true", [21], True, 21, 21, 29),
}


def result(variant: str, amount: int) -> int:
    """Values are fixture specifications, never learned from a baseline execution."""
    _, _, _, compiled, method, resource = VARIANTS[variant]
    return 7 if variant == "mutation" else amount + compiled + method + resource + 11


def state(variant: str, amount: int, *, after: bool, instrumented: bool) -> dict:
    """Each component has its own root so equal sums cannot hide wrong selection."""
    _, _, _, compiled, method, resource = VARIANTS[variant]
    values = {"total": 2, "compiled": 0, "method": 0, "resource": 0, "directory": 0, "helper": 0}
    if after:
        values.update(total=2 + amount + int(instrumented and variant == "mutation"),
                      compiled=compiled, method=method, resource=resource, directory=11,
                      helper=3 if variant == "collision" else 0)
    return {"nodes": [], "roots": {"global:App." + name: project.scalar(value) for name, value in values.items()}}


def observation(value: dict, variant: str, amount: int, instrumented: bool) -> None:
    assert type(amount) is int and (amount == 7 or variant == "mutation" and 0 <= amount <= 7)
    assert value["function_id"] == FUNCTION and value["gaps"] == [] and value["fixture"] == {"status": "ready"}
    assert value["before"] == state(variant, amount, after=False, instrumented=instrumented)
    after = state(variant, amount, after=True, instrumented=instrumented)
    assert value["after"] == after
    graph = {"nodes": [], "roots": {**after["roots"], "result": project.scalar(result(variant, amount))}}
    assert value["outcome"] == {"kind": "return", "graph": graph}


def check_report(path: Path, variant: str) -> tuple[int, dict]:
    """Require complete independent values, two repeats and a real selected witness."""
    report = project.document(path)
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == 1
    case, = report["cases"]
    assert case["function"] == FUNCTION and case["exit_code"] == int(variant == "mutation")
    captured, = project.document(path.parent / case["case"] / "typed-bundle.json")["cases"]
    assert captured["contract"]["function_id"] == FUNCTION
    amount, = case["arguments"]
    for lane in ("baseline", "instrumented_on"):
        assert len(captured[lane]) == 2
        for attempt in captured[lane]:
            observation(attempt["observation"], variant, amount, lane == "instrumented_on")
            execution = attempt["execution"]
            assert execution["channels"]["stdout"] == execution["channels"]["stderr"] == []
            if lane == "instrumented_on":
                assert execution["witness"]["functions"] == {FUNCTION: 1}
                assert not any(execution["witness"]["losses"].values())
    return 4, report


def member(variant: str, *, compiler: bool) -> str:
    """The folded and identical fixtures deliberately distinguish identity from bytes."""
    versions = {"active": 21, "intermediate": 17, "version-only": 9,
                "identical": 21, "collision": 21, "mutation": 21}
    version = 21 if variant == "folded" and compiler else versions.get(variant)
    prefix = "META-INF/versions/" + str(version) + "/" if version else ""
    return prefix + "dep/Library.class"


def check_archives(folder: Path, variant: str) -> None:
    """Check the literal runtime member and full physical archive without a resolver clone."""
    identity = project.document(folder / "java-compiler-identity.json")
    original = Path(identity["argv"][5]).parent
    context = project.document(folder / "java-build-context.json")
    assert context["schema_version"] == 2 and context["profile"] == "source-classpath-archives-v1"
    assert context["archive_feature"] == 21 and len(context["entries"]) == 2
    directory, jar = context["entries"]
    assert directory["kind"] == "directory" and jar["kind"] == "jar"
    project.dependency(directory, original, folder)
    path = project.local(jar["path"], original, folder)
    assert jar["files"] == {"": project.sha(path)} and jar["directories"] == []
    with zipfile.ZipFile(path) as archive:
        members = {name: hashlib.sha256(archive.read(name)).hexdigest()
                   for name in archive.namelist() if name.endswith(".class")}
    assert jar["members"] == members
    selected = member(variant, compiler=False)
    assert jar["classes"] == {"dep.Library": {"entry": selected, "sha256": members[selected]}}
    assert jar["multi_release"] is (variant not in ("ordinary", "inactive", "false", "folded"))
    launch = project.document(folder / "prepared-launch.json")
    assert launch["schema_version"] == 2
    resolution = {"schema_version": 1, "profile": "java-runtime-archives-v1", "jdk_feature": 21,
                  "archives": [{"classpath_index": 2, "path": jar["path"], "sha256": project.sha(path),
                                "multi_release": jar["multi_release"], "classes": jar["classes"]}]}
    assert launch["application"]["archive_resolution"] == resolution
    assert project.document(folder / "archive-probe/probe/stdout") == resolution
    record = project.document(folder / "archive-probe/resolution.json")
    assert record["resolution"] == resolution
    java = Path(identity["argv"][0]).resolve(strict=True)
    inputs = {str(java): project.sha(java), str(java.parent.parent / "lib/modules"): project.sha(java.parent.parent / "lib/modules"),
              str(original / "archive-probe/OteleqArchives.java"): project.sha(folder / "archive-probe/OteleqArchives.java")}
    assert record["inputs_sha256"] == inputs
    assert record["argv"] == [str(java), "-Xshare:off", "-cp", str(original / "archive-probe/empty-classpath"),
                              str(original / "archive-probe/OteleqArchives.java"), *launch["ordered_classpath"]]
    frontend = Path(__file__).resolve().parents[1] / "adapters/generation/OteleqArchives.java"
    assert project.sha(frontend) == project.sha(folder / "archive-probe/OteleqArchives.java")
    expected = {(directory["path"], "other/More.class"): directory["classes"]["other.More"]["sha256"],
                (jar["path"], member(variant, compiler=True)): members[member(variant, compiler=True)]}
    reads = project.document(folder / "java-compiler.json")["class_reads_sha256"]
    actual = {}
    for uri, digest in reads.items():
        if uri.startswith("jar:"):
            location, separator, name = uri[4:].rpartition("!/")
            assert separator
            parsed = urlsplit(location)
            assert parsed.scheme == "file" and not parsed.netloc
            key = (unquote(parsed.path), unquote(name))
        else:
            parsed = urlsplit(uri)
            assert parsed.scheme == "file" and not parsed.netloc
            key = (directory["path"], Path(unquote(parsed.path)).relative_to(directory["path"]).as_posix())
        assert key not in actual
        actual[key] = digest
    assert actual == expected


def check_build(folder: Path, variant: str) -> None:
    """Bind compiler options, all inputs/products and source-class origins independently."""
    record = project.document(folder / "build-identities.json")
    identity = project.document(folder / "java-compiler-identity.json")
    metadata = project.document(folder / "java-compiler.json")
    context = project.document(folder / "java-build-context.json")
    application = project.document(folder / "prepared-application.json")
    argv = identity["argv"]
    original_project, original_classes = map(Path, argv[5:7])
    original = original_project.parent
    assert original_project == original / "project" and original_classes == original / "scratch/classes"
    assert record["schema_version"] == 1 and metadata["schema_version"] == 2 and metadata["success"] is True
    assert project.inventory(folder / "project") == record["source_sha256"]
    assert project.inventory(folder / "scratch/classes") == record["classes_sha256"]
    for name, key in (("java-compiler.json", "compiler_metadata_sha256"),
                      ("java-compiler-identity.json", "compiler_identity_sha256"),
                      ("prepared-application.json", "prepared_application_sha256"),
                      ("java-build-context.json", "java_context_sha256")):
        assert project.sha(folder / name) == record[key]
    assert metadata == project.document(folder / "build/stdout")
    assert identity["compiler_metadata_sha256"] == record["compiler_metadata_sha256"]
    project.check_compiler_tooling(folder, identity, original)
    roots = [str(original_project / "src")]
    paths = [str(original / "java-classpath/0000"), str(original / "java-classpath/0001.jar")]
    assert context["source_roots"] == roots and [entry["path"] for entry in context["entries"]] == paths
    assert metadata["options"] == ["-encoding", "UTF-8", "-proc:none", "-implicit:class", "-sourcepath", roots[0],
                                   "-classpath", ":".join(paths), "-d", str(original_classes)]
    sources = {str(original_project / "src/app/App.java"), str(original_project / "src/app/OteleqDriver.java")}
    if variant == "collision":
        sources.add(str(original_project / "src/io/quux/otelc/methods/MethodMetrics.java"))
    assert set(metadata["source_reads_sha256"]) == sources
    assert set(context["source_units"]) == sources - {str(original_project / "src/app/OteleqDriver.java")}
    assert argv[4:] == ["--context-v2", str(original_project), str(original_classes), "1", *roots,
                        "2", *paths, *context["source_units"], str(original_project / "src/app/OteleqDriver.java")]
    assert application["schema_version"] == 1 and application["classpath"] == [str(original_classes), *paths]
    assert application["main_class"] == record["main_class"] == "app.OteleqDriver"
    for name, digest in metadata["source_reads_sha256"].items():
        assert project.sha(project.local(name, original, folder)) == digest
    assert len(metadata["outputs"]) == len(application["bindings"]) == len(record["classes_sha256"])
    assert {row["class"] for row in metadata["outputs"]} == set(application["bindings"])
    for output in metadata["outputs"]:
        name = output["class"]
        relative = name.replace(".", "/") + ".class"
        source, = output["origins"]
        binding = application["bindings"][name]
        assert source in sources and output["output"] == str(original_classes / relative)
        assert binding["source"] == source and binding["source_sha256"] == metadata["source_reads_sha256"][source]
        assert binding["class_sha256"] == project.sha(folder / "scratch/classes" / relative)
        assert binding["provenance"] == "oteleq.jdk-file-manager-v1:" + record["compiler_identity_sha256"]
        policy_path = Path(source).relative_to(original_project).as_posix()
        if policy_path.endswith("/OteleqDriver.java"):
            policy_path = "_oteleq_generated/" + policy_path
        assert binding["policy_path"] == policy_path
    assert {name.replace(".", "/") + ".class" for name in application["bindings"]} == set(record["classes_sha256"])
    check_archives(folder, variant)
    project.check_origins(folder, FUNCTION)
