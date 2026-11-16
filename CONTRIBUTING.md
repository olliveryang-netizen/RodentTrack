# Contributing / 参与改进

Thank you for helping! 感谢参与！

## Reporting a problem / 反馈问题

Open an [issue](../../issues/new/choose) and include:

- what you did and what happened / 操作步骤和出现的情况
- a screenshot of the log in the main window / 主窗口日志的截图
- OS, Python version (`python --version`) and RodentTrack version (`python mouse_tracker.py --version`)

Please **do not upload unpublished experimental videos**. One frame or the `*_trajectory.png` is usually enough.
请**不要上传未发表的实验视频**，一张截图或轨迹图通常就够了。

## Changing the code / 修改代码

```bash
git clone https://github.com/olliveryang-netizen/RodentTrack.git
cd RodentTrack
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q tests
```

- `mouse_tracker.py` – detection, tracking, measures, command line
- `mouse_tracker_gui.py` – main window (imports no OpenCV, so it can install packages first)
- `mouse_tracker_editor.py` – setup window (regions and threshold)
- `i18n.py` – languages. Source strings are Chinese and wrapped in `T("…")`; add the English text to `EN`.
  The test `test_every_string_has_english` fails if a translation is missing.
- `examples/demo/make_demo_videos.py` – synthetic videos with ground truth used by the tests

Keep changes small and add a test when you change a measure. If a change alters results, say so in `CHANGELOG.md`.

## Adding a language / 增加语言

Copy the `EN` dictionary in `i18n.py`, translate the values, register it in `TRANSLATIONS`, and add the language code to `LANG_NAMES`, the `--lang` choices in `mouse_tracker.py` and the label tables (`FIXED`, `ZONE`, `INDEX`).
