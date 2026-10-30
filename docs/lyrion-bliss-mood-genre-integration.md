# Bliss + Mood/Genre fusion for Lyrion — integration workstream

**Status (2026-10-19):** Architecture/implementation handover; **not yet
deployed**. This is the current product priority, ahead of scanner
performance and the deferred [platform-resource roadmap](platform-resource-roadmap.md).

## Target user experience

Keep the upstream Bliss Mixer functional and unchanged. Let a user opt into
an experimental **Bliss + Mood/Genre** strategy through a separately
installed Lyrion extension, initially Bliss Mixer Lab. The output is still
a Lyrion playlist / DSTM queue obeying existing candidate eligibility,
artist/repeat constraints, virtual library and source restrictions.
Two independent influence settings govern Genre and Mood/Theme (default 0),
with a visible Bliss-only A/B fallback.

The intended use is *better musical coherence and intentional movement*
between songs, not changing acoustic-feature analysis or replacing the
Bliss analysis itself. Final product evaluation must use real music and
listening feedback in addition to numerical tests.

## Mixing strategy decision record — deliberately open (2026-10-19)

**No final mixing strategy has been selected.** The earlier discussion
identified three **peer product alternatives**. This project's
`Bliss-first` first implementation is a low-risk **vertical integration
test**, not a claim that Bliss-first yields the best musical results.
The current host's guidance SPI v2 can only rerank an already admitted
Bliss pool. Extending candidate admission is a separate host capability.

| Strategy | Who proposes candidate songs? | How are they ranked? | What must be built? |
| --- | --- | --- | --- |
| **Bliss-first** | Bliss's acoustic neighbourhood | Independent Genre/Mood guidance within the existing pool, with established host rules | Read-only vectors, verified LMS file identity, bounded provider, opt-in Lab wiring |
| **Mood-/Genre-first** (feature-first) | Nearest-neighbour or indexed Mood/Genre features; optionally separate searches for each | Host evaluates Bliss transitions plus calibrated features | New feature candidate retrieval/index and host-owned candidate-source API, retaining Lyrion hard constraints |
| **Hybrid** | Union or deliberately diversified combination of Bliss and feature candidate sources | Host normalizes comparable evidence, controls diversity/drift, applies common hard constraints | Both candidate sources, deduplication, per-source provenance, calibration, fallback and consistent final selector |

**Rationale for the implementation order, not a product verdict:** Bliss-first
needs no new candidate-admission contract and can validate the exact track
identity, feature quality, latency and neutral fallback on the existing
`lms-blissmixer-lab` integration. The limitation is **candidate recall**:
a desirable Mood/Genre track that Bliss does not propose can never be
selected. Feature-first and Hybrid must be tested precisely to determine
whether overcoming that limitation improves listening quality.

**Strategy-selection gate:** Compare all three on the **same frozen library,
seed(s), and mandatory Lyrion filters**. Evaluate (a) candidate coverage and
head-validation coverage, (b) actual genre/mood coherence and transition
quality from listening reviews, (c) drift versus original seed(s),
(d) diversity/artist repeats, (e) fallback when signals are missing, and
(f) Pi latency/memory budget. A/B tests must include Bliss-only as control.
Score scales from the 56D Mood and 87D Genre heads are not interchangeable,
and the prototype's raw RMS-based high similarities are not calibrated
probabilities. **Do not select a global strategy or default weights before
these gates pass.**

At all times, preserve upstream Bliss, existing Lab/Better Call Bliss use,
original `bliss.db` and audio in read-only mode, and a valid Bliss-only
fallback. Mood-/Genre-first is **not** allowed to bypass the common Lyrion
membership/genre/artist/repeat constraints, even when it introduces songs
outside Bliss's candidate set.

## Grounded current state

- Upstream Bliss Mixer owns its existing acoustic database `bliss.db`,
  its source files, and original mixing rules; read-only consumers never
  write or rewrite them.
- `bliss-mood-poc` can produce a separate SQLite schema v3 database with
  `feature_tracks` and `feature_models` for independent per-track
  `moodtheme` (56 Sigmoid) and `genre` (87 Sigmoid), optionally
  `voice` (2 Softmax). All heads share a Discogs-EffNet 1280D encoder
  during offline inference. No inference should occur during mix creation.
- `feature_tracks` uses **the exact original `TracksV2.File` key** and
  a per-model fingerprint. Floating vectors must be decoded according to
  the ordered `classes_json` stored with their model fingerprint:
  IEEE-754 float32 little-endian. Do **not** use Bliss's `rowid` as a
  cross-database identifier and do not match by artist/title.
- `chrober/lms-blissmixer-lab` already provides a separate Bliss-first
  candidate pool and is a Lyrion host for optional guidance providers;
  it can invoke native JSONL SPI v2 providers via its shared host.
- `chrober/bliss-playlist-guidance-spi` permits bounded reranking of
  an **existing** Bliss-qualified shortlist. SPI v2 candidate and anchor
  schema already includes optional `database_file`, but current Lab
  provider adapters may populate only `candidate_id` and
  `lms_urlmd5`, and sometimes `database_file: null`.
  **The canonical file-key join must be implemented and tested**, not
  assumed to work merely because the schema has the field.
- Inference parity on synthetic fixtures is not a real-music validation.
  The stored `validated_against_essentia` flag is currently false.
  Production consumers must ignore such vectors by default.
  A **clearly marked experimental Lab-only preview** may deliberately
  opt into inspecting unvalidated results without relabeling them validated
  or silently activating them in production mixes.

Reference repos:
[chrober/lms-blissmixer-lab](https://github.com/chrober/lms-blissmixer-lab),
[chrober/bliss-playlist-guidance-spi](https://github.com/chrober/bliss-playlist-guidance-spi),
[chrober/lms-guidance-library-signals](https://github.com/chrober/lms-guidance-library-signals),
[chrober/bliss-guidance-library-signals](https://github.com/chrober/bliss-guidance-library-signals).

## Explicit separation of three responsibilities

| Role | Owner / initial integration |
| --- | --- |
| Feature production | Offline `bliss-mood-poc scan-features`; separate schema-v3 feature SQLite sidecar |
| Candidate admission / hard constraints | Existing Bliss Mixer / BlissMixerLab, unchanged in first release |
| Guidance and final choice | New optional Mood/Genre guidance source via existing SPI v2; Lab combines bounded signals with its other providers and owns playlist/queue |

### First integration experiment: Bliss-first + Mood/Genre reranking

1. Lyrion/Bliss Mixer Lab acquires its usual bounded Bliss candidate pool.
2. The host resolves **exact** per-track Bliss keys for seed/context tracks
   and candidates. Any unresolved mapping gives **neutral** guidance.
   Avoid inventing or guessing file roots in the native provider.
3. The new feature guidance provider opens a *trusted*, locally configured
   **read-only** schema-v3 SQLite sidecar. It verifies schema, model key,
   class ordering, vector size/ranges/finiteness and validation policy.
   Reuse one SQLite connection/snapshot per invocation; query only
   requested seeds and bounded shortlist, no full-library read or ONNX.
4. Compute Genre and Mood similarity **separately**, only between compatible
   same-head vectors from the same model/preprocessing fingerprint and label
   ordering. Handle near-zero vectors, degenerate/uniform scores, missing
   anchors/candidates and different taxonomies as **neutral**; do not
   average scores between heads directly.
5. Produce separately bounded `genre` and `mood_theme` SPI v2 guidance
   channels (signed [-1, 1], confidence [0, 1]). The host performs any
   calibrated shortlist normalization and weighted combination with Bliss,
   not the provider. Host influences are separately user-controlled, default
   to 0, and can be disabled independently. Neutral configuration must
   reproduce the existing Bliss order.
6. Preserve Bliss eligibility: the provider may **only re-rank**
   admitted tracks and cannot add tracks, bypass repeat/genre constraints,
   or force a new route. Timeout, malformed sidecar, missing data or
   provider failure must leave a valid Bliss-only mix.

The first product target is a Lab-only A/B preview. Do not enable provider
by default. Full native Lyrion plugin packaging and actual Pi binary
execution are separate verification gates.

### Other equal-priority strategy candidates (not part of the first bridge)

- **Feature-first:** mood/genre retrieves candidates outside Bliss's
  acoustic shortlist, followed by Bliss transition scoring. The current
  SPI v2 cannot do this; it needs a new host-owned candidate-source contract.
- **Hybrid:** explicit union of Bliss and feature candidate sources with
  coherent normalization, provenance, fallback and musical drift control.
  Must preserve all existing Lyrion hard filters.
- A user-requested genre journey/mood trajectory and fixed
  source-identity drift anchors are separate future policy controls.
- Voice is already analyzed but is not required for the first Mood+Genre
  blending experiment; singing style is not inferred by the Voice head.

## First implementation slices and acceptance criteria

### F1 — Sidecar inspection and exact identity contract (first coding slice)

In the **feature analyzer repository** provide a small read-only inspection
path or fixture/API for selecting `moodtheme` and `genre` vectors by exact
`track_file`, with correct model metadata and provenance. Synthetic
fixtures must establish: existing/missing track, both heads, only one
head, incompatible model fingerprints, invalid/malformed vector, zero
vector, and unavailable sidecar. This is **not** a fresh ONNX scan or a
change to the schema.

In the Lab integration, verify with a representative frozen set of Lyrion
tracks that `candidate_id` / `lms_urlmd5` can be mapped unambiguously to
the exact Bliss `TracksV2.File` key. If not, make the adapter supply the
explicit `database_file` field from a verified source (including seed
anchors), with regression tests. No artist/title guessing, no rowid join,
no implicit path normalization.

**Gate:** given a known seed and a bounded candidate batch, the system
fetches only the expected vectors and correctly reports missingness and
validation status without touching `bliss.db` or audio files.

### F2 — Native, provider-neutral scoring prototype

Implement a small read-only native Mood/Genre SPI v2 JSONL provider
(new dedicated provider project preferred rather than putting mixer
policy into the scanner). Support `describe`, `prepare`, `score`,
`close`, a trusted feature-SQLite resource kind and independently
bounded per-head channels. Provide deterministic fixtures for:
equal vs dissimilar vectors, single missing head, mixed fingerprints,
disabled/zero influence, corrupted SQLite, timeout and neutral failures.
Do not spawn FFmpeg or ONNX at mixing time.

**Gate:** frozen Bliss candidate batch + seed => per-channel signals
with provenance and strict bounds; missing/invalid data yields neutral
fallback and no new candidate.

### F3 — Experimental Lyrion plugin + Lab host wiring

Implement a separately installable passive Lyrion plugin using existing
guidance provider kit conventions (descriptor/defaults/status/native SPI
configuration/settings), discoverable from Lab and off by default.
Use a trusted configured feature-sidecar path, never a path originating
from a playlist request. Follow the existing Lab deadline and process
handling. The host renders concise diagnostics for number of covered
tracks, missing anchors, fingerprint mismatch, and contributions.
Do not modify production upstream Bliss Mixer.

**Gate:** a reproducible Bliss-only vs Bliss+Genre vs Bliss+Mood vs
combined preview on the same frozen seed/candidate set, with existing
hard constraints and failure fallbacks unchanged.

### F4 — Musical evaluation and safe release gates

Collect a representative real-music set including ambiguous multi-genre
tracks, closely related genres, large mood shifts, long intros, and
duplicates. Review the actual 56/87 scores against the user's judgement
and, where possible, independent Essentia full-track references. Record
subjective results and validate the provenance flag accurately.
Run performance checks on real Pi/Lyrion later; a Linux ARM64 CI build
alone is not proof of piCorePlayer ABI/runtime compatibility.
Release only with opt-in controls, working fallback, source licensing review
and no production use of unvalidated vectors by default.

## Immediate work order

**Current state:** The read-only schema-v3 `inspect-features` extraction
is implemented and locally validated (PR #12). The standalone native
Mood/Genre scorer is under review in PR #13. The remaining integration
seam is **verified Lyrion-to-Bliss `track_file` mapping for seeds and
candidates**, followed by opt-in Lab provider wiring. Lab repository
write access was unavailable in the last attempt; no host edits are
claimed. None of these implementation steps predetermines a final
Bliss-first, Mood-/Genre-first, or Hybrid strategy.

**Deferred:** [platform resource architecture](platform-resource-roadmap.md).
Read [chat-handover.md](chat-handover.md) for repository/CI rules; Windows
Rust binaries are built by PR-triggered GitHub Actions, **never locally**.


## F1 first implementation — read-only feature lookup CLI

A focused F1 code slice adds `bliss-mood inspect-features` for existing
schema-v3 sidecars. A bounded repeated `--track-key` list uses the exact
`TracksV2.File` values and returns independently typed Mood/Genre
`model_key`, label order, preprocessing and aggregation metadata,
validation flags and scores (only when permitted). It never scans media,
invokes ONNX, creates a database or writes to the source sidecar.

Example (replace the executable with the verified Actions artifact):

```powershell
& {
    $exe = 'PATH-TO-VERIFIED-GITHUB-ACTIONS-EXE'
    & $exe inspect-features --db .\mood.db --track-key 'Artist/Album/track.flac' `
        --models moodtheme,genre --json
    # In an isolated Lab preview, append --include-experimental to reveal
    # unvalidated predictions. The default emits no such score vectors.
}
```

Read-only lookup is a **diagnostic/contract first step**, not a deployed
Guidance SPI provider. Next task: host-side exact-key mapping for LMS
anchors/candidates, followed by a separate SPI v2 provider. Do not imply
that the extractor already reranks Lyrion tracks.
