# Qualification storage and restoration

<!-- markdownlint-disable MD013 -->

## Automatic complete qualification bundles

All 50 Make qualification targets now run through `ci.qualification_run`. After the maintained qualifier finishes its application/exporter cleanup, the wrapper compresses every file, directory and symbolic link in `REPORT_DIR`, including binaries, source snapshots, raw telemetry, logs, manifests and failed-attempt records. Python and Go control targets also compress `AUDIT_DIR`. No language-specific selection is used; this storage workflow applies to all eight languages. The wrapper preserves the qualification command's nonzero exit code. A compression failure fails an otherwise successful command and preserves its raw outputs. An interrupted run retains raw outputs for a later explicit cold pack.

Each output becomes a new sibling `OUTPUT.bundle-UNIQUE_ID` directory containing `qualification.tar.gz`, `files.jsonl.gz` and a small `receipt.json`. `OUTPUT.compressed.json` records the bundle path, command outcome and trusted receipt SHA256. The complete index is compressed as well as the data. Packing and verification stream their payloads; they do not create a temporary uncompressed tar or read an entire binary into memory. Complete decompression, exact member identities, hashes, gzip trailers, a restoration probe for each distinct metadata class on the original output volume and a second complete comparison with the original tree must pass before raw removal. There is no automatic history purge or replacement of an older bundle.

For direct qualifier invocations, use the same wrapper:

```sh
python3 -m ci.qualification_run --root /absolute/new/evidence -- \
  python3 tests/qualify_generation.py \
    --otelc-root /absolute/provider --report-dir /absolute/new/evidence \
    --cli /absolute/quux-oteleq
```

Choose a new output path. The wrapper refuses existing unrelated output trees before starting a command. For a retained-only command it accepts a previously owned compressed output, restores it if necessary, runs the explicit `--retained-only` command, then compresses the complete result again. Supply a new audit output when that qualifier requires one. Commands that inspect a report without this wrapper must first restore its bundle.

Archive reads, restoration and raw deletion are restricted to dedicated qualification storage. The defaults are the platform temporary directory, the hosted `RUNNER_TEMP` and the checkout's existing `oteleq-qualification` workspace. To use another persistent location, first create a dedicated directory and set `OTELEQ_QUALIFICATION_HOME` to its absolute path in your environment. An output must be a child of that directory; the storage root itself, a whole home directory and arbitrary CLI paths cannot be archived or removed. This setting is independent of `REPORT_DIR` and archive metadata.

Both hosted native workflows compress their full evidence and SDK build directories after successful or failed commands, including failed SDK builds. Cancellation skips raw retirement because child cleanup may have been interrupted. Their artifact upload uses `always()`, includes any remaining raw trees and uses ZIP compression level 9 as a fallback after cancellation or compression refusal. Hidden evidence is included. An incomplete archive or failed qualification remains a failure; successful storage is not a successful equivalence result. The existing seven-day hosted retention period is unchanged.

## Verify or restore a complete bundle

Read the exact bundle path and `receipt_sha256` from the separately retained `OUTPUT.compressed.json`. The following commands use that recorded hash as the trust anchor:

```sh
python3 -m ci.qualification_bundle verify \
  --store /absolute/evidence.bundle-UNIQUE_ID \
  --receipt-sha256 RECORDED_RECEIPT_SHA256

python3 -m ci.qualification_bundle restore \
  --store /absolute/evidence.bundle-UNIQUE_ID \
  --receipt-sha256 RECORDED_RECEIPT_SHA256 \
  --root /absolute/evidence
```

Restore requires a new destination with an existing canonical parent. It never overwrites an existing tree or extracts files through a symbolic link. Symbolic links are restored only after regular files; their original targets remain data and are never executed. Keep restored links inside this private evidence tree and do not follow a recorded external target without separately checking it. Regular file bytes, modes, owner/group, extended attributes and nanosecond modification times are retained. Restored hardlinked regular files are independent copies. Inodes, change times and original link counts remain historical facts in the compressed index. Restoring data does not reproduce the original kernel identities or recertify an original launch; readers that require those original live facts need their documented retained-data path.

Existing completed trees are not rewritten by this workflow change. Once their readers, applications and exporters have stopped, pack an explicitly selected whole tree with:

```sh
python3 -m ci.qualification_bundle pack \
  --root /absolute/completed/evidence \
  --store /absolute/completed/evidence-bundle \
  --confirm-cold --remove-raw
```

Retain its returned receipt hash separately. Omit `--remove-raw` for a preservation-only pack. Special files such as sockets, set-ID permissions and filesystem flags refuse packing and leave raw data present. Raw removal also refuses hardlinks with another link outside the selected tree, because unlinking them would change external file facts. A cold corpus with no concurrent writers is required; a child process exiting does not prove that an unrelated application has stopped. Stop and inspect all processes before standalone packing. Allow room for the compressed result while the originals still exist. Compression ratios depend on the data; already compressed archives can save little. Old APFS clones can share physical blocks, so directory byte totals are not a promise of recoverable space.

## Earlier selected cold-receipt profile

The existing checkout-only cold-receipt tool remains available for historic corpora without changing their original-content manifests. It supports generated `node-runtime/node-launch.json`, `node-runtime/node-plain-launch.json` and prepared Java `sdk-runtime/class-load.log` files. That earlier profile does not archive application binaries, source snapshots, providers, dependencies or compiler inputs. Neither storage profile adds application capability or equivalence evidence.

## Establish the cold boundary

Stop all readers, applications, exporters, qualifiers and other writers for the selected corpus. Check live processes and open files separately. The tool's exclusive lock prevents two operations on the same archive; it does not prove that application processes have stopped or lock unrelated archives. Never evict files used by another active chat or qualification.

Use a canonical absolute corpus root and a new archive directory outside it. Select exact relative paths explicitly; the command does not discover candidates or execute recorded commands. For example, save this selection outside the corpus:

```json
{
  "schema_version": 1,
  "kind": "oteleq.cold-receipts",
  "root": "/absolute/qualification/completed-corpus",
  "paths": [
    "comparison/case/baseline-0/node-runtime/node-plain-launch.json",
    "comparison/case/instrumented_on-0/node-runtime/node-launch.json"
  ]
}
```

From the oteleq checkout, with Python 3.12 or later:

```sh
python3 -m ci.qualification_archive pack \
  --root /absolute/qualification/completed-corpus \
  --selection /absolute/qualification/receipt-selection.json \
  --store /absolute/qualification/archives/completed-corpus
```

`pack` leaves every original file present. It creates a private mode-0700 directory containing `receipts.tar.gz`, `index.json` and an operation lock. Existing archive directories are refused. Failed packing leaves originals intact and may leave partial archive output for inspection. Do not use an incomplete archive to reclaim originals.

Retain the returned `index_sha256` in a separate trusted operational receipt. Every subsequent command requires that exact hash. The internal payload seal detects accidental edits; it does not authenticate an index supplied by an untrusted party. The index binds the original root, sorted unique paths, payload hashes, lengths, modes, UID/GID, nanosecond modification times and bounded byte-exact extended attributes, plus the archive hash. Set-ID bits, filesystem flags, special files and multiple links are refused. Access time, inode, creation time and change time are outside this restored-file contract; do not use this profile if a frozen reader binds them.

## Verify, disclose and evict

```sh
python3 -m ci.qualification_archive verify \
  --root /absolute/qualification/completed-corpus \
  --store /absolute/qualification/archives/completed-corpus \
  --index-sha256 RECORDED_INDEX_SHA256
```

Verification reads the complete gzip stream through its trailer, checks the indexed expansion budget, then checks the exact ordered regular-file member list and every payload hash. Links, extra/duplicate/missing members, unsupported extended tar headers and nonzero trailing data are refused. Verification uses a temporary decompressed tar file; allow disk space for one selected corpus. Limits are 100,000 files, 64 MiB per payload, 128 GiB total payload and 64 MiB of index JSON.

`status` uses the same arguments and reports explicit `present` and `archived` paths. Existing files must match both bytes and recorded metadata. A matching original-content manifest remains meaningful when its files are archived, but those raw paths are unavailable until materialised. Keep the index hash and this availability state beside the original qualification receipt. Do not rewrite a frozen manifest or call a missing raw path directly readable.

Only after successful archive verification, a copied-sample round trip, review and a fresh check that the original corpus is idle:

```sh
python3 -m ci.qualification_archive evict \
  --root /absolute/qualification/completed-corpus \
  --store /absolute/qualification/archives/completed-corpus \
  --index-sha256 RECORDED_INDEX_SHA256 --confirm-cold
```

Eviction verifies the archive and preflights all present originals before removing any. It rechecks each original immediately before unlinking and writes a durable per-path JSONL receipt in the archive directory. This requires a quiescent corpus; a hostile concurrent writer is outside the contract. An I/O failure can leave a partially evicted corpus. The verified index remains sufficient to restore every indexed file; `status` reconciles actual availability after an interrupted operation. Do not infer availability solely from the final journal line.

## Materialise before existing readers

```sh
python3 -m ci.qualification_archive restore \
  --root /absolute/qualification/completed-corpus \
  --store /absolute/qualification/archives/completed-corpus \
  --index-sha256 RECORDED_INDEX_SHA256
```

Restore to the exact original root, under the same UID and an environment able to reproduce the recorded GIDs/attributes. Platform-controlled attributes that cannot be reproduced cause refusal; include representative metadata in the copied-sample proof before eviction. Preflight checks all conflicts before writing. Identical existing files are accepted only if their bound metadata also matches. New files are staged privately, checked and installed with an atomic no-replace rename. Existing targets, symlinks and multiple links are never overwritten, and no hardlinks are used. A later I/O failure may leave some files restored; rerunning resumes from verified existing files.

The native no-replace implementations are Apple's [`renameatx_np` with `RENAME_EXCL`](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h) and Linux `renameat2` with `RENAME_NOREPLACE`. Unsupported platforms/filesystems refuse restoration. macOS extended attributes use bounded file-descriptor APIs; Linux uses Python's corresponding OS APIs. Component tests distinguish native execution from simulated platform branches; platform qualification remains separate.

Run the existing frozen retained verifier only after restoration succeeds. It continues to read its original paths and original formats; the archive tool does not substitute another reader, launch applications or alter functional verdicts. Re-evict materialised copies only after that verifier stops and against the same verified index. Preserve unique failures and source/provider identities throughout.

## Validation

```sh
python3 -m unittest discover -s tests -p 'test_generation_archive*.py' -v
make check
```

The generation gate discovers these regressions and enforces an independent 80% line-coverage floor for each archive module. Actual large-corpus compression ratios and retained-reader compatibility need their own exact-revision operational receipts; synthetic tests do not establish those results.
