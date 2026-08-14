# LOE — multimedia processing (auto-captioning, transcripts, audio description)

**Purpose:** size the effort to make ACP *process* audio/video content for accessibility —
auto-generate transcripts and captions (and, later, audio description) — rather than only detecting
their absence. **Grounding:** the "current state" below is read from `main` (2026-08-14); the estimates
are engineering judgement, in **person-weeks (pw)** for one experienced engineer, and are ranges
because ASR/AD accuracy and GPU cost carry real uncertainty.

---

## 1. Current state — what ACP does with media today

ACP **detects the absence** of media accessibility, structurally, and routes it to a human. It does
**not** process media content (no speech-to-text, no caption generation).

- **HTML `<video>` / `<audio>` detection** — `api/scanner.py:1603-1610` inspects the markup for
  `<track kind="captions|subtitles|descriptions">`:
  - no captions/subtitles track → `HTML_VIDEO_NO_CAPTIONS` (**1.2.2**)
  - no descriptions track and no transcript → `HTML_VIDEO_NO_DESCRIPTION` (**1.2.3**)
- **Capability:** `remediation_capability.py:278-280` declares **1.2.1 / 1.2.2 / 1.2.3 = HUMAN**;
  `assessment_policy.py:42-44` marks them **human-only**, and lines 96-97 scope them to **`html` only**.
- **pptx audio autoplay (1.4.2)** — `office_structure.pptx_audio_autoplay_checks` detects and *blocks*
  auto-starting embedded audio.
- **Standalone media files** (`.mp4/.mov/.webm`, `.mp3/.m4a/.wav`) appear in the Discover inventory
  (File-types config) but have **no content-level assessment** — there is no track to inspect and no
  ASR, so the engine can only flag them for human review.
- **No ASR / transcription pipeline exists** — no Whisper, ffmpeg, or media decode anywhere in the repo.

**So the gap is:** turn "we can see there are no captions" into "we produce a draft caption /
transcript the customer's reviewer approves," and extend assessment from HTML-embedded media to
standalone media files.

---

## 2. Scope of "process multimedia"

Three WCAG obligations, three levels of difficulty:

| SC | Need | Difficulty | Approach |
|---|---|---|---|
| **1.2.1** Audio-only / video-only | a **transcript** | Moderate | ASR → text transcript |
| **1.2.2** Captions (prerecorded) | **time-synced captions** (WebVTT/SRT) | Moderate | ASR w/ timestamps → cue segmentation |
| **1.2.3** Audio description / media alternative | describe **visual** info in gaps, or a full transcript | **Hard** | scene detection + vision + gap-fit; or fall back to transcript-as-alternative |

**Recommended framing:** Phase 1 delivers 1.2.1 + 1.2.2 (transcripts + captions) as an **AI-assisted,
human-approved** lane — the same "propose, a person confirms" pattern ACP already uses for alt text.
Phase 2 tackles 1.2.3 (audio description), which is materially harder and should stay AI-assist-human,
not full-auto.

---

## 3. Technical approach & components (reuses existing platform)

The good news: the durable job queue, the HITL review-card pattern, the local-first AI stance, and the
🟢/🟡 provenance model all already exist and are reused — this is a **new lane in a proven pipeline**,
not a new platform.

1. **Media ingest + decode** — download the file, extract the audio track with **ffmpeg**, normalize
   (16 kHz mono), handle mp4/mov/webm/mp3/m4a/wav, enforce duration/size caps, chunk long media.
2. **ASR (speech→text)** — **faster-whisper** (CTranslate2) or whisper.cpp, producing a transcript with
   **segment/word timestamps** + language detection. **Runs locally / in-tenant** (PHI: audio in a
   hospital context can contain patient info — must not leave the network, consistent with ACP's
   local-first rule). **GPU strongly preferred** (Whisper on CPU is ~real-time-or-slower; on GPU it's
   many× faster) — this ties directly to the RunPod/GPU story (see Risks).
3. **Caption generation** — segment the timestamped transcript into cues with reading-speed and
   line-length rules (≈2 lines, ≤37 chars, ≤~180 wpm), emit **WebVTT** (and SRT). 
4. **Transcript generation** — clean full-text transcript for 1.2.1 and as a media alternative.
5. **Audio description (Phase 2)** — shot/scene detection → keyframe extraction → vision captioning of
   keyframes → fit descriptions into speech gaps → text AD track (optional TTS). Lower accuracy;
   human-authored with AI draft.
6. **Human review UI** — a media review card: play the clip, edit the transcript/caption text and
   timing, approve. ASR is ~90–95% accurate (proper nouns, clinical jargon, and overlap are the misses),
   so **human review is mandatory for compliance** — this is an assist, not a certifier.
7. **Storage & delivery** — sidecar `.vtt`/`.srt` + transcript, downloadable; for HTML sources, write a
   `<track>` reference; for standalone media the source is read-only, so captions are delivered as
   companion files (same "we don't write back to the source" model as remediated docs).
8. **Pipeline integration** — a media file-type lane in `scan_discover`/`scan_file`, a `scan_scope` axis
   for media (today video/audio have none), capability declarations (`remediation_capability.py` +
   `capability.js`), and **long-job handling** (media minutes → processing minutes: timeouts, chunking,
   progress, retries on the existing Postgres queue).
9. **Detection upgrades** — detect *existing* embedded caption/subtitle tracks in containers (don't
   re-caption already-captioned media), and extend detection from HTML-embedded to standalone files.

---

## 4. Effort breakdown

### Phase 1 — Transcripts + captions (1.2.1, 1.2.2), AI-assisted + human-approved

| Workstream | pw |
|---|---|
| Media ingest + ffmpeg audio extraction (formats, caps, chunking) | 1.0 |
| ASR integration (faster-whisper), GPU wiring, language detect | 2.0 |
| Caption cue segmentation (WebVTT/SRT) + transcript output | 1.5 |
| Pipeline lane: discover/scan_file, media `scan_scope` axis, capability decls | 2.0 |
| Long-job handling on the durable queue (timeouts, chunking, progress) | 1.5 |
| Storage/delivery (sidecar .vtt, download, HTML `<track>` write) | 1.0 |
| Human review UI — transcript/caption editor + approve | 2.5 |
| Detect existing embedded tracks (skip already-captioned) | 1.0 |
| Test corpus + accuracy harness (labeled media, WER/timing metrics) | 1.5 |
| **Phase 1 subtotal** | **~14 pw** → plan **10–14 pw** (T-shirt **L**) |

### Phase 2 — Audio description (1.2.3), AI-assist-human, higher uncertainty

| Workstream | pw |
|---|---|
| Shot/scene detection + keyframe extraction | 1.5 |
| Vision captioning of keyframes + gap-fitting into audio pauses | 2.5 |
| AD track generation (text; optional TTS) | 1.5 |
| Review UI for AD (timing-sensitive) | 2.0 |
| Test + calibration | 1.0 |
| **Phase 2 subtotal** | **~8.5 pw** → plan **8–16 pw** (T-shirt **XL**, wide band) |

### Cross-cutting / infra
| Item | pw |
|---|---|
| Container: ffmpeg + Whisper model weights, image size | 0.5 |
| GPU capacity + per-media-minute cost model (ties to RunPod R2/R12) | 1.0 + ongoing cost |

### Totals
- **Phase 1 only (transcripts + captions):** **~10–14 pw** + ~1.5 pw infra.
- **Phase 1 + basic Phase 2 (AI-assisted AD):** **~20–30 pw** all-in.

---

## 5. Dependencies & risks

- **GPU is effectively required.** Whisper on CPU is roughly real-time or slower; a 30-min video =
  ~30+ min CPU per file, which doesn't scale to an estate. This depends on the **RunPod/GPU lane, which
  is currently NOT working in prod** (see BACKLOG **R2/R12** — vision falls back to local; the same
  provider path would gate ASR). **This LOE assumes the GPU lane is fixed first**, or accepts slow CPU
  ASR for a pilot-sized corpus.
- **Accuracy → human review is mandatory.** ASR ~90–95% (worse on clinical jargon, names, overlap);
  captions must never be certified auto. AD is far from solved — keep it assist-human.
- **PHI / privacy.** Hospital audio can contain patient data → ASR must run **local/in-tenant** (Whisper
  local, never cloud speech APIs). This is consistent with ACP's local-first stance and is a *constraint*,
  not a blocker.
- **Long-running jobs & storage.** Media minutes → processing minutes and large I/O; the durable queue
  handles async but needs timeout/chunk/progress tuning, and media files are large to download/transcode.
- **Write-back limits.** Sources are read-only, so captions ship as companion files/downloads for
  standalone media — set expectations that ACP does not embed captions back into the customer's source.
- **Format/codec coverage.** ffmpeg covers most, but DRM/unusual codecs will fail — needs an honest
  "couldn't process" path, not a fabricated pass.

---

## 6. Assumptions & explicitly out of scope

**Assumptions:** one experienced engineer; builds on the existing job queue / HITL / capability
framework (not greenfield); GPU compute available (or CPU accepted for a small pilot); local ASR model
(faster-whisper) acceptable; captions delivered as companion files.

**Out of scope for this LOE:** live/streaming captioning; sign-language interpretation; multi-language
translation of captions; TTS voicing of audio description beyond a text track (optional Phase 2 stretch);
embedding captions back into the customer's source media.

---

## 7. Recommendation

Do **Phase 1 (transcripts + captions, 1.2.1/1.2.2)** as an AI-assisted, human-approved lane — **~10–14
pw**, gated on the GPU lane being fixed (**R2/R12**). It reuses the proven propose→approve→verify
pattern, extends assessment from HTML-only to standalone media, and closes the two most common media
failures. Treat **audio description (1.2.3)** as a separate, later, AI-assist-human effort (**+8–16 pw**)
with realistic accuracy expectations — do not promise full-auto AD.
