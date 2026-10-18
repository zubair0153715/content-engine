# LLM + Automation Options — Research (2026-10-17)

Research-only survey. Nothing wired into the engine, no signups made, no money spent.
Recommendation at the bottom — Zubair approves ("me approvr kardu ga") before any integration.

## ✅ FINAL DECISION — APPROVED 2026-10-17

- **Primary LLM: Google Gemini free tier** — `llm.py`, provider `gemini`, model `gemini-2.5-flash`, key `GEMINI_API_KEY` (already works in-container).
- **Fallback LLM: OpenRouter `:free`** — provider `openrouter`, default model `meta-llama/llama-3.3-70b-instruct:free`, key `OPENROUTER_API_KEY` (HIS optional signup; unset = primary-only, logged, no crash).
- **Chinese models: REJECTED** — DeepSeek free grant unverified, Kimi K2 has no free API tier, Qwen free tier ended Apr 2026.
- **Automation repos: NONE** — n8n needs 2–4 GB RAM (VM has 834 MB free), LangGraph/CrewAI are overkill for a linear deterministic pipeline, Playwright optional-later only, Ollama infeasible on this VM.
- **Wired into v2** (`~/workspace/content-engine/llm.py`): OpenAI-compatible chat-completions for both providers, `LLM_PROVIDER` one-var switch, keys read at call time, graceful `LLMUnavailable` everywhere. Used by research (angle ranking, heuristic fallback) and script (`--draft`, draft ≠ approved). Tests in `TESTING.md`.
- **Still his action (optional):** OpenRouter free signup → `OPENROUTER_API_KEY` as a dashboard secret (never in chat). Primary needs nothing.

---

## Part 1 — Free LLM providers (verified Oct 2026)

| Provider | Free offer (verified) | Limits | Key signup (HIS action) | Commercial use | Fit for Content Engine |
|---|---|---|---|---|---|
| **Google Gemini API** (ai.google.dev) | **Free tier, no credit card.** Flash models: Gemini 3.x Flash, 2.5 Flash/Flash-Lite | ~10 RPM, ~1,500 RPD, 250k TPM (per-project; check AI Studio). Pro models NOT on free tier since Apr 2026 | aistudio.google.com → Get API key. **He ALREADY has a working `GEMINI_API_KEY` in the container** (used by /style, /pharma-ai) | Free-tier inputs **may be used by Google to improve products** — fine for content scripts, NOT for sensitive client data | ✅ **Best fit.** Already working, OpenAI-compatible endpoint available, strong EN; Urdu/Roman-Urdu OK |
| **OpenRouter** (openrouter.ai) | `:free` models, no card | 20 RPM, **50 RPD** (1,000 RPD after a one-time $10 credit purchase). Free endpoints **may log prompts** | openrouter.ai → free account → API key | Yes (check per-model terms) | ✅ **Best fallback.** One key, many models (Gemma 4, Nemotron, GLM free variants). 50/day is enough for ~10-15 videos/day |
| **Zhipu / Z.ai GLM** (open.bigmodel.cn) | GLM-4.7-Flash / GLM-4.6V-Flash **free per token** (reported by multiple Oct-2026 trackers); new accounts also get trial credits | 1 concurrent request on free Flash models (per community trackers — verify in console) | z.ai / open.bigmodel.cn signup, international endpoint (no Chinese phone needed per trackers) | Standard API terms | ✅ Good 2nd fallback. Strong Chinese/English; Urdu untested — mark as *verify* |
| **DeepSeek** (platform.deepseek.com) | **CONFLICTING — unverified.** Some sources (May 2026): 5M-token grant on signup. Oct-2026 sources: zero balance, top-up required. Treat as NO free trial until checked at signup | — | platform.deepseek.com; some reports say mainland-China phone verification required (third-party claim — unverified) | API terms standard | ⚠️ Cheap paid fallback only: V4.1 Flash $0.15/$0.60 per 1M in/out off-peak. Don't count on free |
| **Alibaba Qwen / DashScope** | Free developer tier **ENDED Apr 2026**. New Alibaba Cloud accounts: ~70M token trial (1M/model, 90 days, Singapore endpoint only) | Trial expiry 90 days | Alibaba Cloud Model Studio signup | Standard | ⚠️ Optional. Trial is real but temporary + region-locked; Qwen chat (chat.qwen.ai) is free but not an API |
| **Moonshot / Kimi** (platform.kimi.ai) | **No free API tier.** Min top-up ~$1 to activate. (One source mentions ¥15 one-off voucher with real-name verification — unverified, don't rely on it) | Tier 0: 3 RPM, 1.5M tokens/day after top-up | platform.kimi.ai | Standard | ❌ Skip for free use |
| **Ollama (local)** | Free software, but **NOT feasible on this VM — tested**: only **834 MB RAM available** (8 GB total, 2 vCPU); a 1.5B Q4 model needs ~1.5 GB+ and would OOM the container. Also couldn't install (no `zstd`, apt blocked) | N/A | None | Fully private | ❌ Skip until better hardware. Revisit on a 16GB+ machine |

**Bonus free-testing route (not production):** NVIDIA build.nvidia.com gives free trial API credits (no card) for DeepSeek V4.1 Flash, Kimi K3, GLM and others — evaluation only, good for *testing* a provider before committing.

### What the engine needs (for sizing)
Per video: ~4–8 LLM calls (research angles, script, hooks, SEO pack, thumbnail prompt) ≈ 3k–6k tokens total. Gemini free tier (1,500 RPD) covers **~200+ videos/day** — the free tier is not the bottleneck. TTS/ffmpeg remain the real cost/time drivers (unchanged).

## Part 2 — Automation repos (assessed, not blindly added)

| Repo | What it is | Real fit? | Verdict |
|---|---|---|---|
| **n8n** | Self-hosted workflow automation (visual) | Needs 2–4 GB RAM + Docker + ongoing maintenance; this VM can't host it comfortably. And **crons + engine.py already do scheduling/triggering**. n8n adds a UI Zubair won't open on his phone | ❌ **No.** Overkill; solves nothing engine.py + cron don't already solve |
| **LangGraph / CrewAI** | Agent orchestration frameworks (he already knows both) | The pipeline is a **linear, deterministic 8-stage flow** — no branching, no negotiation between agents. engine.py + the v2 task queue already orchestrate it. Adding a framework here = "agents for appearance", which the master doc itself forbids | ❌ **No** for now. Revisit ONLY if the pipeline ever needs conditional branching (e.g., QC-fail → auto re-shoot decisions) |
| **Playwright** | Browser automation | Could help *research-assist* on JS-heavy pages, but `browser.search` already covers research. Could help *upload-assist* later, but uploads need HIS logins anyway (standing rule) | ⚠️ **Optional later.** Not now — no current gap it fills |
| *(swept, nothing else qualified)* | — | — | — |

**Bottom line on automation:** engine.py + task queue + crons already cover orchestration and scheduling. The master doc's own rule applies: *"Do not create multiple agents simply for appearance."* Add nothing.

## ✅ RECOMMENDATION (for Zubair's approval)

1. **Primary LLM: Google Gemini free tier (Flash)** — key already works in-container, zero new signup, limits far above engine needs. Use for research briefs + scriptwriting (EN + Roman-Urdu).
2. **Fallback: OpenRouter `:free` models** — one extra key, no card, 50 req/day. Engine keeps an OpenAI-compatible provider abstraction so fallback = changing one env var, not code.
3. **Automation repos: NONE added.** engine.py + v2 task queue + crons stay. (Playwright = maybe later; n8n/LangGraph/CrewAI = no.)
4. **What Zubair does himself (2 min, only if he wants the fallback):** sign up at openrouter.ai (free, no card) → create API key → hand it over via the dashboard secret form (never paste in chat). Nothing needed for the primary — it already works.
5. **Honest limits carried forward:** free-tier prompts may be used for product improvement (no sensitive client data through free tier); no local LLM on this VM (834 MB RAM free); AI video-gen and auto-publishing still need budget/approvals — unchanged.

*Unverifiable items marked above: DeepSeek free-grant status, Kimi ¥15 voucher, GLM free-Flash concurrency limits — all flagged, none load-bearing for the recommendation.*
