# -*- coding: utf-8 -*-
"""
Language support for RodentTrack (中文 / English).

The source strings are Chinese; `T()` returns the English text when the language is "en".
Language is chosen, in order, from:
  1. `--lang zh|en` on the command line, or the language box in the main window
  2. the environment variable RODENTTRACK_LANG
  3. the "lang" entry in ~/.mouse_tracker_gui.json (saved by the main window)
  4. the system locale (Chinese locales -> zh, everything else -> en)

This module imports only the standard library, so the GUI can use it before numpy/OpenCV are installed.
"""
import json
import locale
import os

PREFS = os.path.join(os.path.expanduser("~"), ".mouse_tracker_gui.json")
LANG_NAMES = {"zh": "中文", "en": "English"}


def _detect():
    env = os.environ.get("RODENTTRACK_LANG", "").lower()[:2]
    if env in LANG_NAMES:
        return env
    try:
        with open(PREFS, encoding="utf-8") as f:
            v = json.load(f).get("lang")
        if v in LANG_NAMES:
            return v
    except Exception:
        pass
    try:
        loc = (locale.getlocale()[0] or os.environ.get("LANG", "") or "").lower()
    except Exception:
        loc = ""
    return "zh" if loc.startswith(("zh", "chinese")) else "en"


_LANG = _detect()


def get_lang():
    return _LANG


def set_lang(lang, save=False):
    """Switch the language ("zh" or "en"). save=True remembers the choice for next time."""
    global _LANG
    lang = (lang or "").lower()[:2]
    if lang not in LANG_NAMES:
        return
    _LANG = lang
    os.environ["RODENTTRACK_LANG"] = lang
    if save:
        try:
            try:
                with open(PREFS, encoding="utf-8") as f:
                    p = json.load(f)
            except Exception:
                p = {}
            p["lang"] = lang
            with open(PREFS, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False)
        except Exception:
            pass


def T(text, /, **kw):
    """Translate a Chinese source string, then fill in {placeholders}."""
    text = TRANSLATIONS.get(_LANG, {}).get(text, text)
    return text.format(**kw) if kw else text


# --------------------------------------------------------------------------- result labels
FIXED = {
    "zh": {"video": "视频", "fps": "帧率", "analyzed_s": "分析时长(s)", "start_s": "开始时间(s)",
           "detect_rate_%": "检测率(%)", "distance_cm": "总运动距离(cm)", "mean_speed_cm_s": "平均速度(cm/s)",
           "center_time_s": "中心区时间(s)", "center_entries": "中心区进入次数", "immobile_time_s": "不动时间(s)",
           "total_explore_s": "总接触时间(s)", "error": "错误"},
    "en": {"video": "Video", "fps": "FPS", "analyzed_s": "Analysed (s)", "start_s": "Start (s)",
           "detect_rate_%": "Detection rate (%)", "distance_cm": "Distance (cm)", "mean_speed_cm_s": "Mean speed (cm/s)",
           "center_time_s": "Centre time (s)", "center_entries": "Centre entries", "immobile_time_s": "Immobile time (s)",
           "total_explore_s": "Total exploration (s)", "error": "Error"},
}
ZONE = {
    "zh": [("_explore_bouts", "接触次数"), ("_explore_latency_s", "首次接触潜伏期(s)"), ("_mean_bout_s", "平均每次接触(s)"),
           ("_explore_s", "接触时间(s)"), ("_explore_%", "接触时间占比(%)"), ("_zone_entries", "区域进入次数"),
           ("_zone_s", "区域停留时间(s)"), ("_on_top_s", "爬上物体时间(s)")],
    "en": [("_explore_bouts", "exploration bouts"), ("_explore_latency_s", "first-contact latency (s)"),
           ("_mean_bout_s", "mean bout (s)"), ("_explore_s", "exploration time (s)"), ("_explore_%", "exploration (%)"),
           ("_zone_entries", "zone entries"), ("_zone_s", "zone time (s)"), ("_on_top_s", "climbing time (s)")],
}
INDEX = {"zh": ("辨别指数DI({b} vs {a})", "区域偏好指数({b} vs {a})"),
         "en": ("Discrimination index DI ({b} vs {a})", "Zone preference index ({b} vs {a})")}


def label(k):
    """Readable column name for an internal result key."""
    L = _LANG
    if k in FIXED[L]:
        return FIXED[L][k]
    if k.startswith("DI_") and "_vs_" in k:
        b, a = k[3:].split("_vs_", 1)
        return INDEX[L][0].format(b=b, a=a)
    if k.startswith("zoneIndex_") and "_vs_" in k:
        b, a = k[10:].split("_vs_", 1)
        return INDEX[L][1].format(b=b, a=a)
    for suf, name in ZONE[L]:
        if k.endswith(suf):
            return f"{k[:-len(suf)]} {name}"
    return k


def readable(S):
    return {label(k): v for k, v in S.items()}


def result_file(base):
    return f"{base}_结果.csv" if _LANG == "zh" else f"{base}_results.csv"


def bins_file(base):
    return f"{base}_分时段.csv" if _LANG == "zh" else f"{base}_time_bins.csv"


def batch_file():
    return "汇总结果.csv" if _LANG == "zh" else "summary_readable.csv"


def show_keys():
    """Columns shown first in the result table of the main window."""
    return [label(k) for k in ("video", "distance_cm", "mean_speed_cm_s", "detect_rate_%", "center_time_s",
                               "immobile_time_s", "total_explore_s")]


def show_zone_suffixes():
    names = dict(ZONE[_LANG])
    return [names[s] for s in ("_explore_bouts", "_explore_s", "_explore_latency_s")]


def index_prefixes():
    return tuple(p.split("(")[0].split(" (")[0] for p in INDEX[_LANG])


# --------------------------------------------------------------------------- English text
EN = {
    # ---- mouse_tracker.py (command line + analysis)
    "[已保存] {p}": "[saved] {p}",
    "分析 {v}  (配置: {c})": "Analysing {v}  (config: {c})",
    "共 {n} 个视频": "{n} videos found",
    "[完成] 汇总表: {p}": "[done] summary table: {p}",
    "无法打开视频: {p}（若是 iPhone HEVC 的 .mov，可先用 ffmpeg 转 H.264）":
        "Cannot open video: {p} (for an iPhone HEVC .mov, convert it to H.264 with ffmpeg first)",
    "读取不到视频帧，无法生成背景": "No frames could be read, so the background cannot be built",
    "  ! 读不到帧率，按 30 fps 计算(可在配置 analysis.fps_override 指定)":
        "  ! Frame rate not found; using 30 fps (set analysis.fps_override in the config to change it)",
    "起始帧读取失败": "Could not read the start frame",
    "没有读到任何帧": "No frames were read",
    "  ! {b}: 只有 {p:.0f}% 的帧检测到动物，建议在设置窗口调阈值或检查排除区域":
        "  ! {b}: the animal was detected in only {p:.0f}% of frames; adjust the threshold in the setup window or check the exclusion zones",
    "时段": "Bin",
    "运动距离(cm)": "Distance (cm)",
    "中心区时间(s)": "Centre time (s)",
    "接触次数": "bouts",
    "接触时间(s)": "exploration time (s)",
    "找不到配置文件: {p}": "Config file not found: {p}",
    "文件夹里没有找到视频": "No videos found in the folder",
    "[{i}/{n}] {v}  (配置: {c})": "[{i}/{n}] {v}  (config: {c})",
    "  × 失败: {e}": "  × failed: {e}",
    "黑箱白鼠行为视频分析": "Rodent behaviour video analysis (open field, object recognition, social interaction)",
    "标记场地/物体/网笼/排除区": "mark the arena / objects / cages / exclusion zones",
    "场地内宽(cm)": "Arena inner width (cm)",
    "场地内长(cm)": "Arena inner length (cm)",
    "同 setup(区域和阈值在同一个窗口里设置)": "same as setup (regions and threshold are set in one window)",
    "分析单个视频": "analyse one video",
    "输出标注视频": "write an annotated video",
    "批量分析文件夹": "analyse every video in a folder",
    "包括子文件夹": "include sub-folders",
    "配置里没有场地四角(arena)，请先运行 setup": "The config has no arena corners; run setup first",
    "  {b}: {p:3d}%  ({r:.0f} 帧/秒)": "  {b}: {p:3d}%  ({r:.0f} frames/s)",
    "指标": "Measure",
    "数值": "Value",

    # ---- mouse_tracker_gui.py (main window)
    "这台电脑的 Python 还缺少以下组件，分析视频需要它们：\n\n  {m}\n\n现在自动安装吗？（需要联网，约 1–3 分钟，只需一次）":
        "Python on this computer is missing these packages, which are needed to analyse videos:\n\n  {m}\n\n"
        "Install them now? (needs internet, about 1–3 minutes, only once)",
    "视频文件": "Video files",
    "所有文件": "All files",
    "RodentTrack · 啮齿动物行为视频分析": "RodentTrack · rodent behaviour video analysis",
    "单个视频": "Single video",
    "视频文件夹(批量)": "Video folder (batch)",
    "配置文件(区域/阈值)": "Config file (regions/threshold)",
    "结果保存到": "Save results to",
    "\n▶ 正在安装：{m}（请稍候，不要关闭窗口）\n": "\n▶ Installing: {m} (please wait, do not close the window)\n",
    "开始分析…": "Analysing…",
    "开始批量分析…": "Batch analysis…",
    "运行中…": "Running…",
    "\n结果已保存在：{p}\n  *_{r}    全部指标\n  *_{b}  每个时段的距离、接触次数和时间\n  *_track.csv   逐帧轨迹坐标\n  *_trajectory.png / *_heatmap.png  轨迹图和热图\n":
        "\nResults saved in: {p}\n  *_{r}    all measures\n  *_{b}  distance, bouts and time per bin\n"
        "  *_track.csv   frame-by-frame coordinates\n  *_trajectory.png / *_heatmap.png  trajectory and heat map\n",
    "就绪": "Ready",
    "1. 选择视频和配置": "1. Choose video and config",
    "2. 实验参数": "2. Experiment settings",
    "从第几秒开始": "Start at (s)",
    "分析到第几秒(空=结尾)": "End at (s, blank = end)",
    "分时段统计(秒/段)": "Time bin (s)",
    "3. 运行（按顺序）": "3. Run (in order)",
    "① 设置区域和阈值": "① Set regions & threshold",
    "② 分析单个视频": "② Analyse one video",
    "③ 批量分析文件夹": "③ Batch-analyse folder",
    "打开结果文件夹": "Open results folder",
    "停止": "Stop",
    "4. 结果（完整数据见结果文件夹里的 CSV 和图片）": "4. Results (full data: CSV files and images in the results folder)",
    "提示": "Note",
    "上一个步骤还在运行": "The previous step is still running",
    "需要安装组件": "Packages needed",
    "\n缺少组件：{m}。请重新打开本窗口并选择“是”自动安装。\n":
        "\nMissing packages: {m}. Reopen this window and choose “Yes” to install them.\n",
    "\n安装后仍然缺少组件。请把上面的信息截图，在 GitHub Issues 里提问。\n":
        "\nPackages are still missing after installation. Please take a screenshot of the messages above and open a GitHub issue.\n",
    "\n✔ 组件安装完成，可以开始了：先点“新建…”建一个配置文件，再点“① 设置区域和阈值”。\n":
        "\n✔ Packages installed. Next: click “New…” to create a config file, then “① Set regions & threshold”.\n",
    "完成": "Done",
    "组件安装完成，可以开始分析了。": "Packages installed. You can start analysing now.",
    "选择视频": "Choose a video",
    "选择放视频的文件夹": "Choose the folder that holds the videos",
    "选择配置文件": "Choose a config file",
    "新建配置文件（例如 NOR第1批.json）": "New config file (e.g. NOR_batch1.json)",
    "实验配置.json": "my_experiment.json",
    "新配置：{p}\n下一步点“① 设置区域和阈值”。\n": "New config: {p}\nNext, click “① Set regions & threshold”.\n",
    "分时段": "Time bin",
    "正在打开设置窗口（读取视频需要几秒；如果没看到窗口，请在任务栏/程序坞里点 Python 图标）…":
        "Opening the setup window (reading the video takes a few seconds; if no window appears, click the Python icon in the taskbar/Dock)…",
    "设置已保存：{n} 个物体/网笼。下一步点“② 分析单个视频”。\n": "Setup saved: {n} objects/cages. Next, click “② Analyse one video”.\n",
    "结果文件夹还不存在，请先分析": "The results folder does not exist yet; run an analysis first",
    "\n已停止\n": "\nStopped\n",
    "\n汇总表：{p}\n": "\nSummary table: {p}\n",
    "选择视频…": "Choose video…",
    "选择文件夹…": "Choose folder…",
    "打开已有…": "Open…",
    "新建…": "New…",
    "选择…": "Choose…",
    "“{n}”需要填数字": "“{n}” must be a number",
    "请先选择一个视频": "Please choose a video first",
    "请先选择视频文件夹": "Please choose a video folder first",
    "请先选择或新建一个配置文件": "Please open or create a config file first",
    "配置文件还不存在，请先点“① 设置区域和阈值”，画好后点“保存并关闭”":
        "The config file does not exist yet. Click “① Set regions & threshold”, draw the regions, then click “Save & close”",
    "场地内宽": "Arena width",
    "场地内长": "Arena length",
    "开始秒数": "Start (s)",
    "结束秒数": "End (s)",
    "当前选的是示例配置，里面的场地和物体位置是按示例视频画的，和你的视频对不上。\n\n建议点“否”，再点“新建…”建立自己的配置。\n仍要继续吗？":
        "This is an example config: its arena and object positions were drawn for the demo video and will not match yours.\n\n"
        "We suggest clicking “No”, then “New…” to create your own config.\nContinue anyway?",
    "设置窗口已关闭（没有保存）。\n": "Setup window closed (not saved).\n",
    "  拖框画区域 → 一键分析 → 得到接触时间、潜伏期、轨迹和热图":
        "  Draw regions → analyse → exploration time, latency, trajectory and heat map",
    "输出标注视频(用于核对，会慢一些)": "Write an annotated video (for checking; a little slower)",
    "在设置窗口里用鼠标拖框画场地和物体，拖白色角点调整；再点“★ 自动设定阈值”，最后点“保存并关闭”。":
        "In the setup window, drag boxes to draw the arena and objects, drag white corners to adjust, click “★ Auto threshold”, then “Save & close”.",
    "配置文件": "Config file",
    "出错（代码 {c}），请看上面的信息": "Error (code {c}); see the messages above",

    # ---- mouse_tracker_editor.py (setup window)
    "物体": "Object",
    "网笼": "Cage",
    "白鼠（比地面亮）": "White animal (brighter than floor)",
    "黑鼠（比地面暗）": "Dark animal (darker than floor)",
    "亮暗都算": "Either",
    "点选区域后：拖中间=移动，拖白色角点=调整大小/形状；Delete 键删除":
        "Click a region, then: drag the middle to move, drag white corners to resize/reshape; Delete key removes it",
    "在画面上拖一个框，框住箱子底面。之后可分别拖 4 个角点，对准底面四角":
        "Drag a box around the arena floor. Then drag each of the 4 corners onto the floor corners",
    "拖一个框，框住圆形物体（底座）": "Drag a box around the round object (its base)",
    "拖一个框，框住方形物体": "Drag a box around the square object",
    "拖一个框，框住整个网笼底面": "Drag a box around the whole cage floor",
    "拖一个框，框住反光/亮斑等要忽略的地方（小鼠在里面时不会被识别，请只框场地外或很小的亮斑）":
        "Drag a box around glare or bright spots to ignore (the animal is not detected inside it, so only mark areas outside the arena or very small spots)",
    "读取视频": "Reading video",
    "已添加 {n}，可以在右边改名字（如 Novel / Familiar）": "Added {n}. You can rename it on the right (e.g. Novel / Familiar)",
    "正在自动计算阈值…": "Computing the threshold…",
    "自动设定完成：{pol}，灵敏度 {t}，老鼠约 {a:.0f} cm²，抽查 {n} 帧识别率 {r:.0f}%。拖动时间条检查几帧，紫色轮廓应包住老鼠":
        "Auto threshold done: {pol}, sensitivity {t}, animal ≈ {a:.0f} cm², detected in {r:.0f}% of {n} sampled frames. "
        "Drag the time bar to check a few frames: the magenta outline should cover the animal",
    "很好": "good",
    "偏低：开头放鼠前的空箱画面也算在内；否则请调灵敏度":
        "low: frames of the empty arena before the animal is placed also count; otherwise adjust the sensitivity",
    "已保存到 {p}": "Saved to {p}",
    "设置区域和阈值 — ": "Set regions & threshold — ",
    "读取不到视频画面": "Could not read any video frames",
    "示例配置": "Example config",
    "这是示例配置，里面的区域是按模拟视频画的。\n清空后在你的视频上重新画吗？":
        "This is an example config; its regions were drawn for the demo video.\nClear them and draw on your own video?",
    "第一步：拖一个框框住箱子底面（场地）": "Step 1: drag a box around the arena floor",
    "正在读取视频并生成背景…": "Reading the video and building the background…",
    "正在读取视频并生成背景… {p}%": "Reading the video and building the background… {p}%",
    "1. 场地（箱子底面）": "1. Arena (floor of the box)",
    "2. 物体 / 网笼 / 排除区（拖框添加）": "2. Objects / cages / exclusion zones (drag to add)",
    "选中的区域": "Selected region",
    "3. 识别老鼠": "3. Animal detection",
    "{m}分{s:04.1f}秒": "{m} min {s:04.1f} s",
    "场地已画好。如果镜头有点斜，可以分别拖 4 个白色角点对准底面四角。下一步：添加物体或网笼":
        "Arena drawn. If the camera is tilted, drag the 4 white corners onto the floor corners. Next: add objects or cages",
    "选中的区域：{n}": "Selected region: {n}",
    "请先画场地": "Please draw the arena first",
    "自动设定没有找到稳定的结果：请检查场地是否画对，或手动拖“灵敏度”滑块":
        "Auto threshold found no stable setting: check the arena outline, or move the “Sensitivity” slider by hand",
    "抽查 {n} 帧：{ok} 帧识别到老鼠（{r:.0f}%）。": "{ok} of {n} sampled frames detected the animal ({r:.0f}%): ",
    "还没有画场地（箱子底面），请先点“拖框画场地”": "No arena yet. Click “Draw arena” first",
    "保存？": "Save?",
    "设置已修改，关闭前保存吗？": "Settings changed. Save before closing?",
    "错误": "Error",
    "＋ 圆形物体": "＋ Round object",
    "＋ 方形物体": "＋ Square object",
    "＋ 网笼": "＋ Cage",
    "＋ 排除反光区": "＋ Exclude glare",
    "框太小了，请按住鼠标拖出一个框": "Box too small: hold the mouse button and drag",
    "确认": "Confirm",
    "清空场地和所有区域？": "Clear the arena and all regions?",
    "设置有误：{e}": "Setting error: {e}",
    "左上": "TL",
    "右上": "TR",
    "右下": "BR",
    "左下": "BL",
    "排除": "excl.",
    "场地内宽/内长需要填数字": "Arena width/length must be numbers",
    "视频时间": "Time",
    "视频画面": "Video frame",
    "背景(无老鼠)": "Background (no animal)",
    "拖框画场地": "Draw arena",
    "内宽 cm": "Width cm",
    "内长 cm": "Length cm",
    "删除选中": "Delete selected",
    "全部清空": "Clear all",
    "名称": "Name",
    "类型": "Type",
    "接触距离 cm": "Contact zone cm",
    "(虚线圈=接触范围)": "(dashed ring = contact zone)",
    "★ 自动设定阈值": "★ Auto threshold",
    "灵敏度": "Sensitivity",
    "去噪点": "Denoise",
    "老鼠面积 cm²": "Animal area cm²",
    "到": "to",
    "显示识别区域(红色)": "Show detected pixels (red)",
    "检查识别率": "Check detection rate",
    "灵敏度：老鼠缺一块→往右调；\n反光被当成老鼠→往左调":
        "Sensitivity: part of the animal missing → move right;\nglare detected as the animal → move left",
    "保存": "Save",
    "保存并关闭": "Save & close",
    "选中：场地（拖白色角点调整）": "Selected: arena (drag white corners to adjust)",
    "这一帧没有识别到老鼠（如果画面里有老鼠，请把灵敏度往右调，或点“自动设定阈值”）":
        "No animal detected in this frame (if there is one, move Sensitivity to the right or click “Auto threshold”)",
    "识别到老鼠：面积 {a:.1f} cm²（紫色轮廓）": "Animal detected: {a:.1f} cm² (magenta outline)",
    "选中：排除区": "Selected: exclusion zone",
    "选中的区域（点一下画面上的区域）": "Selected region (click a region in the image)",
}

TRANSLATIONS = {"en": EN}   # add more languages here: {"ja": JA, ...}
