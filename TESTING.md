# Content Engine — Testing (v2, 2026-10-17)

Real results only. Nothing below is asserted without a run.

## v2.2 visuals proof run: visualtest-001 ("5 AI tools for pharmacy students")

Full worker-path pipeline (research → … → imgfetch → visuals → assemble →
platforms → seo → package → qc) on 2026-10-17, fresh project, no manual
asset drops:

| Stage | Result |
|---|---|
| imgfetch (NEW) | ✅ 5/5 scenes got real Wikimedia Commons photos (CC/public-domain, sources + licenses in `assets/image_sources.json` → manifest). Query derivation: adjacent word-pairs from narration ("drug interaction", "pharmacy science"); topic queries interleaved for generic hook/CTA scenes; weak-word filter ("follow", "facts"); title-relevance re-rank with rel≥1 floor; `filetype:bitmap` + PIL-verify. Caught in testing: PDF thumbnails, a bird photo ("here facts"), a concert photo ("follow") — all fixed by the filters above. |
| visuals | ✅ All 5 composited (9:16 crop + text overlay) — zero fallback slides. |
| assemble | ✅ Per-scene Ken Burns direction (zoom-in / zoom-out / pan-right / pan-left, deterministic by index) + **0.5s xfade crossfades** between all 4 boundaries (verified: mid-transition frame shows true blend, total duration == narration total 50.1s). Audio muxed from concatenated scene MP3s. |
| qc | ✅ **PASS, score 100/100** — all checks green incl. duration_match and no-black-frame checks with the new xfade timeline. |

Final: `projects/visualtest-001/final.mp4` (50.1s) + 1:1 + 16:9 + SEO pack.
Honest note: slideshow-style (real photos + motion + transitions + captions) —
not character animation or text-to-video (needs GPU/paid API, ROADMAP v3).

## v2 demo run: demo-002 ("3 prompt engineering tricks most people miss")

End-to-end through the v2 pipeline on 2026-10-17:

| Stage | Result |
|---|---|
| research `--auto` | ✅ 8 facts from Wikipedia API ("Prompt engineering" page), each with source URL + retrieval date; 5 angles ranked (heuristic — no LLM key on VM); DDG-lite sweep attempted → bot-walled, reported honestly in brief. Operator appended 5 facts from 2026 web sources (The AI Corner, Prompt Builder, Voiceflow) with URLs. |
| script | ✅ Operator-authored `scenes.json`: 5 scenes, ~44s estimated. (LLM `--draft` path tested separately — see below.) |
| voiceover (hosted) | ✅ 5/5 scenes, 37.6s total, per-scene engine logged `[hosted]`. |
| voiceover (piper) | ✅ `tts_piper()` unit-tested: 4.8s MP3 from local synthesis, no hosted calls. Wired as `--tts-engine piper` + automatic per-scene fallback. |
| visuals | ✅ 4 AI images composited (9:16 crop + text overlay); scene5 used the motion-graphics fallback (no image) — fallback path exercised deliberately. |
| assemble | ✅ 37.6s master, h264 + aac, captions burned in (+ `captions.srt`). |
| platforms | ✅ `final_1x1.mp4` 1080×1080, `final_16x9.mp4` 1920×1080, blurred-bg pillarbox, durations match master ±0.1s. |
| seo | ✅ Topic-aware (was hardcoded for demo-001 in v1 — fixed and verified: title/alts/description all match demo-002 topic). |
| package | ✅ `manifest.json` lists all 3 renders; `UPLOAD_CHECKLIST.md` written. |
| qc | ✅ **PASS, score 100/100** — master + both platform renders checked (dims, codec, audio, duration match, no black start/end frames, caption safe-area by construction). |

## Module tests

| Test | Result |
|---|---|
| `llm.py --status` (no keys on VM) | ✅ `{"gemini": false, "openrouter": false}` — no crash |
| `llm.chat()` no keys | ✅ clean `LLMUnavailable` with setup instructions |
| `llm.chat()` bogus key | ✅ HTTP error → OpenRouter skipped (no key) → `LLMUnavailable("All LLM providers failed: gemini/gemini-2.5-flash")`. Fallback-degradation path exercised. |
| research LLM path, no key | ✅ falls back to keyword heuristic, logs it, brief still written |
| `engine.py script --draft`, no key | ✅ exit 1 with actionable message ("write scenes.json manually"), no traceback |
| `queue.py` add/list/show/approve/cancel/retry | ✅ all verbs work; `run-once` advanced T002 received → … → `awaiting_approval` (auto-research ran, LLM draft unavailable → parked with manual instructions). Second `run-once` correctly no-op'd (still parked, unapproved). |
| `dashboard.py` (stdlib, :8099) | ✅ `/`, `/project/demo-002`, `/queue`, `/analytics`, `/new` → 200. Library lists demo-001 + demo-002. Approve POST → 303, `status.json` written. New-video POST → task queued. `/files/.../final.mp4` with `Range:` → **206** (seeking works). |
| `analytics.py add` + `report` (0–1 videos) | ✅ honest `insufficient_data` + 3 guidance recommendations. The ≥2-video comparison path is code-reviewed but **not live-tested** (no real performance data exists yet — fabricating it would be dishonest). |

## Known limitations found during testing

1. Wikipedia opensearch needs a rephraseable query for niche topics; `--research-query` override + single-word fallback added. Very niche topics still produce thin briefs — the brief says so.
2. DDG-lite is bot-walled from servers — the module logs this instead of pretending.
3. `analytics.py report` comparison logic awaits the second real video's data.
4. Dashboard serves on 127.0.0.1 only — expose via SSH tunnel or a reverse proxy for phone access (operator's choice; not done by default for security).

## v2.1 free-tool integration tests (2026-10-17)

Real runs on this VM (CPU-only, egress proxy). Winners wired, losers documented.

| Test | Result |
|---|---|
| Edge-TTS install + voice list | ✅ `pip install edge-tts` OK; 4 Urdu voices listed (ur-PK-AsadNeural M, ur-PK-UzmaNeural F, ur-IN pair). |
| Edge-TTS synthesis | ❌ **REJECTED — network, not code.** `list_voices` (plain HTTPS) works, but synthesis needs `wss://` and the egress proxy mangles the WebSocket upgrade (101 with invalid Connection header). Direct connection blocked too. Would work on an unrestricted network — documented in ROADMAP, not wired. |
| Pollinations.ai images (3 tries) | ❌ **REJECTED.** Endpoint reachable, 6–7s/image, but free tier bakes a `pollinations.ai` watermark into every image despite `nologo=true`, quality hit-or-miss (test image missed the requested smartphone), and 1 of 3 requests hit a 60s timeout. Not client-grade. |
| faster-whisper tiny, CPU int8 | ✅ **WIRED as QC.** 38s audio → transcript in **2.1s**; EN accuracy good (minor mishearings: "role"→"roll"). Needed 2 compat shims (documented in `whisper_qc.py`): av 19.x dropped `av.open(metadata_errors=)`; huggingface_hub chokes on bracketed IPv6 in no_proxy. Also: this package's `queue.py` shadows stdlib `queue` for in-process third-party imports — sanitized in `whisper_qc` and `tts_gtts` (see ARCHITECTURE landmine note). |
| whisper QC on demo-002 | ✅ similarity 0.90 vs approved script → `pass`. |
| gTTS EN + UR | ✅ **WIRED.** Both synthesize (UR 1.1s; EN 79.7s on first call through proxy, ~4s after). Robotic quality, but free + no key + Urdu voice. Opt-in `--tts-engine gtts`, plus auto-fallback for non-EN when hosted fails. |
| tooltest-001 end-to-end (gTTS) | ✅ 2 scenes, gTTS voiceover 15.2s → visuals (motion-graphics fallback) → assemble → platforms → seo → package → **QC PASS 100/100**, whisper check similarity **1.00**. `final.mp4` 15.3s 1080×1920. |
| `queue.py add --script-file` | ✅ queues a validated script at `awaiting_approval`, `approved` stays False. Test task T003 added/cancelled cleanly. |
| numpy/scipy env note | ⚠️ faster-whisper's install upgraded numpy to 2.5.4, tripping scipy 1.11.4's `<1.28` pin. Grep: **no workspace pipeline imports scipy** (content-engine, medexplain clean) — dormant, but noted. If anything breaks, `pip install "numpy<1.28"` restores it (faster-whisper tolerates numpy 1.x). |

## Regression note (v1)

demo-001 artifacts untouched. v1 `stage_seo` hardcode replaced by the
topic-aware version — demo-001's `seo.json` on disk was NOT regenerated
(it remains as v1 produced it).

## v2.3 animation upgrade tests (2026-10-17)

Zubair: "full animation type video ho jaise cartoons hote hain... huggingface
ke sath connect karo... repos bhi dekhna, free tokens wali". Tested on this VM.

| Test | Result |
|---|---|
| HF Inference API, no token | ❌ **401** on `router.huggingface.co`, old `api-inference.huggingface.co` unreachable. The free unauthenticated tier is dead — confirmed by direct test, not docs. |
| `image_fetch.fetch_hf` (no token) | ✅ returns None immediately (graceful). With `HF_TOKEN`: free accounts get ~$0.10/mo provider credits (~10 FLUX images) — wired as 4th source, honest bonus tier. PRO $9/mo → $2 credits ≈ 200 images/mo. |
| Kinetic typography filter gen | ✅ `_kinetic_filters("5 AI TOOLS", 10.5)` builds valid drawtext chain (count-up eif + slide-up + alpha envelope). |
| Kinetic single-segment render | ✅ ffmpeg rc=0, no warnings; frame at t=3s shows giant "5" count-up + "5 AI TOOLS" keyword center + static top banner — real kinetic-typography look. |
| `assemble` full (visualtest-001, fresh segments) | ✅ 5/5 scenes `kinetic`; xfade types `['fade','slideleft','dissolve','slideright']`; 50.1s; **QC PASS 100/100**; platforms re-rendered from kinetic master; QC PASS again. |
| `engine.py aiclips` (no key) | ✅ `aiclips: skipped (no MAGIC_HOUR_API_KEY or SDK)` — pipeline unaffected. Module UNTESTED live (needs owner's free key). |
| `video_clips.py` compile | ✅ py_compile OK. Not live-tested (no key — would be dishonest to claim otherwise). |
| Manim | ⚠️ **assessed, skipped.** Not installed; install is heavy (deps) and CPU renders run minutes-per-short-clip — incompatible with the worker's 5–20 min/video budget. ffmpeg-native kinetic text + count-ups + transitions cover the motion-graphics need at zero new deps. Documented in ROADMAP. |
| Repo hunt: Open-Sora / Mochi-1 / LTX-2.5 / Wan 2.2 / CogVideoX | ❌ **all need GPU** (24–80GB VRAM). Infeasible on this CPU-only VM (834 MB free). Not attempted — would be dishonest to pretend otherwise. See ANIMATION_MARKET.md. |
| Repo hunt: Magic Hour API | ✅ **wired (untested-live).** Free signup credits (400 + 100/day per docs), no card, image-to-video incl. LTX-2.5 480p on free tier. `video_clips.py` + `aiclips` stage, graceful skip. Owner action: free signup at magichour.ai/developer → `MAGIC_HOUR_API_KEY`. |
| Repo hunt: fal.ai free web | ℹ️ 5 free daily generations (768p, commercial OK per docs) — **web only, no API**: can't integrate into the pipeline, but Zubair can hand-make hero clips. Documented in ANIMATION_MARKET.md. |
| Kinetic timing fix (same day) | ✅ Visual frame check caught kinetic keyword overlapping burned-in captions mid-scene. Fixed: kinetic is now an intro punch (fade in 0.8s → hold ≤2.2s → fade out), captions own the rest. Re-rendered visualtest-001: frame @1.2s shows clean separated layers, frame @5s shows captions only. **QC PASS 100/100** again, all 3 ratios. |
