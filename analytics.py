#!/usr/bin/env python3
"""Honest analytics — Content Engine v2 (master doc stage K).

No platform API integrations (they need app review/approval). Performance is
entered MANUALLY from YouTube Studio / TikTok / Instagram insights:

    python3 analytics.py add --project demo-001 --platform youtube_shorts \\
        --views 1200 --retention 38 --likes 45 --comments 6

`report` aggregates across projects, compares platforms, and derives up to 3
concrete recommendations FROM THE DATA. With <2 videos of data it says so
plainly instead of inventing insight.

Usage:
    python3 analytics.py add --project ID --platform NAME --views N
        [--retention PCT] [--likes N] [--comments N] [--notes "..."] [--date YYYY-MM-DD]
    python3 analytics.py report [--json]
"""
import argparse
import datetime
import json
import os
import sys

BASE = os.path.expanduser("~/workspace/content-engine")
PROJECTS = os.path.join(BASE, "projects")
PLATFORMS = ["youtube_shorts", "instagram_reels", "tiktok", "facebook_reels"]


def apath(pid):
    return os.path.join(PROJECTS, pid, "analytics.json")


def load_entries(pid):
    p = apath(pid)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("entries", [])
    return []


def project_meta(pid):
    meta = {"project": pid}
    for fn in ("manifest.json", "qc_report.json", "script.json"):
        fp = os.path.join(PROJECTS, pid, fn)
        if os.path.exists(fp):
            try:
                with open(fp, encoding="utf-8") as f:
                    d = json.load(f)
                if fn == "qc_report.json":
                    meta["qc_score"] = d.get("score")
                elif fn == "script.json":
                    sc = d.get("scenes", [])
                    meta["scenes"] = len(sc)
                    if sc:
                        meta["hook_chars"] = len(sc[0].get("narration", ""))
            except Exception:
                pass
    vp = os.path.join(PROJECTS, pid, "final.mp4")
    if os.path.exists(vp):
        try:
            import subprocess
            r = subprocess.run(["ffprobe", "-v", "error",
                                "-show_entries", "format=duration",
                                "-of", "csv=p=0", vp],
                               capture_output=True, text=True, timeout=30)
            meta["duration_s"] = round(float(r.stdout.strip()), 1)
        except Exception:
            pass
    return meta


def cmd_add(a):
    d = os.path.join(PROJECTS, a.project)
    if not os.path.isdir(d):
        sys.exit(f"unknown project: {a.project}")
    if a.platform not in PLATFORMS:
        sys.exit(f"platform must be one of {PLATFORMS}")
    entries = load_entries(a.project)
    entries.append({
        "date": a.date or datetime.date.today().isoformat(),
        "platform": a.platform,
        "views": a.views,
        "avg_retention_pct": a.retention,
        "likes": a.likes or 0,
        "comments": a.comments or 0,
        "notes": a.notes or "",
    })
    with open(apath(a.project), "w", encoding="utf-8") as f:
        json.dump({"project": a.project, "entries": entries}, f, indent=2)
    print(f"[analytics] logged {a.platform} {a.views} views for {a.project}")


def pct(n):
    return f"{n:.1f}%"


def cmd_report(a):
    projects = sorted(os.path.isdir(os.path.join(PROJECTS, p))
                      for p in [os.path.join(PROJECTS, x)
                                for x in os.listdir(PROJECTS)])
    pids = sorted(d for d in os.listdir(PROJECTS)
                  if os.path.isdir(os.path.join(PROJECTS, d)))
    rows = []
    for pid in pids:
        for e in load_entries(pid):
            r = dict(e)
            r.update(project_meta(pid))
            rows.append(r)

    report = {"generated": datetime.datetime.now(
        datetime.timezone.utc).isoformat(),
        "videos_with_data": len({r["project"] for r in rows}),
        "total_entries": len(rows)}

    if len({r["project"] for r in rows}) < 2:
        report["status"] = "insufficient_data"
        report["recommendations"] = [
            "Log at least 2 videos' performance (views + retention per "
            "platform) before expecting recommendations — one data point is "
            "an anecdote, not a pattern.",
            "When logging, always include avg_retention_pct: it is the "
            "metric most correlated with algorithmic distribution on "
            "Shorts/Reels/TikTok.",
            "Keep video duration in the 30–45s band for the next 3 videos "
            "so duration is controlled while you test hooks and topics.",
        ]
        out = json.dumps(report, indent=2)
        print(out)
        return

    # per-platform aggregates
    by_plat = {}
    for r in rows:
        p = by_plat.setdefault(r["platform"], {"views": [], "ret": []})
        p["views"].append(r["views"])
        if r.get("avg_retention_pct") is not None:
            p["ret"].append(r["avg_retention_pct"])
    plat_stats = {p: {"avg_views": round(sum(v["views"]) / len(v["views"])),
                      "avg_retention_pct": round(sum(v["ret"]) / len(v["ret"]), 1)
                      if v["ret"] else None,
                      "n": len(v["views"])}
                  for p, v in by_plat.items()}
    report["by_platform"] = plat_stats

    # duration vs retention (videos with both)
    dr = [(r["duration_s"], r["avg_retention_pct"], r["project"]) for r in rows
          if r.get("duration_s") and r.get("avg_retention_pct") is not None]
    recs = []
    if len(dr) >= 2:
        dr.sort()
        short, long = dr[0], dr[-1]
        if short[1] > long[1]:
            recs.append(
                f"Shorter holds better: {short[2]} ({short[0]:.0f}s) retained "
                f"{pct(short[1])} vs {long[2]} ({long[0]:.0f}s) at {pct(long[1])}. "
                f"Keep the next video under {short[0]:.0f}s and re-test.")
        elif long[1] > short[1]:
            recs.append(
                f"Longer holds better here: {long[2]} ({long[0]:.0f}s) retained "
                f"{pct(long[1])} vs {short[2]} at {pct(short[1])}. Topic depth may "
                f"be beating brevity — try a 50–60s version next.")
        else:
            recs.append("Duration shows no clear retention link yet — vary the "
                        "hook instead of the length for the next 2 videos.")
    # platform pick
    ranked = sorted(((p, s["avg_retention_pct"] or 0) for p, s in
                     plat_stats.items() if s["avg_retention_pct"] is not None),
                    key=lambda x: -x[1])
    if ranked:
        best, best_r = ranked[0]
        recs.append(f"Best retention so far: {best} ({pct(best_r)} avg). "
                    f"Publish the next video there first; treat others as "
                    f"repurposed distribution.")
    # hook length proxy
    hk = [(r.get("hook_chars", 0), r.get("avg_retention_pct"), r["project"])
          for r in rows if r.get("avg_retention_pct") is not None]
    if len(hk) >= 2:
        hk.sort()
        if hk[0][1] > hk[-1][1] and hk[0][0] < hk[-1][0]:
            recs.append(f"Tighter hooks win: {hk[0][2]} opened with "
                        f"{hk[0][0]} chars and retained {pct(hk[0][1])}. Keep "
                        f"scene-1 narration under ~120 characters.")
    while len(recs) < 3:
        recs.append("Not enough variation in the data for a third finding — "
                    "change ONE variable (hook, topic, or duration) next video.")
    report["status"] = "ok"
    report["recommendations"] = recs[:3]
    print(json.dumps(report, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--project", required=True)
    p.add_argument("--platform", required=True)
    p.add_argument("--views", type=int, required=True)
    p.add_argument("--retention", type=float, default=None)
    p.add_argument("--likes", type=int, default=0)
    p.add_argument("--comments", type=int, default=0)
    p.add_argument("--notes", default="")
    p.add_argument("--date", default="")
    p = sub.add_parser("report")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "add":
        cmd_add(a)
    else:
        cmd_report(a)


if __name__ == "__main__":
    main()
