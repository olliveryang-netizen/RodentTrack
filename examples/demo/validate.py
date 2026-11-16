#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Accuracy check on synthetic videos with known ground truth.

    python examples/demo/validate.py              # 3 kinds x 5 seeds, 60 s each (~5 min)
    python examples/demo/validate.py --seeds 2 --secs 30

Writes validation/validation.csv and validation/accuracy.png (tracked vs true exploration time).
"""
import argparse
import os
import sys
import tempfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import mouse_tracker as mt  # noqa: E402
import make_demo_videos as demo  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--secs", type=float, default=60)
    ap.add_argument("--out", default="validation")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for kind in demo.KINDS:
            for seed in range(1, a.seeds + 1):
                p = os.path.join(tmp, f"{kind}_{seed}.mp4")
                cfg, truth, track = demo.make(kind, p, a.secs, 30, seed)
                S = mt.analyze_video(p, cfg, tmp, verbose=False)
                tr = pd.read_csv(os.path.join(tmp, f"{kind}_{seed}_track.csv"))
                n = min(len(tr), len(track))
                body = np.hypot(tr.x_cm.values[:n] - track[:n, 0], tr.y_cm.values[:n] - track[:n, 1])
                nose = np.hypot(tr.nose_x_cm.values[:n] - track[:n, 2], tr.nose_y_cm.values[:n] - track[:n, 3])
                for name, t in truth.items():
                    rows.append(dict(kind=kind, seed=seed, zone=name, true_s=t, tracked_s=S[f"{name}_explore_s"],
                                     detect_pct=S["detect_rate_%"], body_err_cm=np.nanmedian(body),
                                     nose_err_cm=np.nanmedian(nose)))
                print(kind, seed, {k: (v, S[f"{k}_explore_s"]) for k, v in truth.items()})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(a.out, "validation.csv"), index=False)
    d = df.tracked_s - df.true_s
    r = np.corrcoef(df.true_s, df.tracked_s)[0, 1]
    print(f"\n{len(df)} zones: r = {r:.3f}, mean |error| = {d.abs().mean():.2f} s, "
          f"body error = {df.body_err_cm.median():.2f} cm, nose error = {df.nose_err_cm.median():.2f} cm, "
          f"detection = {df.detect_pct.min():.0f}-{df.detect_pct.max():.0f} %")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    mk = {"nor2": ("o", "2 objects"), "nor4": ("s", "4 objects"), "social": ("^", "social, 2 cages")}
    for kind, (m, lab) in mk.items():
        s = df[df.kind == kind]
        ax.scatter(s.true_s, s.tracked_s, marker=m, s=34, facecolor="white" if kind == "nor4" else "black",
                   edgecolor="black", lw=1.2, label=lab, zorder=3)
    hi = max(df.true_s.max(), df.tracked_s.max()) * 1.08
    ax.plot([0, hi], [0, hi], color="0.6", lw=1, ls="--", zorder=1)
    ax.set_xlim(0, hi)
    ax.set_ylim(0, hi)
    ax.set_xlabel("True exploration time (s)", fontweight="bold")
    ax.set_ylabel("RodentTrack (s)", fontweight="bold")
    ax.text(0.04, 0.96, f"r = {r:.3f}\nmean |error| = {d.abs().mean():.2f} s\nn = {len(df)} zones",
            transform=ax.transAxes, va="top", fontsize=9)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(a.out, "accuracy.png"), dpi=160)


if __name__ == "__main__":
    main()
