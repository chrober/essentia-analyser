# Model-independent features and future mixing strategies

## Current implementation (experimental)

The Rust proof of concept [bliss-mood-poc](../README.md) implements an
opt-in capability registry, one Discogs-EffNet audio/embedding pass, and
independent Sigmoid and Softmax classification heads for three registered models:

| Registry model ID | Capability | Classes | Encoder |
| --- | --- | --- | --- |
| moodtheme | mood_theme | 56 | Discogs-EffNet 1280D |
| genre | genre | 87 | Discogs-EffNet 1280D |
| voice | voice_presence | 2 (Softmax) | Discogs-EffNet 1280D |

A descriptor maps the model ID to a capability, trusted local weight filenames,
metadata and dimensional constraints. The generic scanner stores independent
vectors with exact model/preprocessing fingerprints; no model names or class
lists are hard-coded in the feature storage format. This is *head-agnostic
within a compatible encoder family*, not arbitrary support for MusicNN, VGGish,
regressors, or models whose output is not a supported Sigmoid/Softmax vector.

Genre, Mood/Theme and Voice/Instrumental remain different score spaces.
The per-head `output_type` controls validity checks and per-model aggregation
provenance: Sigmoid allows independent 0..1 labels, whereas Softmax requires
a normalized sum of approximately one across mutually exclusive classes.
The registry schema v2 makes this explicit; older v1 registries still default
to Sigmoid so existing custom model configurations remain readable. The system does not imply
that a score of 0.8 has the same probabilistic meaning for both models.

## Planned separation of responsibilities

Three distinct concepts must not be merged in the user-facing application:

1. **Feature source**: performs offline analysis and exposes versioned numeric
   descriptors for a local track (e.g. Bliss 23D, 87D Genre, 56D Mood/Theme).
   Providers declare *capabilities*, not hard-coded model names.
2. **Candidate source**: determines which eligible tracks are proposed for
   mixing (e.g. Bliss similarity, Genre/Mood proximity, or a union of both).
3. **Guidance/scoring source**: contributes bounded scores or preferences for
   candidates the selected strategy is considering (e.g. Bliss transition
   similarity, Mood/Theme anchor distance, Last.fm relationships, local
   listening statistics).

An overall **mixing strategy** decides candidate source(s), normalization,
soft/hard constraints, reranking, and variation. Common Lyrion membership,
repeat-window and playlist integrity rules remain in the host regardless
of the chosen strategy. Unavailable or unvalidated features must lead to
explicit, predictable fallback, not silently alter the candidate pool.

## Three product strategies under evaluation (no final decision)

- **Bliss-first (first integration experiment only)**: Bliss admits candidates based on acoustic similarity;
  compatible Genre/Mood signals may rerank only that candidate pool. This is
  feasible with today's Bliss Guidance SPI v2 after adding an opt-in feature
  provider. The existing SPI forbids external providers from admitting tracks.
- **Mood-/Genre-first** (feature-first): Genre/Mood descriptors generate
  candidates; Bliss provides transition similarity in the final scoring.
  This requires a new candidate-selection host contract. It must **not**
  silently reinterpret the existing Bliss-only eligibility semantics.
- **Hybrid**: candidate sources union or otherwise combine their proposals,
  then a coherent strategy evaluates transition quality, musical identity,
  preference, and diversity. Feature score scales must be normalized and
  calibrated rather than directly summed.


**Decision status:** All three approaches remain genuine competing
product options, not a sequentially predetermined roadmap ending with one
choice. Bliss-first was implemented first **only because current SPI v2
provides bounded reranking of Bliss's pool**, allowing evaluation of the
full feature→sidecar→guidance path without changing hard candidate
admission. This does **not** establish that Bliss-first is the best
algorithm: it can miss tracks with excellent Mood/Genre compatibility that
Bliss never proposed. Mood-/Genre-first and Hybrid require a new host
candidate-source contract and calibrated cross-source scoring; they
should be evaluated on the same frozen seeds, eligibility constraints,
candidate coverage, listening impressions, drift/diversity and Pi budget
before the product strategy is selected. See the detailed
[strategy decision record](lyrion-bliss-mood-genre-integration.md#mixing-strategy-decision-record--deliberately-open-2026-10-19).

Model selection and mixing strategy are separate user settings. A model can
declare capability genre without the UI needing to display its ONNX filename.
Capability alone does not make score semantics or taxonomies interchangeable;
mapping and calibration may be needed when another model is substituted.

## Preserved historical prototype: PR #13 read-only Bliss Guidance SPI v2

**Research reference, not an integrated production feature (29 October 2026).**
[PR #13](https://github.com/chrober/bliss-mood-poc/pull/13) was an
experimental, standalone **Bliss-first guidance/scoring provider**.
Its source is retained on the branch
[`feat/bliss-mood-genre-guidance-spi`](https://github.com/chrober/bliss-mood-poc/tree/feat/bliss-mood-genre-guidance-spi);
the principal implementation is
[`src/bin/bliss-feature-guidance.rs`](https://github.com/chrober/bliss-mood-poc/blob/feat/bliss-mood-genre-guidance-spi/src/bin/bliss-feature-guidance.rs).
**Preserve this branch** as a technical reference even if the
historical draft PR is closed without merge.

The prototype implements a separate JSONL **Bliss Guidance SPI v2**
process with `describe`, `prepare`, `score` and `close`.
It reads only a trusted **schema-v3 feature SQLite sidecar** and
uses exact `database_file` song identities for source anchors and
already-admitted Bliss candidates. Genre (87D) and Mood/Theme (56D)
are separate bounded-influence guidance channels; mismatched
model fingerprints, missing/nonvalidated vectors or incompatible
classes yield neutral/no guidance by default. It does **not**
modify Bliss or Lyrion databases, decode audio, run ONNX or
admit new candidates. Its provisional normalized RMS-based
score was a **contract proof of concept**, not an empirically
selected musical similarity metric.

**Why retain it?** The branch supplies reusable examples of the
host/provider protocol, source-key matching, read-only safety,
fallback and per-channel influence. It can inform a *future*
Lyrion/BlissMixerLab integration, but does not itself demonstrate
an end-to-end host plugin: verified LMS/Bliss identity mapping
and separate Lab wiring were not completed in PR #13. Any revival
must be reconciled with the current native Essentia scanner,
feature provenance, experimental-validation gates and current
Similarity Metric Evaluation; **do not merge or deploy the old
RMS scorer unchanged** or mistake it for a completed integration.

This is an **integration prototype**, not a replacement for either
research objective: (A) a reliable **general musical similarity
metric without user training**, or (B) **optional personal
metric learning** from user preferences with a configurable
0–100% personal influence once validated. Similarly, it does
not decide between Bliss-first, feature-first or Hybrid
candidate strategies. Possible relationships between Essentia
Genre/Mood features and Bliss acoustic descriptors deserve
separate empirical testing before building rules that claim
to identify genres or moods from Bliss features.

## Drift protection as an orthogonal policy

Drift control should be available across strategies. It compares future
candidates to a frozen source identity (single or multi-track anchor), recent
mix history, and a selectable target preference. Genre consistency, mood
consistency and acoustic transition quality are distinct objectives; a
user-requested style transition should not be accidentally defeated by a
hardcoded starting-genre rule.

Compare four experimental conditions with fixed seeds and identical LMS hard
constraints: original Bliss, Bliss with existing dynamic/adaptive weighting,
Bliss with model-based guidance, and Bliss with both. Feature-first and Hybrid
should be evaluated separately once their candidate-selection contracts exist.

## Compatibility and boundaries

- Keep the original Bliss database read-only; never rewrite source audio.
- Preserve the legacy Mood-only CLI and sidecar rows while the feature path is
  evaluated. Writable schema v3 must not be used with v2-only binaries.
- Keep [Bliss Guidance SPI v2](https://github.com/chrober/bliss-playlist-guidance-spi/blob/main/SPI.md)
  unchanged and Bliss-first. A future strategy host must introduce its own
  candidate-source abstraction rather than mislabel a provider as a candidate
  generator.
- No modifications to production BlissMixer, BlissMixerLab or Better Call Bliss
  are part of this pull request.
- Numerical parity on synthetic files is **not** proof of useful predictions
  on music. Experimental/unvalidated flags remain false for production and
  users must evaluate real tracks before enabling automated playlists.

## Vocal characteristics and finer genres

`voice` currently distinguishes predominantly voice vs instrumental music.
It does **not** classify clean vocals, screams, growls, rap techniques or
singer timbre; those require models trained on the corresponding labels.
Song-wide average Softmax scores also cannot be interpreted as the proportion
of time containing voice.

The 400-label Discogs taxonomy would offer Black Metal, Post-Metal and
Psychedelic Rock categories for improved style matching. However, the
Discogs-EffNet head is officially hosted as a TensorFlow `.pb` without an
ONNX file in the official directory. This enhancement remains out of scope
until an independent conversion and TensorFlow-vs-ONNX parity gate pass.


## Active next phase (2026-10-19)

The concrete staged Lyrion integration contract is in
[lyrion-bliss-mood-genre-integration.md](lyrion-bliss-mood-genre-integration.md).
The **first Bliss-first experiment** reranks only the existing
acoustically eligible candidate pool via SPI v2 and preserves every upstream
hard constraint. This is an integration shortcut, **not** a product
decision against Mood-/Genre-first or Hybrid.
Exact `TracksV2.File` key mapping between Lyrion and the read-only feature
sidecar is the first unsolved implementation seam. Separate Mood/Genre
signals and an explicitly experimental opt-in preview come before any
feature-first or hybrid candidate admission. Platform resource tuning is
[deferred](platform-resource-roadmap.md).
