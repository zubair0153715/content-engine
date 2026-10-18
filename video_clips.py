"""Optional AI video-clip stage (Magic Hour image-to-video).

STATUS: UNTESTED live — needs the owner's free API key (see README
"AI video clips (owner action)"). Written against Magic Hour's documented
Python SDK (magichour.ai/api/image-to-video, docs 2026-10-05). Until a key
exists and one clip is verified end-to-end, treat this module as
integration-ready, not integration-proven.

What it does when active: for each scene, takes the composited scene image
(assets/{scene}_comp.jpg), sends it to Magic Hour image-to-video
(LTX-2.5, 480p — the free-tier model/resolution), and saves the returned
AI-animated clip as assets/{scene}_aiclip.mp4. stage_assemble prefers the
AI clip over the Ken Burns still when present.

Without MAGIC_HOUR_API_KEY (or on ANY failure: no SDK, quota exhausted,
API error) every function returns None and the engine keeps its ffmpeg
motion path — the pipeline never breaks.
"""

import os

# Model + resolution valid on Magic Hour's free tier (per their docs).
MH_MODEL = os.environ.get("MH_VIDEO_MODEL", "ltx-2.5")
MH_RESOLUTION = os.environ.get("MH_VIDEO_RES", "480p")
MH_SECONDS = float(os.environ.get("MH_VIDEO_SECONDS", "5"))


def available():
    """True only if a key is configured AND the SDK imports."""
    if not os.environ.get("MAGIC_HOUR_API_KEY", "").strip():
        return False
    try:
        import magic_hour  # noqa: F401
        return True
    except Exception:
        return False


def _client():
    from magic_hour import Client
    return Client(token=os.environ["MAGIC_HOUR_API_KEY"].strip())


def animate_scene(comp_path, dest, motion_prompt="", timeout_s=600):
    """Animate one composited scene image -> AI video clip.

    Returns dest on success, None on any failure (caller falls back).
    UNTESTED live — first real call must be watched by the operator.
    """
    if not available():
        return None
    try:
        client = _client()
        # Documented SDK pattern (magichour.ai/api/image-to-video):
        # local image path -> SDK uploads -> async job, wait for completion.
        kwargs = dict(
            assets={"image_file_path": comp_path},
            end_seconds=MH_SECONDS,
            name=f"content-engine scene clip ({os.path.basename(comp_path)})",
            resolution=MH_RESOLUTION,
            wait_for_completion=True,
            download_outputs=True,
            download_directory=os.path.dirname(dest) or ".",
        )
        if motion_prompt:
            kwargs["prompt"] = motion_prompt
        res = client.v1.image_to_video.generate(**kwargs)
        # SDK downloads to download_directory; locate the mp4.
        ddir = os.path.dirname(dest) or "."
        cands = [os.path.join(ddir, f) for f in os.listdir(ddir)
                 if f.lower().endswith(".mp4")]
        if not cands:
            return None
        newest = max(cands, key=os.path.getmtime)
        if os.path.abspath(newest) != os.path.abspath(dest):
            os.replace(newest, dest)
        # fail fast if it isn't a real video
        if os.path.getsize(dest) < 20000:
            return None
        return dest
    except Exception as e:
        print(f"[video_clips] animate failed ({type(e).__name__}): {e}")
        return None


def stage_aiclips(pid, motion_style="subtle camera push-in, gentle motion"):
    """Optional stage: AI-animate every scene composite.

    Run: python3 engine.py aiclips --project ID
    No-op (with one log line) when the key/SDK is unavailable.
    """
    import engine as E
    d = E.pdir(pid)
    import json
    with open(os.path.join(d, "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    if not available():
        E.log("aiclips: skipped (no MAGIC_HOUR_API_KEY or SDK)")
        return {}
    outs = {}
    for s in script["scenes"]:
        comp = os.path.join(d, "assets", f"{s['id']}_comp.jpg")
        dest = os.path.join(d, "assets", f"{s['id']}_aiclip.mp4")
        if os.path.exists(dest):
            E.log(f"aiclips {s['id']}: cached")
            outs[s["id"]] = dest
            continue
        if not os.path.exists(comp):
            continue
        got = animate_scene(comp, dest, motion_style)
        if got:
            outs[s["id"]] = dest
            E.log(f"aiclips {s['id']}: AI clip ready")
        else:
            E.log(f"aiclips {s['id']}: failed -> Ken Burns still will be used")
    return outs
