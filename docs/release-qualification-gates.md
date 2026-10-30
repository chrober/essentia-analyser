# PR #17: release qualification after numerical real-MP3 parity

**As of 21 October 2026** · Branch `feat/essentia-cpp-worker-backend` ·
Draft [PR #17](https://github.com/chrober/bliss-mood-poc/pull/17).
This checklist separates proven numerical equivalence from the much broader
questions of **codec support, operating-system packaging, redistribution and
licensing**. Neither a successful numeric scan nor a CI fixture licenses a
production Windows/macOS/Linux release.

## Windows Native-License-Inventur — 21 October 2026, reales Kit verifiziert

Das lokal bereits vorhandene native Entwicklungskit hat den
`audit_windows_native_release.py`-Check **bestanden**.
Es enthält **100 PE-x64-EXE/DLL-Dateien** mit korrekten SHA256-Dateihashes,
deren Herkunft auf **77 MSYS2-Pakete** zurückgeführt wird.
**94 referenzierte Notice-Dateien** existieren und sind nicht leer.
Es fehlen **keine referenzierten Dateien**. Bei **17 Paketen**
hat `pacman` allerdings **keine installierte Notice-Datei** gefunden.
Dies ist eine **Beweislücke, kein Beweis für Lizenzlosigkeit**.
Der Status bleibt `distribution_release_status=BLOCKED`,
`release_approved=false`, `license_inventory_complete=false`.

[Die maßgebliche Lizenz- und Distributionsstrategie](essentia-licensing-distribution-strategy.md)
bewertet vier Szenarien ausdrücklich getrennt. Besonders wichtig:
ein Downloader/Installer mit Originalquellen und unabhängigen
Systempaketen reduziert den Umfang **eigener Weitergabe**, nicht
automatisch die AGPL-Betrachtung der miteinander verbundenen
Rust-/C++-Programme oder die spezifischen Rechte an ONNX-Gewichten.
Das bisherige **öffentliche** GitHub-Actions-Test-ZIP ist kein rein
internes Paket, nur weil `dev` im Dateinamen steht.

**Sicherungsmaßnahme im Branch:** Ein *erneuter öffentlicher Upload*
des nativen Windows-EXE-/DLL-Artefakts ist bis auf Weiteres deaktiviert
und benötigt neben einem **privaten Repository** eine explizite
CI-Variable `NATIVE_BINARY_REDISTRIBUTION_REVIEWED=true`. Die
vorhandenen Windows-Native-Build-, Protokoll-, numerischen und
PR-#16-Handoff-Smokes bleiben aktiviert; ihr Erfolg ist weiterhin ein
**Funktionsnachweis, keine Lizenzfreigabe**. Ältere bereits verfügbare
CI-Artefakte sind **nicht automatisch gelöscht**; sie separat prüfen.

Neu: `scripts/triage_windows_native_license_gaps.py` erstellt
aus den geprüften bestehenden Manifesten einen **versionsgenauen
Prüfauftrag** für die 17 Notice-Lücken, einschließlich zugehöriger
DLL-Namen, tatsächlicher installierter Paketversionen,
*unverifizierter* Paket-Lizenzmetadaten und manifestverzeichneter
Importpfade. Das Tool zieht **keinen** Source-Code herunter, löscht
**keine** DLL und behauptet **keine** Lizenzkompatibilität.
Der Review-Auftrag gehört in den Release-Prozess, nicht in die
numerische DSP-Paritätsmessung.

### Lokaler Quell-/Lizenz-Evidenzbericht ohne neue Audioscans

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    $repo = 'D:\LMS\bliss-mood-poc'
    $kit = 'D:\LMS\essentia-cli-test'
    $out = Join-Path $repo (
        'triage-essentia-license-gaps-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    )
    Set-Location $repo
    git switch feat/essentia-cpp-worker-backend
    if ($LASTEXITCODE -ne 0) { throw 'Branchwechsel fehlgeschlagen' }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Git Pull fehlgeschlagen' }

    python -m unittest discover -s tests -p 'test_triage_windows_native_license_gaps.py'
    if ($LASTEXITCODE -ne 0) { throw 'Lizenz-Evidenz-Regressionstests fehlgeschlagen' }

    python scripts/triage_windows_native_license_gaps.py --kit-root $kit --output-dir $out
    if ($LASTEXITCODE -ne 0) { throw "Technische Paketprüfung fehlgeschlagen: $out" }

    $data = Get-Content (Join-Path $out 'native-license-evidence-backlog.json') -Raw |
        ConvertFrom-Json
    if ($data.binary_integrity -ne 'PASS' -or
        $data.distribution_release_status -ne 'BLOCKED') {
        throw 'Unerwarteter Integritäts- oder Freigabestatus'
    }
    Write-Host "Technischer Nachweis: $out"
    Write-Host "Offene Lizenz-Notice-Pakete: $($data.missing_installed_notice_packages)"
}
~~~

**Nächste technische Reduktionsarbeit:** *Nicht* die vorhandenen
Video-/Encoder-DLLs aus der funktionierenden Closure entfernen.
Stattdessen die **wirklichen** FFmpeg-Buildflags und Dekoderanforderungen
MP3/FLAC/WAV dokumentieren, einen separaten minimalen
Essentia-Audio-Build erzeugen, und dessen PE-Abhängigkeitsgraph und
analysierende Smokes gezielt mit dem bisherigen validierten Build
vergleichen. Das wäre ein **neues Paketierungs-Experiment**, kein
Grund, die alte MP3-Gesamtkohorte nochmals zu scannen.

---

## Current authoritative Windows qualification checkpoint — 21 October 2026

The real-audio gate, including **two separately downloaded, unmodified
lossless songs**, is now **PASS**. This section supersedes older "next",
"open" and "pre-inference rejection" descriptions further below, retained
as diagnostic history. Numerical tolerance was **never relaxed (0.001)**.

| Actual test | Audio coverage | Worst C++ vs Rust v5 score delta | Outcome |
| --- | --- | ---: | --- |
| MP3, 4 fixed Rust workers | 100 real MP3 songs, 14,500 scores | 1.2695789337158203e-5 | **PASS**, 0 patch mismatches |
| MP3, adaptive enabled with 6 active workers | Same 100 MP3 songs; 4..8 policy | 1.2695789337158203e-5 | **PASS**, identical stored Rust-v5 scores to fixed 4; zero actual worker adjustments |
| Controlled WAV24 and FLAC from shared real-song PCM | Same 837-patch signal in two containers | 6.3700000000332935e-6 both | **PASS**, bit-identical decoded PCM24; cross-format scores exactly equal |
| **Original downloaded FLAC, 48 kHz / 24-bit / stereo** | **604.75 s, 608 patches** | **2.019999999991473e-6** | **PASS** |
| **Original downloaded WAV, 44.1 kHz / 16-bit / stereo** | **356.28 s, 358 patches** | **1.3999999999292356e-6** | **PASS**, embedded MJPEG cover artwork ignored by first-audio-stream probe |

The two independent lossless downloads each passed all three ONNX model
heads (87 Genre, 56 Mood/Theme, 2 Voice classes), source SHA256 checks,
C++/Rust patch counts, backend/model identity checks and strict numerical
tolerance. The FLAC's 604.75 s duration explains the earlier historical
default 420 s **preflight** rejection; its 51.5 MiB size was acceptable.
The WAV was 59.9 MiB and includes non-audio cover artwork. These are
two songs, not a universal cross-codec sample-rate/platform proof.
Private local evidence:
`D:\LMS\bliss-mood-poc\benchmark-bandcamp-lossless-20261020-220117\natural-lossless-parity-private.json`.
The WAV/FLAC controlled-source and MP3 original references must be kept
unchanged. **Do not rerun completed parity scans** just to update documents.

**Development versus distribution decision:**

- **Numerical Windows development gate: PASS**, for the exact tested
  MP3/FLAC/WAV source/cohort, ONNX binaries and worker fingerprints.
- **Windows native development-kit integrity: independently testable**
  using `scripts/audit_windows_native_release.py` on the existing
  `D:\LMS\essentia-cli-test` directory. This audits existing EXE/DLL
  bytes against `worker-dependencies.json` and cross-checks
  `NATIVE-PROVENANCE.json` including actual installed notices.
  No music, private databases, weights or files are written.
- **GitHub native Windows CI now audits the actual staged
  development kit**, after the C++/MinGW build and upstream MSYS2
  provenance inventory and before upload. It runs the same read-only
  auditor against the genuine staged EXE/DLL/notice directory and
  uploads the audit JSON with **build diagnostics**, not as a new
  licensed release artifact. This catches real package hash or notice
  mismatch independently from synthetic unit fixtures.
- **Public release/redistribution gate: BLOCKED pending manual legal
  review.** The current bundle deliberately has
  `release_approved=false` and
  `license_inventory_complete=false`. Neither source publication,
  the IPC separation, separate prerequisites nor a passing Windows
  executable automatically cures Essentia AGPL, FFmpeg/native DLL or
  MTG model rights. See
  [license/distribution strategy](essentia-licensing-distribution-strategy.md).
- **Scope and PR state:** #17 remains Draft, no merge, no modifications
  to similarity PR #16 or `main`. Similarity research may reuse the
  already verified Windows Rust-v5 CLI; it does not need new parity
  benchmarks.

### Read-only existing Windows native kit audit

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    $repo = 'D:\LMS\bliss-mood-poc'
    $kit = 'D:\LMS\essentia-cli-test'
    $output = Join-Path $repo (
        'audit-windows-essentia-release-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    )
    Set-Location $repo
    git switch feat/essentia-cpp-worker-backend
    if ($LASTEXITCODE -ne 0) { throw 'PR17 branch switch failed' }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'PR17 update failed' }

    python -m unittest discover -s tests -p 'test_audit_windows_native_release.py'
    if ($LASTEXITCODE -ne 0) { throw 'Native kit audit regression tests failed' }

    python scripts/audit_windows_native_release.py --kit-root $kit --output-dir $output
    if ($LASTEXITCODE -ne 0) {
        throw "Native bundle manifest integrity failed; audit evidence: $output"
    }
    Write-Host "Audit result saved locally: $output"
    Write-Host 'Expected truthful distribution_release_status: BLOCKED'
}
~~~

**Expected** `binary_integrity=PASS`,
`distribution_release_status=BLOCKED`, package-count and missing
notice lists. A failed hash, PE architecture or manifest consistency
check fails the audit (nonzero exit) and is **not** simply a license
review item. The audit never creates a distributable artifact nor
claims that `BLOCKED` is a technically broken scanner.

---

## Evidence and acceptance matrix

| Gate | Current decision | Evidence or condition for advancing |
| --- | --- | --- |
| Same real MP3 cohort, 100 tracks / 14,500 values, 4 Rust-v5 workers | **PASS** | Max class-score delta 1.2695789337158203e-5 vs saved original C++, tolerance 1e-3; 0 patch mismatches |
| Rust-v5 worker invariance, adaptive enabled 6 vs fixed 4 | **PASS** | 0.0 score difference across all 14,500 scores, identical patch counts and official model SHA. Controller sampled resources but made 0 adjustments |
| Adaptive-policy increase/decrease and stabilization on real music | **NOT DEMONSTRATED** | Actual run held 6 workers throughout; deterministic Rust unit tests cover simulated high/low loads, but dynamic changes under real controlled load have not been measured |
| Controlled real-song PCM24 WAV vs FLAC using same original signal | **PASS** | User's 20 October 2026 run: PCM24 SHA equal, 837 patches, both backends WAV vs FLAC score difference 0.0; C++ vs Rust v5 max 6.3700000000332935e-6 in each format (limit 1e-3). **Source was MP3-derived; not independent FLAC coverage.** |
| Windows x64 native C++ worker synthetic WAV/FLAC/MP3 fixture | **PASS (CI fixture)** | Verified original worker/ONNX handoff in native Windows workflow; does not substitute for real music |
| Two independent original lossless FLAC/WAV files | **PASS for the 2 tested downloads** | Real Bandcamp FLAC 48 kHz/24-bit and WAV 44.1 kHz/16-bit, verified original C++ vs Rust v5 (max 2.02e-6 and 1.40e-6), matching patch counts and fingerprints. Wider coverage remains open |
| Linux x86_64 original Essentia native smoke | **Partially validated** | Existing Linux CI numeric fixture, but portable packages, loader/library ABI and target distro matrix not release-qualified |
| macOS Intel / Apple Silicon, Pi 4 / piCorePlayer | **NOT QUALIFIED** | Native builds, loader/shared-library closure, ONNX runtime architecture, 1-worker memory, real-codec smoke |
| Redistributable native DLLs / `.so` / `.dylib` | **NOT LICENSE CLEARED** | Actual package dependency closure, exact source/versions, notices, counterpart source/build scripts, reproducible manifest; see licensing strategy |
| Essentia AGPL, Rust code provenance, FFmpeg/FFTW/libsamplerate licenses | **LEGAL REVIEW OPEN** | Consult `essentia-licensing-distribution-strategy.md`; test binaries are not automatically cleared for publication |
| MTG models (EffNet, Genre, Mood, Voice), weights and derived data rights | **RIGHTS OPEN** | Match downloaded exact SHA256 to each model license and separate terms for redistribution/noncommercial use |
| Stable multi-worker performance guarantee | **NOT MEASURED** | Existing 6-worker adaptive-enabled 92.8667 s vs prior 4-worker 183.2888 s is an uncontrolled between-run difference, NOT causal adaptive speedup |

**Release policy:** Do not quietly flip experimental-native DSP into a default
or advertise cross-platform/codec guarantees based solely on existing 100 MP3
parity. A merge of experimental code can be a separate explicit engineering
decision from bundling or distributing third-party binaries or model weights.
PR #16 similarity work remains separate.

## Verified controlled WAV24 / FLAC result — 20 October 2026

The user's real-song test **PASSED** on the exact source WAV and verified Rust-v5
and original C++ worker already present in the local Windows test kits:

| Measurement | Real outcome |
| --- | ---: |
| `status` | **PASS** |
| `pcm24_sha_equal` | **true** (bit-identical 24-bit PCM after independent decoding) |
| Patches, both backends / both formats | **837** |
| Original Essentia C++ vs corrected Rust v5 — WAV24 | **6.3700000000332935e-6** maximum class-score deviation |
| Original Essentia C++ vs corrected Rust v5 — FLAC | **6.3700000000332935e-6** |
| Rust v5 — WAV vs FLAC | **0.0** across class scores |
| Original C++ — WAV vs FLAC | **0.0** across class scores |

**Private report is local only** at
`D:\LMS\bliss-mood-poc\benchmark-real-wav-flac-v5-20261020-204139\private-codec-report.json`.
The controlled WAV24/FLAC pair comes from a **real song originally stored as MP3**.
The shared PCM control proves codec/container agreement for that signal,
but does not prove native independently sourced FLAC/WAV library coverage,
non-Windows portability or redistribution rights. **Do not re-run this
already PASSing gate** merely to check the report again.

The next data gap is a small set of **original, unmodified** FLAC/WAV files
sampled from the music NAS; see the native-lossless cohort gate below.

---

## Historical procedure: bit-exact decoded PCM across real-song WAV24 and FLAC (PASSED)

The existing real audio example is a full-song WAV, originally decoded from
one of the confirmed failing real MP3s during resampler root-cause analysis.
Do **not** rescan all 100 MP3 songs again just to test lossless containers.

The new helper `scripts/verify_lossless_codec_parity.py`:

1. Validates original source PCM WAV hash and prior **genuine original
   Essentia C++** plus corrected **Rust v5** results, including their exact
   official encoder/head SHA256, ordered labels, preprocessing keys and
   equal full-song patch counts.
2. Quantizes the existing **float32 PCM** into exactly **one shared
   24-bit integer WAV**. Encodes FLAC **from that quantized WAV**.
   A float32 WAV and a FLAC do **not** intrinsically represent identical
   samples; quantization is therefore explicit rather than hidden.
3. Independently decodes WAV24 and FLAC back to signed 24-bit LE PCM using
   FFmpeg. Requires byte-for-byte identity, identical raw stream lengths,
   identical original sample rates and channel counts, or **fails before
   inference**. This does not compare arbitrary input files by filename.
4. Runs the validated **same Rust-v5 analyzer binary** four times:
   `wav24/rust`, `wav24/original C++`, `flac/rust`,
   `flac/original C++`, ONNX threads 1 and same model dir.
5. Verifies each format's C++/Rust parity, both individual backend's
   WAV-vs-FLAC score parity, all patch counts, fingerprint distinction and
   the unmodified original max per-class **0.001** tolerance.
6. Writes detailed private audio controls/JSON/stderr to **one fresh
   local directory**. The script reports a concise status and max scores;
   on any failure preserve the partial output for diagnosis rather than
   rescanning blindly.

This qualifies one *controlled original real-song signal through WAV24 and
FLAC decoding*. It does not prove the quality of independently sourced FLAC
collections or float-vs-PCM24 bit equivalence, and it is not a license grant.

### Reuse existing Windows development binaries, do NOT recompile or replace

Run in **Windows PowerShell**, with installed `python`, `ffmpeg` and
`ffprobe`, and the existing official model directory. Source music and the
original MP3 cohort are never accessed.

~~~powershell
& {
    $ErrorActionPreference = 'Stop'

    $repo = 'D:\LMS\bliss-mood-poc'
    $real = Join-Path $repo 'benchmark-essentia-real-20261020-160351'
    $source = Join-Path $real 'mp3-wav-control-20261020-164836'
    $savedV5 = Join-Path $real 'rust-v5-one-track-20261020-190110'
    $rustKit = 'D:\LMS\bliss-mood-rust-v5-test'
    $nativeKit = 'D:\LMS\essentia-cli-test'
    $output = Join-Path $repo (
        'benchmark-real-wav-flac-v5-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    )

    Set-Location $repo
    git switch feat/essentia-cpp-worker-backend
    if ($LASTEXITCODE -ne 0) { throw 'Cannot switch to PR17 branch' }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Cannot update PR17 branch' }

    python -m unittest discover -s tests -p 'test_verify_lossless_codec_parity.py'
    if ($LASTEXITCODE -ne 0) { throw 'Lossless codec regression tests failed' }

    Get-Command ffmpeg -ErrorAction Stop | Out-Null
    Get-Command ffprobe -ErrorAction Stop | Out-Null

    $analyzer = Join-Path $rustKit 'bliss-mood.exe'
    $nativeWorker = Join-Path $nativeKit 'essentia-worker\bliss-essentia-worker.exe'
    $build = Join-Path $rustKit 'BUILD.txt'
    $sums = Join-Path $rustKit 'SHA256SUMS.txt'
    $mergeSha = 'a6a5c8607064e95d291cc85a0500472ff20bcc4e'
    foreach ($file in @($analyzer, $nativeWorker, $build, $sums)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Missing input: $file"
        }
    }
    if (-not (Get-Content -LiteralPath $build -Raw).Contains($mergeSha)) {
        throw 'Scanner is not the previously validated Rust-v5 build'
    }
    $line = Get-Content -LiteralPath $sums -TotalCount 1
    $m = [regex]::Match($line, '^([0-9a-fA-F]{64})\s+\*?bliss-mood\.exe\s*$')
    if (-not $m.Success) { throw 'Malformed scanner checksums' }
    if ((Get-FileHash -LiteralPath $analyzer -Algorithm SHA256).Hash -ine
        $m.Groups[1].Value) {
        throw 'Rust v5 scanner SHA256 mismatch'
    }

    $args = @(
        'scripts/verify_lossless_codec_parity.py',
        '--input-wav', (Join-Path $source 'control-from-mp3-decoded-float32.wav'),
        '--saved-cpp-wav-json', (Join-Path $source 'essentia-wav.json'),
        '--saved-rust-v5-wav-json', (Join-Path $savedV5 'rust-v5-full-wav.json'),
        '--analyzer', $analyzer,
        '--essentia-worker', $nativeWorker,
        '--models-dir', (Join-Path $repo 'models'),
        '--output-dir', $output,
        '--score-max-tolerance', '0.001'
    )

    Write-Host "`n=== ORIGINAL C++ VS RUST V5: REAL PCM WAV24 AND FLAC ==="
    python @args
    if ($LASTEXITCODE -ne 0) {
        throw "Lossless codec parity FAILED. Preserve private evidence at: $output"
    }
    Write-Host "`n=== WAV24 / FLAC CODEC GATE PASSED ==="
    Write-Host "Private results directory: $output"
}
~~~

Only paste the concise console JSON, especially `status`, `pcm24_sha_equal`,
`patches`, `wav24_cpp_vs_rust_max`, `flac_cpp_vs_rust_max`,
`rust_wav_vs_flac_max`, `cpp_wav_vs_flac_max`. Do not post source
music, raw PCM, full private class/track reports or third-party native
DLL archives.

## Historical native-lossless preflight and retry instructions (PASSED after correction)

**Initial 20 October 2026 result: PRE-INFERENCE FILTER, NOT PARITY FAILURE.**
The user provided a locally downloaded **48 kHz / 24-bit stereo FLAC**
and **44.1 kHz / 16-bit stereo WAV** of *different* songs. The WAV
also contains an MJPEG embedded-cover stream; the native test selects
the first audio stream via ffprobe `-select_streams a:0`.
The first test terminated at source selection: `Explicit .flac outside
bounded duration/size/rate limits`. The 48 kHz rate is explicitly
allowed; the old generic message did not distinguish a long song
(>420 seconds) from a large file (>150 MiB). No ONNX inference or
C++/Rust score comparison took place. No prior sidecars were touched.

**Correction:** For exactly two explicitly named lossless original
files, the helper now reports the *actual* duration/file size and the
specific violated limits. Explicit mode allows a deliberately bounded
`--max-seconds 1800 --max-file-mib 512` override, without widening
the automatic NAS traversal (still limited to 900 seconds). A song
over 1800 seconds or 512 MiB should be replaced with a shorter/smaller
original track, rather than trimming/transcoding it and calling it
an untouched original. The strict **0.001** score tolerance is unchanged.

The test script `scripts/verify_original_lossless_tracks.py` always:
- Reads **only** the two exact local FLAC/WAV sources; it does not
  reanalyze the prior 100-MP3 cohort, modify NAS or overwrite sidecars.
- Validates the existing genuine Essentia-C++/corrected Rust-v5 real
  WAV reference, exact ONNX weights/label order, native worker SHA and
  backend fingerprint; compares both models on each source (4 calls).
- Requires the exact same source audio SHA256 in the two backend
  reports, equal patch count and max per-class-score error <=0.001.
  Source file SHA256 is verified before and after scan.
- Retains full JSON/diagnostics locally in one new private folder.
  Track paths, titles and copied model/native binaries do not go
  into public GitHub logs. The MP3 twins are useful provenance but
  **cannot** be used as bit-identical PCM references.

### Ready-to-run Bandcamp retry, without NAS search

Place the two locally copied downloads as `sample.flac` and
`sample.wav` in `D:\LMS\bliss-mood-lossless-test`. In Windows
PowerShell run the existing single-block experiment with the following
additional flags inserted in the Python `$arguments` array:

~~~powershell
'--track', 'sample.flac',
'--track', 'sample.wav',
'--max-seconds', '1800',
'--max-file-mib', '512',
~~~

**Before rerunning**, print actual source metadata (no NAS scan):
~~~powershell
& {
    $root = 'D:\LMS\bliss-mood-lossless-test'
    foreach ($name in @('sample.flac', 'sample.wav')) {
        $file = Join-Path $root $name
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Missing downloaded source: $file"
        }
        $sizeMiB = (Get-Item -LiteralPath $file).Length / 1MB
        $info = ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate,channels,bits_per_raw_sample,bits_per_sample:format=duration -of json "$file" | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw "Audio probe failed: $name" }
        $seconds = [double]$info.format.duration
        Write-Host ("{0}: {1:N1}s, {2:N1}MiB, {3}Hz, {4}ch" -f $name, $seconds, $sizeMiB, $info.streams[0].sample_rate, $info.streams[0].channels)
        if ($seconds -gt 1800 -or $seconds -lt 30 -or $sizeMiB -gt 512) {
            throw "Original song is outside permitted bounded test: $name"
        }
    }
}
~~~

For a fully self-checking command, reuse the already provided Windows
test harness with exactly the new explicit bounds and the same
pinned executable/ONNX/C++ worker and saved real-WAV references. Do
not repeat the successful controlled WAV24/FLAC test.

## Historical next steps (superseded by completed native lossless test)

If it passes, preserve the evidence and select *a bounded real naturally
occurring FLAC/WAV sample* with different sample rates, durations and
channels for later testing. Do not present the converted test file as a
new independent library track. Reuse the comparison tools and official
models; prioritize the specific audio formats/platforms to be supported
before declaring any product-wide codec guarantee.

The [licensing/distribution strategy](essentia-licensing-distribution-strategy.md)
remains the source of outstanding legal release work. It deliberately
does not equate "users download the DLLs" with a categorical GPL/AGPL
compliance exemption.
