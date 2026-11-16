#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RodentTrack — video tracking for rodent behaviour tests (mouse_tracker.py)

Tasks: novel object recognition (2 objects), object placement / object-in-place (4 objects),
two-cage social interaction (live stimulus animal inside a wire cage), open-field centre time.

Sub-commands
  setup    draw the arena, objects, wire cages and areas to ignore on a video frame -> JSON config
  tune     same window as setup (regions and threshold are set together)
  analyze  analyse one video (mp4 / mov / avi ...)
  batch    analyse every video in a folder with one config -> summary_all.csv

Examples
  python mouse_tracker.py setup   video1.mp4 -c nor.json --arena-w 40 --arena-h 40
  python mouse_tracker.py analyze video1.mp4 -c nor.json -o results --video
  python mouse_tracker.py batch   D:/videos  -c nor.json -o results
  python mouse_tracker.py --lang en analyze video1.mp4 -c nor.json

Run without arguments (double-click, or F5 in IDLE) to open the graphical interface.
"""
import argparse
import copy
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n  # noqa: E402
from i18n import T  # noqa: E402

__version__ = "1.0.0"

if __name__ == "__main__" and len(sys.argv) == 1:   # double-click / F5 in IDLE: open the GUI (the GUI itself does not need cv2)
    import mouse_tracker_gui
    mouse_tracker_gui.main()
    sys.exit(0)

import numpy as np  # noqa: E402
import cv2  # noqa: E402

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".m4v", ".mkv", ".wmv")

DEFAULT_DETECTION = {
    "polarity": "bright",      # bright: white animal on dark floor (default); dark: dark animal on light floor; both; absolute: brightness threshold, no background
    "threshold": 30,           # grey-level difference from the background (0-255); brightness threshold in absolute mode
    "blur": 5,                 # Gaussian blur kernel (odd, 0 = off) against pixel noise
    "open_kernel": 5,          # morphological opening: removes the tail and small reflections
    "close_kernel": 5,         # morphological closing: fills holes inside the body
    "min_area_cm2": 2.0,       # smallest animal area (cm2); smaller blobs are noise
    "max_area_cm2": 60.0,      # largest animal area (cm2); larger blobs are glare
    "clahe": False,            # local contrast enhancement (uneven lighting)
    "bg_frames": 50,           # frames used for the median background (the moving animal disappears)
    "exclude_cages": True,     # ignore the inside of wire cages (the stimulus animal is not tracked)
    "body_open_cm": 1.0,       # kernel used to strip the tail when finding head/tail (mouse ~1, rat ~2)
    "proc_width": 960,         # frames are downscaled to this width before analysis (fast, accurate enough)
}
DEFAULT_ANALYSIS = {
    "start_s": 0.0,            # start of analysis (skip placing the animal)
    "end_s": None,             # end of analysis (None = end of video), e.g. 300 = first 5 min
    "smooth_frames": 5,        # median filter window for the track (frames)
    "max_gap_frames": 15,      # gaps shorter than this are linearly interpolated
    "min_bout_s": 0.2,         # bouts shorter than this are not counted
    "merge_gap_s": 0.2,        # bouts separated by less than this are merged
    "center_ratio": 0.5,       # centre zone as a fraction of the arena side (open field)
    "immobile_speed_cm_s": 2.0,
    "immobile_min_s": 1.0,
    "exclude_climbing": True,  # body centre on the object (climbing) is not exploration
    "heading_deg": None,       # optional: head must point to the object within this angle (e.g. 45)
    "fps_override": None,      # set manually if the phone video reports a wrong frame rate
    "bin_s": 60,               # length of time bins (s), e.g. 60 = per minute
}
DEFAULT_MARGIN_CM = {"object": 2.0, "cage": 3.0}

COL = {"object": (60, 220, 60), "cage": (0, 150, 255), "arena": (255, 255, 0),
       "exclude": (60, 60, 255), "animal": (255, 0, 255), "nose": (0, 255, 255)}


# --------------------------------------------------------------------------- config
def fill_defaults(cfg):
    cfg.setdefault("arena", None)
    cfg.setdefault("zones", [])
    cfg.setdefault("exclude", [])
    cfg.setdefault("comparisons", None)
    for key, d in (("detection", DEFAULT_DETECTION), ("analysis", DEFAULT_ANALYSIS)):
        cfg.setdefault(key, {})
        for k, v in d.items():
            cfg[key].setdefault(k, v)
    for z in cfg["zones"]:
        z.setdefault("type", "object")
        z.setdefault("interaction_cm", DEFAULT_MARGIN_CM.get(z["type"], 2.0))
    return cfg


def load_config(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return fill_defaults(json.load(f))
    return fill_defaults({})


def save_config(cfg, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(T("[已保存] {p}", p=path))


def is_example_config(path):
    p = (path or "").replace("\\", "/")
    return "/examples/configs/" in p or "/examples/demo/" in p


# --------------------------------------------------------------------------- video
def open_video(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(T("无法打开视频: {p}（若是 iPhone HEVC 的 .mov，可先用 ffmpeg 转 H.264）", p=path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    return cap, fps, n


def read_frame_at(cap, idx):
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(idx)))
    ok, f = cap.read()
    return f if ok else None


def scale_cfg(cfg, s):
    """Convert pixel coordinates in the config (original resolution) to the downscaled resolution."""
    c = copy.deepcopy(cfg)
    if s == 1:
        return c

    def sc(z):
        if "center" in z:
            z["center"] = [v * s for v in z["center"]]
        if "radius" in z:
            z["radius"] = z["radius"] * s
        if "points" in z:
            z["points"] = [[x * s, y * s] for x, y in z["points"]]
    if c.get("arena"):
        sc(c["arena"])
    for z in c.get("zones", []) + c.get("exclude", []):
        sc(z)
    return c


def proc_scale(det_cfg, width):
    pw = det_cfg.get("proc_width") or 0
    return min(1.0, float(pw) / width) if pw else 1.0


def median_background(cap, start_f, end_f, n_samples, size=None):
    """Median of many frames: the moving animal is not in the median, while fixed glare,
    objects and cages are, so they cancel out when the background is subtracted."""
    end_f = max(start_f + 1, end_f)
    idxs = np.linspace(start_f, end_f - 1, num=max(3, int(n_samples))).astype(int)
    frames = []
    for i in np.unique(idxs):
        f = read_frame_at(cap, i)
        if f is not None:
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            frames.append(cv2.resize(g, size, interpolation=cv2.INTER_AREA) if size else g)
    if not frames:
        raise RuntimeError(T("读取不到视频帧，无法生成背景"))
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


# --------------------------------------------------------------------------- geometry
def shape_mask(z, hw):
    m = np.zeros(hw, np.uint8)
    s = z["shape"]
    if s == "circle":
        c = tuple(int(round(v)) for v in z["center"])
        cv2.circle(m, c, int(round(z["radius"])), 255, -1)
    elif s == "rect":
        (x1, y1), (x2, y2) = z["points"]
        cv2.rectangle(m, (int(min(x1, x2)), int(min(y1, y2))), (int(max(x1, x2)), int(max(y1, y2))), 255, -1)
    else:
        cv2.fillPoly(m, [np.int32(np.round(z["points"]))], 255)
    return m


def arena_scale(arena):
    p = np.float32(arena["points"])
    W, H = arena["width_cm"], arena["height_cm"]
    sides = [np.linalg.norm(p[1] - p[0]) / W, np.linalg.norm(p[2] - p[3]) / W,
             np.linalg.norm(p[3] - p[0]) / H, np.linalg.norm(p[2] - p[1]) / H]
    return float(np.mean(sides))


class Geometry:
    """Turns the config into pixel masks; the 4 arena corners give a perspective transform to cm
    (a slightly tilted camera is fine)."""

    def __init__(self, cfg, hw):
        if not cfg.get("arena"):
            raise RuntimeError(T("配置里没有场地四角(arena)，请先运行 setup"))
        self.hw = hw
        a = cfg["arena"]
        self.W, self.H = float(a["width_cm"]), float(a["height_cm"])
        src = np.float32(a["points"])
        dst = np.float32([[0, 0], [self.W, 0], [self.W, self.H], [0, self.H]])
        self.M = cv2.getPerspectiveTransform(src, dst)
        self.px_per_cm = arena_scale(a)
        self.arena_mask = np.zeros(hw, np.uint8)
        cv2.fillPoly(self.arena_mask, [np.int32(np.round(src))], 255)
        excl = np.zeros(hw, np.uint8)
        for e in cfg["exclude"]:
            excl |= shape_mask(e, hw)
        self.zones = []
        for z in cfg["zones"]:
            m = shape_mask(z, hw)
            r = int(round(float(z.get("interaction_cm", 2.0)) * self.px_per_cm))
            near = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) if r > 0 else m.copy()
            mo = cv2.moments(m)
            cx, cy = (mo["m10"] / mo["m00"], mo["m01"] / mo["m00"]) if mo["m00"] else (0, 0)
            self.zones.append(dict(name=z["name"], type=z["type"], mask=m, near=near, center=(cx, cy),
                                   cnt=cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2],
                                   near_cnt=cv2.findContours(near, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]))
            if z["type"] == "cage" and cfg["detection"].get("exclude_cages", True):
                excl |= m
        self.exclude_cnt = cv2.findContours(excl, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
        self.detect_mask = cv2.bitwise_and(self.arena_mask, cv2.bitwise_not(excl))
        self.arena_pts = np.int32(np.round(src))

    def to_cm(self, xy):
        xy = np.asarray(xy, np.float64).reshape(-1, 1, 2)
        out = np.full(xy.shape, np.nan)
        ok = ~np.isnan(xy).any(axis=2).ravel()
        if ok.any():
            out[ok] = cv2.perspectiveTransform(xy[ok].astype(np.float32), self.M)
        return out.reshape(-1, 2)

    def draw(self, img, active=None):
        t = max(1, int(round(img.shape[1] / 640)))
        cv2.polylines(img, [self.arena_pts], True, COL["arena"], t)
        cv2.drawContours(img, self.exclude_cnt, -1, COL["exclude"], t)
        for z in self.zones:
            c = COL[z["type"]]
            hit = active is not None and active.get(z["name"], False)
            cv2.drawContours(img, z["cnt"], -1, c, t + 1)
            cv2.drawContours(img, z["near_cnt"], -1, (255, 255, 255) if hit else c, t * (2 if hit else 1))
            cv2.putText(img, z["name"], (int(z["center"][0]) - 20, int(z["center"][1]) + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45 * t, c, t)
        return img


# --------------------------------------------------------------------------- detection
def odd(k):
    k = int(k)
    return 0 if k <= 0 else (k if k % 2 else k + 1)


class Detector:
    def __init__(self, det, geom, bg_raw):
        self.d = det
        self.g = geom
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)) if det.get("clahe") else None
        self.bg = self.prep(bg_raw) if bg_raw is not None else None
        ppc2 = geom.px_per_cm ** 2
        self.amin = det["min_area_cm2"] * ppc2
        self.amax = det["max_area_cm2"] * ppc2
        ko, kc = odd(det["open_kernel"]), odd(det["close_kernel"])
        self.ko = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ko, ko)) if ko else None
        self.kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kc, kc)) if kc else None
        kb = odd(det.get("body_open_cm", 1.0) * geom.px_per_cm)
        self.kb = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kb, kb)) if kb >= 3 else None
        self.tail_px = 0.15 * ppc2   # the removed part must exceed 0.15 cm2 to count as a visible tail

    def prep(self, gray):
        if self.clahe is not None:
            gray = self.clahe.apply(gray)
        b = odd(self.d["blur"])
        return cv2.GaussianBlur(gray, (b, b), 0) if b else gray

    def diff_image(self, frame):
        g = self.prep(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        pol = self.d["polarity"]
        if pol == "absolute" or self.bg is None:
            return g
        if pol == "bright":
            return cv2.subtract(g, self.bg)
        if pol == "dark":
            return cv2.subtract(self.bg, g)
        return cv2.absdiff(g, self.bg)

    def detect(self, frame):
        diff = self.diff_image(frame)
        _, m = cv2.threshold(diff, int(self.d["threshold"]), 255, cv2.THRESH_BINARY)
        m = cv2.bitwise_and(m, self.g.detect_mask)
        if self.ko is not None:
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, self.ko)
        if self.kc is not None:
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, self.kc)
        cnts = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[-2]
        best, best_a = None, 0
        for c in cnts:
            a = cv2.contourArea(c)
            if self.amin <= a <= self.amax and a > best_a:
                best, best_a = c, a
        if best is None:
            return None, m, diff
        return self.body_parts(best, best_a), m, diff

    def body_parts(self, cnt, area):
        """Body without the tail: an opening with a ~1-cm disc removes the thin tail and keeps the body.
        Centre, main axis and both ends are measured on the body; the end where the removed pixels lie is the tail."""
        x, y, w, h = cv2.boundingRect(cnt)
        pad = 2
        blob = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
        cv2.drawContours(blob, [cnt - (x - pad, y - pad)], -1, 255, -1)
        core = blob
        if self.kb is not None:
            c2 = cv2.morphologyEx(blob, cv2.MORPH_OPEN, self.kb)
            n_lab, lab, stats, _ = cv2.connectedComponentsWithStats(c2)
            if n_lab > 1:
                core = np.where(lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA]), 255, 0).astype(np.uint8)
        ys, xs = np.nonzero(core)
        pts = np.column_stack([xs, ys]).astype(np.float64)
        c = pts.mean(0)
        d = pts - c
        if len(pts) >= 5:
            ev, evec = np.linalg.eigh(np.cov(d.T))
            axis = evec[:, np.argmax(ev)]
        else:
            axis = np.array([1.0, 0.0])
        proj = d @ axis
        ends = [pts[np.argmax(proj)], pts[np.argmin(proj)]]
        # tail evidence: removed pixels that lie beyond either end of the body
        ry, rx = np.nonzero((blob > 0) & (core == 0))
        rp = (np.column_stack([rx, ry]) - c) @ axis if len(rx) else np.array([])
        tail = (float((rp > proj.max() * 0.6).sum()), float((rp < proj.min() * 0.6).sum()))
        off = np.array([x - pad, y - pad], np.float64)
        c = c + off
        ends = (ends[0] + off, ends[1] + off)
        return dict(cx=c[0], cy=c[1], area=area, contour=cnt, ends=ends, axis=axis, tail=tail)


def choose_nose(r, prev_nose, vel, fast, tail_px):
    """Pick the nose among the two ends of the body axis, in this order:
    1) moving fast along the body axis -> the leading end;
    2) tail visible -> the end opposite the tail;
    3) otherwise -> the end closer to the previous nose (temporal continuity)."""
    e1, e2 = r["ends"]
    c = np.array([r["cx"], r["cy"]])
    if vel is not None and fast:
        cosv = abs(np.dot(vel, r["axis"])) / (np.linalg.norm(vel) + 1e-9)
        if cosv > 0.6:
            return e1 if np.dot(e1 - c, vel) >= np.dot(e2 - c, vel) else e2
    t1, t2 = r["tail"]
    if max(t1, t2) > tail_px and max(t1, t2) > 3 * min(t1, t2):
        return e2 if t1 > t2 else e1
    if prev_nose is not None:
        return e1 if np.linalg.norm(e1 - prev_nose) <= np.linalg.norm(e2 - prev_nose) else e2
    return e1


# --------------------------------------------------------------------------- time-series helpers
def fill_short_gaps(a, max_gap):
    a = a.copy()
    isn = np.isnan(a)
    if max_gap <= 0 or isn.all() or not isn.any():
        return a
    for s, e in runs_of(isn):
        if s > 0 and e < len(a) and (e - s) <= max_gap:
            a[s:e] = np.interp(np.arange(s, e), [s - 1, e], [a[s - 1], a[e]])
    return a


def rolling_median(a, w):
    if w <= 1:
        return np.array(a, float)
    import pandas as pd
    return np.array(pd.Series(a).rolling(int(w), center=True, min_periods=1).median(), dtype=float)


def runs_of(b):
    b = np.asarray(b, bool).astype(np.int8)
    d = np.diff(np.concatenate([[0], b, [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def clean_bouts(b, fps, min_s, merge_s):
    b = np.asarray(b, bool).copy()
    g = int(round(merge_s * fps))
    if g > 0:
        for s, e in runs_of(~b):
            if s > 0 and e < len(b) and e - s <= g:
                b[s:e] = True
    m = int(round(min_s * fps))
    for s, e in runs_of(b):
        if e - s < m:
            b[s:e] = False
    return b, runs_of(b)


def lookup(mask, xs, ys):
    h, w = mask.shape
    out = np.zeros(len(xs), bool)
    ok = ~(np.isnan(xs) | np.isnan(ys))
    xi = np.clip(np.round(xs[ok]).astype(int), 0, w - 1)
    yi = np.clip(np.round(ys[ok]).astype(int), 0, h - 1)
    out[ok] = mask[yi, xi] > 0
    return out


# --------------------------------------------------------------------------- analysis
def analyze_video(path, cfg, outdir, save_video=False, verbose=True):
    import pandas as pd
    det_cfg, an = cfg["detection"], cfg["analysis"]
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    cap, fps, n = open_video(path)
    if an.get("fps_override"):
        fps = float(an["fps_override"])
    if not fps or fps <= 0 or fps > 1000:
        fps = 30.0
        print(T("  ! 读不到帧率，按 30 fps 计算(可在配置 analysis.fps_override 指定)"))
    start_f = int(round(an["start_s"] * fps))
    end_f = n if an.get("end_s") in (None, "", 0) else min(n, int(round(an["end_s"] * fps)))
    if n <= 0:
        end_f = int(1e9)
    first = read_frame_at(cap, start_f)
    if first is None:
        raise RuntimeError(T("起始帧读取失败"))
    ps = proc_scale(det_cfg, first.shape[1])
    hw = (int(round(first.shape[0] * ps)), int(round(first.shape[1] * ps)))
    size = (hw[1], hw[0]) if ps < 1 else None
    geom = Geometry(scale_cfg(cfg, ps), hw)
    bg = median_background(cap, start_f, min(end_f, n if n > 0 else start_f + 3000), det_cfg["bg_frames"], size)
    cv2.imwrite(os.path.join(outdir, f"{base}_background.png"), bg)
    det = Detector(det_cfg, geom, bg)

    writer = None
    if save_video:
        writer = cv2.VideoWriter(os.path.join(outdir, f"{base}_annotated.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), fps, (hw[1], hw[0]))
    fast_px = 8.0 * geom.px_per_cm / fps   # moving forward = > 8 cm/s on average over 0.3 s
    win = max(3, int(round(0.3 * fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
    cx, cy, nx, ny, area = [], [], [], [], []
    prev_nose, hist = None, []
    f = start_f
    total = (end_f - start_f) if n > 0 else 0
    t0, last_pct = time.time(), -1
    while f < end_f:
        ok, frame = cap.read()
        if not ok:
            break
        if size:
            frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        r, _, _ = det.detect(frame)
        if r is None:
            cx.append(np.nan); cy.append(np.nan); nx.append(np.nan); ny.append(np.nan); area.append(np.nan)
            hist.clear()
        else:
            c = np.array([r["cx"], r["cy"]])
            hist.append(c)
            hist[:] = hist[-win:]
            vel = (hist[-1] - hist[0]) if len(hist) >= 3 else None
            fast = vel is not None and np.linalg.norm(vel) / (len(hist) - 1) > fast_px
            nose = choose_nose(r, prev_nose, vel, fast, det.tail_px)
            prev_nose = nose
            cx.append(c[0]); cy.append(c[1]); nx.append(nose[0]); ny.append(nose[1]); area.append(r["area"])
        if writer is not None:
            vis = frame.copy()
            active = {}
            if r is not None:
                for z in geom.zones:
                    xi, yi = int(np.clip(nose[0], 0, hw[1] - 1)), int(np.clip(nose[1], 0, hw[0] - 1))
                    active[z["name"]] = z["near"][yi, xi] > 0
            geom.draw(vis, active)
            if r is not None:
                cv2.drawContours(vis, [r["contour"]], -1, COL["animal"], 2)
                cv2.circle(vis, (int(c[0]), int(c[1])), 4, COL["animal"], -1)
                cv2.circle(vis, (int(nose[0]), int(nose[1])), 5, COL["nose"], -1)
            cv2.putText(vis, f"t={(f - start_f) / fps:7.2f}s", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            writer.write(vis)
        f += 1
        if verbose and total > 0:
            pct = int(100 * (f - start_f) / total)
            if pct // 10 != last_pct // 10:
                last_pct = pct
                print(T("  {b}: {p:3d}%  ({r:.0f} 帧/秒)", b=base, p=pct, r=(f - start_f) / max(1e-6, time.time() - t0)), flush=True)
    cap.release()
    if writer is not None:
        writer.release()

    nfr = len(cx)
    if nfr == 0:
        raise RuntimeError(T("没有读到任何帧"))
    cx, cy, nx, ny, area = (np.array(v, float) for v in (cx, cy, nx, ny, area))
    detected = ~np.isnan(cx)
    g = an["max_gap_frames"]
    w = an["smooth_frames"]
    cx_s = rolling_median(fill_short_gaps(cx, g), w)
    cy_s = rolling_median(fill_short_gaps(cy, g), w)
    nx_s = rolling_median(fill_short_gaps(nx, g), max(1, w // 2 * 2 - 1) if w > 2 else 1)
    ny_s = rolling_median(fill_short_gaps(ny, g), max(1, w // 2 * 2 - 1) if w > 2 else 1)
    for a in (cx_s, cy_s, nx_s, ny_s):   # long losses stay empty
        a[np.isnan(fill_short_gaps(cx, g))] = np.nan
    cm = geom.to_cm(np.column_stack([cx_s, cy_s]))
    ncm = geom.to_cm(np.column_stack([nx_s, ny_s]))
    step = np.r_[np.nan, np.linalg.norm(np.diff(cm, axis=0), axis=1)]
    speed = step * fps
    t = np.arange(nfr) / fps

    track = pd.DataFrame({"frame": np.arange(start_f, start_f + nfr), "time_s": t, "detected_raw": detected.astype(int),
                          "x_px": cx_s / ps, "y_px": cy_s / ps, "nose_x_px": nx_s / ps, "nose_y_px": ny_s / ps,
                          "x_cm": cm[:, 0], "y_cm": cm[:, 1], "nose_x_cm": ncm[:, 0], "nose_y_cm": ncm[:, 1],
                          "area_cm2": area / geom.px_per_cm ** 2, "speed_cm_s": speed})

    S = {"video": os.path.basename(path), "fps": round(fps, 3), "analyzed_s": round(nfr / fps, 2),
         "start_s": an["start_s"], "detect_rate_%": round(100 * detected.mean(), 1),
         "distance_cm": round(float(np.nansum(step)), 1),
         "mean_speed_cm_s": round(float(np.nansum(step)) / (nfr / fps), 2)}
    # open-field centre zone
    r = an["center_ratio"]
    inc = ((cm[:, 0] > geom.W * (1 - r) / 2) & (cm[:, 0] < geom.W * (1 + r) / 2) &
           (cm[:, 1] > geom.H * (1 - r) / 2) & (cm[:, 1] < geom.H * (1 + r) / 2))
    inc_c, inc_runs = clean_bouts(inc, fps, an["min_bout_s"], an["merge_gap_s"])
    track["in_center"] = inc_c.astype(int)
    S["center_time_s"] = round(inc_c.sum() / fps, 2)
    S["center_entries"] = len(inc_runs)
    imm = np.nan_to_num(speed, nan=0) < an["immobile_speed_cm_s"]
    imm_c, _ = clean_bouts(imm & ~np.isnan(speed), fps, an["immobile_min_s"], 0)
    S["immobile_time_s"] = round(imm_c.sum() / fps, 2)

    explore_t, zone_runs = {}, {}
    for z in geom.zones:
        name = z["name"]
        body_in = lookup(z["mask"], cx_s, cy_s)
        body_near = lookup(z["near"], cx_s, cy_s)
        nose_near = lookup(z["near"], nx_s, ny_s)
        expl = nose_near.copy()
        if an["exclude_climbing"]:
            expl &= ~body_in
        if an.get("heading_deg"):
            hv = np.column_stack([nx_s - cx_s, ny_s - cy_s])
            tv = np.column_stack([z["center"][0] - cx_s, z["center"][1] - cy_s])
            cosang = (hv * tv).sum(1) / (np.linalg.norm(hv, axis=1) * np.linalg.norm(tv, axis=1) + 1e-9)
            expl &= np.degrees(np.arccos(np.clip(cosang, -1, 1))) <= float(an["heading_deg"])
        expl_c, er = clean_bouts(expl, fps, an["min_bout_s"], an["merge_gap_s"])
        near_c, nr = clean_bouts(body_near, fps, an["min_bout_s"], an["merge_gap_s"])
        track[f"{name}_explore"] = expl_c.astype(int)
        track[f"{name}_zone"] = near_c.astype(int)
        track[f"{name}_on_top"] = body_in.astype(int)
        te = expl_c.sum() / fps
        explore_t[name] = te
        zone_runs[name] = er
        S[f"{name}_explore_s"] = round(te, 2)
        S[f"{name}_explore_bouts"] = len(er)
        S[f"{name}_explore_latency_s"] = round(er[0][0] / fps, 2) if er else np.nan
        S[f"{name}_mean_bout_s"] = round(te / len(er), 2) if er else 0.0
        S[f"{name}_zone_s"] = round(near_c.sum() / fps, 2)
        S[f"{name}_zone_entries"] = len(nr)
        S[f"{name}_on_top_s"] = round(body_in.sum() / fps, 2)
    tot = sum(explore_t.values())
    S["total_explore_s"] = round(tot, 2)
    for name, te in explore_t.items():
        S[f"{name}_explore_%"] = round(100 * te / tot, 1) if tot > 0 else np.nan
    comps = cfg.get("comparisons")
    if not comps and len(geom.zones) == 2:
        comps = [[geom.zones[0]["name"], geom.zones[1]["name"]]]
    for a_name, b_name in (comps or []):
        A, B = S.get(f"{a_name}_explore_s", np.nan), S.get(f"{b_name}_explore_s", np.nan)
        S[f"DI_{b_name}_vs_{a_name}"] = round((B - A) / (A + B), 3) if (A + B) > 0 else np.nan
        A2, B2 = S.get(f"{a_name}_zone_s", np.nan), S.get(f"{b_name}_zone_s", np.nan)
        S[f"zoneIndex_{b_name}_vs_{a_name}"] = round((B2 - A2) / (A2 + B2), 3) if (A2 + B2) > 0 else np.nan

    track.to_csv(os.path.join(outdir, f"{base}_track.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame([S]).to_csv(os.path.join(outdir, f"{base}_summary.csv"), index=False, encoding="utf-8-sig")
    rd = i18n.readable(S)
    pd.DataFrame({T("指标"): list(rd.keys()), T("数值"): list(rd.values())}).to_csv(
        os.path.join(outdir, i18n.result_file(base)), index=False, encoding="utf-8-sig")
    time_bins(track, step, fps, zone_runs, an.get("bin_s") or 60).to_csv(
        os.path.join(outdir, i18n.bins_file(base)), index=False, encoding="utf-8-sig")
    make_plots(base, outdir, bg, geom, cx_s, cy_s, cm)
    if detected.mean() < 0.9:
        print(T("  ! {b}: 只有 {p:.0f}% 的帧检测到动物，建议在设置窗口调阈值或检查排除区域", b=base, p=100 * detected.mean()))
    return S


def time_bins(track, step, fps, zone_runs, bin_s):
    import pandas as pd
    n = len(track)
    per = max(1, int(round(bin_s * fps)))
    rows = []
    for b0 in range(0, n, per):
        b1 = min(n, b0 + per)
        r = {T("时段"): f"{b0 / fps:.0f}-{b1 / fps:.0f}s",
             T("运动距离(cm)"): round(float(np.nansum(step[b0:b1])), 1),
             T("中心区时间(s)"): round(track["in_center"].iloc[b0:b1].sum() / fps, 2)}
        for name, runs in zone_runs.items():
            r[f"{name} " + T("接触次数")] = sum(1 for s, e in runs if b0 <= s < b1)
            r[f"{name} " + T("接触时间(s)")] = round(track[f"{name}_explore"].iloc[b0:b1].sum() / fps, 2)
        rows.append(r)
    return pd.DataFrame(rows)


def make_plots(base, outdir, bg, geom, cx, cy, cm):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # trajectory on the background (to check the regions and the detection)
    vis = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)
    geom.draw(vis)
    fig, ax = plt.subplots(figsize=(8, 8 * vis.shape[0] / vis.shape[1]))
    ax.imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
    ax.plot(cx, cy, "-", color="#e8336d", lw=0.8, alpha=0.8)
    ok = np.where(~np.isnan(cx))[0]
    if len(ok):
        ax.plot(cx[ok[0]], cy[ok[0]], "o", color="#36c46f", ms=7, label="start")
        ax.plot(cx[ok[-1]], cy[ok[-1]], "s", color="#ffd400", ms=7, label="end")
        ax.legend(loc="lower right", fontsize=8)
    ax.set_title(f"{base} trajectory")
    ax.axis("off")
    fig.savefig(os.path.join(outdir, f"{base}_trajectory.png"), dpi=130, bbox_inches="tight")
    plt.close(fig)
    # occupancy heatmap (cm coordinates, 1-cm grid)
    ok = ~np.isnan(cm).any(1)
    H, xe, ye = np.histogram2d(cm[ok, 0], cm[ok, 1], bins=[max(1, int(geom.W)), max(1, int(geom.H))],
                               range=[[0, geom.W], [0, geom.H]])
    H = cv2.GaussianBlur(H.T.astype(np.float32), (0, 0), 1.2)
    fig, ax = plt.subplots(figsize=(6, 6 * geom.H / geom.W))
    ax.imshow(H, extent=[0, geom.W, geom.H, 0], cmap="inferno", interpolation="bilinear")
    for z in geom.zones:
        for cnt in z["cnt"]:
            p = geom.to_cm(cnt.reshape(-1, 2))
            p = np.vstack([p, p[:1]])
            ax.plot(p[:, 0], p[:, 1], color="#66e0ff" if z["type"] == "object" else "#ffa040", lw=1.2)
            c = geom.to_cm([z["center"]])[0]
            ax.text(c[0], c[1], z["name"], color="white", ha="center", va="center", fontsize=8)
    ax.set_xlabel("cm"); ax.set_ylabel("cm")
    ax.set_title(f"{base} occupancy heatmap")
    fig.savefig(os.path.join(outdir, f"{base}_heatmap.png"), dpi=130, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------- shared GUI helpers
def fit_scale(w, h, maxw=1280, maxh=820):
    return min(1.0, maxw / w, maxh / h)


# --------------------------------------------------------------------------- setup (mouse-driven setup window)
def cmd_setup(args):
    import mouse_tracker_editor
    mouse_tracker_editor.run(args.video, args.config, getattr(args, "arena_w", None), getattr(args, "arena_h", None))


# --------------------------------------------------------------------------- analyze / batch
def per_video_config(video, default_cfg_path):
    own = os.path.splitext(video)[0] + ".json"
    return load_config(own if os.path.exists(own) else default_cfg_path), (own if os.path.exists(own) else default_cfg_path)


def cmd_analyze(args):
    import pandas as pd
    if not os.path.exists(args.config):
        sys.exit(T("找不到配置文件: {p}", p=args.config))
    cfg = load_config(args.config)   # single video: the config given with -c is used
    print(T("分析 {v}  (配置: {c})", v=args.video, c=args.config))
    S = analyze_video(args.video, cfg, args.out, save_video=args.video_out)
    print(pd.Series(i18n.readable(S)).to_string())


def cmd_batch(args):
    import pandas as pd
    pattern = os.path.join(args.folder, "**", "*") if args.recursive else os.path.join(args.folder, "*")
    files = sorted(p for p in glob.glob(pattern, recursive=args.recursive)
                   if p.lower().endswith(VIDEO_EXTS) and "_annotated" not in os.path.basename(p))
    if not files:
        sys.exit(T("文件夹里没有找到视频"))
    print(T("共 {n} 个视频", n=len(files)))
    rows = []
    for i, p in enumerate(files, 1):
        cfg, used = per_video_config(p, args.config)
        print(T("[{i}/{n}] {v}  (配置: {c})", i=i, n=len(files), v=os.path.basename(p), c=os.path.basename(used)))
        try:
            rows.append(analyze_video(p, cfg, args.out, save_video=args.video_out, verbose=False))
        except Exception as e:
            print(T("  × 失败: {e}", e=e))
            rows.append({"video": os.path.basename(p), "error": str(e)})
    out = os.path.join(args.out, "summary_all.csv")
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    pd.DataFrame([i18n.readable(r) for r in rows]).to_csv(os.path.join(args.out, i18n.batch_file()), index=False, encoding="utf-8-sig")
    print(T("[完成] 汇总表: {p}", p=out))


def build_parser():
    ap = argparse.ArgumentParser(prog="mouse_tracker.py", description=T("黑箱白鼠行为视频分析"))
    ap.add_argument("--lang", choices=["zh", "en"], help="界面/结果语言 Language of messages and result files")
    ap.add_argument("--version", action="version", version=f"RodentTrack {__version__}")
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("setup", help=T("标记场地/物体/网笼/排除区"))
    a.add_argument("video"); a.add_argument("-c", "--config", required=True)
    a.add_argument("--arena-w", type=float, help=T("场地内宽(cm)")); a.add_argument("--arena-h", type=float, help=T("场地内长(cm)"))
    a.set_defaults(func=cmd_setup)
    a = sp.add_parser("tune", help=T("同 setup(区域和阈值在同一个窗口里设置)"))
    a.add_argument("video"); a.add_argument("-c", "--config", required=True)
    a.set_defaults(func=cmd_setup)
    a = sp.add_parser("analyze", help=T("分析单个视频"))
    a.add_argument("video"); a.add_argument("-c", "--config", required=True)
    a.add_argument("-o", "--out", default="results"); a.add_argument("--video", dest="video_out", action="store_true", help=T("输出标注视频"))
    a.set_defaults(func=cmd_analyze)
    a = sp.add_parser("batch", help=T("批量分析文件夹"))
    a.add_argument("folder"); a.add_argument("-c", "--config", required=True)
    a.add_argument("-o", "--out", default="results"); a.add_argument("--video", dest="video_out", action="store_true", help=T("输出标注视频"))
    a.add_argument("-r", "--recursive", action="store_true", help=T("包括子文件夹"))
    a.set_defaults(func=cmd_batch)
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:   # no arguments (F5 in IDLE, double-click) -> GUI
        import mouse_tracker_gui
        mouse_tracker_gui.main()
        return
    if "--lang" in argv:   # set the language before the help texts are built
        i = argv.index("--lang")
        if i + 1 < len(argv):
            i18n.set_lang(argv[i + 1])
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
