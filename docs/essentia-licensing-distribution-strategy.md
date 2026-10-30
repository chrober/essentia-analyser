# Lizenz- und Distributionsstrategie: Rust-Frontend, Essentia C++ und ONNX

> **Source-merge decision (28 October 2026):** The user requires integrating the qualified **source** of the original Essentia C++ backend and static multi-worker scanner into `main` via [PR #20](https://github.com/chrober/bliss-mood-poc/pull/20), **without treating the merge as a redistribution license grant**. The existing `distribution_release_status=BLOCKED`, `release_approved=false`, `license_inventory_complete=false` and 17 missing installed native notices remain unresolved and explicitly apply to binary packaging/publishing. No unaudited Windows native C++ EXE/DLL bundle should be publicly shipped by this merge. Legal obligations of publishing source (including AGPL-derived code) may still require independent review; this text is not legal clearance. Original research, inventories and release blocks below remain binding.


**Stand:** 20. Oktober 2026 · **Kontext:** Draft-PR #17 (`feat/essentia-cpp-worker-backend`) · **Status:** Arbeits- und Entscheidungspapier, **keine** rechtliche Freigabe.

Dieses Dokument fasst die Lizenz- und Distributionsüberlegungen für `bliss-mood-poc` zusammen. Es beschreibt den **bisherigen eigenständigen Rust-DSP-Pfad**, den **originalen Essentia-C++-Worker** sowie die Folgen einer Distribution auf **Windows, Linux, macOS und Raspberry Pi/piCorePlayer**. Es trennt belegte Tatsachen, plausible Arbeitshypothesen und noch nicht entschiedene Rechtsfragen.

**Scope:** Keine Änderung von PR #16 (`feat/similarity-metric-evaluation`), `main`, BlissMixerLab oder Musikdateien. Die Validierung von Audioqualität und Similarity ist von der Distributionsfreigabe zu unterscheiden.

## 21.10.2026: Ergebnis der tatsächlichen Windows-Binärinventur und Veröffentlichungssperre

**Direkt vom Anwender am vorhandenen Windows-Entwicklungskit gemessen:**

| Gate | Ergebnis | Bedeutung |
| --- | --- | --- |
| PE-x64 und SHA256/DLL-Closure | **PASS, 100 native Dateien** | Integrität der konkreten EXE/DLL-Dateien bestätigt; keine Lizenzfreigabe |
| MSYS2-Paket-Herkunft | **77 zugeordnete Pakete** | Maschinenlesbare Paketnamen/-versionen; keine Source- oder Lizenztextprüfung |
| Vorhandene und korrekt referenzierte Notice-Dateien | **94 Referenzen gültig, 0 fehlende referenzierte Dateien** | Bezieht sich auf *bereits vorhandene* Hinweise |
| **Pakete ohne installierte Notice** | **17** | Source-Paket/PKGBUILD und tatsächlich geltende Lizenztexte müssen versionsgenau überprüft werden |
| `release_approved` / `license_inventory_complete` | **false / false** | Absichtliche, weiterhin geltende Sperre |
| `distribution_release_status` | **BLOCKED** | Kein rechtliches oder organisatorisches Release-Gate bestanden |

Der private Auditbericht liegt auf dem Windows-Rechner unter
`D:\LMS\bliss-mood-poc\audit-windows-essentia-20261021-060841\release-readiness-audit-private.json`.
Die **17** betroffenen Pakete sind: `mingw-w64-x86_64-ffmpeg`,
`mingw-w64-x86_64-fftw`, `mingw-w64-x86_64-gmp`,
`mingw-w64-x86_64-gnutls`, `mingw-w64-x86_64-lame`,
`mingw-w64-x86_64-libidn2`, `mingw-w64-x86_64-libssh`,
`mingw-w64-x86_64-libtheora`, `mingw-w64-x86_64-libvorbis`,
`mingw-w64-x86_64-libvpx`, `mingw-w64-x86_64-libx264`,
`mingw-w64-x86_64-nettle`, `mingw-w64-x86_64-opencore-amr`,
`mingw-w64-x86_64-p11-kit`, `mingw-w64-x86_64-rtmpdump`,
`mingw-w64-x86_64-x265`, `mingw-w64-x86_64-xvidcore`.

**Keine der 17 Lizenzbedingungen wird hier aus dem Paketnamen geraten.**
`pacman -Qi`-Lizenzmetadaten sind Suchhinweise, nicht der Text der
korrespondierenden Source-Lizenz. Die technische Analyse
`scripts/triage_windows_native_license_gaps.py` erzeugt deshalb
aus dem **zuvor integritätsgeprüften** Dev-Kit einen deterministischen
Prüfauftrag mit den exakten Paketversionen, *ungeprüften* Upstream-URLs,
betroffenen DLL-Namen und den *im Manifest aufgezeichneten* Importpfaden.
Sie verändert keine Binaries, lädt keine Quellen herunter und setzt
sämtliche rechtlichen Freigabefelder weiterhin auf **false/BLOCKED**.
Die tatsächliche FFmpeg-`configure`-Zeile und verwendete
`--enable-gpl`/`--enable-nonfree`/`--enable-version3`-Schalter
sind **noch nicht belegt**. Der bloße Fund von libx264/x265 in der
Closure ersetzt diese Prüfung nicht.

**Abgleich mit den Szenarien A–D aus Abschnitt 4:**

- **A (Komplettpaket)**: Auf der öffentlichen Repository-CI vorerst
  **keine weiteren nativen Windows-Binärarchive** veröffentlichen.
  Der Build und alle technischen Tests bleiben eingeschaltet; die
  CI-Artifakt-Upload-Stage ist für öffentliche Repositories ausgesetzt.
  Bereits veröffentlichte ältere Testartefakte werden dadurch **nicht**
  automatisch entfernt. Deren Sichtbarkeit, Fortbestand und Pflichten
  müssen ausdrücklich geprüft werden.
- **B (eigene CLI + mitgeliefertes C++-Worker-EXE)** reduziert möglicherweise
  die von uns mitgelieferten nativen Bibliotheken, ist jedoch **keine
  Lösung** der direkt mit Essentia verknüpften AGPL-/Worker-Fragen.
- **C (CLI + Worker-Quellcode/Build-Skripte; Nutzer baut Worker)**
  ist die bevorzugte weitere **technische** Distributionsuntersuchung,
  einschließlich exaktem Upstream-Pin, Lizenzhinweisen und reproduzierbarer
  Systempaketinstallation. Keine automatische AGPL-Ausnahme.
- **D (nur eigenständiger Rust-DSP-Pfad)** ermöglicht sofort weitere
  private Funktions-/Similarity-Tests ohne ein mitgeliefertes natives
  Essentia-Paket, **nach** Klärung seiner eigenen Code-/Crate-/ONNX-
  Modellrechte für eine spätere allgemeine Weitergabe.

**Reduktionsweg:** Nicht einfach Video-/Encoder-DLLs aus einem
funktionierenden 100-Dateien-Paket löschen. Die im Manifest
verzeichneten Imports dokumentieren eine technische Abhängigkeitskette,
aber nicht alle dynamisch geladenen Codecs. Für einen kleineren
FFmpeg-/Essentia-Build zuerst die wirklich benötigten MP3-/FLAC-/WAV-
Decoder, tatsächlichen Buildflags und Laufzeitimports erfassen;
erst **nach** eigenem neuen Build/Closure-Verifikation und ausgewählten
Codec-Smokes ist eine Reduktion belastbar. Lizenz- und Modellprüfungen
bleiben parallel offen.

Offizielle weiterführende Ausgangspunkte:
[FFmpeg Legal](https://ffmpeg.org/legal.html),
[FFmpeg General / externe Bibliotheken](https://ffmpeg.org/general.html)
und die in Abschnitt 9 verlinkten Essentia-Primärquellen.
Dies ist eine technische Prüfreihenfolge, **keine Rechtsberatung und
keine Freigabe**.

## 1. Kernaussagen

1. **Selbst heruntergeladene Abhängigkeiten** verringern grundsätzlich unsere eigenen Pflichten als Distributor *dieser nicht mitgelieferten Komponenten*. Sie beseitigen weder deren Nutzungsbedingungen noch automatisch Copyleft-Fragen bei eng gekoppelten Programmen. Ein von uns kontrollierter Download-Mirror oder ein weitergegebenes ZIP mit DLLs ist dagegen eine eigene Weitergabe.
2. **Die MIT-Kennzeichnung des Repositories** gilt für eigenen Code, vorbehaltlich Code-Herkunft und Lizenzkompatibilität. Sie lizenziert weder das originale Essentia noch FFmpeg, native Drittbibliotheken oder ONNX-Modellgewichte pauschal unter MIT um.
3. **Essentia C++** ist in der hier verwendeten Originalfassung AGPL-3.0-or-later (mit im upstream Lizenzdokument bezeichneten Drittkomponenten/Ausnahmen). Für den direkt dagegen gelinkten C++-Worker sind AGPL-/Quellcodepflichten und das konkret kombinierte Werk zu prüfen.
4. **Ein separater IPC-Prozess ist hilfreich, aber kein Freibrief.** Ob Rust-CLI und C++-Worker zwei eigenständige Werke oder eine eng zusammengefasste Kombination sind, hängt auch von den ausgetauschten Daten und dem Zusammenspiel ab. Das EFW1/REQ1/RES1-Protokoll über Pipes mit Mel-Patch-Arrays muss daher gesondert bewertet werden.
5. **FFmpeg** ist je nach *tatsächlicher Build-Konfiguration* LGPL- oder GPL-betroffen. Die Existenz einer x264-DLL im Dependency-Closure zeigt eine zu prüfende Abhängigkeit, beweist für sich allein aber noch nicht sämtliche relevanten Link-/Lizenzverhältnisse. Für unsere Audio-Decoding-Aufgabe sollen unnötige Video-/Encoder-Bibliotheken möglichst entfallen.
6. **Die ONNX-Gewichte** werden derzeit bewusst separat vom MTG-Anbieter bezogen. Nutzung und eventuelle kommerzielle Weiterverwendung sind dennoch an die *konkrete* Modelllizenz gebunden; MTG-Webseiten geben hierzu widersprüchliche allgemeine CC-Angaben an.
7. **Linux und macOS** benötigen ebenso native Shared Libraries (`.so` bzw. `.dylib`). Paketmanager erleichtern den Nutzer-seitigen Bezug, lösen aber weder AGPL/Modellfragen noch die Prüfung von ABI, Versionsbindung, Funktion und Reproduzierbarkeit.
8. **Ein öffentlich abrufbares GitHub-Actions-Testartefakt ist rechtlich nicht allein wegen der Bezeichnung „Development“ intern.** Der Umfang der dort tatsächlich eingeräumten/erfüllten Weitergaberechte ist zu prüfen.

## 2. Bestehender Rust-Port versus originaler C++-Worker

| Thema | Bisheriges Rust-DSP-Backend | Neues Essentia-C++-Backend |
| --- | --- | --- |
| Audio-DSP | Eigene Rust-Implementierung in `src/preprocess.rs` mit `rustfft` | Original-Essentia-Algorithmen im nativen Worker; `essentia.dll` / `libessentia.so` / entsprechende macOS-Bibliothek |
| Decoding | Startet externe `ffmpeg`- und `ffprobe`-Kommandos aus `src/audio_decode.rs` | Original-Essentia-`MonoLoader` verwendet darunter native libav/FFmpeg-Komponenten |
| Essentia-Bibliothek gelinkt? | Nein | Ja, im C++-Worker |
| Eigenständige Code-Herkunft | **Noch zu prüfen:** unabhängig implementiert oder konkrete AGPL-Quelltextteile übertragen? | Upstream-Origin und AGPL-3.0-or-later bekannt |
| Rust-/CLI-Lizenz | Repository-`LICENSE` und `Cargo.toml` nennen MIT | Weiterhin MIT für eigenständige Teile; keine automatische Lizenzfreigabe für verbundene Komponenten |
| ONNX-Inferenz | `ort` / ONNX Runtime, gleiche Modellfamilien | Unverändert im Rust-Orchestrator |
| Modellgewichte | Separat heruntergeladen | Separat heruntergeladen |
| Eigene Fremdbinärdistribution | Standard-Windows-CLI enthielt keine FFmpeg-Binaries; Systeminstallation erforderlich | Windows-Testkit bündelt umfangreiche originale C++-/FFmpeg-/MinGW-Laufzeitkette |

**Zur Herkunft des Rust-Ports:** Die unabhängige Implementierung mathematischer Algorithmen ist nicht allein aufgrund numerischer Parität eine Ableitung des Essentia-Quellcodes. Bei tatsächlicher Übernahme oder enger Übersetzung geschützter Quelltextteile können aber Urheber- und Lizenzpflichten entstehen. Die Entwicklungshistorie und `src/audio_decode.rs` / `src/preprocess.rs` sollten gezielt auf Code-Provenienz geprüft werden; weder „eindeutig unabhängig“ noch „AGPL-pflichtig“ ist bisher bewiesen.

**Abhängigkeitsinventur des Rust-Teils:** `Cargo.toml` deklariert u. a. `rustfft`, `ort`, `rusqlite`, `clap` und `serde`. `license = "MIT"` des eigenen Crates ersetzt keine `cargo metadata`-/`cargo-deny`- oder vergleichbare Transitivlizenzprüfung. Auch optionale dynamische ONNX-Runtime-Binärdateien sind gesondert zu inventarisieren.

## 3. Relevante Lizenzfamilien und Prüfaufgaben

### 3.1 Original-Essentia (AGPLv3)

- Verbindliche Grundlage ist die jeweilige **Original-Lizenzdatei des gepinnten Essentia-Commits**, einschließlich Lizenzhinweisen für eingebettete Drittkomponenten. Die aktuell verwendete Windows-Quelle ist MTG/essentia `b0661db99be4a8e2c6fabbe90a996f89786fdd8e`; die Linux-CI benutzte einen anderen geprüften Commit.
- Für eine Binärweitergabe müssen Lizenztexte, Hinweis auf Modifikationen, zulässige Lizenzierung und der **korrespondierende Quellcode einschließlich nötiger Build-/Installationsskripte** entsprechend der tatsächlich anwendbaren Bedingungen verfügbar sein. Eine bloße GitHub-Repository-URL ohne passende Source-/Build-Provenienz ist nicht automatisch ausreichend.
- Die AGPL enthält zudem besondere Anforderungen für die **Remote-Netzinteraktion mit einer modifizierten Version**, soweit die konkrete Anwendungs-/Interaktionssituation darunter fällt. Nicht jede bloß lokale Ausführung löst diese Netzwerkklausel aus.
- Der Worker ist direkt gegen Essentia gelinkt. Ob die MIT-lizenzierte Rust-CLI aufgrund ihrer engen IPC-Zusammenarbeit als eigenständiges Programm bleibt, bedarf einer **einzelfallbezogenen Lizenz-/Urheberrechtsbewertung**. „Zwei Executables“ ist keine abschließende Trennung.
- Die Frage ist *Lizenzkonformität*, nicht ein generelles Verbot kommerzieller Open-Source-Nutzung. Eine alternative kommerzielle Lizenz für Essentia kann ggf. bei MTG angefragt werden, ersetzt aber nicht die gesonderten Rechte an externen Abhängigkeiten.

### 3.2 FFmpeg, FFTW, libsamplerate und weitere native Bibliotheken

- FFmpeg beschreibt LGPL-2.1-or-later als Basis; aktivierte GPL-Komponenten können eine GPL-pflichtige Kombination ergeben. Die **tatsächliche** Konfiguration (`--enable-gpl`, `--enable-nonfree`, `--enable-version3`, aktivierte externe Bibliotheken), Binärlinks, Paketzusammenstellung und Source-Rechte sind nachzuweisen.
- Die momentane Windows-Closure enthält unter anderem x264-/x265- und andere Videokomponenten. Für unsere Anwendungsfälle WAV, FLAC, MP3 und sonstige benötigte Audio-Codecs prüfen, ob eine **auf Audio-Decoding reduzierte FFmpeg-/Essentia-Buildvariante** denselben Analyseumfang mit weniger Abhängigkeiten erfüllt.
- FFTW, libsamplerate und alle übrigen Bibliotheken **anhand der exakten installierten Paketversion und Lizenzdateien** prüfen. Die allgemeine Essentia-Lizenzdatei enthält teilweise historische Lizenzbeschreibungen und ersetzt keine versionsgenaue Prüfung.
- Die LGPL kann trotz dynamischen Linkings spezielle Anforderungen etwa zur Modifizierbarkeit/Ersetzbarkeit der Bibliothek, zu Lizenzhinweisen und Source-Availability auslösen; „dynamisch gelinkt“ ist nicht gleich „keine Pflicht“.
- Für GPL/AGPL/LGPL-kombinierte Werke sind **Lizenzversionen, Ausnahmen und Kompatibilität** zu bewerten, einschließlich Quellcode-/Buildinformationen, nicht lediglich eine SPDX-Zeichenfolge.

### 3.3 ONNX Runtime, Rust-Crates und MTG-Modelle

- ONNX Runtime selbst und die verwendeten Rust-Crates werden unabhängig von den **Modellgewichten** lizenziert; genaue Versions-/Binärinventur erforderlich.
- Modell-Downloader und Gewichte bleiben technisch getrennt. Der separate Bezug durch Anwender beseitigt aber **keine Nutzungsbeschränkung** der konkreten ONNX-Modelle.
- **Ungeklärte Angabe bei MTG:** Die offizielle Modellübersicht bezeichnet MTG-Modelle allgemein als **CC BY-NC-SA 4.0**, die allgemeine Essentia-Lizenzseite nennt **CC BY-NC-ND 4.0**. **Keine dieser Angaben ohne Dateiprüfung pauschal** für alle vier ONNX-Dateien festschreiben.
- Für Discogs-EffNet, Genre, Mood/Theme und Voice/Instrumental jeweils dokumentieren: exakte Datei-URL, SHA256, Herkunft/Autor, spezifische `LICENSE` bzw. Metadaten, Versionsstand, erlaubte Nutzung, kommerzielle Einschränkungen, Attribution und Bedingungen zur Weitergabe abgeleiteter Modelle/Materialien.
- Die rechtliche Einordnung **erzeugter Feature-Vektoren** nicht ungeprüft mit den Bedingungen zur Weitergabe der Gewichte gleichsetzen; bei relevanten Produktionsfällen gesondert untersuchen.

## 4. Wer lädt oder verteilt welche Komponenten?

| Szenario | Typische eigene Weitergabe | Was bleibt offen? |
| --- | --- | --- |
| **A. Komplett-Binary-Paket**: Rust-CLI + Worker + Essentia + FFmpeg + DLLs/Shared Libraries | Wir verteilen die jeweiligen fremden Binaries selbst | Vollständige Lizenztexte, Notice-/Attributions-, Quellcode-/Angebots-, Build- und Kompatibilitätsprüfung der gesamten Closure |
| **B. Kleine CLI + bereits kompilierten Worker; Anwender installiert native Libraries selbst** | Wir verteilen Rust-CLI und Worker-Executable, **nicht** die nativen Laufzeitbibliotheken | Worker-/Essentia-Copyleft-Beziehung, IPC-Bewertung, tatsächliche Link-Konstellation; dokumentierte versionierte System-Prerequisites und technische Laufzeitprüfung |
| **C. Rust-CLI + offen gelegten Worker-Quellcode und Build-/Installationsskripte**; Anwender baut Worker und installiert Bibliotheken selbst | Wir verteilen selbst weniger Dritt-Binaries | Rechte/Provenienz des Worker-Quellcodes, zulässige Kombination, Nutzungs- und Netzwerkbedingungen; komplexerer Support/Build |
| **D. Nur Rust-Frontend; FFmpeg als separates CLI-Prerequisite** | Unsere eigene Rust-CLI, kein Original-Essentia-Binary | Rust-DSP-Codeherkunft, transitive Rust-/ONNX-Lizenzen und dieselben Modellnutzungsrechte |

**Präzisierung:** Das Bereitstellen eines Skripts, das Anwender direkt von offiziellen Paketquellen herunterladen lässt, ist nicht automatisch identisch mit unserer eigenen Weitergabe der Downloads. Trotzdem können **kuratierte, unverzichtbar aufeinander abgestimmte Komponenten** oder enge Programmkopplungen eigenständige Compliance-Fragen auslösen. Eigene Mirrors, Repackaging und als Bestandteil ausgelieferte Archivkopien bleiben klar unser Distributionsvorgang. Ein Installer hat keine pauschale Ausnahme von Urheber- oder Lizenzrecht.

**Gewünschtes Prinzip:** Ein ehrlicher, versionierter Installer nennt vorab Drittanbieter, Lizenzen und Bezugsquellen; lädt ohne Umverteilung fremder Dateien direkt von Originalquellen; prüft Checksums/Architektur; erzeugt ein lokales Runtime-Manifest; meldet unklare Fälle statt stillschweigender „Freigabe“.

## 5. Betriebssystemvergleich

| Thema | Windows x64 | Linux (einschließlich NAS/Docker) | macOS (Intel und Apple Silicon) | Raspberry Pi 4B / piCorePlayer 11 (64-bit) |
| --- | --- | --- | --- | --- |
| Laufzeitbibliotheken | PE: `.dll` | ELF: `.so` | Mach-O: `.dylib` | ELF: `.so`, aber Pi-spezifischer Userland-/libc-Kontext |
| Bezugsweg | MSYS2/MinGW, lokaler Essentia-Build | Distro-Paketmanager und ggf. eigener Essentia-Build | Homebrew und ggf. eigener Essentia-Build | piCore/Tiny Core Extensions (`.tcz`), eigene Builds |
| Loader-/ABI-Prüfung | PE-Imports, DLL-Suchpfad, x64-MinGW/MSVC-Schnittstelle | `readelf -d`, `ldd` nur für vertrauenswürdige Binaries, SONAME, RPATH/RUNPATH, glibc-/musl-Kompatibilität | `otool -L`, `@rpath`/`@loader_path`, Architektur, Codesign/Gatekeeper | Passender Loader/libc, Extensions und ARM64-ONNX-Build |
| Unsere native Build-Evidenz | Original-Essentia-Windows-CI, inklusive vollständigem CLI-Handoff erfolgreich | Original-Essentia-Linux-x86_64-CI mit numerischer Parität erfolgreich | Noch nicht nativ qualifiziert | Noch nicht nativ qualifiziert |
| Distributionspräferenz | Eigene CLI + lokal installierte native Abhängigkeiten/manifestierter Worker; vorerst vorhandenes dev-ZIP nicht als Release behandeln | **Systempakete** + eigene CLI/Worker, Versionen und ABI ausdrücklich prüfen | **Homebrew** + eigene CLI/Worker, ggf. signieren/notarisieren für allgemeine Downloads | Native Extensions, persistente Installationspfade, Ein-Worker-/Speichergate |

### Linux

Linux hat keine Windows-DLLs, dafür aber eine **vergleichbare dynamische Abhängigkeitsschicht**. Der Systempaketmanager verteilt gewöhnlich die `.so`-Bibliotheken und Lizenzinformationen. Eine eigene portable AppImage-, Container- oder Tarball-Distribution, die fremde Libraries mitliefert, holt deren Weitergabepflichten wieder in **unsere** Distributionsverantwortung. Paketversionsbindung, System-ABI, ONNX-Unterstützung und Resultat-Fingerprints müssen pro Ziel geprüft werden.

**Wichtig:** Nicht jede Distribution enthält eine kompatible Essentia-Version als Standardpaket; ein gezielter Upstream-Build kann notwendig sein. Ein grüner Ubuntu-x86_64-CI-Lauf bestätigt nicht jede NAS-/Linux-Variante.

### macOS

Homebrew bietet einen praktikablen **separaten Nutzer-Bezugsweg** für native Libraries. Für selbst bereitgestellte `bliss-mood`- und Worker-Binaries sind die Install-Names (`@rpath` usw.), Intel/ARM-Architektur, Abhängigkeitsversionen und ggf. Apple-Signierung/Notarisierung zu prüfen. Homebrew-Installation löst keine Essentia-AGPL- oder Modelllizenzfragen. macOS-Originalworker/Feature-Parität ist bisher **nicht validiert**.

### Raspberry Pi / piCorePlayer

piCorePlayer hat ein eigenes Extensions-/Persistenzmodell; ein beliebiges Debian-ARM64-Binary und `apt install` können nicht vorausgesetzt werden. Für eine `.tcz`-Extension, die wir selbst mit Drittlibraries ausliefern, gelten wieder die entsprechenden **eigenen Weitergabepflichten**. Zuerst native Pi4-ABI und ONNX, RAM bei einem Worker und Persistenz nach Reboot belegen. Das ist ein separates späteres Qualifikationsziel und **blockiert keine Windows-Similarity-Tests**.

## 6. Verifizierter Status unseres Windows-Artefakts

**CI-Evidenz:** [Native Windows run #39421541546](https://github.com/chrober/bliss-mood-poc/actions/runs/39421541546) für `bdb281d3a952775d62f4b29786e687a05471f9b1`. Der reale Windows-x64-Rust-Scanner, original-Essentia-C++-Worker und die native Closure wurden mit isoliertem PATH und unverändertem PR-#16-Feature-Evaluator erfolgreich getestet. Die **Funktionalität** ist belegt; dies ist keine **Lizenzfreigabe**.

Maschineninventur (aus dem CI-Log):
- **100** native EXE-/DLL-Dateien inklusive Worker und originaler Essentia-DLL.
- **77** aufgezeichnete MSYS2-Paketbesitzer.
- **17** Pakete ohne gefundenen **installierten** Lizenznotice-Dateieintrag: FFmpeg, FFTW, GMP, GnuTLS, Nettle, libidn2, LAME, OpenCORE-AMR, p11-kit, rtmpdump, libssh, libtheora, libvorbis, libvpx, libx264, x265 und Xvid (MSYS2-Paketnamen siehe `NATIVE-PROVENANCE.json`).
- Der Paketmanifest-Status bleibt korrekt **`license_inventory_complete=false`** und **`release_approved=false`**.

„Keine installierte Notice-Datei gefunden“ bedeutet **nicht** „keine Lizenz“ oder „zweifelsfrei unzulässig“. Es heißt, dass die automatische Lizenzsammlung als vollständiger Compliance-Nachweis **nicht ausreicht**. Zu den noch offenen Pflichten können korrespondierender Quellcode, exakte Buildkonfigurationen, Copyright-/Lizenzhinweise, relevante Änderungen und ggf. Source-Angebote gehören.

**Dringende Distributionseinordnung:** Das Test-ZIP `bliss-mood-essentia-windows-x64-dev` wurde als Artefakt eines **öffentlichen** GitHub-Repositories hochgeladen. Der Zusatz „dev“ oder „not release approved“ macht es nicht zu einer rein internen Weitergabe. Vor weiterer allgemeiner Bewerbung oder erneuter Veröffentlichung ist zu prüfen, ob alle tatsächlichen Weitergabebedingungen eingehalten werden; bei ernsthaften ungeklärten Pflichten den öffentlichen Download ggf. vorläufig beschränken bzw. entfernen und eine saubere Build-aus-Quellen-Alternative verwenden.

Die Modelldateien und private Audiodaten sind nicht im ZIP. Dieses Trennen reduziert die eigene Modellgewichtsdistribution, klärt aber deren Nutzung nicht.

## 7. Vorgeschlagene Zielarchitektur und Entscheidungen

```
Nutzerinstallation (versionsgeprüft)
  ├── bliss-mood CLI / Rust-Orchestrator
  ├── original Essentia C++ Worker (separat gebaut/installiert)
  │   ├── original libessentia
  │   └── minimale erforderliche Audio-/DSP-Systembibliotheken
  └── offiziell separat bezogene ONNX-Gewichte und Metadaten
       ↓
  Schema-v3-Features + Backend-/Dependency-/Modell-Fingerprints
```

**Bevorzugter technischer Weg für spätere allgemeine Distribution:** **Schlanke Rust-CLI, separat bereitgestellter/gebauter Original-Essentia-Worker, minimale native Systempakete und unabhängig heruntergeladene, versionsfixierte Modelle.** Dies ist ein **technisches Zielbild**, keine behauptete Copyleft-Ausnahme.

Die Runtime-Abhängigkeiten müssen pro OS/Architektur prüfbar und im Cache-Provenance-Key unterscheidbar bleiben, damit Upgrades keine vermeintlich identischen Feature-Vektoren erzeugen. Unter Windows ist das aktuell über das `worker-dependencies.json` mit SHA256-Hashes realisiert; für Linux/macOS ist eine **gleichwertige, noch zu implementierende** versionssichere Herkunftsprüfung erforderlich.

**Für die sofortigen Similarity-Untersuchungen** sind keine weiteren Plattformpakete nötig. Diese können auf lokal korrekt installierten Windows-Analysewerkzeugen fortgesetzt werden. Lizenz-Compliance und künftig öffentliche Veröffentlichungen sind ein eigener Workstream.

### Stand 21.10.2026: Numerische Parität ≠ Distributionsfreigabe

Die technische Windows-Parität ist jetzt auch mit **zwei unabhängig
heruntergeladenen, unveränderten Lossless-Dateien** belegt
(FLAC 48 kHz/24 Bit und WAV 44,1 kHz/16 Bit; Maximalfehler gegen
Original-Essentia C++ **2,02e-6** bzw. **1,40e-6** bei unveränderter
Toleranz **0,001**). Dazu kommen 100 reale MP3-Songs (14.500
Klassifikationswerte), ein bitidentischer Vergleich zwischen
vier und sechs Rust-v5-Workern und ein kontrollierter PCM24-WAV/FLAC-Test.
Details: [Release-Qualification](release-qualification-gates.md).
Es besteht **kein technischer Grund, diese Audiodateien erneut
zu analysieren**, nur um eine Distributionslizenzfrage zu beantworten.

Neu ist ein **nur lesender Auditor** für das vorhandene
Windows-Entwicklerkit:
`scripts/audit_windows_native_release.py --kit-root D:\LMS\essentia-cli-test`.
Er prüft anhand des vorhandenen `worker-dependencies.json` die
Integrität der nativen PE-x64-EXE-/DLL-Closure (Dateigrößen/SHA256)
und gleicht die echte Dateiliste mit `NATIVE-PROVENANCE.json`,
MSYS2-Paketversionen und tatsächlich vorhandenen Hinweisdateien ab.
Fehlende Notices werden namentlich aufgelistet; manipulierte bzw.
inkonsistente Dateien lassen den Audit fehlschlagen. **Das Skript
verändert weder das Kit noch installiert es Komponenten.** Vor allem
meldet es selbst bei intakten Dateien weiterhin
`distribution_release_status=BLOCKED`; ein erfüllter Hashcheck
ist keine juristische Prüfung. Siehe auch die ausführbare
PowerShell-Anleitung in [Release-Qualification](release-qualification-gates.md).

Der nächste echte Release-Schritt ist eine **manuell geprüfte,
versionsgenaue** Zuordnung von Source/Build-Skripten,
Weitergabebedingungen, Lizenztexten und Modellen zu allen
auszuliefernden Komponenten. Die Lizenzfragen zum eng gekoppelten
EFW1-IPC-Werk und zur Nutzung einzelner MTG-ONNX-Modelle bleiben
ausdrücklich ungeklärt. Insbesondere darf weder
`license_inventory_complete` noch `release_approved`
auf `true` gesetzt werden, nur weil numerische Tests oder die
technische Paketprüfung bestehen.

## 8. Konkrete Prüf-/Freigabe-Checkliste

- [ ] **Code-Herkunft:** Rust-DSP (`preprocess.rs`, `audio_decode.rs`) und eigener Worker: unabhängige Implementierung vs. kopierte/übersetzte fremde Quellcodeanteile klären.
- [ ] **Rust-SBOM:** vollständige `Cargo.lock`-basierte inklusive Build-/Runtime-Abhängigkeiten; Lizenztexte/NOTICE und ONNX-Runtime-Lizenzinventur; keine bloße Ableitung aus `Cargo.toml license=MIT`.
- [ ] **Essentia-AGPL:** exakten Upstream-Commit, Lizenztexte/Third-Party-Hinweise, lokale Änderungen, korrespondierenden Source/Build-/Installationsnachweis erfassen.
- [ ] **IPC-Kombination:** Bewertung, ob Rust-/C++-Komponenten im konkreten EFW1-Protokoll getrennte Werke bilden; Konsequenzen für MIT-Metadaten und Veröffentlichung festhalten.
- [ ] **FFmpeg:** tatsächliches `ffmpeg -buildconf` bzw. Paket-Buildflags, GPL-/Nonfree-Schalter, dynamische Imports und Lizenz-Kompatibilität nachweisen; unnötige Video-/Encoder-Komponenten eliminieren, wenn Audio-Parität erhalten bleibt.
- [ ] **Native Lizenzinventur:** 17 fehlende installierte Notices anhand verifizierter Paketquellen nachziehen; exakte Versionen, SPDX, COPYRIGHT, Source-/Build-URL, Hash und Weitergabebedingungen pro Binärdatei.
- [ ] **Modellrechte:** für jede der vier ONNX-Gewichtsdateien konkrete Lizenz und ggf. kommerzielle Nutzung direkt bei MTG bzw. in der maßgeblichen Modelldatei klären; Widerspruch der zwei Essentia-Dokumentationsseiten nicht ignorieren.
- [ ] **Installer-Fallback:** für getrennte Nutzerinstallation verifizierbare Originaldownloads, eindeutige Zustimmung/Hinweise, Integritätsprüfung, Rückrollbarkeit und `worker-dependencies`-äquivalentes Manifest vorsehen.
- [ ] **Plattformgates:** Linux ELF/ABI/Versionsprüfung, macOS dylib/Signierung, Pi4 piCorePlayer-Userland/`.tcz`/Persistenz plus native Numerical-Parity, bevor eine Plattform als „unterstützt“ gilt.
- [ ] **Veröffentlichungsgate:** Lizenz- und Quellcodebereitstellung inkl. exakter Build-Provenienz *vor* Binärdistribution gegenzeichnen; öffentlichen Status des bestehenden Testartefakts prüfen.
- [ ] **Produktnutzung:** Unterschied zwischen privater Analyse, Weitergabe von Binärdateien, kommerzieller Nutzung der MTG-Modelle und ggf. AGPL-Netzinteraktion dokumentieren.

## 9. Primärquellen, Repo-Nachweise und offene Auslegungen

**Lizenzquellen (Rechtsbedingungen ergeben sich aus den jeweiligen konkreten Lizenzdateien, nicht aus dieser Zusammenfassung):**

- Essentia-Originalquelltext und Lizenzbedingungen: https://github.com/MTG/essentia/blob/b0661db99be4a8e2c6fabbe90a996f89786fdd8e/Essentia%20Licensing.txt
- Essentia AGPL-Volltext: https://github.com/MTG/essentia/blob/b0661db99be4a8e2c6fabbe90a996f89786fdd8e/COPYING.txt
- Essentia-Lizenzierung und Drittbibliotheken: https://essentia.upf.edu/licensing_information.html
- Essentia-Modellübersicht (CC BY-NC-SA-Aussage): https://essentia.upf.edu/models.html
- GNU GPL FAQ zur Frage „separate programs or combined work“: https://www.gnu.org/licenses/gpl-faq.en.html
- AGPLv3, insbesondere Abschnitt 13 (Netzinteraktion): https://www.gnu.org/licenses/agpl-3.0.de.html
- FFmpeg-Lizenz/Compliance-Checkliste: https://www.ffmpeg.org/legal.html
- FFmpeg-Builds mit Drittbibliotheken (x264/x265 etc.): https://www.ffmpeg.org/general.html
- piCorePlayer-Backup/Persistenz: https://docs.picoreplayer.org/information/pcp_backup/

**Projektbelege:**

- Eigene MIT-Kennzeichnung: [`../LICENSE`](../LICENSE), [`../Cargo.toml`](../Cargo.toml)
- Rust-Decoder und -DSP: [`../src/audio_decode.rs`](../src/audio_decode.rs), [`../src/preprocess.rs`](../src/preprocess.rs)
- Native Architektur und Prozessgrenze: [`essentia-cpp-worker-architecture.md`](essentia-cpp-worker-architecture.md)
- Windows-Bundle und verbleibende Lizenzinventur: [`windows-essentia-local-test-kit.md`](windows-essentia-local-test-kit.md), [`../scripts/inventory_essentia_windows_licenses.py`](../scripts/inventory_essentia_windows_licenses.py)
- Zielplattformen und aktuell belegte Tests: [`platform-support-lyrion.md`](platform-support-lyrion.md)

**Entscheidungsstatus:** Weder das jetzige komplette Windows-ZIP noch die vorgeschlagene schlanke Distribution ist allein durch dieses Dokument „rechtlich freigegeben“. Offene Rechtsfragen gezielt mit fachkundiger OSS-Lizenzprüfung klären, bevor allgemeine Releases oder kommerzielle Produkte darauf aufbauen.
