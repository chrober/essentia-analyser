# Scanner source stability and provider provenance — 31 October 2026

Status: **experimental implementation**, [Draft PR #6](https://github.com/chrober/essentia-analyser/pull/6). No merge to `main` or live Lyrion provider enablement.

## Problem

Previously `scan-features` saved the audio hash obtained **after** decoding and model inference while retaining a file size/modification timestamp captured **before** decoding. If a music file changed during inference, the derived feature vector could no longer correspond to the `feature_tracks.audio_sha256` written to the SQLite-v3 sidecar. The analogous legacy `scan` route had the same exposure. Offline provider verification of the recorded SHA-256 alone cannot remedy this scanner-side ambiguity.

## Implementation

New `src/source_guard.rs` checks a source file using a bounded-memory streaming pre-decode SHA-256 (64 KiB buffer). It records metadata (file size, modification time, and, on Unix, device and inode) and the canonical path, compares them after the initial hash, then lets the existing analyser decode/infer. The analyser's **already calculated post-decode file SHA-256** must match the captured initial checksum. Metadata and path are checked again when the analysis completes, and again in the SQLite-writing code before committing the result.

The scanner applies the guard to:

- `scan-features` serial and fixed/auto multi-worker execution, including each reusable worker and the centralized SQLite writer.
- The legacy `scan` / Mood v1-v2 persistence path.
- Explicit standalone `analyze --db` and `analyze-features --db` persistence.

The guard fails before persistence for a stale queued scan timestamp, content modification, replaced source path or inconsistent pre/post hash. Error handling reuses existing failed-track behavior, rather than falling back to a synthetic successful row. It does not change the scanner's SQLite schema, classification vectors, model fingerprints, native IPC protocol or worker scheduling.

## Performance cost

One **additional full source-file read and SHA-256 pass per analysed track** is performed before decoding. The previous post-decode hash remains unchanged. This increases startup/I/O time and may reduce scan throughput on slow spinning disks, NAS mounts and multi-worker scans; no throughput improvement is claimed. Existing up-to-date rows are skipped as before and are **not retroactively audited**. The full-file pass is deliberately not added to the native SPI provider's latency-sensitive scoring path.

## Evidence and limitations

`source_guard` unit tests cover unchanged audio, wrong reported hash, stale queue timestamp, a same-length content mutation, and an edit after the worker completes. Linux and Windows scanner CI compile the feature scanner and legacy path, with native protocol fixture tests. CI status is the merge gate for this draft.

This is a **best-effort stability witness**, not an atomic filesystem snapshot. An adversarial or extremely rapid edit followed by restoration while the decoder holds a separate file handle may evade beginning/end comparisons. Windows uses size, modified timestamp, canonical path and before/after content hash; Unix additionally checks device/inode. There is no cross-process write lock, no authoritative host scan generation and no persistent root-qualified source namespace. Already cached files may have been processed before this guard existed.

### Next steps for `lms-guidance-essentia`

1. Keep [provider Draft PR #1](https://github.com/chrober/lms-guidance-essentia/pull/1) unavailable. Its offline content proof verifies recorded scanner hashes, but a successful standalone SPI run does not establish a common Lyrion catalogue generation.
2. Define a host-owned, stable music-root identity and catalogue snapshot token, together with an analyser-recorded source-root map/provenance witness that survives remote cross-platform scans. The legacy `feature_tracks(track_file, model_id)` key is only root-relative and can collide across music folders.
3. Verify the candidate cohort against the **same authoritative generation** using independently pinned read transactions and a final host generation check; reject all ambiguous or stale candidates. Never invent a token from SQLite timestamps or an equal filename.
4. Benchmark the extra prehash pass across local SSD, NAS and low-power Raspberry Pi hosts; review throughput before merging.

**Architecture:** Generic BlissMixerLab remains unchanged. Provider-facing functionality must continue to use the existing Guidance SPI v2, not an Essentia-specific host hook.
