# Project purpose, open-source commitment, and Lyrion community distribution

**Decision recorded: 30 October 2026.** This is the current project direction, not a hypothetical commercial product plan. This policy documents *our project's intent*; it does not amend upstream licences or silently grant rights to third-party software.

## Mission

`essentia-analyser` is developed **for the Lyrion Music Server community**, as a **free-of-charge, publicly available, open-source project**. The project is **not intended for commercial exploitation**; no paid offering, proprietary edition, commercial model service, commercial licensing strategy, or revenue-generating product is planned.

The practical goal is that interested community members can:

- inspect, build, modify and contribute to the **project-owned** Rust scanner and native Essentia C++ worker sources;
- independently analyse their own music libraries offline using installed prerequisites and legitimately acquired model files;
- produce a versioned SQLite-v3 feature database, without writing to `bliss.db` or requiring a cloud service;
- eventually use that data with the separate `essentia-similarity` engine and optional Lyrion Guidance integration, subject to feature-identity and model-quality verification;
- install/use supported platform binaries or a reproducible installation process **where the applicable third-party licence and source/notice obligations have been met**.

Open-source community usability, cross-platform development, reproducibility and correct attribution are priorities. Compliance work should enable community releases, not derail the research or unnecessarily delay unrelated development.

## Scope and repository boundaries

| Repository | Role |
| --- | --- |
| [`essentia-analyser`](https://github.com/chrober/essentia-analyser) | **This project:** offline Rust scanning/orchestration, original Essentia C++ worker, inference, feature persistence, source provenance, package and platform qualification |
| [`essentia-similarity`](https://github.com/chrober/essentia-similarity) | Player-independent feature comparison; General Metric and optional Personal Metric; **does not** analyse audio |
| [`bliss-mood-poc`](https://github.com/chrober/bliss-mood-poc) | Long-lived laboratory for general experiments and scientific similarity research, including WP1/WP2/WP3 |
| [`bliss-guidance-essentia`](https://github.com/chrober/bliss-guidance-essentia) | Native Bliss Guidance SPI v2 provider |
| [`lms-guidance-essentia`](https://github.com/chrober/lms-guidance-essentia) | Future Lyrion provider configuration/installation |

**No repository consolidation or merge is planned or required.** Historical scanner code stays in `bliss-mood-poc` for reproducibility; new scanner development belongs here. Source and binary packaging independence must not be confused with musical or legal independence.

For initial compatibility the existing executable names remain `bliss-mood(.exe)` and `bliss-essentia-worker(.exe)`. Their later renaming is a distinct, tested change. `cargo build` compiles the Rust CLI; upstream Essentia-dependent native C++ worker requires a separate build and installation.

## Open source, NonCommercial and free of charge are different things

1. **Project-owned code** is currently published under the repository's **MIT licence** (subject to confirming the provenance and rights of any reused code). MIT is an **OSI-style permissive open-source licence and allows third parties commercial use**. The maintainers' decision not to commercialise this project is a *project policy*, **not** a restriction being added to the MIT code licence. Do not insert a misleading “commercial use prohibited” claim in `LICENSE`.
2. **Original Essentia C++** has **AGPL-3.0-or-later** terms (at the audited upstream revision). AGPL also does **not** prohibit commercial use; it imposes copyleft obligations, including for redistributed derivative/combined works, and can add network-source obligations in applicable circumstances. The current native worker links against it. Separate Rust and C++ processes are not automatically a legal exemption.
3. **MTG's pretrained ONNX models** are external assets, **not relicensed as MIT/open source just because our source is public**. Official MTG webpages disagree on whether general model terms are CC BY-NC-SA 4.0 or CC BY-NC-ND 4.0. Both contain **NonCommercial** conditions. The exact licence for each of our four selected model files must be identified; keep per-model attribution/conditions distinct. **Noncommercial community intent is relevant, but it does not prove a particular use or redistribution is licensed.** We do not plan a commercial licence purchase; revisit only if a genuinely relevant use case or the owner's clarification makes that necessary.
4. **FFmpeg and other native dependencies** may be LGPL/GPL/etc. according to their exact build and linked components. A *free-of-charge download* is still a **redistribution** and can carry source, attribution, licence and relinking obligations.
5. Third-party **model weight licences and own-source licences** are distinct. We can publish the program's source while not bundling the weights or external runtime DLLs. Separate downloads are not a way to bypass the model's conditions.

Do not claim “the entire toolchain and all its models are OSI open source” unless this has actually been established for each asset. The intended community project **is** open source; some model weights may have more restrictive non-open-source terms. This distinction is transparent and should appear in public installation instructions.

Primary references: [Essentia licensing](https://essentia.upf.edu/licensing_information.html), [Essentia model catalogue](https://essentia.upf.edu/models.html), [FFmpeg legal](https://ffmpeg.org/legal.html). The pinned-original-library licence is in [MTG's source tree](https://github.com/MTG/essentia/blob/b0661db99be4a8e2c6fabbe90a996f89786fdd8e/Essentia%20Licensing.txt).

## Practical distribution strategy

### Available now — open source and local/community development

- Keep the public source code, issues, documentation, `Cargo.lock`, tests and synthetic fixture CI available **at no charge**.
- Continue Rust scanner, multi-worker, original C++ integration, feature-schema, performance and Lyrion interoperability work normally. A native packaging audit is **not a blocker** to those independent tasks.
- Support building locally with separately and lawfully installed official dependencies. Clearly document the platform/runtime requirements and licences, and never silently infer upstream rights from a green test run.
- Do not commit user libraries, music files, personal paths, model weights or third-party binary bundles into source control.
- Do not present a prebuilt native CI ZIP as “internal” simply because it is named *dev*: old public workflow artifacts need a separate compliance review.

### Future community binaries — desired, but not yet cleared

**Goal:** make Windows/Linux/macOS/ARM builds/installers convenient and **free of charge**, not to prevent community distribution indefinitely. Before publishing each particular native package:

1. Build from a pinned and reproducible set of originals (Rust, Essentia, codec libraries, ONNX Runtime); identify exact file/packaging versions.
2. Supply applicable licence texts, copyright notices, notices of modifications and corresponding sources/build/install instructions for redistributed components; clarify any directly linked worker/AGPL combination issues.
3. Minimise the native runtime to required audio codecs/DSP libraries where practical, and verify the FFmpeg flags and actual loaded dependency chain.
4. Resolve the old Windows dependency notice evidence gaps **for the actual package being offered**. A smaller freshly built bundle may yield a different set; do not use old counts to assert a newly built package's status.
5. Keep model weights separately sourced until per-model use/redistribution rights are verified. Provide explicit upstream URLs, immutable hashes and per-model licence notices, with an installer that fails transparently if verification is unavailable.
6. Run integration/parity tests on each intended platform (including ARM/piCorePlayer where supported). Test binary provenance and licence/source availability as separate gates from numeric quality.
7. Decide whether to release a genuinely compliant full bundle, a smaller source-first installer, or only a documented self-build route for that platform. **The current broad public Windows native-binary release remains blocked**, not source development.

## Priorities and non-goals

**Prioritise** technical delivery and reproducible community usability. Run mechanical audits and collect existing upstream terms incrementally, rather than treating a hypothetical commercial launch as a precondition to implementing features.

**Do not prioritise** proprietary licensing, sales, commercial feature agreements, or rearranging repositories to solve hypothetical licensing concerns. A commercial MTG model licence is **not a near-term project requirement**.

**Do preserve** correct attribution, licence notices, per-model conditions, the ability to provide corresponding source for components covered by copyleft, and explicit documentation of what has or has not been cleared. No one should be led to believe the public source repository alone authorises distributing a copied native/ONNX package.

## Status distinctions

| Deliverable | Status as of 30 Oct 2026 |
| --- | --- |
| Public project-owned source / docs / tests | **Available for community development**, subject to source-code provenance review |
| Locally built private development environment | **Supported as a development pathway** with separately obtained prerequisites, subject to each component's applicable licence |
| Direct download of all four MTG model weights | **Technically implemented**, but per-file licence, version/hash and conditions still need a verified manifest |
| Source-first community installation instructions | **Preferred path to develop next** |
| Public native bundle including original Essentia + FFmpeg/DLLs | **NOT APPROVED / BLOCKED** pending concrete package-specific licence checks |
| Commercial use as a project goal | **Out of scope; not intended** |

For outstanding documented evidence and the 21 October Windows developer-kit audit, see [the detailed compliance assessment](licensing-compliance-review-20261030.md) and [the historical source strategy](essentia-licensing-distribution-strategy.md).

**This is project policy, not legal advice or a licence amendment.**
