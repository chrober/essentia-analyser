# Next-chat Handover-Prompt: Original Essentia C++ unter Windows

Stand: 20.10.2026. Der letzte vollständig **überprüfte Code-Head** ist `e011e99f1dc38790ec441720b696a2f3fe4602e1`. Nachfolgende reine Dokumentationscommits ändern den Branch-Head; die neue Session muss die **Live-CI-Prüfungen für den aktuellen Head** erneut auslesen.

---

Wir setzen **Lyrion: Mood Analysis / bliss-mood-poc** fort.

Nutze direkt das verbundene GitHub-Repository https://github.com/chrober/bliss-mood-poc auf dem Feature-Branch `feat/essentia-cpp-worker-backend` und arbeite in der **Draft-PR #17** https://github.com/chrober/bliss-mood-poc/pull/17. **Nicht nach `main` mergen**, Draft beibehalten und `lms-blissmixer-lab` nicht ändern.

**Lies vor der Implementierung die aktuellen GitHub-Dateien:**
- `docs/handover-essentia-cpp-20261020.md` — umfassender Architektur-/CI-/Fortschrittsbericht einschließlich neuer CI-Statussektion.
- `docs/handover-essentia-windows-linker-20261020.md` — konkrete MinGW-Export-/Import-/Linker-Diagnostik und Entscheidungspfad.
- `docs/essentia-cpp-worker-architecture.md`, `docs/essentia-cpp-windows-native-build.md`, `docs/essentia-cpp-windows-packaging.md` — Implementierung und Packaging.
- Workflows `.github/workflows/native-essentia-windows.yml` und `.github/workflows/native-essentia-cpp.yml`; Quellen `native/essentia_cpp_worker.cpp`, `native/CMakeLists.txt`, `src/essentia_worker.rs`, `src/features.rs`.

**Letzter verifizierter Zustand am Code-SHA `e011e99f1dc3`: Sechs von acht CI-Runs grün, zwei rot.**

1. **Windows-Original-Essentia-C++:** https://github.com/chrober/bliss-mood-poc/actions/runs/39389850876 — die gepinnte original upstream Essentia-Bibliothek `essentia.dll` (MinGW64/FFmpeg9) baut erfolgreich und unser echter Worker kompiliert. **Sein finaler Link scheitert** an `essentia::init()`, `shutdown()`, `Logger::debug()`, `ParameterMap::add()`, `nameOfType()` und weiteren Symbolen. Export-/Import-/ABI-/Link-Konfiguration ist noch ungeklärt; die echten Windows-Audio-, DLL-Closure- und Paritätsschritte wurden noch nicht ausgeführt.
2. **Linux-Original-Essentia-C++:** https://github.com/chrober/bliss-mood-poc/actions/runs/39389850681 — der native Worker, Audio-/Mel-Tests und Mehrformat-Mel-Parität bestanden. Danach scheiterte der Download offizieller ONNX-Modelle von `essentia.upf.edu` mit **curl Fehler 28, HTTP-Verbindungs-Timeout**. Das ist **kein nachgewiesener numerischer Regressionsfehler**. Die komplette frühere Linux-WAV/FLAC/MP3→1280-D EffNet→87/56/2-Head-Parität ist durch https://github.com/chrober/bliss-mood-poc/actions/runs/39373185587 bestätigt. Modellparität wurde auf dem neuesten Code-Head aber wegen des Downloads nicht erneut ausgeführt.
3. Rust/Clippy, Windows-Rust-Programm, Genre-/Voice-Parität und synthetische Windows-DLL-Paketierung bestanden beim zuletzt überprüften Code-Head.

**Deine konkrete nächste Aufgabe:** Untersuche und behebe zuerst den Windows-Original-Essentia-Linkerfehler. Ergänze nötigenfalls Fail-Fast-CI-Diagnostik für `objdump -p`/PE-Exporttabelle, `nm -gC`/Import-Libraries, `pkg-config --libs essentia` und `cmake --build ... --verbose`. Ermittle die **nachgewiesene** Ursache (fehlende DLL-Exporte/MinGW-Importbibliothek, falsches Linkziel/Linkreihenfolge, ABI etc.), bevor du Build-Flags oder Linkmodus änderst. Bevorzuge Original-Essentia samt Upstream-Buildmechanik; prüfe ggf. kontrolliertes statisches Linken. **Keine Dummy-Stubs, kein `essentia-rs`, keine eigene DSP-Nachimplementierung und keine unkontrollierte Änderung an den Algorithmen.**

**Unterschiedliche Upstream-Pins:** Linux hat den numerisch validierten Essentia-Stand `9ceef0a3a7900ad51eb42aa5b6c6789b4bec6a47` (FFmpeg4.4). Windows nutzt `b0661db99be4a8e2c6fabbe90a996f89786fdd8e` aus dem noch offenen upstream PR #1540 (FFmpeg9). Ein Windows-Build muss deshalb **eigenständig** numerisch gegen Rust und nach Möglichkeit gegen die Linux-Referenz validiert werden.

Nach dem Link-Fix: echter Windows-`EFW1/REQ1/RES1`-Handshake inklusive binärer Pipes und mehreren WAV/FLAC/MP3-Jobs; Paket mit allen realen DLL-Abhängigkeiten samt SHA256 erstellen und isoliert ausführen; Windows-Mel-, 1280-D EffNet- und 87/56/2-Head-Parität mit offiziellen Modellgewichten testen; Linux-ONNX-Netzwerkfehler durch erneuten Zugriff bzw. sichere, integritätsgeprüfte Modelldownloads beheben; anschließend auf derselben begrenzten lokalen Bliss-Stichprobe das vorbereitete A/B-Benchmarking (1/2/4/6 Worker) ausführen. **Keine Aussagen über Produktionsreife ohne diese Gates.**

**Feste Entscheidungen:** Rust ist der bestehende Standard und Orchestrator (adaptive Multi-Worker, ONNX-Sessions, SQLite-Single-Writer und Prozess-RAM-Messung bleiben unverändert). Original Essentia C++ ist nur per `--audio-backend essentia` opt-in. `bliss.db` und NAS-Audio bleiben read-only; nie private Musik, Benchmarks oder Modellgewichte committen. Vor lokalen Tests GitHub Actions und zum Code-Commit passenden Windows-x64-Artefaktlauf prüfen; **keine lokalen Rust-Builds auf dem Windows-Rechner** verlangen. PowerShell-Code immer als einen vollständigen äußeren Block `& { ... }` schreiben.

**Bitte ohne neue Grundsatzdiskussion direkt die GitHub-Arbeit fortsetzen, CI-Ergebnisse auf dem exakten HEAD prüfen und nur belegte Testergebnisse als bestanden dokumentieren.**

---
