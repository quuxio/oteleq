"""Independently reconstruct the fixed build-4, no-task Go context profile."""

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

import go_context_sources as source
import go_files as files
from go_provider import require

RULES_FILE = "otelc.yaml"

BUNDLE_SHA256 = "4a928c69ce269e37c98413c93159713fa7bcd8169c5d6b4de167305dc5ca9bb2"
LICENCE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 1024 * 1024
TRACE = "instrumentation/go.opentelemetry.io/otel/sdk/trace/"
INPUTS = {
    **{"instrumentation_temp/go.opentelemetry.io/otel/sdk/trace/" + name: TRACE + name
       for name in ("gls.go", "go.mod", "go.sum", "hook.go", "otel_trace_context.go", RULES_FILE)},
    **{"instrumentation_temp/runtime/" + name: "instrumentation/runtime/" + name
       for name in ("go.mod", RULES_FILE, "runtime_gls.go", "stub.go")},
    "pkg_temp/go.mod": "pkg/go.mod", "pkg_temp/hook/context.go": "pkg/hook/context.go",
    "pkg_temp/runtime/trace_context.go": "pkg/runtime/trace_context.go",
}


def digest(data: bytes) -> str:
    """Bind literal bytes without producer-selected serialisation."""
    return hashlib.sha256(data).hexdigest()


def members(data: bytes) -> dict[str, bytes]:
    """Read only fixed ordinary members; never extract paths from the archive."""
    selected = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            if member.name not in INPUTS:
                continue
            require(member.name not in selected and member.isfile() and 0 <= member.size <= MAX_MEMBER_BYTES,
                    "invalid or repeated Go context archive member")
            stream = archive.extractfile(member)
            with stream:
                selected[member.name] = stream.read(MAX_MEMBER_BYTES + 1)
            require(len(selected[member.name]) == member.size, "incomplete Go context archive member")
    require(set(selected) == set(INPUTS), "incomplete Go context archive")
    return selected


def replace_once(data: bytes, old: bytes, new: bytes) -> bytes:
    """A different pinned source shape requires an explicit recipe change."""
    require(data.count(old) == 1, "Go context source differs from fixed patch")
    return data.replace(old, new)


def render(original: dict[str, bytes], licence: bytes) -> dict[str, bytes]:
    """Apply the reviewed no-task recipe without calling SDK renderers."""
    require(type(original) is dict and set(original) == set(INPUTS)
            and all(type(value) is bytes and len(value) <= MAX_MEMBER_BYTES for value in original.values()),
            "invalid Go context source denominator")
    require(type(licence) is bytes and digest(licence) == LICENCE_SHA256,
            "Go context licence differs from pinned attribution")
    result = {INPUTS[name]: value for name, value in original.items()}
    path = TRACE + "otel_trace_context.go"
    value = replace_once(result[path], b"import (\n", b'import (\n\t"context"\n')
    value = replace_once(value, b"ended *atomic.Bool\n}", b"ended *atomic.Bool\n\ttelemetry context.Context\n}")
    value = replace_once(value, b"&spanWrapper{span, tc.sw, stateForSpan(span)}",
                         b"&spanWrapper{span: span, prev: tc.sw, ended: stateForSpan(span)}")
    result[path] = replace_once(value, b"&spanWrapper{last, nil, tc.sw.ended}",
                               b"&spanWrapper{last, nil, tc.sw.ended, tc.sw.telemetry}")
    path = "instrumentation/runtime/otelc.yaml"
    marker = b"goroutine_propagate:\n"
    require(result[path].count(marker) == 1, "Go task reset rule differs from fixed patch")
    result[path] = result[path].split(marker)[0] + source.RESET_RULE
    result["pkg/runtime/trace_context.go"] += source.DETACH_BRIDGE
    result[TRACE + RULES_FILE] += source.DETACH_RULE + source.TELEMETRY_RULES
    result.update({TRACE + "otelc_detached_span.go": source.DETACH_SOURCE,
                   TRACE + "otelc_telemetry_context.go": source.TELEMETRY_SOURCE,
                   TRACE + "otelc_baggage_context.go": source.BAGGAGE_SOURCE,
                   "pkg/runtime/go.mod": source.BRIDGE_MODULE,
                   "pkg/runtime/otelc_telemetry_context.go": source.TELEMETRY_BRIDGE,
                   "LICENSE.upstream": licence, "NOTICE.upstream": source.NOTICE})
    manifest = {"schema_version": 1, "upstream_module": "go.opentelemetry.io/otelc", "upstream_version": "v1.0.1",
                "upstream_commit": "3b9beed7a1200cf16e59bafa431dd4c4a0601f41",
                "module_sum": "h1:HSgkn7kGhHe4kjtv+ex0ZFRbC66sc+c5KcEHgDXuwxE=",
                "module_go_sum": "h1:fOCi1cByxU0s3sOwXPp5/gAnxsPl5KsTM9elgtBIESE=",
                "bundle_sha256": BUNDLE_SHA256, "tasks": False,
                "detached_spans": "explicit-non-ending-unlink-v1", "telemetry_context": "span-and-baggage-v1",
                "input_files": {name: digest(value) for name, value in original.items()},
                "files": {name: digest(value) for name, value in result.items()},
                "scope": "generated context hooks only; not Go adapter or provider admission"}
    result["context-bundle.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    return result


def reconstruct(bundle: Path) -> dict[str, bytes]:
    """Check the official bundle and vendored licence before rendering bytes."""
    identity, _, raw = files.file(bundle, MAX_BUNDLE_BYTES, keep=True)
    require(identity["sha256"] == BUNDLE_SHA256, "Go context bundle differs from pinned upstream")
    licence_path = Path(__file__).resolve().with_name("go_context_APACHE.txt")
    _, _, licence = files.file(licence_path, MAX_MEMBER_BYTES, keep=True)
    return render(members(raw), licence)


def prepare(bundle: Path, output: Path) -> files.Snapshot:
    """Create a new caller-owned expected profile before the producer build."""
    require(output.is_absolute() and output.parent.resolve(strict=True) == output.parent,
            "Go expected context needs a canonical parent")
    values = reconstruct(bundle)
    output.mkdir(mode=0o700)
    for name, data in values.items():
        directory = output
        for part in Path(name).parts[:-1]:
            directory /= part
            directory.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    result = files.freeze(output)
    require(set(result.identities) == set(values)
            and all(result.identities[name]["sha256"] == digest(data) for name, data in values.items()),
            "Go expected context differs after publication")
    result.verify()
    return result
