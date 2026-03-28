# Zumo — Handoff for Next Agent

> Written: 2026-03-28
> Author: Claude Opus (session with Ben Akiva)
> Project: `c:\Users\darta\Desktop\פרויקטים\zumo`

---

## What Changed This Session

### Speaker Diarization — DONE (Priority 1)

Added pyannote-audio speaker diarization to the pipeline. New step between silence removal and transcription.

#### New File: `src/diarizer.py` (~200 lines)

| Function | Purpose |
|----------|---------|
| `is_available()` | Checks if pyannote.audio is installed (optional heavy dependency) |
| `diarize(audio_path, num_speakers, on_progress)` | Runs pyannote speaker-diarization-3.1. Converts to WAV first for compatibility. Returns `[{"start", "end", "speaker"}, ...]` |
| `merge_segments(segments, gap_threshold)` | Merges consecutive same-speaker segments within gap threshold |
| `align_transcript(transcript, segments, audio_duration, speaker_names)` | Proportional sentence-level alignment (see below) |
| `_split_sentences(text)` | Splits transcript at sentence boundaries (`.?!\n`) |
| `_majority_speaker(start_time, end_time, segments)` | Finds dominant speaker in a time window |
| `_build_speaker_map(segments, speaker_names)` | Maps SPEAKER_00/01/02 to real names by first-appearance order |

#### Alignment Strategy

Hebrew AI returns plain text without timestamps. The alignment works by:
1. Splitting the transcript into sentences
2. Mapping each sentence to a proportional time window (chars/total_chars * duration)
3. Finding the majority speaker in that time window from diarization segments
4. Grouping consecutive same-speaker sentences into labeled paragraphs

**Output format:** `**Ben:** sentence text here.\n\n**Omri:** response text here.`

**Accuracy:** Sentence-level approximation. Good enough for structured analysis by Claude. Not word-perfect at speaker boundaries.

#### Pipeline Flow (Updated)

```
[1/8] Extract audio
[2/8] Silence removal
[3/8] Speaker diarization (pyannote on trimmed audio — higher quality)
[3.5/8] Compress if >25MB (for Hebrew AI upload)
[4/8] Transcription (Hebrew AI)
[5/8] Align speakers with transcript (proportional sentence mapping)
[6/8] Summary (Claude Haiku)
[7/8] Analysis (Claude Sonnet)
[8/8] Save
```

Key: diarization runs on `trimmed_path` (pre-compression) for best quality. Compression only affects the Hebrew AI upload.

#### Modified Files

| File | Change |
|------|--------|
| `pipeline.py` | New step 3 (diarization) + step 5 (alignment). Steps renumbered 1-8. New `--skip-diarization` flag. `process_file()` gets `skip_diarization` param. |
| `src/config.py` | Added `HUGGINGFACE_TOKEN` env var |
| `.env.example` | Added `HUGGINGFACE_TOKEN` with setup links |
| `requirements.txt` | Added `pyannote.audio>=3.1` (optional, pulls torch ~2GB) |

#### CLI Usage (Updated)

```bash
# With diarization (default when pyannote is installed)
python pipeline.py recording.mp4 --user ben-akiva --session-type training --speakers "Ben, Omri, Adi" --local

# Skip diarization explicitly
python pipeline.py recording.mp4 --user ben-akiva --session-type training --skip-diarization --local
```

`--speakers` now serves double duty:
- Tells pyannote how many speakers to expect (`num_speakers`)
- Maps SPEAKER_00/01/02 to real names in order of first appearance

#### Graceful Fallback

Diarization is fully optional:
- If `pyannote.audio` not installed → skipped with install hint
- If `--skip-diarization` flag → skipped
- If diarization throws any error → caught, pipeline continues with raw transcript
- If `HUGGINGFACE_TOKEN` missing → RuntimeError (caught by the fallback)

#### Setup for Diarization

1. Install torch CPU-only first: `pip install torch==2.6.0+cpu torchaudio==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu`
2. Install pyannote + compatible hub: `pip install "pyannote.audio>=3.1,<4.0" "huggingface_hub<0.24"`
3. Get HuggingFace token: https://huggingface.co/settings/tokens (Read access is enough)
4. Accept ALL THREE model terms (required for gated access):
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
   - https://huggingface.co/pyannote/speaker-diarization-community-1
5. Add to `.env`: `HUGGINGFACE_TOKEN=hf_xxx`

#### Version Compatibility (CRITICAL — Windows + Python 3.13)

| Package | Version | Why |
|---------|---------|-----|
| `torch` | 2.6.0+cpu | Earliest version supporting Python 3.13. Must be CPU-only build. |
| `torchaudio` | 2.6.0+cpu | Must match torch version exactly. |
| `pyannote.audio` | 3.4.0 (>=3.1,<4.0) | v4.x uses torchcodec which is broken on Windows. |
| `huggingface_hub` | 0.23.x (<0.24) | v0.24+ removed `use_auth_token` param that pyannote 3.x uses internally. |

**DO NOT upgrade these packages independently.** The version matrix is fragile. pyannote v4 + torchcodec doesn't work on Windows. Newer huggingface_hub breaks pyannote 3.x auth.

The diarizer also patches `torch.load` to set `weights_only=False` because PyTorch 2.6 changed the default, and pyannote 3.x models use unpickling.

#### Tested End-to-End

38-minute Zoom recording (2 speakers):
- pyannote found **2 speakers** in **742 segments** on CPU
- Aligned with 18,830 character Hebrew transcript
- Mapped to "Ben" and "Shai" via `--speakers` flag
- Output format: `**Ben:** text...\n\n**Shai:** text...`
- Total pipeline time: ~7 minutes (download + diarization + transcription)

#### Known Limitations

- **Proportional alignment is approximate** — speaker labels may be off by a few words at boundaries. Acceptable for v1.
- **No Claude-based speaker identification** — names are mapped by first-appearance order, not by content analysis. If `--speakers "Ben, Omri"` is given, SPEAKER_00 (first to speak) = Ben, SPEAKER_01 = Omri.
- **CPU diarization is slow** — 38-minute recording took ~2 minutes. Longer recordings will be slower. GPU (CUDA) is much faster.
- **No caching** — pyannote pipeline is loaded fresh each run. For the Telegram bot (Priority 4), consider caching the pipeline object.
- **torchcodec warning spam** — On Windows, pyannote imports print a long torchcodec warning to stderr. Harmless but ugly. Can be suppressed with `warnings.filterwarnings` if desired.

---

## What's NOT Done Yet (Unchanged from Previous Handoff)

### Priority 2: Integrate zumo-bot-agent.md into processor.py

**Current state:** `src/processor.py` has a basic hardcoded system prompt in `analyze_transcript()`.

**What to do:**
1. Read `zumo-bot-agent.md` at startup (or embed it as a constant)
2. Replace the hardcoded system prompt with the Zumo Bot agent prompt
3. The agent expects input in this format:
```
Session Type: {type}
Speakers: {comma-separated list}
Language: {he or en}

--- TRANSCRIPT ---
{full transcript text}
```
4. Test with the existing transcript in `output/ben-akiva/`

### Priority 3: Build the Real Dashboard HTML

A single HTML page per user, generated by the pipeline, served on Netlify. Based on `DESIGN-SYSTEM.md` and `design-system-preview.html`. See previous handoff for full spec (password gate, session cards, RTL, responsive, static).

### Priority 4: Telegram Bot

`bot.py` using `python-telegram-bot`. Same pattern as `c:\Users\darta\Desktop\פרויקטים\tiktok-pipeline\bot.py`. See previous handoff for full spec.

### Priority 5: Deployment

Railway (bot) + Netlify (dashboard). See previous handoff.

### Priority 6: Onboarding Guide

Markdown doc for new users. See previous handoff.

---

## Key Files to Read First

1. `src/diarizer.py` — NEW: speaker diarization + alignment logic
2. `pipeline.py` — Updated flow with 8 steps
3. `zumo-bot-agent.md` — Agent prompt to integrate next (Priority 2)
4. `src/processor.py` — Where agent prompt needs replacing
5. `DESIGN-SYSTEM.md` — For dashboard build (Priority 3)
6. `design-system-preview.html` — Visual reference

---

## Ben's Preferences (Unchanged)

- No emojis in UI or outputs. Geometric shapes OK.
- Hebrew for content, English for code/technical.
- Don't over-engineer. 5 users max. Keep it simple.
- Dark mode only. Rubik font. Very rounded. Thick strokes.
- He builds cathedrals when houses would do — nudge him to ship.
