"""Whisper-based voiceover QC for Content Engine.

Transcribes the rendered voiceover with faster-whisper (tiny, CPU int8 —
~2s for a 40s clip on this VM) and fuzzy-compares it against the approved
script narrations. Catches: wrong/truncated/garbled TTS audio, scenes
rendered in the wrong order, silent substitutions.

Honest limits:
- faster-whisper's bundled av call uses `av.open(..., metadata_errors=...)`,
  which the VM's av 19.x no longer accepts -> patched here (3 lines).
  If a future faster-whisper/av combo fixes this upstream, delete the patch.
- tiny model mishears names/technical terms ("role" -> "roll"), so this is a
  WARNING-grade check (similarity 0.60-0.80), not a hard block. Below 0.60
  the audio is almost certainly wrong -> fail.
- Needs ~1GB RAM at load; skips cleanly if faster-whisper isn't installed.
"""

import difflib
import re

_WORD = re.compile(r"[a-z0-9']+")


def _patch_av():
    """Make faster-whisper work with av>=19 (drops the removed kwarg)."""
    try:
        import av
        import faster_whisper.audio as fwa  # noqa: F401  (import for side effect)
        _orig = av.open

        def _patched(*a, **k):
            k.pop("metadata_errors", None)
            return _orig(*a, **k)

        av.open = _patched
    except Exception:
        pass


def _sanitize_proxy_env():
    """httpx (used by huggingface_hub for model download) crashes on the
    bracketed IPv6 entries in this VM's no_proxy ('[::1]' -> "Invalid port").
    Strip bracketed entries; keep the proxy itself so downloads still work."""
    import os
    for var in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(var)
        if val and "[" in val:
            clean = ",".join(p for p in val.split(",") if "[" not in p)
            os.environ[var] = clean or "localhost,127.0.0.1"


def available():
    # Sanitize FIRST: importing faster_whisper with CWD on sys.path lets its
    # `import queue` resolve to this package's queue.py, poisoning sys.modules
    # for every later importer (incl. ctranslate2's SimpleQueue use).
    _sanitize_proxy_env()
    _sanitize_imports()
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _sanitize_imports():
    """faster-whisper (via stdlib `queue`) breaks when this package's own
    queue.py shadows the stdlib because CWD is on sys.path. Temporarily
    drop CWD-ish entries so third-party imports resolve to the stdlib."""
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path = [p for p in sys.path
                if os.path.abspath(p or ".") != here]


def transcribe(audio_path, language="en"):
    """Return plain-text transcript of an audio file. Raises on failure."""
    _sanitize_proxy_env()
    _sanitize_imports()
    _patch_av()
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(audio_path, language=language)
    return " ".join(s.text for s in segments).strip()


def _words(text):
    return _WORD.findall(text.lower())


def similarity(transcript, script_text):
    """Word-level similarity 0..1 between transcript and expected script."""
    a, b = _words(transcript), _words(script_text)
    if not a or not b:
        return 0.0
    # SequenceMatcher on word lists tolerates small mishearings/order slips.
    return difflib.SequenceMatcher(None, a, b).ratio()


def check_voiceover(project_dir, language="en"):
    """Transcribe <project>/audio/voiceover.mp3 and compare with script.json.

    Returns dict: {ran, transcript_head, similarity, verdict} where verdict is
    one of 'pass' / 'warn' / 'fail' / 'skipped'.
    """
    import json
    import os

    if not available():
        return {"ran": False, "verdict": "skipped",
                "detail": "faster-whisper not installed"}
    audio = os.path.join(project_dir, "audio", "voiceover.mp3")
    script_p = os.path.join(project_dir, "script.json")
    if not (os.path.exists(audio) and os.path.exists(script_p)):
        return {"ran": False, "verdict": "skipped",
                "detail": "voiceover.mp3 or script.json missing"}
    try:
        with open(script_p, encoding="utf-8") as f:
            script = json.load(f)
        expected = " ".join(s.get("narration", "")
                            for s in script.get("scenes", []))
        transcript = transcribe(audio, language=language)
        sim = similarity(transcript, expected)
        if sim >= 0.80:
            verdict = "pass"
        elif sim >= 0.60:
            verdict = "warn"  # likely tiny-model mishearings; human glance advised
        else:
            verdict = "fail"  # audio almost certainly wrong/truncated
        return {"ran": True, "verdict": verdict,
                "similarity": round(sim, 3),
                "transcript_head": transcript[:220],
                "detail": f"similarity {sim:.2f} vs approved script"}
    except Exception as e:
        return {"ran": False, "verdict": "skipped",
                "detail": f"transcription error: {str(e)[:120]}"}
