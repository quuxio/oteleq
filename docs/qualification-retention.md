# Cold qualification receipts

<!-- markdownlint-disable MD013 -->

Maintainers can archive completed diagnostic receipts without changing their original-content manifests. This checkout-only tool supports generated `node-runtime/node-launch.json`, `node-runtime/node-plain-launch.json` and prepared Java `sdk-runtime/class-load.log` files. It does not archive application binaries, source snapshots, providers, dependencies or compiler inputs. It adds no application capability or equivalence evidence.

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
