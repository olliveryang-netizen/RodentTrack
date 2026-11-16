#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate synthetic test videos with known ground truth.

The videos imitate a real top-view recording: a tilted camera (perspective), a white animal on a
dark floor, a static glare spot, a moving reflection on the glossy wall, flicker and pixel noise.
For each video a ready-to-use config (.json) and the true exploration time per object (.truth.json)
are written, so you can check RodentTrack on your own computer:

    python examples/demo/make_demo_videos.py                 # all three kinds, 60 s each
    python examples/demo/make_demo_videos.py --kind nor2 --secs 20
    python mouse_tracker.py analyze examples/demo/demo_nor2.mp4 -c examples/demo/demo_nor2.json -o results

kinds: nor2 (novel object recognition, 2 objects), nor4 (4 objects), social (two wire cages,
a stimulus animal in the right one).
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import mouse_tracker as mt  # noqa: E402

W = H = 40.0                                                       # arena floor, cm
SRC = np.float32([[80, 40], [560, 45], [580, 450], [60, 445]])     # floor corners in the 640x480 image
M = cv2.getPerspectiveTransform(np.float32([[0, 0], [W, 0], [W, H], [0, H]]), SRC)

KINDS = {
    #          zones: (shape, centre cm, radius/half-size cm, name)          preferred zone, comparisons
    "nor2": ([("circle", (12, 12), 2.5, "Familiar"), ("circle", (28, 28), 2.5, "Novel")], 1, [["Familiar", "Novel"]]),
    "nor4": ([("circle", (10, 10), 2.5, "A"), ("circle", (30, 10), 2.5, "B"),
              ("circle", (10, 30), 2.5, "C"), ("circle", (30, 30), 2.5, "D")], 2, [["A", "C"], ["B", "D"]]),
    "social": ([("rect", (8, 20), 4.0, "Empty"), ("rect", (32, 20), 4.0, "Social")], 1, [["Empty", "Social"]]),
}


def px(p):
    return cv2.perspectiveTransform(np.float32(p).reshape(-1, 1, 2), M).reshape(-1, 2)


def keep_out(c, objs, half_width=1.8):
    """A real animal walks around objects and cages, not through them."""
    for typ, cc, r, _ in objs:
        d = c - np.array(cc, float)
        if typ == "circle":
            n = np.linalg.norm(d)
            if n < r + half_width:
                c = np.array(cc) + (d / n if n > 1e-6 else np.array([1.0, 0])) * (r + half_width)
        else:
            h = r + .3 + half_width
            if np.max(np.abs(d)) < h:
                k = int(np.argmax(np.abs(d)))
                d[k] = math.copysign(h, d[k] if d[k] != 0 else 1.0)
                c = np.array(cc) + d
    return c


def free_goal(objs, rng):
    """A random walking goal that is not on an object or cage."""
    while True:
        g = rng.uniform(5, 35, 2)
        if np.allclose(keep_out(g, objs, half_width=3.5), g):
            return g


def simulate_path(objs, pref, n, fps, rng):
    """Wander, walk to objects and sniff them with the nose pointing at the object."""
    c = np.array([20.0, 35.0])
    th = -math.pi / 2
    visits = [pref] * 5 + [i for i in range(len(objs)) if i != pref] * 2
    rng.shuffle(visits)
    vi, state, target, goal, dwell = 0, "pick", None, None, 0
    gt = []
    for _ in range(n):
        if state == "pick":
            if rng.random() < 0.6 and vi < len(visits):
                target, vi, state = visits[vi], vi + 1, "go_obj"
            else:
                goal, state = free_goal(objs, rng), "wander"
        if state == "go_obj":
            o = objs[target]
            d = np.array(o[1]) - c
            dist = np.linalg.norm(d)
            if dist <= o[2] + 3.5 + 0.8:
                state, dwell = "dwell", int(rng.uniform(1.0, 3.0) * fps)
            else:
                th = math.atan2(d[1], d[0])
                c = c + 12 / fps * d / dist
        elif state == "dwell":
            d = np.array(objs[target][1]) - c
            th = math.atan2(d[1], d[0]) + rng.normal(0, 0.15)
            dwell -= 1
            if dwell <= 0:
                goal, state = free_goal(objs, rng), "wander"
        elif state == "wander":
            d = goal - c
            dist = np.linalg.norm(d)
            if dist < 1:
                state = "pick"
            else:
                th = math.atan2(d[1], d[0])
                c = c + 15 / fps * d / dist
        c = np.clip(c, 3.5, W - 3.5)
        c2 = keep_out(c, objs)
        if state == "wander" and not np.allclose(c2, c):
            state = "pick"   # bumped into an object: choose a new goal
        c = c2
        gt.append((c.copy(), c + 3.5 * np.array([math.cos(th), math.sin(th)]), th))
    return gt


def render(kind, objs, gt, out, fps, rng):
    tmp = out + ".tmp.mp4"
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480))
    floor = np.full((480, 640), 18, np.uint8)
    cv2.fillPoly(floor, [np.int32(SRC)], 30)
    cv2.circle(floor, (430, 360), 16, 250, -1)            # static glare on the floor
    floor = cv2.GaussianBlur(floor, (7, 7), 0)
    stim = np.array([32.0, 20.0])
    for f, (c, nose, th) in enumerate(gt):
        img = (floor.astype(np.int16) + int(4 * math.sin(f / 15))).clip(0, 255).astype(np.uint8)   # flicker
        for typ, cc, r, _ in objs:
            if typ == "circle":
                cv2.circle(img, tuple(np.int32(px([cc])[0])), int(r * 12), 90, -1)
            else:
                q = px([[cc[0] - r, cc[1] - r], [cc[0] + r, cc[1] - r], [cc[0] + r, cc[1] + r], [cc[0] - r, cc[1] + r]])
                cv2.polylines(img, [np.int32(q)], True, 200, 2)
                for k in range(1, 8):                     # wire mesh
                    a = q[0] + (q[1] - q[0]) * k / 8
                    b = q[3] + (q[2] - q[3]) * k / 8
                    cv2.line(img, tuple(np.int32(a)), tuple(np.int32(b)), 140, 1)
        if kind == "social":                              # stimulus animal inside the right cage
            stim = np.clip(stim + rng.normal(0, 0.3, 2), [29.5, 17.5], [34.5, 22.5])
            p = px([stim])[0]
            cv2.ellipse(img, (int(p[0]), int(p[1])), (30, 13), (f * 2) % 180, 0, 360, 235, -1)
        body = [c + np.array([3.5 * math.cos(a) * math.cos(th) - 1.6 * math.sin(a) * math.sin(th),
                              3.5 * math.cos(a) * math.sin(th) + 1.6 * math.sin(a) * math.cos(th)])
                for a in np.linspace(0, 2 * math.pi, 40)]
        cv2.fillPoly(img, [np.int32(px(body))], 235)
        tail = np.int32(px([c - 3.3 * np.array([math.cos(th), math.sin(th)]),
                            c - 9 * np.array([math.cos(th + 0.3), math.sin(th + 0.3)])]))
        cv2.line(img, tuple(tail[0]), tuple(tail[1]), 200, 2)
        g = px([c])[0]                                    # moving reflections on the wall (outside the floor)
        cv2.ellipse(img, (int(g[0]), int(min(38, g[1] * 0.08 + 8))), (30, 8), 0, 0, 360, 150, -1)
        cv2.ellipse(img, (int(max(5, min(55, g[0] * 0.08))), int(g[1])), (6, 26), 0, 0, 360, 140, -1)
        img = (img.astype(np.int16) + rng.normal(0, 3, img.shape)).clip(0, 255).astype(np.uint8)
        vw.write(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    vw.release()
    ff = shutil.which("ffmpeg")
    if ff:   # smaller H.264 file that plays everywhere
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", tmp, "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "26", "-pix_fmt", "yuv420p", out])
        if r.returncode == 0:
            os.remove(tmp)
            return
    os.replace(tmp, out)


def make(kind, out, secs=60, fps=30, seed=1):
    objs, pref, comps = KINDS[kind]
    rng = np.random.default_rng(seed)
    n = int(secs * fps)
    gt = simulate_path(objs, pref, n, fps, rng)
    render(kind, objs, gt, out, fps, rng)

    zones = []
    for typ, cc, r, name in objs:
        if typ == "circle":
            zones.append({"name": name, "type": "object", "shape": "circle", "center": px([cc])[0].tolist(),
                          "radius": r * 12, "interaction_cm": 2.0})
        else:
            q = px([[cc[0] - r - .3, cc[1] - r - .3], [cc[0] + r + .3, cc[1] - r - .3],
                    [cc[0] + r + .3, cc[1] + r + .3], [cc[0] - r - .3, cc[1] + r + .3]])
            zones.append({"name": name, "type": "cage", "shape": "polygon", "points": q.tolist(), "interaction_cm": 3.0})
    cfg = mt.fill_defaults({"arena": {"points": SRC.tolist(), "width_cm": W, "height_cm": H},
                            "zones": zones, "exclude": [], "comparisons": comps})

    truth = {}   # nose within the contact zone and body centre not on the object
    for typ, cc, r, name in objs:
        m = 2.0 if typ == "circle" else 3.0
        if typ == "circle":
            near = [np.linalg.norm(no - cc) <= r + m and np.linalg.norm(c - cc) > r for c, no, _ in gt]
        else:
            h = r + .3   # the cage zone is drawn 0.3 cm outside the cage outline (same as the config)
            near = [np.max(np.abs(no - cc)) <= h + m and np.max(np.abs(c - cc)) > h for c, no, _ in gt]
        truth[name] = round(float(sum(near)) / fps, 2)
    track = np.array([[c[0], c[1], no[0], no[1]] for c, no, _ in gt])
    return cfg, truth, track


def main():
    ap = argparse.ArgumentParser(description="Generate synthetic demo videos with ground truth")
    ap.add_argument("--kind", choices=list(KINDS) + ["all"], default="all")
    ap.add_argument("--secs", type=float, default=60)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default=HERE, help="output folder (default: examples/demo)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for kind in (KINDS if a.kind == "all" else [a.kind]):
        base = os.path.join(a.out, f"demo_{kind}")
        cfg, truth, track = make(kind, base + ".mp4", a.secs, a.fps)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        with open(base + ".truth.json", "w", encoding="utf-8") as f:
            json.dump({"explore_s": truth, "secs": a.secs, "fps": a.fps}, f, indent=2)
        np.save(base + ".track_cm.npy", track)
        print(f"{base}.mp4  true exploration time (s): {truth}")


if __name__ == "__main__":
    main()
