# -*- coding: utf-8 -*-
"""
Tests: run with `python -m pytest -q` from the repository folder.

1. every Chinese UI/result string has an English translation
2. synthetic videos with known ground truth: detection rate, body position error and
   exploration time per object must be close to the truth
"""
import ast
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "examples", "demo"))

import i18n  # noqa: E402
import mouse_tracker as mt  # noqa: E402
import make_demo_videos as demo  # noqa: E402

SOURCES = ["mouse_tracker.py", "mouse_tracker_gui.py", "mouse_tracker_editor.py"]


def t_keys():
    keys = set()
    for f in SOURCES:
        tree = ast.parse(open(os.path.join(ROOT, f), encoding="utf-8").read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "T" and n.args \
                    and isinstance(n.args[0], ast.Constant):
                keys.add(n.args[0].value)
    return keys


def test_every_string_has_english():
    missing = sorted(k for k in t_keys() if k not in i18n.EN)
    assert not missing, f"no English text for: {missing}"


def test_placeholders_match():
    import string
    fmt = string.Formatter()
    for zh, en in i18n.EN.items():
        a = {f for _, f, _, _ in fmt.parse(zh) if f}
        b = {f for _, f, _, _ in fmt.parse(en) if f}
        assert a == b, f"placeholders differ: {zh!r} -> {en!r}"


def test_labels_both_languages():
    S = {"video": "x.mp4", "Novel_explore_s": 3.0, "DI_Novel_vs_Familiar": 0.2}
    i18n.set_lang("en")
    assert i18n.readable(S) == {"Video": "x.mp4", "Novel exploration time (s)": 3.0,
                                "Discrimination index DI (Novel vs Familiar)": 0.2}
    assert i18n.result_file("a") == "a_results.csv"
    i18n.set_lang("zh")
    assert "Novel 接触时间(s)" in i18n.readable(S)
    assert i18n.result_file("a") == "a_结果.csv"


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    out = {}
    for kind in ("nor2", "nor4", "social"):
        p = str(d / f"{kind}.mp4")
        cfg, truth, track = demo.make(kind, p, secs=30, fps=30, seed=3)
        out[kind] = (p, cfg, truth, track)
    return out


@pytest.mark.parametrize("kind", ["nor2", "nor4", "social"])
def test_synthetic_accuracy(videos, kind, tmp_path):
    p, cfg, truth, track = videos[kind]
    i18n.set_lang("en")
    S = mt.analyze_video(p, json.loads(json.dumps(cfg)), str(tmp_path), verbose=False)
    assert S["detect_rate_%"] >= 98
    for name, t in truth.items():
        # exploration time within 0.6 s or 10 % of the truth
        assert abs(S[f"{name}_explore_s"] - t) <= max(0.6, 0.1 * t), (name, S[f"{name}_explore_s"], t)
    # body-centre error (cm) against the ground-truth path
    tr = pd.read_csv(tmp_path / f"{kind}_track.csv")
    n = min(len(tr), len(track))
    err = np.hypot(tr["x_cm"].values[:n] - track[:n, 0], tr["y_cm"].values[:n] - track[:n, 1])
    assert np.nanmedian(err) < 0.5
    for f in (f"{kind}_results.csv", f"{kind}_time_bins.csv", f"{kind}_trajectory.png", f"{kind}_heatmap.png"):
        assert (tmp_path / f).exists(), f
