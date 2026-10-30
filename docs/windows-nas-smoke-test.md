# Windows NAS smoke test: relative Bliss track keys

These steps use an exact relative Bliss track key and the existing NAS mount. Start with one song, NOT 65k.

## 1. Pull the current source

    Set-Location 'D:\LMS\bliss-mood-poc'
    git status --short
    git pull --ff-only

Review local changes before pulling; do not overwrite local work.

## 2. Test the UNC share and the local toolchain

    $sourceRoot = '\\192.168.1.100\music'
    $trackKey = 'Acid Mammoth/2024 - Supersonic Megafuana Collision/04 Atomic Shaman.mp3'
    $song = Join-Path $sourceRoot ($trackKey -replace '/', '\')
    Test-Path -LiteralPath $song
    Get-Command cargo, ffmpeg

The file must be accessible. The trackKey must exactly match the path stored in the Lyrion Bliss database.

## 3. Download official models and compile

    .\scripts\download-models.ps1
    cargo test
    cargo build --release

The ort crate builds/downloads native ONNX Runtime dependencies on first build.

## 4. Analyze one song and persist experimental Mood scores

    .\target\release\bliss-mood.exe analyze $song --models-dir .\models --threads 2 --max-patches 10 --db .\mood-test.db --track-key $trackKey --json | Tee-Object .\mood-first-track.json

The command reads the NAS MP3 but never modifies it. The output mood-test.db is a new independent SQLite DB in the clone root. At this stage numerical equivalence with Essentia is NOT established, so these scores are marked experimental.

If ONNX inference fails, capture the full error and check the dedicated GitHub Actions ONNX model smoke test; do not start a library-wide job.

## 5. Batch pilot against a local copy of bliss.db

Obtain a consistent snapshot of the Pi's upstream bliss.db using SQLite's online-backup method or by copying when there are no active writers. Store it locally as D:\LMS\bliss-mood-poc\bliss.db. Never modify the live LMS source.

The one-track dry-run (read-only):

    .\target\release\bliss-mood.exe scan --bliss-db .\bliss.db --db .\mood-test.db --models-dir .\models --source-root '\\192.168.1.100\music' --only-track 'Acid Mammoth/2024 - Supersonic Megafuana Collision/04 Atomic Shaman.mp3' --dry-run --json

Use --source-root only. The Bliss keys are RELATIVE to the share: there is no leading /mnt/music prefix and --library-root must be omitted.

To test successful incremental persistence, repeat without --dry-run, then rerun and check the up_to_date counter. Single-file mode 'analyze' intentionally does not store an incremental file stat and therefore the first 'scan' updates it once.

## 6. Later Pi follow-up

On the Pi the same relative keys require --source-root pointing at the ACTUAL persistent NAS mount directory on piCorePlayer (not a Windows UNC path). Before enabling a post-library-scan hook, verify ARM compatibility, compare Windows/Pi mtime resolution and run --dry-run against the imported DB. A mass reanalysis after transferring the first 65k rows must be avoided.

See docs/lyrion-hybrid-analysis.md. Never deploy scores for live mixing until Essentia parity is validated.
