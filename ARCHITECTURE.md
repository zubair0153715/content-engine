# Content Engine — Architecture (v2)

```
                    ┌─────────────┐
                    │  dashboard  │  stdlib http.server :8099
                    │  (library, queue, analytics, approve/reject)
                    └──────┬──────┘
                           │ reads/writes
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ queue.py │ │ projects │ │analytics │
        │(JSON task │ │  */      │ │  .json   │
        │ queue)   │ │ manifest │ │          │
        └────┬─────┘ │ qc_report│ └──────────┘
             │      │ status   │
             │      └────┬─────┘
             ▼           ▼
   ┌─────────────────────────────────┐
   │            engine.py            │  10 stages, each resumable
   │ research→script→voiceover→      │
   │ imgfetch→visuals→aiclips→       │
   │ assemble→platforms→seo→         │
   │ package→qc                      │
   └────┬────────────┬─────────┬─────┘
        ▼            ▼         ▼
  ┌──────────┐ ┌────────┐ ┌────────┐
  │research_ │ │ llm.py │ │ piper/ │
  │agent.py  │ │gemini→ │ │ local  │
  │(wikipedia│ │openrtr │ │ TTS    │
  │ + LLM)   │ │        │ │        │
  └──────────┘ └────────┘ └────────┘
```

## Components

| File | Responsibility | Inputs → Outputs |
|---|---|---|
| `engine.py` | 10-stage pipeline (v2.3: +imgfetch, +aiclips); every stage independently runnable and resumable (skips finished work) | topic/scenes → `projects/<id>/` |
| `research_agent.py` | Auto-research: Wikipedia API facts (sourced + dated) → LLM angle ranking (heuristic fallback) → `research_brief.md` in v1 format | `--topic`, `--research-query` → brief |
| `image_fetch.py` | Per-scene auto image-fetch: Wikimedia (no key) → Pexels → Pixabay → Hugging Face FLUX (`HF_TOKEN`, ~10 free/mo) → fallback slide | scene text → `assets/{scene}.jpg` + `image_sources.json` |
| `video_clips.py` | Optional `aiclips` stage: Magic Hour image-to-video per scene. UNTESTED live (needs `MAGIC_HOUR_API_KEY`); graceful skip | `assets/{scene}_comp.jpg` → `assets/{scene}_aiclip.mp4` |
| `llm.py` | Provider abstraction. Gemini primary (`GEMINI_API_KEY`), OpenRouter fallback (`OPENROUTER_API_KEY`). One env var switches provider | messages → text; raises `LLMUnavailable`, never crashes |
| `queue.py` | JSON task queue with the master doc's states, priorities, exponential-backoff retry, resume-without-redo | `queue.json` |
| `dashboard.py` | Stdlib web UI: library, project detail (video preview + Range streaming), approve/reject, new-video form, queue, analytics | port 8099 |
| `analytics.py` | Manual performance entries → aggregates → 3 data-derived recommendations (honest "insufficient data" below 2 videos) | `analytics.json` per project |

## Stage → queue-state mapping

`researching` → research · `scriptwriting` → script (+`--draft`) ·
`awaiting_approval` → human reviews `scenes.draft.json` ·
`generating_media` → voiceover, visuals · `editing` → assemble, platforms,
seo, package · `quality_checking` → qc · `ready_for_publishing` → manual upload.

## Key design decisions

1. **Linear pipeline, no agent framework.** The flow is deterministic;
   engine.py + queue.py orchestrate it. (Master doc: "Do not create multiple
   agents simply for appearance.")
2. **Humans at the consequential gates.** Script approval and publishing are
   always operator-approved — the master doc's own default policy.
3. **Pillarbox, not crop, for platform renders.** The 9:16 master is placed on
   a blurred-background canvas for 1:1/16:9, so burned-in captions (bottom
   safe zone) stay fully visible. Verified in QC.
4. **Secrets at call time.** `GEMINI_API_KEY` / `OPENROUTER_API_KEY` are read
   from the environment when needed, never stored in files or logs.
5. **Honest degradation.** Every LLM/TTS/research network call has a
   documented fallback or a loud, actionable failure — never a silent wrong
   result and never an invented one.
6. **No in-process third-party imports without a path guard.** This package
   ships `queue.py`, which shadows stdlib `queue` for any library imported
   in-process (urllib3, ctranslate2, …) whenever CWD is on `sys.path`.
   `whisper_qc.py` and `tts_gtts()` sanitize `sys.path` around third-party
   imports and restore it after. Any future in-process third-party import
   MUST do the same — or run it in a subprocess.

## Data layout

```
content-engine/
  engine.py  research_agent.py  llm.py  queue.py  dashboard.py  analytics.py
  queue.json
  bin/piper/            # local TTS (binary + en_US-lessac-medium voice)
  projects/<id>/
    research_brief.md  script.json  scenes.draft.json
    audio/voiceover.mp3 (+ voiceover_meta.json)
    assets/sceneN.jpg  assets/sceneN_comp.jpg  assets/thumbnail.png
    segments/  joined.mp4  final.mp4  final_1x1.mp4  final_16x9.mp4
    captions.srt  seo.json  manifest.json  qc_report.json
    UPLOAD_CHECKLIST.md  status.json  analytics.json
```

## What is NOT in the architecture (deliberately)

- AI text-to-video generation (needs GPU / paid API — ROADMAP v3).
- Auto-publishing to TikTok/Instagram/YouTube (needs platform app review —
  manual-upload package instead).
- n8n / LangGraph / CrewAI (assessed in LLM_AUTOMATION_OPTIONS.md — no gap
  they fill; crons + queue.py already schedule).
- Local LLM on this VM (834 MB RAM free — infeasible; documented).
