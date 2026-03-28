# 🎙️ Zoom Transcriber

כלי לוקלי לתמלול הקלטות זום — מעלים קובץ, חותך שקטים, מתמלל דרך Hebrew AI, שומר כ-MD.

## Flow

```
Upload video/audio
    → Extract audio (ffmpeg)
    → Detect & remove silence >30s
    → Send to Hebrew AI API
    → Get transcription
    → Generate one-line summary (Claude Haiku)
    → Save .md to ~/zoom-transcriptions/
    → Update index.md
    → Delete source file
```

## Setup

### 1. Prerequisites

**ffmpeg** must be installed:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (via Chocolatey)
choco install ffmpeg
```

### 2. Install

```bash
cd zoom-transcriber
pip install -r requirements.txt
```

### 3. API Keys

Get your keys:
- **Hebrew AI:** https://hebrew-ai.com/en/profile/apikeys
- **Anthropic (optional):** https://console.anthropic.com/settings/keys

Enter them in the app UI, or set as environment variables:

```bash
export HEBREW_AI_API_KEY="your-key"
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 4. Run

```bash
python app.py
```

Opens at http://127.0.0.1:7860

## Output

Everything saves to `~/zoom-transcriptions/`:

```
~/zoom-transcriptions/
├── index.md                          ← Master index with all transcriptions
├── 2026-03-27_14-30-00_meeting.md    ← Individual transcription
├── 2026-03-28_09-15-00_session.md
└── ...
```

### index.md format

| Date | File | Original | Trimmed | Summary | Link |
|------|------|----------|---------|---------|------|
| 2026-03-27 | team-meeting | 01:02:00 | 00:48:30 | סיכום פגישת צוות על פרויקט X | [file.md](./file.md) |

### Transcription .md format

```markdown
# team-meeting

| Field | Value |
|-------|-------|
| **Date** | 2026/03/27 14:30:00 |
| **Original Duration** | 01:02:00 |
| **Trimmed Duration** | 00:48:30 |
| **Silence Removed** | 00:13:30 |

---

[transcription text...]
```

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Silence threshold | 30s | Remove silent segments longer than this |
| Delete source | ✅ On | Delete the uploaded video/audio after transcription |
| Language | עברית | Hebrew or English |
