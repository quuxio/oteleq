# Qualification data retention

## Worktree limits

Reuse an existing checkout. Keep at most two normal development worktrees, including the canonical checkout. An additional frozen provider or maintenance checkout must name its consumer and explain why Git objects or a compressed source record are insufficient. Do not create another worktree while this limit is exceeded.

Before retiring a terminal copy, preserve source branches and required evidence, review its consumers and open files, and verify full restoration of any required archive. Keep shared Git common stores and uncommitted work. Historical source manifests alone do not require permanent expanded development copies; current original-file identity contracts remain protected until their readers are migrated explicitly.

## Live maintenance dependencies

- Keep `2026-10-20/pause-for-reboot/quux-oteleq-gh.py`: the scheduled maintenance uses this account-verifying GitHub/Git helper. Its dated parent is not evidence that this file is unused.
- Keep `work/oteleq-retention-scheduler` and its registered Git common directory. It is the dedicated scheduled source checkout. Do not remove a Git common store while any registered worktree depends on it.
- Keep the paused, uncommitted Rust query work in `work/oteleq-rust-original-query`, its pinned SDK/tool inputs and the frozen helper/source roots used by current reviews. The broader implementation goal remains paused.
- Do not delete unregistered historical data from the periodic job. Use the [assessment](2026-10-26/qualification-data-assessment.md) to establish the evidence, input references and cold boundary first.

## Complete compression for new runs

Use the maintained oteleq Make qualification targets, or `python3 -m ci.qualification_run --root /absolute/new/output -- COMMAND`. The new workflow compresses complete terminal report/audit trees, verifies every archived byte and gzip trailer, rechecks the original tree and publishes its receipt before retiring raw data. Both hosted native workflows also compress complete SDK build output and retain compressed failure evidence. See the source checkout's `docs/qualification-retention.md` for complete-bundle verification and restoration. Keep the small `OUTPUT.compressed.json` trust anchor beside each immutable compressed bundle.

Materialise a bundle before an existing reader needs raw paths. Restored inodes, change times and link counts are new filesystem facts; the index preserves the originals as historical data. Interruptions, changed content, unsupported special files and external hardlinks preserve raw data for an explicit cold retry. This workflow change does not itself rewrite the existing dated corpora or their original evidence manifests. The older selected-receipt archive profile below remains separate.

<!-- markdownlint-disable MD013 -->

Keep evidence that can reproduce or audit a published claim. Remove inactive compiler caches after retaining coverage and the exact tested CLI. Keep one accepted source/provider profile and each unique failed or reduced counterexample; retain older published evidence while its claim remains supported.

## What must remain

- Exact application/harness sources, configuration, concrete inputs, locks and source/build/tool identities.
- Commands, terminal receipts, actual process identities, application channels and complete typed observations.
- Raw OTLP, final health/loss/drain records, comparisons, refusals and independently expected values.
- Tested binaries and build inventories where retained checks bind their hashes.
- Original failed attempts and corrected audits under separate identities.

Copies of the same bytes do not require separate physical blocks. The completed APFS passes retain their original paths and byte hashes with independent copy-on-write files. They preserve mode, owner/group, flags, xattrs and nanosecond modification time. Inode/ctime/birthtime changes are permitted only for these hash-bound retained outputs. Writable hardlinks are not used. Source/provider/input roles are excluded.

`du` can count shared APFS blocks more than once. Do not add its directory totals and present that as unique physical usage. Record volume free space separately; concurrent cleanup can affect its change.

## Prevention for each new native qualification

1. Freeze source with `git archive`; do not copy `target`, `node_modules`, Go caches or another run's work directory into a source snapshot.
2. Put compiler caches outside the target application. Keep at most the current delivery cache; remove inactive caches after the outer process is terminal, coverage is retained and the tested executable is retained independently.
3. Finish all application/SDK processes and preserve the outer controller's `exit_code` and `finished_at` receipt.
4. Seal the raw evidence, then run the local retention command below. It only selects native attempt `scratch/application` and `scratch/application.otelc.json` outputs with an existing command and matching application build identity. It refuses changed content, open products, unsupported flags, symlinks and changed terminal receipts.
5. Recheck retained observations, telemetry and source/provider manifests. Keep the plan/apply receipts beside the qualification record.

Plan without replacing files:

```sh
python3 /Users/sclarke/github/oteleq-qualification/compact_native_outputs.py \
  --report-root /absolute/new/qualification \
  --terminal-receipt /absolute/controller-result.json \
  --record /absolute/new/retention-plan.json
```

Apply after checking the plan, using a distinct new record:

```sh
python3 /Users/sclarke/github/oteleq-qualification/compact_native_outputs.py \
  --report-root /absolute/new/qualification \
  --terminal-receipt /absolute/controller-result.json \
  --record /absolute/new/retention-apply.json --apply
```

This is a local maintenance command, with a pinned native helper. Its validation covers dry-run preservation, exact bytes/metadata, separate inodes, write isolation, changed-product refusal and active-input refusal. Automatic producer integration requires a separate reviewed change; it is not part of the frozen Python sequence qualification. Other Go/Rust/helper/cache profiles used in this cleanup have explicit inventoried plans, rather than an unrestricted filesystem deduplicator.

## Hosted native archive verification

The current lifetime reader `2026-10-26/audit-native-lifetime-shard-02.py` and metric reader `2026-10-26/audit-native-metric-captures-06.py` require an original archive SHA256 supplied independently from GitHub artifact metadata. They stream every member in the complete fixed selection and match its bytes to both the local index and retained copy. A rewritten local index cannot authenticate changed evidence. Keep the original ZIP, GitHub metadata, index and source archives together; materialise the selected files before reading them. Historical runner stat/kernel facts remain historical data.

Recorded invocation for the retained completed-C audit:

```sh
/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python -B \
  /Users/sclarke/github/oteleq-qualification/2026-10-26/audit-native-lifetime-shard-02.py \
  c-completed 5ae9e885330ac83e45616c6d0c867442b4907059ceec43d9e1d69d5818beb4b5
```

The readers use exclusive output directories. For an additional replay, retain a copy of the reader with a distinct output identity, as the peer review does; preserve earlier outputs. The metric reader takes language, startup state, selection-index version and the independent archive digest, in that order. The nine lifetime and six C/C++ metric strengthened original-byte audits and seven dual-interpreter regression controls are recorded under `2026-10-26/native-lifetime-d1b1a0e`, `2026-10-26/native-metric-5ff52e0` and `2026-10-26/archive-selection-regressions-01`.

## Remaining compression opportunity

A transparent APFS compression probe made no allocation saving. It was not applied to the originals.

Ordinary gzip does reduce the sampled raw receipts. One sample per class compressed Node launch/plain receipts to about 12.3% of their original size and a Java class-load log to about 6.1%. The approximately 19.4 GB Node receipt class and 3.2 GB class-log class could therefore shrink substantially. These are sample estimates, not measured complete-archive totals.

An archive change must retain an authenticated index with every original path, size, SHA256 and required metadata. Verify every member by a complete decompression before unlinking an original. Provide and test explicit restoration to the original owned paths, refusing symlinks, traversal and conflicting files. Materialise archives before invoking frozen readers. Keep active/current records directly readable. Never compress every existing COW clone independently and thereby expand its shared storage.

This reader/restore change remains separate work. The current raw receipt paths have not been removed. Unique Go/Rust binaries, frozen SDK products and source/module inputs also remain until their evidence contracts permit another representation.

## Cleanup records

The `2026-10-23` directory contains the cache inventory/removal receipt, retained coverage hashes, COW inventories, original controller outcomes, read-only recovery audit, before/after hash audits, compression samples and retention-command validation. The older native pass's original final-summary error remains recorded; its successful read-only recovery does not rewrite that attempt as successful.

## Reviewed archive restore trial, 23 October 2026

Two selected completed Node/Java corpora have fully verified archives and separately checked independent APFS copies of every original. The original-path restore trial is tracked in `2026-10-23/qualification-retention/original-path-roundtrip.json`; consult that record before using either corpus. During the trial, raw paths may be temporarily archived while originals remain in the recorded backup roots. No source/provider role is selected. Frozen readers must run only after full materialisation. The pinned indexes and restored-versus-archived status remain separate from original-content manifests.

### Current pilot availability

The two-corpus trial is complete. All 450 selected raw paths are now archived; temporary independent backups were removed only after exact restoration and matching before/after frozen-reader results. Restore these corpora before existing readers run. Every original-content manifest remains unchanged. `2026-10-23/qualification-retention/final-selected-archives.json` records the final state.

| Corpus | Archived files | Trusted index SHA256 |
| --- | ---: | --- |
| qualification-bb1fb96-stock-emission-off | 111 | `364671775f3772e4677ce40cd5a23df4b85fa036d56ce71c8a647c204972d825` |
| controls-a295-node24 | 339 | `2f8a7eab45826383dbadc1b6f392fc6716a20d5d895ead2a204fd82dc33719c8` |

Original payload bytes: 1,008,031,812; archive payload bytes: 113,005,618. The 895,026,194-byte difference excludes index/receipt overhead and is not an attribution of whole-volume free space. Other planned groups remain directly materialised and unmodified.
