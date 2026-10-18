# Content Engine — Roadmap

## v1 — DONE (2026-10-17)
Topic → 9:16 vertical short + SEO package. 8 stages (research template →
script → hosted TTS → AI-image/motion visuals → ffmpeg assemble → SEO →
manual-upload package → QC gate 0–100). Demo: `projects/demo-001`
("3 AI tools that save 2 hours daily", 38.1s, QC 100/100).

## v2 — THIS BUILD (2026-10-17)
"Jo reh gaya wo sab" — every buildable piece of the master doc:

- [x] **Auto-research** — `research_agent.py`: Wikipedia API facts
      (sourced + dated) → LLM angle ranking with keyword-heuristic fallback
      → `research_brief.md` in v1 format. DDG-lite sweep attempted, honestly
      reported as bot-walled.
- [x] **LLM abstraction** — `llm.py`: Gemini primary (`GEMINI_API_KEY`),
      OpenRouter `:free` fallback (`OPENROUTER_API_KEY`), one-env-var
      provider switch, graceful degradation everywhere. Wired into research
      (angle ranking) and script (`--draft` from brief; draft ≠ approved).
- [x] **Multi-platform renders** — `platforms` stage: 1:1 (1080×1080) and
      16:9 (1920×1080) from the 9:16 master via blurred-bg pillarbox
      (captions stay visible); QC checks dimensions + duration per variant.
- [x] **Topic-aware SEO** — was hardcoded for demo-001 in v1; now generated
      from topic + scenes (still a template — review before uploading).
- [x] **Local TTS fallback** — Piper (`bin/piper`, en_US-lessac-medium)
      installed and wired: `--tts-engine piper`, plus automatic
      hosted→Piper fallback per scene (EN).
- [x] **Task queue + scheduling** — `queue.py`: master-doc states,
      priorities, exponential-backoff retry (3 attempts), resume without
      redoing finished stages, LLM script auto-draft → `awaiting_approval`.
- [x] **Web dashboard** — `dashboard.py` (stdlib only, :8099): content
      library, project detail with video preview (Range streaming),
      approve/reject, new-video → queue form, queue view, analytics view.
- [x] **Honest analytics** — `analytics.py`: manual performance entries →
      aggregates → 3 data-derived recommendations; "insufficient data"
      instead of invented insight below 2 videos.
- [x] **Docs** — README (v2), ARCHITECTURE.md, ROADMAP.md, TESTING.md.

## v2.1 — FREE TOOL INTEGRATION (2026-10-17)
Every candidate tested on this VM; only winners wired:

- [x] **faster-whisper voiceover QC** — `whisper_qc.py`: transcribes the
      rendered voiceover (tiny model, CPU int8, ~2s per 40s clip) and
      fuzzy-matches it against the approved script (`voiceover_script_match`
      QC check: pass ≥0.80, warn 0.60–0.80, fail <0.60). Catches
      wrong/truncated/garbled TTS. Needed two compat shims, both documented
      in-module: `av.open(metadata_errors=)` patch (VM has av 19.x) and
      no_proxy bracket-stripping for huggingface_hub. Demo-002: similarity
      0.90 → pass; tooltest-001: 1.00 → pass.
- [x] **gTTS engine** — `--tts-engine gtts`: free, no key, plain HTTPS,
      robotic quality, HAS Urdu. Wired as opt-in + automatic fallback for
      non-English when hosted TTS fails (Piper is EN-only). Test video
      `projects/tooltest-001` (15.3s, QC 100/100) fully voiced by gTTS.
- [x] **`queue.py add --script-file`** — queue a pre-written script that
      parks at `awaiting_approval` WITHOUT auto-approving (feeds the weekly
      cron; the human gate stays intact).
- [x] **Weekly cron `content-engine-weekly`** — Sundays ~09:23 PKT:
      renders any approved task, picks a trending AI-tools topic, queues a
      validated script → `awaiting_approval`. He reviews in dashboard,
      approves, uploads manually.
- [ ] **Edge-TTS** — REJECTED: installs fine and lists 4 Urdu voices
      (ur-PK-Asad/Uzma), but synthesis needs wss:// and this VM's egress
      proxy breaks WebSocket upgrades (101 with invalid Connection header).
      Would work on an unrestricted network; documented, not wired.
- [ ] **Pollinations.ai images** — REJECTED: free endpoint works (6–7s per
      image) but free tier bakes a `pollinations.ai` watermark into every
      image despite `nologo=true`, quality is hit-or-miss, and latency
      spikes (one 60s timeout in 3 tries). Not client-grade; documented.
- [ ] **faster-whisper as caption generator** — assessed, not needed:
      captions are burned from the approved script (aligned by construction);
      whisper's job is verification, which is the higher-value use.

## v2.2 — VISUALS UPGRADE (2026-10-17, Zubair's feedback)

His test video had NO real visuals (only fallback slides) — root cause:
`stage_visuals` only composited pre-dropped `assets/`; the autonomous worker
path never generated any image.

- [x] **`imgfetch` stage** (`image_fetch.py`): per-scene keyword queries
      (adjacent word-pairs from narration, e.g. "drug interaction") →
      Wikimedia Commons (no key, freely licensed, title-relevance re-rank,
      `filetype:bitmap` filter, PIL-verify) → Pexels (`PEXELS_API_KEY`) →
      Pixabay (`PIXABAY_API_KEY`) → fallback slide if nothing. Sources +
      licenses → `assets/image_sources.json` → manifest. Respects
      pre-dropped assets.
- [x] **Smoother motion (ffmpeg-only):** 0.5s xfade crossfades between scenes
      (video extended by the overlap so total duration == narration total);
      Ken Burns direction varies deterministically per scene
      (zoom-in / zoom-out / pan-right / pan-left); audio muxed separately
      from the concatenated scene MP3s. Captions, 3 aspect ratios, QC
      unchanged.
- [x] **Pollinations re-test** — one explicit test (`model=flux`,
      `private=true`, `nologo=true`): fast (8s) but the visible
      `pollinations.ai` watermark persists → stays REJECTED, not relitigated.
- [ ] **Character animation / text-to-video** — still needs GPU or paid API.
      v3. This upgrade is honestly slideshow-style: real photos + motion +
      transitions + captions.


## v2.3 — ANIMATION UPGRADE (2026-10-17, Zubair's "full animation" ask)

Market researched (ANIMATION_MARKET.md): Higgsfield ("hugsfield") $15–19/mo,
Hailuo ~$0.25/6s clip, Pika ~$0.14/5s — **no free production path to
cartoon-style text-to-video exists**. HF Inference free anon tier is dead
(tested: HTTP 401). All open video models need 24–80 GB VRAM (infeasible here).

- [x] **Kinetic typography** — `_kinetic_filters()` in `engine.py`: per-scene
      animated keyword overlay (ffmpeg drawtext: slide-up + fade in/out);
      leading numbers get a giant 0→N count-up (`eif`). Zero GPU.
      Proof: visualtest-001 re-rendered, 5/5 scenes kinetic, QC 100/100.
- [x] **Transition variety** — xfade cycles `fade/slideleft/dissolve/
      slideright/fadewhite/smoothup` deterministically (was fade-only).
- [x] **HF image source** — `fetch_hf()` in `image_fetch.py`: FLUX.1-schnell
      via Inference Providers, optional `HF_TOKEN`, 4th source (after
      Wikimedia/Pexels/Pixabay). Free tier ≈ 10 images/mo — honest bonus tier.
- [x] **`aiclips` stage + `video_clips.py`** — Magic Hour image-to-video
      (free signup credits, no card) wired as optional stage; `assemble`
      prefers AI clips when present. **UNTESTED live** (needs owner's key) —
      graceful skip verified, pipeline unaffected.
- [ ] **Manim** — assessed, skipped: heavy deps + minutes-per-clip CPU
      renders break the worker budget; ffmpeg-native covers the need.
- [ ] **Character animation / text-to-video** — still paid-only. Cheapest
      real path documented: Hailuo ~$0.25/6s clip; Magic Hour free credits
      first, then $19/mo.

## v3 — NEEDS BUDGET / APPROVALS (not buildable free; documented, not faked)
1. **AI text-to-video generation** — needs GPU (local) or paid API
   (Runway/Pika/Veo). No free tier covers series production.
2. **Auto-publishing** — TikTok/Instagram/YouTube APIs need app review,
   business accounts, and (for TikTok) approval. Manual-upload package
   remains the honest path until then.
3. **Local LLM** — infeasible on this VM (834 MB RAM free). Revisit on a
   16 GB+ machine (Ollama + 8B Q4).
4. **Licensed music/SFX library** — bundle a verified free-licensed track
   (YouTube Audio Library / Pixabay) + loudness normalization.
5. **Urdu Piper voice** — no quality open Urdu Piper voice verified yet;
   hosted TTS remains the Urdu path (with the Roman-Urdu Heh-Goal workaround).
6. **Conditional re-shoot agent** — only if QC-fail → auto-fix decisions ever
   need branching (this is the one case where LangGraph would earn its place).

## Explicitly rejected (assessed, not omitted by accident)
- n8n (2–4 GB RAM need; crons + queue.py already schedule)
- LangGraph / CrewAI (linear deterministic pipeline — "agents for appearance"
  forbidden by the master doc itself)
- DeepSeek free tier (unverified Oct 2026), Kimi API (no free tier),
  Qwen free tier (ended Apr 2026) — see LLM_AUTOMATION_OPTIONS.md
