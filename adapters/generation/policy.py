"""Validate and freeze selection, concrete fixtures and execution policy."""
from collections.abc import Mapping
import fnmatch
import json
import keyword
import math
from pathlib import Path
import tomllib
from typing import Any

import domains
import filesystem_effects
import http_effects
import java_provider
import java_profiles
import java_actions
import java_project
import go_project
import native_source
import node_source
import python_provider
import preconditions
import return_expectations
import sequences
import typescript_provider


LANGUAGES = ("c", "cpp", "rust", "python", "java", "javascript", "typescript", "go")
MAX_CASES = domains.MAX_CASES
MAX_CHANNEL_BYTES = 256 * 1024
DEFAULTS = {
    "schema_version": 1,
    "languages": list(LANGUAGES),
    "sources": {"include": ["**"], "exclude": []},
    "functions": {"include": ["*"], "exclude": []},
    "generation": {"seed": 20261008, "cases_per_function": 3},
    "limits": {"case_timeout_ms": 60000, "baseline_repeats": 2,
               "instrumented_repeats": 2, "max_capture_bytes": MAX_CHANNEL_BYTES},
    "fixtures": [],
    "effects": {"filesystem": []},
    "adapters": {"rust": {"backend": "compiler"}, "python": {"import_roots": []},
                 "go": {"module_roots": [], "build_tags": [], "build_timeout_ms": 180000}, "typescript": {"backend": "source"},
                 "java": {"backend": "legacy"}},
}


def keys(document: Mapping[str, Any], allowed: set[str], label: str) -> None:
    """Reject misspellings and capabilities which would otherwise be ignored."""
    if not isinstance(document, dict) or set(document) - allowed:
        raise ValueError(f"unsupported {label} fields; allowed: {', '.join(sorted(allowed))}")


def strings(value: Any, label: str, *, empty: bool = False) -> list[str]:
    """Read distinct nonblank strings, preserving the configured order."""
    if (not isinstance(value, list) or not empty and not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{label} must be a list of distinct nonblank strings")
    return value.copy()


def integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    """Exclude booleans and out-of-contract resource settings."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def expected_baseline(value: Any) -> dict[str, Any]:
    """An intentional error is declared by the caller, never inferred from lanes."""
    keys(value, {"kind", "category", "type", "value"}, "expected_baseline")
    if value.get("kind") == "return" and set(value) == {"kind"}:
        return {"kind": "return"}
    if value.get("kind") == "return_value" and set(value) == {"kind", "value"}:
        return {"kind": "return_value", "value": return_expectations.validate(value["value"])}
    if (set(value) == {"kind", "category", "type"} and value.get("kind") == "error"
            and value.get("category") in ("exception", "panic") and type(value.get("type")) is str
            and 0 < len(value["type"]) <= 1024 and value["type"].strip()):
        return value.copy()
    raise ValueError("expected_baseline requires return, a typed return_value or an explicit error category/type")


def scalar_arguments(value: Any) -> bool:
    """Recognise the same finite scalar list for case and construction inputs."""
    return isinstance(value, list) and all(type(item) in (str, int, float, bool)
                                          and (type(item) is not float or math.isfinite(item)) for item in value)


def fixture_cases(value: dict, label: str) -> list[list[Any]] | None:
    """A missing case list selects domain generation; explicit lists stay strict."""
    if "cases" not in value:
        if "domains" not in value:
            raise ValueError(f"{label} requires concrete cases or declared scalar domains")
        return None
    cases = value["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError(f"{label}.cases must contain 1 to {MAX_CASES} argument lists")
    for arguments in cases:
        if not scalar_arguments(arguments):
            raise ValueError(f"{label} currently requires finite scalar arguments")
    identities = [json.dumps(arguments, ensure_ascii=True, allow_nan=False) for arguments in cases]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{label} contains duplicate concrete cases")
    return cases


def fixture(value: Any, index: int) -> dict[str, Any]:
    """Validate concrete cases or independent domains without executing target code."""
    label = f"fixtures[{index}]"
    keys(value, {"function", "source", "language", "cases", "expected_baseline", "domains", "preconditions", "receiver", "sequence"}, label)
    function, source = value.get("function"), value.get("source", "**")
    if any(not isinstance(item, str) or not item.strip() for item in (function, source)):
        raise ValueError(f"{label} requires a function pattern and source pattern")
    language = value.get("language")
    if language is not None and language not in LANGUAGES:
        raise ValueError(f"{label} has an unsupported language")
    cases = fixture_cases(value, label)
    result = {"function": function, "source": source, "language": language,
              "expected_baseline": expected_baseline(value.get("expected_baseline", {"kind": "return"}))}
    if cases is not None:
        result["cases"] = cases
    if "domains" in value:
        result["domains"] = fixture_domains(value["domains"], cases or [], label)
    if "preconditions" in value:
        result["preconditions"] = preconditions.validate(value["preconditions"])
        if "domains" in result:
            preconditions.bind(result["preconditions"], len(result["domains"]))
        for arguments in cases or []:
            preconditions.require(arguments, result["preconditions"])
    if "receiver" in value:
        result["receiver"] = receiver(value["receiver"])
    if "sequence" in value:
        result["sequence"] = sequences.fixture(value, expected_baseline)
    return result


def receiver(value: Any) -> dict[str, Any]:
    """Declare a same-module constructor/factory; application code runs in workers."""
    keys(value, {"factory", "arguments"}, "fixture.receiver")
    factory, arguments = value.get("factory"), value.get("arguments", [])
    parts = factory.split("::") if isinstance(factory, str) else []
    if not parts or not all(part.isidentifier() for part in parts) or len(parts) == 1 and keyword.iskeyword(factory):
        raise ValueError("receiver.factory requires one ordinary same-module class or function name")
    if not scalar_arguments(arguments):
        raise ValueError("receiver.arguments requires finite scalar constructor inputs")
    return {"factory": factory, "arguments": arguments.copy()}


def fixture_domains(value: Any, cases: list[list[Any]], label: str) -> list[dict]:
    """Validate independent domains and any explicit concrete fixtures together."""
    if not isinstance(value, list):
        raise ValueError(label + ".domains must be an array")
    result = [domains.validate(item) for item in value]
    for arguments in cases:
        domains.arguments(arguments, result)
    return result


def load(path: Path | None) -> dict[str, Any]:
    """Return a complete immutable-by-convention policy suitable for the owned plan."""
    if path is not None and (not path.is_file() or path.stat().st_size > 1024 * 1024):
        raise ValueError("generation policy must be a regular file of at most 1 MiB")
    document = tomllib.loads(path.read_text(encoding="utf-8")) if path is not None else {}
    return validate(document)


def adapters(value: Any) -> dict[str, Any]:
    """Freeze explicit provider selection without guessing execution support."""
    keys(value, {"c", "cpp", "rust", "python", "go", "typescript", "java", "node"}, "adapters")
    rust = value.get("rust", {})
    keys(rust, {"backend"}, "adapters.rust")
    backend = rust.get("backend", "compiler")
    if type(backend) is not str or backend not in ("compiler", "llvm"):
        raise ValueError("adapters.rust.backend must be compiler or llvm")
    python = value.get("python", {})
    typed = value.get("typescript", {})
    keys(typed, {"backend"}, "adapters.typescript")
    node = node_source.settings(value["node"]) if "node" in value else None
    if node is not None and node["backend"] == node_source.SOURCE and typed.get("backend", "source") != "source":
        raise ValueError("source-v1 uses adapters.node.typescript_compiler; legacy TypeScript backend must remain source")
    java = value.get("java", {})
    keys(java, {"backend", "profile", "source_roots", "classpath", "witness_profile"}, "adapters.java")
    java_provider.backend(java.get("backend", "legacy"))
    return {**{language: native_source.settings(value[language]) for language in ('c', 'cpp') if language in value},
            **({"node": node} if node is not None else {}),
            "rust": {"backend": backend},
            "typescript": {"backend": typescript_provider.backend(typed.get("backend", "source"))},
            "java": {**java_profiles.settings(java), **java_project.settings(java), **java_actions.settings(java)},
            "python": python_provider.settings(python),
            "go": go_project.settings(value.get("go", {}))}


def validate(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate either parsed TOML or the resolved policy in an owned JSON plan."""
    keys(document, set(DEFAULTS), "policy")
    if type(document.get("schema_version", 1)) is not int or document.get("schema_version", 1) != 1:
        raise ValueError("unsupported generation policy schema_version")
    result = {"schema_version": 1}
    result["languages"] = strings(document.get("languages", list(LANGUAGES)), "languages")
    if set(result["languages"]) - set(LANGUAGES):
        raise ValueError("policy contains an unsupported language")
    for name in ("sources", "functions"):
        section = document.get(name, {})
        keys(section, {"include", "exclude"}, name)
        result[name] = {key: strings(section.get(key, DEFAULTS[name][key]), f"{name}.{key}", empty=key == "exclude")
                        for key in ("include", "exclude")}
    section = document.get("generation", {})
    keys(section, {"seed", "cases_per_function"}, "generation")
    result["generation"] = {
        "seed": integer(section.get("seed", DEFAULTS["generation"]["seed"]), 0, 2**64 - 1, "generation.seed"),
        "cases_per_function": integer(section.get("cases_per_function", 3), 1, MAX_CASES, "generation.cases_per_function"),
    }
    section = document.get("limits", {})
    keys(section, set(DEFAULTS["limits"]), "limits")
    bounds = {"case_timeout_ms": (1, 900000), "baseline_repeats": (2, 32),
              "instrumented_repeats": (2, 32), "max_capture_bytes": (1, MAX_CHANNEL_BYTES)}
    result["limits"] = {key: integer(section.get(key, DEFAULTS["limits"][key]), low, high, "limits." + key)
                        for key, (low, high) in bounds.items()}
    fixtures = document.get("fixtures", [])
    if not isinstance(fixtures, list):
        raise ValueError("fixtures must be an array of tables")
    result["fixtures"] = [fixture(value, index) for index, value in enumerate(fixtures)]
    result["adapters"] = adapters(document.get("adapters", {}))
    result["effects"] = effects(document.get("effects", {}))
    return result


def effects(value: Any) -> dict:
    """Freeze supported effect protocols without overlapping process bindings."""
    keys(value, {"filesystem", "http"}, "effects")
    result = filesystem_effects.settings({"filesystem": value.get("filesystem", [])}, keys, integer)
    if "http" in value:
        result["http"] = http_effects.settings(value["http"], keys, integer)
    environments = [item["environment"] for entries in result.values() for item in entries]
    if len(environments) != len(set(environments)):
        raise ValueError("effect fixture environments must be distinct across protocols")
    return result


def selected(value: str, section: Mapping[str, list[str]]) -> bool:
    """Match complete POSIX paths or qualified function IDs with case-sensitive globs."""
    return (any(fnmatch.fnmatchcase(value, pattern) for pattern in section["include"])
            and not any(fnmatch.fnmatchcase(value, pattern) for pattern in section["exclude"]))


def matching_fixture(entry: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve exactly one matching fixture, retaining ambiguity as an error."""
    found = [item for item in config["fixtures"]
             if fixture_matches(entry, item)]
    if len(found) > 1:
        raise ValueError("multiple configured fixtures match " + entry["otelc_function"])
    return found[0] if found else None


def concrete_cases(entry: Mapping[str, Any], config: Mapping[str, Any]) -> list[list[Any]] | None:
    """Read reviewed concrete cases through the single fixture selection rule."""
    matched = matching_fixture(entry, config)
    return matched.get("cases") if matched else None


def fixture_matches(entry: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    """Match a language-scoped fixture to its original callable and source path."""
    return (item.get("language") in (None, entry.get("language"))
            and fnmatch.fnmatchcase(entry["otelc_function"], item["function"])
            and fnmatch.fnmatchcase(entry["path"], item["source"]))
