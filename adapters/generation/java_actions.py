"""Explicit generated Java invocation inputs, independent of producer metadata."""

import hashlib
import json

import java_handle_callers as callers
import java_profiles
import java_witness as witness

FIELD = 'java_witness_profile'
FINISH = '''OteleqRendezvous.awaitRelease(java.lang.System.getenv("OTELEQ_ACTION_IDS").split(",",-1)[OTELEQ_ACTION_POSITION]);'''


def settings(options: dict) -> dict:
    """Keep older generated profiles unchanged unless explicitly selected."""
    if 'witness_profile' not in options:
        return {}
    witness.require(type(options['witness_profile']) is str and options['witness_profile'] == witness.HANDLE_PROFILE
                    and type(options.get('backend')) is str and options['backend'] == 'prepared'
                    and type(options.get('profile')) is str
                    and options['profile'] in (java_profiles.SAFE, java_profiles.ARCHIVES),
                    "generated handles require the explicit safe/archive prepared Java profile")
    return {'witness_profile': witness.HANDLE_PROFILE}


def enabled(entry: dict) -> bool:
    """A malformed explicit selection cannot silently choose the old witness."""
    if FIELD not in entry:
        return False
    witness.require(entry.get('language') == 'java', "Java witness selected for another language")
    settings({'backend': entry.get('java_backend'), 'profile': entry.get('java_profile'),
              'witness_profile': entry[FIELD]})
    return True


def qualified(entry: dict, name: str) -> str:
    prefix = entry['package'] + '.' if entry['package'] else ''
    return name if prefix and name.startswith(prefix) else prefix + name


def references(entry: dict, owners: list[str] | None = None) -> dict[str, str]:
    """Bind declared source models to independently compiled binary class names."""
    result = {}
    names = [model['name'] for model in entry.get('java_models', [])]
    if 'receiver_class' in entry:
        names.append(entry['receiver_class'])
    for name in names:
        source = qualified(entry, name)
        if owners is None:
            binary = source
        else:
            matches = [owner for owner in owners if owner.replace('$', '.') == source]
            witness.require(len(matches) == 1, "declared Java model has no unique compiler class")
            binary = matches[0]
        result[name] = binary.replace('.', '/')
        result[source] = result[name]
    return result


def members(entry: dict, *, owner: str | None = None, owners: list[str] | None = None) -> tuple[str, dict, object]:
    """Emit source from the frozen declaration; resolve binary identities at build."""
    witness.require(enabled(entry), "generated action caller requires explicit selection")
    instance = 'receiver_fixture' in entry
    source = entry['receiver_class'] if instance else entry['name'].rsplit('.', 1)[0]
    qualified_source = qualified(entry, source)
    if owner is not None:
        witness.require(owner.replace('$', '.') == qualified_source, "compiled target changed the declared Java owner")
    binary = (owner or qualified_source).replace('.', '/')
    caller = ((entry['package'].replace('.', '/') + '/') if entry['package'] else '') + 'OteleqDriver'
    return callers.members(source, binary, entry['name'].rsplit('.', 1)[-1], entry['parameters'], entry['output'],
                           caller_owner=caller, instance=instance, references=references(entry, owners))


def declarations(entry: dict, owner: str, owners: list[str]) -> tuple[dict, object]:
    """Compiler class names may refine descriptors, never change emitted source."""
    source, expected, route = members(entry, owner=owner, owners=owners)
    witness.require(source == members(entry)[0], "binary binding changed the generated caller source")
    return expected, route


def case_id(case: dict) -> str:
    """Bind the whole frozen case, including construction and sequence inputs."""
    witness.require(type(case) is dict and type(case.get('id')) is str and 0 < len(case['id']) <= 1024,
                    "invalid generated case identity")
    raw = json.dumps(case, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def action_ids(case: dict) -> list[str]:
    """Freeze distinct call IDs and a final barrier before the JVM starts."""
    identity = case_id(case)
    schedule = case.get('sequence')
    witness.require(schedule is None or type(schedule) is list
                    and all(type(step) is dict and step.get('action') == 'call' for step in schedule),
                    "unsupported generated Java action schedule")
    count = len(schedule) if schedule is not None else 1
    witness.require(0 < count <= 64, "generated Java action count exceeds the supported scope bound")
    labels = ['call-' + str(index) for index in range(count)] + ['finish']
    return [hashlib.sha256((identity + '\n' + label).encode()).hexdigest() for label in labels]
