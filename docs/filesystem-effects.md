# Declared filesystem effects

Generated tests for all eight language IDs can reconstruct private filesystem fixtures independently for every baseline/on attempt. The comparator requires exact before/after records as `filesystem:NAME` channels alongside typed outcomes/state and application stdout/stderr. A function returning the same value while writing different bytes is an observed difference.

## Configure a fixture

Add declarations to the same TOML policy passed to `plan --config`:

```toml
[[effects.filesystem]]
name = "data"
environment = "APP_DATA_DIR"
path_mode = "relative"
files = [{ path = "seed.bin", hex = "00ff", mode = 0o600 }]
directories = ["empty"]
max_entries = 256
max_bytes = 65536
max_depth = 16
```

Application code reads its directory through `APP_DATA_DIR`. The runner creates the fixture after compilation, before launching the worker; build tools do not receive this binding. Fixtures live under each owned external attempt directory. Original application/dependency sources and build manifests are preserved. This is trusted local application execution, with no filesystem sandbox.

The application must already accept the declared environment binding. This does not redirect hardcoded paths or substitute fixture paths into scalar arguments. Snapshots cover the whole worker, before startup and after execution/cleanup, so observed effects can include imports, initialisation and shutdown. Ordered calls share those filesystem boundaries; they do not receive intermediate filesystem snapshots.

`path_mode` defaults to `absolute`, exposing the actual private attempt path. Explicit `relative` supplies a path relative to the recorded worker directory; symmetric worker layouts can therefore receive the same literal value across independent attempts. Application output and observed values are never rewritten to conceal path differences. A working-directory change can affect application path resolution and must be assessed as part of its diagnostic harness.

Declare up to eight roots with distinct names and uppercase application environment variables. System, runtime, compiler and telemetry control variables are rejected. Names use lowercase letters, digits, `_` and `-`, beginning with a letter. Initial paths must be literal relative components: absolute paths, empty components, `.`, `..`, backslashes, colons and NUL are refused. Duplicate paths and file/directory conflicts are errors. File `hex` contains complete byte pairs; absent contents default to empty. File modes are explicit integers from `0o000` through `0o777`, defaulting to `0o600`; initial directories use `0o700`.

The example uses the default limits. `max_entries` accepts 1 through 1024 including the root, `max_bytes` accepts 0 through 65536 total regular-file bytes at each boundary, and `max_depth` accepts 1 through 16. Initial fixtures must fit. Observed paths are limited to 1024 bytes. Encoded records also count towards the configured capture budget; before/after records, typed data and other channels must fit the combined case budget. Oversized required observations cannot pass as equal prefixes.

## Observations and failures

Each attempt retains `filesystem-controls.json` with frozen declarations and actual environment bindings, plus one `filesystem-NAME.json` containing schema version 1 and before/after snapshots. Entries use lossless relative `path_hex`, `kind`, POSIX `mode` and complete file-content `hex`. The root has an empty path; its removal is an explicit `absent` record. File creation/deletion, content changes, directory membership, permission changes and root replacement are observable.

Capture uses directory descriptors and no-follow/nonblocking opens. Symlinks and special files are refused without following or consuming them. Unreadable/disappearing entries, changes detected during reading, unsupported hosts and reached bounds remain visible gaps. An incomplete initial fixture refuses execution; an incomplete final snapshot makes the required capture incomplete. Missing required channels cannot pass. Replay, generated/exported suites and scalar shrinking retain the same declarations and independently reconstruct their data.

Inode/device/link count and timestamps help detect changes during capture but are excluded from equality. Snapshots are not atomic. Transient writes restored between boundaries, hardlink/inode identity, ownership, ACLs, extended attributes, undeclared paths, network traffic and resource events are unobserved. Declared application filesystem roots do not remove any of these gaps. A separate qualified event or fixture protocol is required when those effects matter.

## Maintainer qualification

Run the maintained integration corpus with a qualified built otelc provider and Python environment:

```sh
make generation-filesystem-otelc \
  OTELC_ROOT=/absolute/path/to/otelc \
  REPORT_DIR=/absolute/path/to/new-filesystem-evidence \
  PYTHON=/absolute/path/to/otelc/.venv/bin/python
```

The [20 October exact-revision record](qualification/filesystem-effects-2026-10-20.json) completes 544 actual application launches against merged integrated otelc `0419a51`, with Rust compiler and TypeScript source backends. Other backend/project combinations need their own qualification. The corpus checks literal initial/final bytes and return values independently of lane agreement. It covers eight matching cases, eight deliberate same-return file differences, two incomplete Python effects, generated/exported suites, missing/incomplete evidence controls and scalar reduction/replay. Integration execution is separate from `make check`; implementation regressions alone do not qualify a different provider or shipping artefact. The result is **equivalence over these tests and observations**.

After the original process has terminated, the maintainer script's `--resume` option can revalidate retained completed execution routes and continue completed shrinks with the same frozen CLI/provider. All four initial routes must already exist. It refuses an unfinished shrink directory; it does not discard or restart partial evidence. Retain the earlier log separately. Copied original-shrink evidence keeps its actual original command, worker directory and fixture binding; the checker verifies matching sidecars against that original before accepting the copy.
