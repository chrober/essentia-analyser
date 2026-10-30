# Workstation bootstrap + Pi 4 incremental Mood scans

**Status:** Native Rust batch/incremental engine exists. Lyrion post-scan plugin integration and the ARM/piCorePlayer execution path are not yet implemented or validated.

## Desired operation

1. Initial analysis of ~65,000 songs on a powerful Windows/Linux host. Read a **copy** of the Pi's Bliss SQLite database to obtain each exact TracksV2.File identity. Use root mapping for the actual audio location on the analysis machine.
2. Transfer the finished mood.db to a persistent LMS data directory on the Pi, not a volatile piCorePlayer RAM filesystem. Stage the file and atomically rename while no active writer is running. Never copy a live SQLite WAL database without an SQLite backup.
3. After each completed LMS library scan, the Mood plugin launches the same ARM64 Rust analyzer on the Pi. It should also wait for the existing Bliss analyzer to finish (or read a consistent snapshot) before reconciling the library.
4. On the Pi, compare each Bliss file key with mood.db: skip only when file size, modification timestamp and exact model/preprocessing fingerprint agree; otherwise analyze and upsert. Missing or bad songs do not erase previously stored results.
5. Mix generation reads mood.db with zero ONNX inference and falls back to ordinary Bliss when no **validated** scores exist.

## Implemented commands

PowerShell first analysis (the root paths are *illustrative* and must match your library):

    bliss-mood scan --bliss-db .\bliss.db --db .\mood.db --models-dir .\models --library-root "/mnt/music" --source-root "D:\Music" --threads 4 --json

Read-only preview on Pi:

    ./bliss-mood scan --bliss-db /path/to/bliss.db --db /path/to/mood.db --models-dir /path/to/models --threads 1 --dry-run --json

Small incremental Pi batch:

    nice -n 15 ./bliss-mood scan --bliss-db /path/to/bliss.db --db /path/to/mood.db --models-dir /path/to/models --threads 1 --max-new 20 --json

The Rust CLI reads Bliss's TracksV2.File WHERE Ignore IS NOT 1 in read-only mode. The ONNX sessions are loaded only when needed and **reused for the entire run**. It writes each successful analysis independently to a versioned SQLite mood.db. It never prunes by default.

## SQLite identity and cross-host caveats

- SQLite schema v2 adds a compact mood_track_state table for file_size, modified_ns and model_key to the v1 score/model tables. v1 databases migrate without deleting scores.
- A newly analyzed audio file gets a SHA-256, but existing files are not rehashed every scan (that would be expensive across 65k tracks).
- The initial host and Pi should access the same media, preferably the same NAS-backed files. Differences in mtime precision between Windows/SMB and Linux may cause mass invalidation. **Inspect the --dry-run summary before enabling automatic follow-up on the Pi**. If tens of thousands appear stale, fix cross-host file identity rather than starting a full Pi reanalysis.
- Never use Bliss's internal rowid as a persistent external identifier. Exact TracksV2.File values determine identity.

## Post-scan plugin design (future integration)

Mirror upstream BlissMixer's post-scan Importer and background analyzer command, but do not modify its registration or the original bliss.db. The separate Mood/BlissMixerLab adapter should:

- Register its own end-of-library-scan callback and schedule one background worker, rather than performing ONNX inside the Perl callback.
- Coalesce scan events and never run multiple competing analyzer instances.
- Offer opt-in auto-analysis, status counters, low CPU priority, 1-thread default, a small --max-new limit, and manual restart/stop.
- Wait until Bliss Analyzer is idle or use a stable copy of its database; avoid concurrent rebuild races.
- Store mood.db in a persistent directory and read/cache a consistent snapshot for mixing.
- Leave existing BlissMixerLab/BetterCallBliss functional with mood enabled or disabled.

## Raspberry Pi 4 / piCorePlayer 11.1.0 validation

- Prefer the official 64-bit piCorePlayer image (verify actual CPU/userspace architecture).
- ARM64 ONNX Runtime support does *not* guarantee that the published binaries execute on piCorePlayer or support Cortex-A72 CPU instructions. Test native library linkage, libc ABI, FFmpeg availability, and actual ONNX inference.
- If deploying ONNX Runtime proves difficult, test the exact models using the Rust inference framework 'tract'.
- Benchmark during Lyrion playback: resident RAM peak, per-song wall clock, CPU governor/temperature, throttling, UI latency, and audio dropouts. Start with one process, one inference thread, and five songs.
- Current model preprocessing is explicitly unvalidated against Essentia. No productive plugin use of its experimental scores before numerical parity and a real Pi run.
