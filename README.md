# Content Engine v2

Topic in → multi-platform short video + SEO package out.
Implements every *buildable* piece of the Autonomous AI Content Empire plan
(see `LLM_AUTOMATION_OPTIONS.md` for the provider/repo survey and
`ROADMAP.md` for what stays out and why).

## What v2 does

```
research ──→ script ──→ voiceover ──→ imgfetch ──→ visuals ──→ aiclips ──→ assemble ──→ platforms
  (auto,            (LLM draft,      (hosted TTS     (real photos,   (optional AI
   web)              human           + local Piper    free, auto)     video clips,
                     approves)        fallback)                      Magic Hour)
        ──→ seo ──→ package ──→ qc gate ──→ manual upload
```

| Piece | What happens |
|---|---|
| `research --auto` | `research_agent.py`: Wikipedia API facts (sourced + dated) → LLM angle ranking (keyword-heuristic fallback) → `research_brief.md`. `--research-query` overrides the search query. DDG-lite sweep attempted; honestly reported when bot-walled. |
| `script --draft` | LLM drafts `scenes.draft.json` from the brief. **Draft ≠ approved** — promote with `script --project P --script-file scenes.draft.json` after review. Without an LLM key it exits with instructions for manual authoring. |
| `voiceover` | Hosted TTS default; `--tts-engine piper` (local EN) or `--tts-engine gtts` (free, robotic, has Urdu). Hosted failures auto-fall-back per scene: Piper for EN, gTTS otherwise. |
| `imgfetch` | **NEW:** auto-fetches a real, topically-relevant photo per scene — keyword queries derived from the narration → **Wikimedia Commons** (no key, freely licensed) → **Pexels** (`PEXELS_API_KEY`) → **Pixabay** (`PIXABAY_API_KEY`) → **Hugging Face** (`HF_TOKEN`, FLUX.1-schnell, ~10 free images/mo — bonus tier). Sources + licenses logged to `assets/image_sources.json` (in manifest). Scenes with nothing found keep the fallback slide. |
| `visuals` | Fetched images composited (9:16 crop + text overlay); motion-graphics slide fallback when no image. |
| `aiclips` | **NEW (optional, v2.3):** AI-animates each scene composite via **Magic Hour** image-to-video (free signup credits, no card; LTX-2.5 480p on free tier). **UNTESTED live** — needs owner's key; without it (or on any failure) the engine keeps its ffmpeg motion path. `assemble` prefers AI clips when present. |
| `assemble` | Ken Burns segments (direction varies per scene: zoom-in / zoom-out / pan, deterministic) matched to narration, **kinetic typography** (v2.3: animated keyword overlay — slide-up + fade; leading numbers get a giant 0→N count-up, ffmpeg-only, zero GPU), **transition variety** (v2.3: xfade cycles fade/slideleft/dissolve/slideright/fadewhite/smoothup), captions burned in → `final.mp4` (1080×1920 h264+aac). |
| `platforms` | `final_1x1.mp4` (1080×1080) + `final_16x9.mp4` (1920×1080) via blurred-background pillarbox — the full 9:16 frame stays visible so captions are never cropped. |
| `seo` | Topic-aware package (title, alts, description, hashtags, pinned comment, thumbnail concept). Template — review before uploading. |
| `package` / `qc` | `manifest.json` (all renders) + `UPLOAD_CHECKLIST.md`; QC checks master + both platform renders (dims, duration, audio, black frames, caption safe-area by construction) + **whisper voiceover-vs-script match** (`whisper_qc.py`: faster-whisper tiny on CPU transcribes the voiceover, fuzzy-matches the approved script — pass ≥0.80, warn 0.60–0.80, fail <0.60). Score 0–100, blocks "ready" on failure. |
| `queue.py` | Task queue with the master doc's states, priorities, exponential-backoff retry (3 attempts), resume-without-redo. `run-once` processes one task; LLM auto-drafts scripts then parks at `awaiting_approval`. |
| `dashboard.py` | Stdlib web UI (`:8099`): content library, project detail (video preview with seeking, approve/reject, downloads), new-video → queue form, queue view, analytics view. |
| `analytics.py` | Manual performance entries → aggregates → 3 data-derived recommendations. Says "insufficient data" below 2 videos instead of inventing insight. |
| `llm.py` | Provider abstraction: **Gemini primary** (`GEMINI_API_KEY`), **OpenRouter `:free` fallback** (`OPENROUTER_API_KEY`). `LLM_PROVIDER` switches with one env var. Keys read at call time, never stored. |

## Run a new topic

```bash
cd ~/workspace/content-engine

# Full auto pipeline (research auto; script drafted by LLM, YOU approve it)
python3 engine.py research --project my-topic --topic "My video topic" --auto
python3 engine.py script --project my-topic --topic "My video topic" --draft
# ... review projects/my-topic/scenes.draft.json ...
python3 engine.py script --project my-topic \
  --script-file projects/my-topic/scenes.draft.json
python3 engine.py voiceover --project my-topic   # --tts-engine piper|gtts
python3 engine.py imgfetch --project my-topic --topic "My video topic"  # auto real photos
python3 engine.py visuals --project my-topic     # or drop your own images in assets/ first
for s in assemble platforms seo package qc; do
  python3 engine.py $s --project my-topic
done
# seo needs the topic: python3 engine.py seo --project my-topic --topic "..."

# Or via the queue (recommended for series):
python3 queue.py add --topic "My video topic" --priority 3
python3 queue.py run-once        # research (+draft) ...
# review draft, then:
python3 queue.py approve T001 --script-file projects/<id>/scenes.draft.json
python3 queue.py run-once        # ... renders, QC, ready_for_publishing

# Dashboard:
python3 dashboard.py --port 8099   # http://127.0.0.1:8099/
```

## LLM setup (owner actions)

- **Primary (Gemini, free):** nothing to do — `GEMINI_API_KEY` is already set
  in the deployment container (same key as `/style` and `/pharma-ai`).
  On this VM the key is absent, so LLM features degrade gracefully here and
  run fully in the deployed container.
- **Fallback (OpenRouter, free — optional, 2 min, YOUR action):**
  1. Sign up at **openrouter.ai** (free, no credit card).
  2. Create an API key (Keys page → Create).
  3. Set it as a **secret env var** `OPENROUTER_API_KEY` in the FastAPI Cloud
     dashboard (same place the Gemini key lives). **Never paste keys in chat.**
  4. Verify: `python3 llm.py --status` should show `"openrouter": true`.
  Without it the engine runs primary-only and logs one line — nothing breaks.

## Image sources (owner actions — optional upgrades)

- **Wikimedia Commons (default, works now):** no key, no signup — always on,
  all media freely licensed. Quality varies by topic (great for
  science/history/places, thinner for niche commercial topics).
- **Pexels (recommended upgrade, free, YOUR action, ~2 min):**
  1. Sign up free at **pexels.com/api** (no credit card).
  2. Create an API key.
  3. Set it as env var `PEXELS_API_KEY` (VM: export it; container: FastAPI
     Cloud dashboard secret). **Never paste keys in chat.**
  Pexels photos are higher-quality lifestyle/commercial shots — noticeably
  better scenes for business/marketing topics. Without it the engine uses
  Commons and logs one line — nothing breaks.
- **Pixabay (alternative):** same pattern, `PIXABAY_API_KEY` from pixabay.com/api.
- **Hugging Face (bonus image source, YOUR action, ~2 min):**
  1. Free signup at **huggingface.co**, create a token (Settings → Access Tokens).
  2. Set it as `HF_TOKEN` (VM: export; container: dashboard secret).
  Free accounts get ~$0.10/month provider credits (~10 FLUX images/month) —
  a bonus source for scenes nothing else covers, not production capacity.
  PRO ($9/mo) → $2 credits (~200 images/mo) makes it real. Without the token
  the engine skips it silently. **Never paste keys in chat.**
- **Magic Hour (AI video clips — the biggest free visual upgrade, YOUR action, ~2 min):**
  1. Free signup at **magichour.ai/developer** (no credit card) — you get
     trial credits immediately (400 signup + 100/day per their docs).
  2. Create an API key, set it as `MAGIC_HOUR_API_KEY` (dashboard secret).
  3. Optionally `pip install magic-hour` where the worker runs (the module
     also works if the SDK is missing — it just skips).
  Then `python3 engine.py aiclips --project ID` AI-animates every scene
  (LTX-2.5, 480p on free tier); `assemble` uses the clips automatically.
  **Status: integration-ready, NOT live-tested** (no key existed to test
  with) — first run must be watched. Without the key everything works as
  before. **Never paste keys in chat.**

## Honest limits (v2.3)

- **TTS backends:** hosted (default, best quality) → Piper (local, EN only)
  → gTTS (free, robotic, has Urdu; opt-in or non-EN fallback). Edge-TTS
  tested and rejected: this VM's egress proxy breaks its WebSocket handshake.
- **Visuals are motion-graphics, honestly:** real photos + Ken Burns motion
  (zoom/pan, varies per scene) + **kinetic typography** (v2.3: animated
  keywords slide-up + fade, leading numbers get a giant 0→N count-up) +
  **varied transitions** (v2.3: xfade cycles fade/slideleft/dissolve/
  slideright/fadewhite/smoothup) + burned-in captions. This is NOT character
  animation or text-to-video — those need a GPU or paid API (ROADMAP v3).
  Market research (ANIMATION_MARKET.md, 2026-10-17): **no free production
  path to cartoon-style video exists** — Higgsfield ("hugsfield")
  $15–19/mo, Hailuo ~$0.25/6s clip, Pika ~$0.14/5s; HF's free inference tier
  is dead (tested: HTTP 401); all open video models need 24–80 GB VRAM.
- **No AI video generation (free).** The `aiclips` stage is wired for
  Magic Hour's free trial credits (image-to-video, LTX-2.5 480p) but is
  **UNTESTED live** — it needs the owner's free API key first. Without the
  key the engine runs its ffmpeg motion path, unchanged. (ROADMAP v3.)
- **No auto-publishing.** Platform APIs need app review/approvals; v2 ships a
  manual-upload package. Publishing stays human-approved (master doc default).
- **Hosted TTS is the default** (same backend as medexplain). Piper is the
  local fallback (EN only for now; no quality open Urdu Piper voice verified).
- **Urdu TTS quirk inherited:** backend fails on Urdu Heh-Goal (U+06C1) —
  Roman-Urdu narration, proper Urdu script on-screen/captions.
- **Research is Wikipedia + operator sources.** DDG-lite news sweep is
  bot-walled from servers; the brief says so instead of pretending.
- **Angle scores are heuristics/LLM judgment, not virality predictions.**
- **Analytics needs manual entries** — no platform API integrations (they need
  app review). Two videos minimum before recommendations mean anything.
- **No background music bundled** — add `assets/music.mp3` from a verified
  free-licensed source (YouTube Audio Library / Pixabay) if you want it.

## Demos

- `projects/demo-001/` — v1: "3 AI tools that save 2 hours daily" (38.1s, QC 100/100).
- `projects/demo-002/` — v2: "3 prompt engineering tricks most people miss"
  (auto-research → 3 aspect ratios → dashboard → QC).
- `projects/tooltest-001/` — v2.1: free-tool test (15.3s, QC 100/100) —
  voiceover 100% gTTS, whisper QC similarity 1.00.

## Weekly automation

Cron `content-engine-weekly` (Sundays ~09:23 PKT, owner: AI Edge channel
goal): renders any approved task, picks a trending AI-tools topic, queues a
validated script → `awaiting_approval`. He reviews the script in the
dashboard, approves, uploads manually. `queue.py add --script-file` feeds
this flow without auto-approving.
