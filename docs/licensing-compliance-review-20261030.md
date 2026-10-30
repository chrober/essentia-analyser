# Lizenz- und Distributionsprüfung — Essentia Analyser (30. Oktober 2026)

> **Status: SOURCE-ONLY DEVELOPMENT; PUBLIC NATIVE-BINARY RELEASE = BLOCKED.**
>
> Diese Prüfung dokumentiert die **aktuell belastbare technische/urheberrechtliche Evidenz** und offene juristische Fragen, nicht die abschließende Rechtsberatung oder eine Lizenzfreigabe. Insbesondere machen der MIT-Lizenztext, ein erfolgreicher CI-Build, separate Executables oder nutzerseitige Downloads eine nicht geprüfte Drittanbieterdistribution **nicht** automatisch zulässig.

> **Project context explicitly confirmed on 30 October 2026:** `essentia-analyser` is a **free-of-charge open-source project for the Lyrion community**. **No commercial use or product offering is intended by the maintainers.** The permanent general research lab `bliss-mood-poc`, the standalone scanner, the separate similarity engine and Guidance integrations are intentionally **separate repositories**. There is **no request or plan to merge them**. The purpose of this audit is to make an eventual **free, licence-compliant community installation** possible, **not** to prepare a commercial product or buy proprietary licences. See [community project policy](community-project-policy.md).
>
> **Scope correction:** `BLOCKED` concerns **unverified public native binary packaging**, not further source development, private local experiments, independent scientific research, contributing, or a requirement to obtain commercial MTG licences. A free download is nonetheless a redistribution, and external model terms still apply. Maintain the existing MIT licence for owned source; MIT formally permits commercial downstream reuse despite our own noncommercial intent.

## 1. Herkunft der belegten Befunde

| Gegenstand | Quelle, Stichtag und Reichweite |
| --- | --- |
| Lizenzstrategie und Risiken | [`bliss-mood-poc/docs/essentia-licensing-distribution-strategy.md`](https://github.com/chrober/bliss-mood-poc/blob/9a9ca062f9bf5adacb640f89c9dc8cf29895f951/docs/essentia-licensing-distribution-strategy.md), ursprüngliche Notizen 20.–28.10.2026 |
| Native Windows-Kit-Audit und Release-Gates | [`docs/release-qualification-gates.md`](release-qualification-gates.md), [`docs/windows-essentia-local-test-kit.md`](windows-essentia-local-test-kit.md), [`scripts/audit_windows_native_release.py`](../scripts/audit_windows_native_release.py) und [`scripts/triage_windows_native_license_gaps.py`](../scripts/triage_windows_native_license_gaps.py). **Alte Messung 21.10.2026**, nicht erneut am privaten Kit ausgeführt |
| Übernommener Lizenz-/Programmstand | [`Cargo.toml`](../Cargo.toml), [`Cargo.lock`](../Cargo.lock), [`LICENSE`](../LICENSE), [`src/preprocess.rs`](../src/preprocess.rs), [`src/audio_decode.rs`](../src/audio_decode.rs), [`native/essentia_cpp_worker.cpp`](../native/essentia_cpp_worker.cpp), [`native/CMakeLists.txt`](../native/CMakeLists.txt), [`scripts/download-models.ps1`](../scripts/download-models.ps1), [`model-registry.json`](../model-registry.json) |
| Neue Repo-Veröffentlichung | [`essentia-analyser` extraction PR #1](https://github.com/chrober/essentia-analyser/pull/1), [`docs/extraction-provenance.md`](extraction-provenance.md), [`scanner-ci.yml`](../.github/workflows/scanner-ci.yml). Source-only: keine UPF-Essentia-Library, keine ONNX-Gewichte, keine FFmpeg-/MinGW-DLLs im Git-Tree und **kein CI Upload/Release-Schritt** |
| Externes Original | Essentia pinned Windows source [`b0661db` Licensing](https://github.com/MTG/essentia/blob/b0661db99be4a8e2c6fabbe90a996f89786fdd8e/Essentia%20Licensing.txt), [Essentia-Website](https://essentia.upf.edu/licensing_information.html), [Essentia-Modellübersicht](https://essentia.upf.edu/models.html), [FFmpeg Legal](https://ffmpeg.org/legal.html), [ONNX Runtime MIT](https://github.com/microsoft/onnxruntime/blob/main/LICENSE), [GNU GPL/AGPL FAQ](https://www.gnu.org/licenses/gpl-faq.en.html) |

Das ausführliche historische `bliss-mood-poc`-Dokument ist **weiterhin eine Referenz**, aber seit der Ausgliederung liegt die operative Release-Compliance-Verantwortung für den Scanner **hier**.

## 2. Präzise Aufteilung nach Komponenten

| Bestandteil / Binärform | Vorliegende Evidenz | Noch zu klären |
| --- | --- | --- |
| **Eigene Rust-CLI `bliss-mood(.exe)`** | Repository-`LICENSE` und `Cargo.toml` deklarieren **MIT** für eigene Quellteile; `ort`, `rustfft`, `rusqlite`, `clap` und `serde` im Cargo-Manifest; sperrt selbst keine externe Modellauswahl | **Provenienz** der Essentia-nachgebauten `src/preprocess.rs` und `src/audio_decode.rs`; **vollständige Cargo.lock-SBOM** mit exakten Crate-Lizenzen und Notices; eventuelle dynamische ONNX Runtime Runtime-Komponenten |
| **Eigener C++-Worker `bliss-essentia-worker(.exe)`** | Eigener C++-Adapter verwendet und **linkt unmittelbar gegen** original MTG Essentia C++; Quelltext importiert, keine upstream Essentia-Source in diesem Repository | AGPL-Anforderungen für **das gelinkte/weitergegebene Worker-Binary**, einschl. korrespondierendem Source/Build/Notices; Herkunft/Weitergaberechte am eigenen Adapter; ob dessen Lizenzierung für das kombinierte Werk angepasst werden muss |
| **Upstream MTG Essentia** | Gepinnte Windows-Revisionslizenz bestätigt **GNU AGPL-3.0-or-later**; Linux CI benutzte teils einen anderen gepinnten Upstream-Commit; Essentia enthält weitere Drittkomponenten | Exakten **je Plattform** gebauten Commit, Änderungen, Third-Party-Lizenzen, Buildparameter und korrespondierende Quellen/Build-Anleitungen beweisbar archivieren; AGPL-Copyleft und §13 bei geeigneter modifizierter netzinteraktiver Version juristisch prüfen |
| **Rust↔C++ EFW1/REQ1/RES1 Pipes** | Zwei Prozesse, expliziter Binärvertrag (Pfad-Anforderung, Mel-Patch-Floatdaten), eng koordiniertes DSP/Inference-Verfahren; das Vorhandensein zweier EXEs beweist keine eigenständigen Werke | Eigenständiges Werk oder gemeinsam zu behandelnde Kombination? Bewertung der konkreten IPC-Kopplung/Weitergabe durch kundige OSS-Lizenzprüfung; **kein** automatischer MIT-/AGPL-Trennungsbeweis |
| **FFmpeg im Rust-DSP-Pfad** | `src/audio_decode.rs` startet externe `ffmpeg`/`ffprobe`-Befehle, statt FFmpeg einzubetten | Für ein mitgeliefertes FFmpeg-Binary die **tatsächliche** FFmpeg-Konfiguration/Lizenz, Source/Notice und Weitergabe prüfen; separate nutzerseitige Installation reduziert eigene Binärweitergabe |
| **FFmpeg, FFTW etc. im C++-Build** | MTG MonoLoader nutzt libav/FFmpeg; FFTW kann GPL-pflichtig sein; libsamplerate und weitere Bibliotheken versionsabhängig | FFmpeg `--enable-gpl`, `--enable-version3`, `--enable-nonfree` und tatsächliche dynamische Imports/Versionen identifizieren; keine Lizenz anhand des DLL-Namens erraten; audio-only Alternative reproduzierbar neu bauen/prüfen |
| **ONNX Runtime und Rust `ort`** | Microsofts ONNX Runtime selbst **MIT**, unabhängig von den Modellen | `Cargo.lock`-basierte transitive Lizenzinventur und die wirklich bezogenen MSVC/Linux/ARM64-Runtime-Binaries |
| **4 ONNX-Gewichte** | [`model-registry.json`](../model-registry.json) referenziert **Discogs-EffNet bsdynamic**, **MTG-Jamendo Mood/Theme 56**, **MTG-Jamendo Genre 87**, **Voice/Instrumental 2**. Gewichte liegen nicht im Repo; [Downloader](../scripts/download-models.ps1) lädt sie direkt vom Essentia-Webserver | **Jedes Gewicht individuell**: konkrete aktuelle Lizenzdatei und Version, Quelle/URL, SHA-256, rechtmäßige Nutzungsart, Attribution, Weitergabe und ggf. kommerzielle Zusatzlizenz bei MTG; keine pauschale Übernahme aus dem allgemeinen Website-Text |

### Zentrale offizielle Lizenzinkonsistenz bei den Modellen

- [`essentia.upf.edu/models.html`](https://essentia.upf.edu/models.html) nennt **CC BY-NC-SA 4.0** für von MTG erstellte Modelle und fordert ausdrücklich, die jeweilige **Modell-LICENSE** zu prüfen.
- [`essentia.upf.edu/licensing_information.html`](https://essentia.upf.edu/licensing_information.html) nennt dagegen **CC BY-NC-ND 4.0** allgemein für Essentia-Modelle.

**Beide Varianten beschränken die lizenzierte Nutzung auf NonCommercial.** Die abweichenden SA- vs. ND-Regeln dürfen nicht stillschweigend vereinheitlicht werden. Aus dem derzeitigen Modellregister und Downloader ergibt sich **kein per-Datei-Lizenznachweis** für die vier exakt verwendeten Gewichte. **Kommerzielle Nutzung ist nicht unser Projektziel.** Für die geplante kostenlose, nichtkommerzielle Lyrion-Community-Nutzung sind die **konkreten Modell-LICENSE-Texte und Bedingungen** entscheidend: diese pro Gewicht verifizieren, inklusive Attribution und Download-/Weitergaberechten. Eine kostenpflichtige kommerzielle MTG-Lizenz ist **keine aktuell angestrebte Aufgabe**; bei Unklarheiten lieber eine gezielte Frage zur nichtkommerziellen Community-Nutzung an MTG richten. Das separat heruntergeladene Modell ist dadurch **nicht** lizenzfrei. Die Nutzung eigener analysierter Feature-Vektoren muss ggf. eigenständig rechtlich bewertet werden; nicht ungeprüft mit der Gewichtsdistribution gleichsetzen.

**Zusätzlich:** Der bestehende Downloader verifiziert bislang nur Nicht-Leere; kein gepinnter SHA-256-Vergleich, kein unveränderliches Version-/Lizenzmanifest, keine Bestätigung der konkreten Lizenzbedingungen. Vor einem allgemeinen Installer muss dies technisch und organisatorisch nachgerüstet werden.

### Rechtliche Feinheit: AGPL vs. NonCommercial

Die **GNU AGPL** ist eine freie Copyleft-Lizenz und untersagt kommerzielle Nutzung **nicht pauschal**, auch wenn Essentias Marketing-/Licensing-Seite sie als Weg für nichtkommerzielle Anwendungen beschreibt. Pflichten können durch Weitergabe eines abgeleiteten/kombinierten Werkes und bei einer unter §13 fallenden netzinteraktiven modifizierten Version entstehen. Der **CC-NC-Modellvertrag** ist eine **separate** Nutzungsrestriktion. Kommerzielle Nutzungsfragen von **Essentia-Code** und **Modellgewichten** dürfen deshalb nicht vermischt werden.

## 3. Belegter Windows-Lizenzinventurstatus (ursprüngliches Kit vom 21.10.2026)

Der bisherige private Audit bestätigte **100 native EXE/DLL-Dateien**, **77 zugeordnete MSYS2-Pakete** und **94 gültige Referenzen auf tatsächlich vorhandene Notice-Dateien**. Bei **17 Paketen** wurde jedoch **keine installierte Notice-Datei** gefunden. Das ist eine **Nachweislücke, nicht der Beweis fehlender Lizenzrechte**. Das damalige Kit behält `release_approved=false`, `license_inventory_complete=false`, `distribution_release_status=BLOCKED`.

Im bisherigen Kit betroffene MSYS2-Pakete (exakte Versionen sind **aus dem privaten Bericht** wieder zu ermitteln, nicht aus dem Namen zu erraten):

`mingw-w64-x86_64-ffmpeg`, `mingw-w64-x86_64-fftw`, `mingw-w64-x86_64-gmp`, `mingw-w64-x86_64-gnutls`, `mingw-w64-x86_64-lame`, `mingw-w64-x86_64-libidn2`, `mingw-w64-x86_64-libssh`, `mingw-w64-x86_64-libtheora`, `mingw-w64-x86_64-libvorbis`, `mingw-w64-x86_64-libvpx`, `mingw-w64-x86_64-libx264`, `mingw-w64-x86_64-nettle`, `mingw-w64-x86_64-opencore-amr`, `mingw-w64-x86_64-p11-kit`, `mingw-w64-x86_64-rtmpdump`, `mingw-w64-x86_64-x265`, `mingw-w64-x86_64-xvidcore`.

Der exakte private Auditbericht und das Kit wurden **bei dieser Repository-Review nicht neu eingesehen**. Für eine Freigabe sind die gebauten Artefakte und per-Version-Lizenztexte wieder zusammenzuführen. Vorhandene GPL-Bibliotheksnamen in der Closure allein beweisen weder `--enable-gpl` noch tatsächliche Link-Konstellation; die originale FFmpeg-`configure`-Zeile fehlt als Beleg.

Der frühere öffentliche `bliss-mood-essentia-windows-x64-dev`-Workflow hatte ein echtes native EXE/DLL-Artefakt hochgeladen. Der Zusatz `dev` ist **keine interne Nutzungsausnahme**. Bereits veröffentlichte Alt-Artefakte sind separat auf Sichtbarkeit/Downloads und Quellcodepflichten zu prüfen. Die neu eingerichtete `essentia-analyser`-CI baut **nur das Rust-CLI und einen synthetischen C++-IPC-Testprozess**, besitzt **keinen** Schritt für die Weitergabe einer echten Essentia-Library, Worker-Binärpakete oder Modellgewichte.

## 4. Distributionsszenarien und Entscheidung

| Szenario | Was wir selbst weitergeben | Status |
| --- | --- | --- |
| **A – Komplettpaket**: Rust CLI + C++ Worker + Essentia/FFmpeg/DLL-Closure + ggf. Modelle | Eigene Binaries und fremde verknüpfte Binaries/Modelle | **BLOCKED**: vollständige AGPL-, FFmpeg-/GPL-/LGPL-, Modell- und Native-Notice-Compliance notwendig |
| **B – Rust CLI + fertiger C++ Worker**, System installiert `libessentia`, DLLs etc. separat | Eigenes Rust-Binary **und** unmittelbar Essentia-gelinkten Worker | **BLOCKED**: allein nicht hinreichend für Worker-AGPL und IPC-/Copyleft-Grenzfrage |
| **C – Source-first**: eigene Quelltexte + reproduzierbare Worker-/Systembuild-Anleitung, Modelle vom offiziellen Anbieter | Eigenes Quellen-Repo; weniger von uns bereitgestellte Dritt-Binaries | **Bevorzugte technische Untersuchung**, aber **keine pauschale AGPL-/Modelllizenz-Ausnahme** und keine juristische Freigabe der konkreten Kombination |
| **D – Nur Rust-DSP**: kein C++ Worker; externes FFmpeg als Nutzer-Prerequisite; eigene Rust-CLI | Eigenes Rust-Binary, ggf. normale transitive Rust-/ONNX-Binary-Links | **Weniger native Copyleft-Komplexität**, aber noch **Rust-DSP-Provenienz**, komplette Rust-SBOM und **MTG-NC-Modellnutzung** klären |

Ein Nutzerseitiger Direktdownload von offiziellen Servern reduziert unsere eigene **Weitergabe fremder Dateien**, ändert aber nicht die Lizenzbedingungen, die **Nutzung** der heruntergeladenen Komponenten, oder die Frage, ob wir eine eng gekoppelten Programmkomplex ausliefern/anleiten. Spiegelserver oder mitgelieferte Download-Archive sind wieder eigene Weitergabe.

## 5. Verbindliche technische und juristische Freigabegates

**Unmittelbar und ohne Audio-Neuscan:**

1. **Quellcode-Herkunft** der Rust-DSP-Nachimplementierung sowie des C++-Adapters dokumentieren und unabhängige Implementierung/übernommene geschützte Codeanteile prüfen.
2. **SBOM für Rust** aus dem tatsächlich verwendeten `Cargo.lock` (inkl. transitive Build- und Laufzeitbibliotheken) mit per-Crate-Lizenztexten, `cargo-deny`/Lizenzreport und reproduzierbaren Versionen. Das Manifest-MIT ist **keine** Transitivlizenzbescheinigung.
3. **Essentia-Lizenz** am exakten Windows- und Linux-Pin jeweils archivieren; kombinierte Worker-/AGPL-, IPC- und ggf. Netzwerk-Situation fachkundig prüfen. Korrespondierende Quelltexte/Build-/Installationsskripte und Hinweise versioniert bereitstellen, wenn Weitergabe rechtmäßig erfolgt.
4. **Modelle einzeln klären**: alle vier URLs/Hashes/Metadaten und maßgeblichen Lizenzbedingungen, Attribution sowie Rechte für **nichtkommerzielle Community-Nutzung und nutzerseitigen Download** dokumentieren. Nur bei konkreten Unklarheiten MTG gezielt um Klärung bitten; **keine kommerzielle Lizenzierungsinitiative**.
5. **FFmpeg-Konfiguration** und tatsächliche Binary-Imports/Quellversion pro Distributionsplattform auditieren (`--enable-gpl`, `--enable-version3`, `--enable-nonfree`, notwendige Audio-Codecs); ggf. eine **kleinere Audio-only**-Buildkonfiguration unabhängig bauen und testen.
6. **17 Windows-Notice-Lücken** im früheren Audit mit **den exakten Paketversionen** durch `triage_windows_native_license_gaps.py`, originale Lizenztexte und DLL→Paket→Source-Closure schließen; nie aus einem reinen Hash-PASS eine rechtliche Freigabe ableiten.
7. **Installer/Downloads** nur mit verifizierten Pins/Hashes, Herkunft, Lizenzhinweisen, kontrolliertem opt-in, reproduzierbarem Dependency-Manifest, klaren Fehlschlägen und niemals stillschweigendem Copy/Mirror von Drittanbieterdateien.
8. **Plattform und Release**: Linux / macOS / Pi4 aarch64 Lizenz- und native Build/ABI/Source-Compliance separat. Verhindern, dass öffentliche GitHub Actions, Releases oder ZIPs die Sperre durch neue Artifact-Uploads umgehen. Bestehende alte öffentliche Artefakte separat prüfen.
9. **Konkrete Compliance-Entscheidung vor einem öffentlich herunterladbaren nativen Binary-Release**: GPL/AGPL-Kombination, Third-Party-Lizenzen, korrespondierende Quelltexte/Notices sowie die tatsächlich angebotenen Modell-Dateien bzw. deren **separaten Bezug** prüfen. Kein kommerzieller Release geplant; `release_approved` bleibt **für solche Binärpakete** bis dahin `false`. Die Entwicklung und öffentliche Quellenverfügbarkeit laufen unabhängig davon weiter.

**Keine private Audiodatei benötigt**: Alle obigen Prüfungen sind Lizenz-/Quellcode-/Abhängigkeitsaufgaben und verlangen keinen erneuten Songscan.

## 6. Aktueller präziser Gesamtstatus

- **Im GitHub-Repository tatsächlich vorhanden:** eigener Rust-/C++-Quellcode unter übernommener MIT-Lizenzdeklaration, `Cargo.lock`, native Worker Build-Skripte, original Lizenz-/Release-Risiko-Dokumentation und eigene source-only CI.
- **Noch nicht nachgewiesen:** unabhängige Quellcode-Provenienzprüfung und gesamte kombinierte Lizenzvereinbarkeit, korrespondierender Essentia-/FFmpeg-Source- und Binär-Lizenzsatz, per-Modell-Lizenzbestätigung, aufgelöste Windows-Notices, genehmigte Distributionsartefakte und alle OS-Source-/Build-/Lizenz-BOMs.
- **Daher:** öffentliches und kostenloses Community-Projekt konsequent fortsetzen, Quellcode/Tests/Docs offen halten, die **Source-first-Nutzerinstallation** als pragmatische nächste Distributionsstufe entwickeln; **keine unüberprüfte öffentliche Weitergabe nativer Essentia-/FFmpeg-Bundles oder Modellgewichte**. Ein freies GitHub-Binary-Release mit nativen Komponenten ist weiterhin **nur bis zur paketbezogenen Compliance-Prüfung gesperrt**. Kommerzielle Vermarktung ist nicht geplant.

Die hier aufgelisteten Aktivitäten sind **Freigabevoraussetzungen**, keine Annahmen, dass derzeit bereits eine Lizenz verletzt sei. Nur kompetente rechtliche Einzelfallprüfung kann den zulässigen Umfang des kombinierten Angebots abschließend entscheiden.
