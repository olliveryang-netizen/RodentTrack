#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Setup window (mouse only):
  - drag boxes to draw the arena / objects / cages / exclusion zones; drag the white corner
    handles to resize, drag the middle to move
  - automatic threshold; drag the time bar to inspect any frame (magenta outline = detected animal)
Opened by `mouse_tracker.py setup`, or run on its own:
  python mouse_tracker_editor.py video.mp4 config.json
"""
import base64
import math
import os
import sys

import numpy as np
import cv2
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mouse_tracker as mt  # noqa: E402
from i18n import T  # noqa: E402

def type_names():
    return {"object": T("物体"), "cage": T("网笼")}


def polarities():
    return [(T("白鼠（比地面亮）"), "bright"), (T("黑鼠（比地面暗）"), "dark"), (T("亮暗都算"), "both")]


C_ARENA, C_OBJ, C_CAGE, C_EXCL, C_MOUSE = "#00e5ff", "#3ddc84", "#ff9f1a", "#ff4d4d", "#ff3df5"
HANDLE = 6          # half-size of a corner handle (screen px)
N_SAMPLES = 40      # frames sampled for the background and the auto threshold

def tool_hint(tool):
    return {
        "select": T("点选区域后：拖中间=移动，拖白色角点=调整大小/形状；Delete 键删除"),
        "arena": T("在画面上拖一个框，框住箱子底面。之后可分别拖 4 个角点，对准底面四角"),
        "circle": T("拖一个框，框住圆形物体（底座）"),
        "rect": T("拖一个框，框住方形物体"),
        "cage": T("拖一个框，框住整个网笼底面"),
        "exclude": T("拖一个框，框住反光/亮斑等要忽略的地方（小鼠在里面时不会被识别，请只框场地外或很小的亮斑）"),
    }[tool]


def to_photo(bgr):
    ok, buf = cv2.imencode(".png", bgr)
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))


class Editor:
    def __init__(self, root, video, cfg_path, aw=None, ah=None):
        self.root, self.video, self.cfg_path = root, video, cfg_path
        self.cfg = mt.load_config(cfg_path)
        self.dirty = False
        root.title(T("设置区域和阈值 — ") + os.path.basename(video))

        # ---------------- read video, sample frames, background
        self.cap, fps, n = mt.open_video(video)
        self.fps = fps if fps and 0 < fps < 1000 else 30.0
        self.n = n if n > 0 else int(self.fps * 600)
        first = mt.read_frame_at(self.cap, 0)
        if first is None:
            raise RuntimeError(T("读取不到视频画面"))
        self.H, self.W = first.shape[:2]
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.k = min(1.0, (sw - 420) / self.W, (sh - 190) / self.H)       # display scale
        self.dsize = (int(self.W * self.k), int(self.H * self.k))
        self.ps = mt.proc_scale(self.cfg["detection"], self.W)              # analysis scale
        self.psize = (int(round(self.W * self.ps)), int(round(self.H * self.ps)))
        self.load_samples()

        if mt.is_example_config(self.cfg_path) and (self.cfg["zones"] or self.cfg.get("arena")):
            if messagebox.askyesno(T("示例配置"), T("这是示例配置，里面的区域是按模拟视频画的。\n清空后在你的视频上重新画吗？")):
                self.clear_all(ask=False)
        if self.cfg.get("arena"):
            aw = aw or self.cfg["arena"]["width_cm"]
            ah = ah or self.cfg["arena"]["height_cm"]
        self.aw = tk.StringVar(value=str(aw or 40))
        self.ah = tk.StringVar(value=str(ah or 40))

        # ---------------- state
        self.tool = "select"
        self.sel = None              # ("arena", None) / ("zone", i) / ("exclude", i)
        self.drag = None
        self.view = tk.StringVar(value="frame")
        self.show_mask = tk.BooleanVar(value=False)
        d = self.cfg["detection"]
        self.pol = tk.StringVar(value=d["polarity"] if d["polarity"] in ("bright", "dark", "both") else "bright")
        self.thr = tk.IntVar(value=int(d["threshold"]))
        self.noise = tk.IntVar(value=int(d["open_kernel"]))
        self.amin = tk.StringVar(value=str(d["min_area_cm2"]))
        self.amax = tk.StringVar(value=str(d["max_area_cm2"]))
        self.tvar = tk.DoubleVar(value=0.0)
        self.name = tk.StringVar()
        self.ztype = tk.StringVar()
        self.margin = tk.StringVar()
        self.status = tk.StringVar()
        self.hint = tk.StringVar(value=tool_hint("select"))
        self.det = None
        self.cur_frame = self.samples_full[len(self.samples_full) // 2]
        self.tvar.set(self.sample_times[len(self.samples_full) // 2])

        self.build_ui()
        self.rebuild_detector()
        self.render_image()
        if not self.cfg.get("arena"):
            self.set_tool("arena")
            self.status.set(T("第一步：拖一个框框住箱子底面（场地）"))

    # =================================================================== data
    def load_samples(self):
        win = tk.Toplevel(self.root)
        win.title(T("读取视频"))
        lab = ttk.Label(win, text=T("正在读取视频并生成背景…"), padding=20)
        lab.pack()
        win.update()
        idxs = np.unique(np.linspace(0, max(0, self.n - 2), N_SAMPLES).astype(int))
        self.samples_full, self.samples_proc, self.sample_times = [], [], []
        disp, gray = [], []
        for j, i in enumerate(idxs):
            f = mt.read_frame_at(self.cap, i)
            if f is None:
                continue
            small = cv2.resize(f, self.dsize, interpolation=cv2.INTER_AREA)
            proc = cv2.resize(f, self.psize, interpolation=cv2.INTER_AREA) if self.ps < 1 else f
            self.samples_full.append(small)
            self.samples_proc.append(proc)
            self.sample_times.append(i / self.fps)
            disp.append(small)
            gray.append(cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY))
            lab.config(text=T("正在读取视频并生成背景… {p}%", p=int(100 * (j + 1) / len(idxs))))
            win.update()
        win.destroy()
        if not disp:
            raise RuntimeError(T("读取不到视频画面"))
        self.bg_disp = np.median(np.stack(disp), axis=0).astype(np.uint8)
        self.bg_proc = np.median(np.stack(gray), axis=0).astype(np.uint8)
        self.cur_proc = self.samples_proc[len(self.samples_proc) // 2]

    # =================================================================== UI
    def build_ui(self):
        root = self.root
        main = ttk.Frame(root)
        main.pack(fill="both", expand=True)
        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=8)
        self.cv = tk.Canvas(left, width=self.dsize[0], height=self.dsize[1], bg="black",
                            highlightthickness=0, cursor="crosshair")
        self.cv.pack()
        tl = ttk.Frame(left)
        tl.pack(fill="x", pady=(6, 0))
        ttk.Label(tl, text=T("视频时间")).pack(side="left")
        dur = self.n / self.fps
        self.tscale = ttk.Scale(tl, from_=0, to=max(1.0, dur), variable=self.tvar, command=self.on_time)
        self.tscale.pack(side="left", fill="x", expand=True, padx=6)
        self.tlabel = ttk.Label(tl, width=16)
        self.tlabel.pack(side="left")
        ttk.Radiobutton(tl, text=T("视频画面"), value="frame", variable=self.view, command=self.render_image).pack(side="left")
        ttk.Radiobutton(tl, text=T("背景(无老鼠)"), value="bg", variable=self.view, command=self.render_image).pack(side="left")
        ttk.Label(left, textvariable=self.hint, foreground="#0a58ca").pack(anchor="w", pady=(4, 0))
        ttk.Label(left, textvariable=self.status).pack(anchor="w")

        right = ttk.Frame(main, width=380)
        right.pack(side="right", fill="y", padx=(4, 8), pady=8)

        f1 = ttk.LabelFrame(right, text=T("1. 场地（箱子底面）"), padding=6)
        f1.pack(fill="x", pady=3)
        ttk.Button(f1, text=T("拖框画场地"), command=lambda: self.set_tool("arena")).grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Label(f1, text=T("内宽 cm")).grid(row=1, column=0, pady=4)
        ttk.Entry(f1, textvariable=self.aw, width=6).grid(row=1, column=1)
        ttk.Label(f1, text=T("内长 cm")).grid(row=1, column=2)
        ttk.Entry(f1, textvariable=self.ah, width=6).grid(row=1, column=3)
        for v in (self.aw, self.ah):
            v.trace_add("write", lambda *a: self.after_shape_change())

        f2 = ttk.LabelFrame(right, text=T("2. 物体 / 网笼 / 排除区（拖框添加）"), padding=6)
        f2.pack(fill="x", pady=3)
        for i, (t, tool) in enumerate([(T("＋ 圆形物体"), "circle"), (T("＋ 方形物体"), "rect"),
                                       (T("＋ 网笼"), "cage"), (T("＋ 排除反光区"), "exclude")]):
            ttk.Button(f2, text=t, command=lambda tl=tool: self.set_tool(tl)).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        ttk.Button(f2, text=T("删除选中"), command=self.delete_sel).grid(row=2, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(f2, text=T("全部清空"), command=self.clear_all).grid(row=2, column=1, sticky="ew", padx=2, pady=2)
        f2.columnconfigure(0, weight=1)
        f2.columnconfigure(1, weight=1)

        self.fz = ttk.LabelFrame(right, text=T("选中的区域"), padding=6)
        self.fz.pack(fill="x", pady=3)
        ttk.Label(self.fz, text=T("名称")).grid(row=0, column=0, sticky="e")
        self.e_name = ttk.Entry(self.fz, textvariable=self.name, width=14)
        self.e_name.grid(row=0, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Label(self.fz, text=T("类型")).grid(row=1, column=0, sticky="e")
        self.c_type = ttk.Combobox(self.fz, textvariable=self.ztype, values=list(type_names().values()), width=6, state="readonly")
        self.c_type.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(self.fz, text=T("接触距离 cm")).grid(row=2, column=0, sticky="e")
        self.s_margin = ttk.Spinbox(self.fz, from_=0, to=10, increment=0.5, textvariable=self.margin, width=6)
        self.s_margin.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(self.fz, text=T("(虚线圈=接触范围)"), foreground="#666").grid(row=2, column=2, sticky="w")
        self.name.trace_add("write", self.on_zone_edit)
        self.ztype.trace_add("write", self.on_zone_edit)
        self.margin.trace_add("write", self.on_zone_edit)

        f3 = ttk.LabelFrame(right, text=T("3. 识别老鼠"), padding=6)
        f3.pack(fill="x", pady=3)
        ttk.Button(f3, text=T("★ 自动设定阈值"), command=self.auto_threshold).grid(row=0, column=0, columnspan=3, sticky="ew")
        for i, (t, v) in enumerate(polarities()):
            ttk.Radiobutton(f3, text=t, value=v, variable=self.pol, command=self.on_det_change).grid(row=1 + i, column=0, columnspan=3, sticky="w")
        ttk.Label(f3, text=T("灵敏度")).grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Scale(f3, from_=60, to=4, variable=self.thr, command=lambda v: self.on_det_change()).grid(row=4, column=1, sticky="ew", pady=(6, 0))
        self.l_thr = ttk.Label(f3, width=4)
        self.l_thr.grid(row=4, column=2)
        ttk.Label(f3, text=T("去噪点")).grid(row=5, column=0, sticky="w")
        ttk.Scale(f3, from_=0, to=21, variable=self.noise, command=lambda v: self.on_det_change()).grid(row=5, column=1, sticky="ew")
        self.l_noise = ttk.Label(f3, width=4)
        self.l_noise.grid(row=5, column=2)
        ttk.Label(f3, text=T("老鼠面积 cm²")).grid(row=6, column=0, sticky="w")
        fa = ttk.Frame(f3)
        fa.grid(row=6, column=1, columnspan=2, sticky="w")
        ttk.Entry(fa, textvariable=self.amin, width=5).pack(side="left")
        ttk.Label(fa, text=T("到")).pack(side="left")
        ttk.Entry(fa, textvariable=self.amax, width=5).pack(side="left")
        for v in (self.amin, self.amax):
            v.trace_add("write", lambda *a: self.on_det_change())
        ttk.Checkbutton(f3, text=T("显示识别区域(红色)"), variable=self.show_mask, command=self.render_image).grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Button(f3, text=T("检查识别率"), command=self.check_rate).grid(row=8, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        f3.columnconfigure(1, weight=1)
        ttk.Label(f3, text=T("灵敏度：老鼠缺一块→往右调；\n反光被当成老鼠→往左调"), foreground="#666").grid(row=9, column=0, columnspan=3, sticky="w", pady=(4, 0))

        f4 = ttk.Frame(right, padding=(0, 8))
        f4.pack(fill="x")
        ttk.Button(f4, text=T("保存"), command=self.save).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(f4, text=T("保存并关闭"), command=lambda: self.save() and self.close(force=True)).pack(side="left", expand=True, fill="x", padx=2)

        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_motion)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<Delete>", lambda e: self.delete_sel_key(e))
        root.bind("<BackSpace>", lambda e: self.delete_sel_key(e))
        root.bind("<Escape>", lambda e: self.set_tool("select"))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.update_zone_panel()
        self.update_labels()

    def set_tool(self, tool):
        self.tool = tool
        self.hint.set(tool_hint(tool))
        self.cv.config(cursor="crosshair" if tool != "select" else "arrow")

    def update_labels(self):
        self.l_thr.config(text=str(int(self.thr.get())))
        self.l_noise.config(text=str(int(self.noise.get())))
        t = self.tvar.get()
        self.tlabel.config(text=T("{m}分{s:04.1f}秒", m=int(t // 60), s=t % 60))

    # =================================================================== shapes
    def get(self, ref):
        kind, i = ref
        return self.cfg["arena"] if kind == "arena" else self.cfg["zones" if kind == "zone" else "exclude"][i]

    def refs(self):
        r = [("zone", i) for i in range(len(self.cfg["zones"]))] + [("exclude", i) for i in range(len(self.cfg["exclude"]))]
        return r + ([("arena", None)] if self.cfg.get("arena") else [])

    @staticmethod
    def rect_of(z):
        (x1, y1), (x2, y2) = z["points"]
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    def handles(self, ref):
        z = self.get(ref)
        if ref[0] == "arena" or z.get("shape") == "polygon":
            return [tuple(p) for p in z["points"]]
        if z["shape"] == "circle":
            return [(z["center"][0] + z["radius"], z["center"][1])]
        x1, y1, x2, y2 = self.rect_of(z)
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

    def inside(self, ref, x, y):
        if ref[0] == "arena":
            return False
        z = self.get(ref)
        if z["shape"] == "circle":
            return math.dist(z["center"], (x, y)) <= z["radius"]
        if z["shape"] == "rect":
            x1, y1, x2, y2 = self.rect_of(z)
            return x1 <= x <= x2 and y1 <= y <= y2
        return cv2.pointPolygonTest(np.float32(z["points"]), (float(x), float(y)), False) >= 0

    def move(self, ref, dx, dy):
        z = self.get(ref)
        if "center" in z:
            z["center"] = [z["center"][0] + dx, z["center"][1] + dy]
        if "points" in z:
            z["points"] = [[px + dx, py + dy] for px, py in z["points"]]

    def move_handle(self, ref, hi, x, y):
        z = self.get(ref)
        x = min(max(x, 0), self.W - 1)
        y = min(max(y, 0), self.H - 1)
        if ref[0] == "arena" or z.get("shape") == "polygon":
            z["points"][hi] = [x, y]
        elif z["shape"] == "circle":
            z["radius"] = max(3.0, math.dist(z["center"], (x, y)))
        else:
            c = self.handles(ref)
            ox, oy = c[(hi + 2) % 4]
            z["points"] = [[min(x, ox), min(y, oy)], [max(x, ox), max(y, oy)]]
            # when dragged past the opposite corner, keep holding the same corner
            nx1, ny1, nx2, ny2 = self.rect_of(z)
            corners = [(nx1, ny1), (nx2, ny1), (nx2, ny2), (nx1, ny2)]
            self.drag["hi"] = min(range(4), key=lambda j: math.dist(corners[j], (x, y)))

    def next_name(self, typ):
        prefix = "Obj" if typ == "object" else "Cage"
        used = {z["name"] for z in self.cfg["zones"]}
        i = 1
        while f"{prefix}{i}" in used:
            i += 1
        return f"{prefix}{i}"

    def ppc(self):
        try:
            a = dict(self.cfg["arena"], width_cm=float(self.aw.get()), height_cm=float(self.ah.get()))
            return mt.arena_scale(a)
        except Exception:
            return None

    # =================================================================== mouse
    def img_xy(self, e):
        return e.x / self.k, e.y / self.k

    def hit_handle(self, cx, cy):
        order = ([self.sel] if self.sel else []) + [r for r in self.refs() if r != self.sel]
        for ref in order:
            for hi, (hx, hy) in enumerate(self.handles(ref)):
                if abs(hx * self.k - cx) <= HANDLE + 3 and abs(hy * self.k - cy) <= HANDLE + 3:
                    if ref == self.sel or ref[0] == "arena":
                        return ref, hi
        return None

    def on_press(self, e):
        x, y = self.img_xy(e)
        if self.tool != "select":
            self.drag = {"mode": "new", "x0": x, "y0": y, "x": x, "y": y}
            return
        h = self.hit_handle(e.x, e.y)
        if h:
            self.sel = h[0]
            self.drag = {"mode": "handle", "ref": h[0], "hi": h[1]}
        else:
            hit = next((r for r in self.refs() if self.inside(r, x, y)), None)
            self.sel = hit or (("arena", None) if self.cfg.get("arena") else None)
            self.drag = {"mode": "move", "ref": hit, "x": x, "y": y} if hit else None
        self.update_zone_panel()
        self.draw_overlay()

    def on_motion(self, e):
        if not self.drag:
            return
        x, y = self.img_xy(e)
        d = self.drag
        if d["mode"] == "new":
            d["x"], d["y"] = x, y
        elif d["mode"] == "handle":
            self.move_handle(d["ref"], d["hi"], x, y)
        elif d["mode"] == "move":
            self.move(d["ref"], x - d["x"], y - d["y"])
            d["x"], d["y"] = x, y
        self.draw_overlay()

    def on_release(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        if d["mode"] == "new":
            x1, x2 = sorted((d["x0"], d["x"]))
            y1, y2 = sorted((d["y0"], d["y"]))
            if (x2 - x1) * self.k < 8 or (y2 - y1) * self.k < 8:
                self.status.set(T("框太小了，请按住鼠标拖出一个框"))
                return
            self.create_shape(x1, y1, x2, y2)
            self.set_tool("select")
        self.after_shape_change()

    def create_shape(self, x1, y1, x2, y2):
        t = self.tool
        if t == "arena":
            self.cfg["arena"] = {"points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                                 "width_cm": float(self.aw.get() or 40), "height_cm": float(self.ah.get() or 40)}
            self.sel = ("arena", None)
            self.status.set(T("场地已画好。如果镜头有点斜，可以分别拖 4 个白色角点对准底面四角。下一步：添加物体或网笼"))
            return
        if t == "exclude":
            self.cfg["exclude"].append({"shape": "rect", "points": [[x1, y1], [x2, y2]]})
            self.sel = ("exclude", len(self.cfg["exclude"]) - 1)
            return
        typ = "cage" if t == "cage" else "object"
        z = {"name": self.next_name(typ), "type": typ, "interaction_cm": mt.DEFAULT_MARGIN_CM[typ]}
        if t == "circle":
            z.update(shape="circle", center=[(x1 + x2) / 2, (y1 + y2) / 2], radius=((x2 - x1) + (y2 - y1)) / 4)
        else:
            z.update(shape="rect", points=[[x1, y1], [x2, y2]])
        self.cfg["zones"].append(z)
        self.sel = ("zone", len(self.cfg["zones"]) - 1)
        self.status.set(T("已添加 {n}，可以在右边改名字（如 Novel / Familiar）", n=z["name"]))

    def delete_sel_key(self, e):
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return
        self.delete_sel()

    def delete_sel(self):
        if not self.sel:
            return
        kind, i = self.sel
        if kind == "arena":
            self.cfg["arena"] = None
        else:
            self.cfg["zones" if kind == "zone" else "exclude"].pop(i)
        self.sel = None
        self.after_shape_change()

    def clear_all(self, ask=True):
        if ask and not messagebox.askyesno(T("确认"), T("清空场地和所有区域？")):
            return
        self.cfg["arena"], self.cfg["zones"], self.cfg["exclude"] = None, [], []
        self.cfg["comparisons"] = None
        self.sel = None
        if hasattr(self, "cv"):
            self.set_tool("arena")
            self.after_shape_change()

    def after_shape_change(self):
        self.dirty = True
        self.update_zone_panel()
        self.rebuild_detector()
        self.render_image()

    # =================================================================== selected-zone panel
    def update_zone_panel(self):
        self._updating = True
        z = self.get(self.sel) if self.sel and self.sel[0] == "zone" else None
        st = "normal" if z else "disabled"
        for w in (self.e_name, self.s_margin):
            w.config(state=st)
        self.c_type.config(state="readonly" if z else "disabled")
        self.name.set(z["name"] if z else "")
        self.ztype.set(type_names()[z["type"]] if z else "")
        self.margin.set(str(z.get("interaction_cm", 2.0)) if z else "")
        self.fz.config(text=T("选中的区域：{n}", n=z["name"]) if z else
                       (T("选中：场地（拖白色角点调整）") if self.sel and self.sel[0] == "arena" else
                        (T("选中：排除区") if self.sel else T("选中的区域（点一下画面上的区域）"))))
        self._updating = False

    def on_zone_edit(self, *a):
        if getattr(self, "_updating", False) or not self.sel or self.sel[0] != "zone":
            return
        z = self.get(self.sel)
        nm = self.name.get().strip()
        if nm and all(o is z or o["name"] != nm for o in self.cfg["zones"]):
            z["name"] = nm
        inv = {v: k for k, v in type_names().items()}
        if self.ztype.get() in inv and inv[self.ztype.get()] != z["type"]:
            z["type"] = inv[self.ztype.get()]
            z["interaction_cm"] = mt.DEFAULT_MARGIN_CM[z["type"]]
            self._updating = True
            self.margin.set(str(z["interaction_cm"]))
            self._updating = False
        try:
            z["interaction_cm"] = max(0.0, float(self.margin.get()))
        except ValueError:
            pass
        self.dirty = True
        self.fz.config(text=T("选中的区域：{n}", n=z["name"]))
        self.draw_overlay()
        self.schedule(self.rebuild_and_render, 300)

    # =================================================================== detection
    def det_params(self):
        d = self.cfg["detection"]
        d["polarity"] = self.pol.get()
        d["threshold"] = int(self.thr.get())
        d["open_kernel"] = int(self.noise.get())
        try:
            d["min_area_cm2"] = max(0.1, float(self.amin.get()))
            d["max_area_cm2"] = max(d["min_area_cm2"] + 0.1, float(self.amax.get()))
        except ValueError:
            pass
        return d

    def rebuild_detector(self):
        self.det = None
        if not self.cfg.get("arena"):
            return
        try:
            self.cfg["arena"]["width_cm"] = float(self.aw.get())
            self.cfg["arena"]["height_cm"] = float(self.ah.get())
            geom = mt.Geometry(mt.scale_cfg(self.cfg, self.ps), (self.psize[1], self.psize[0]))
            self.det = mt.Detector(self.det_params(), geom, self.bg_proc)
        except Exception as ex:
            self.status.set(T("设置有误：{e}", e=ex))

    def on_det_change(self):
        self.update_labels()
        self.dirty = True
        self.schedule(self.rebuild_and_render, 120)

    def rebuild_and_render(self):
        self.rebuild_detector()
        self.render_image()

    def schedule(self, fn, ms):
        if getattr(self, "_job", None):
            self.root.after_cancel(self._job)
        self._job = self.root.after(ms, fn)

    def auto_threshold(self):
        if not self.cfg.get("arena"):
            messagebox.showinfo(T("提示"), T("请先画场地"))
            return
        self.status.set(T("正在自动计算阈值…"))
        self.root.config(cursor="watch")
        self.root.update()
        ppc2 = self.ppc() * self.ps
        ppc2 = ppc2 * ppc2
        best = None
        for pol in ("bright", "dark", "both"):
            d = dict(self.cfg["detection"], polarity=pol, open_kernel=max(3, int(self.noise.get()) or 5))
            geom = mt.Geometry(mt.scale_cfg(self.cfg, self.ps), (self.psize[1], self.psize[0]))
            det = mt.Detector(d, geom, self.bg_proc)
            diffs = [cv2.bitwise_and(det.diff_image(f), geom.detect_mask) for f in self.samples_proc]
            res = []
            for thr in range(5, 81, 3):
                good, areas = 0, []
                for df in diffs:
                    _, m = cv2.threshold(df, thr, 255, cv2.THRESH_BINARY)
                    if det.ko is not None:
                        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, det.ko)
                    if det.kc is not None:
                        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, det.kc)
                    a = sorted((cv2.contourArea(c) for c in cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]), reverse=True)
                    if a and 3 * ppc2 <= a[0] <= 300 * ppc2 and (len(a) < 2 or a[1] < 0.25 * a[0]):
                        good += 1
                        areas.append(a[0] / ppc2)
                res.append((thr, good / len(diffs), float(np.median(areas)) if areas else 0))
            top = max(r[1] for r in res)
            plateau = [r for r in res if r[1] >= top - 0.05]
            pick = plateau[len(plateau) // 2]
            cand = (top, pol, pick)
            if best is None or top > best[0] + 0.02:
                best = cand
        self.root.config(cursor="")
        top, pol, (thr, rate, area) = best
        if top < 0.3:
            self.status.set(T("自动设定没有找到稳定的结果：请检查场地是否画对，或手动拖“灵敏度”滑块"))
            return
        self.pol.set(pol)
        self.thr.set(thr)
        if area > 0:
            self.amin.set(f"{max(1.0, area * 0.3):.1f}")
            self.amax.set(f"{area * 2.5:.0f}")
        self.view.set("frame")
        self.update_labels()
        self.rebuild_and_render()
        self.status.set(T("自动设定完成：{pol}，灵敏度 {t}，老鼠约 {a:.0f} cm²，抽查 {n} 帧识别率 {r:.0f}%。拖动时间条检查几帧，紫色轮廓应包住老鼠",
                          pol={v: t for t, v in polarities()}[pol], t=thr, a=area, n=len(self.samples_proc), r=100 * rate))

    def check_rate(self):
        if self.det is None:
            messagebox.showinfo(T("提示"), T("请先画场地"))
            return
        ok = sum(self.det.detect(f)[0] is not None for f in self.samples_proc)
        n = len(self.samples_proc)
        verdict = T("很好") if ok / n >= 0.95 else T("偏低：开头放鼠前的空箱画面也算在内；否则请调灵敏度")
        self.status.set(T("抽查 {n} 帧：{ok} 帧识别到老鼠（{r:.0f}%）。", n=n, ok=ok, r=100 * ok / n) + verdict)

    # =================================================================== canvas
    def on_time(self, v=None):
        self.update_labels()
        self.view.set("frame")
        self.schedule(self.load_frame, 150)

    def load_frame(self):
        f = mt.read_frame_at(self.cap, int(self.tvar.get() * self.fps))
        if f is not None:
            self.cur_frame = cv2.resize(f, self.dsize, interpolation=cv2.INTER_AREA)
            self.cur_proc = cv2.resize(f, self.psize, interpolation=cv2.INTER_AREA) if self.ps < 1 else f
        self.render_image()

    def render_image(self):
        self.update_labels()
        self.det_result = None
        if self.view.get() == "bg":
            img = self.bg_disp.copy()
        else:
            img = self.cur_frame.copy()
            if self.det is not None:
                r, mask, _ = self.det.detect(self.cur_proc)
                self.det_result = r
                if self.show_mask.get():
                    m = cv2.resize(mask, self.dsize, interpolation=cv2.INTER_NEAREST) > 0
                    img[m] = (0.45 * img[m] + 0.55 * np.array([40, 40, 255])).astype(np.uint8)
                if r is None:
                    self.status.set(T("这一帧没有识别到老鼠（如果画面里有老鼠，请把灵敏度往右调，或点“自动设定阈值”）"))
                else:
                    a = r["area"] / (self.det.g.px_per_cm ** 2)
                    self.status.set(T("识别到老鼠：面积 {a:.1f} cm²（紫色轮廓）", a=a))
        self.photo = to_photo(img)
        self.cv.delete("img")
        self.cv.create_image(0, 0, anchor="nw", image=self.photo, tags="img")
        self.cv.tag_lower("img")
        self.draw_overlay()

    def draw_overlay(self):
        cv_, k = self.cv, self.k
        cv_.delete("ov")
        ppc = self.ppc() if self.cfg.get("arena") else None
        a = self.cfg.get("arena")
        if a:
            pts = [c * k for p in a["points"] for c in p]
            cv_.create_polygon(pts, outline=C_ARENA, fill="", width=3 if self.sel == ("arena", None) else 2, tags="ov")
            for i, lab in enumerate([T("左上"), T("右上"), T("右下"), T("左下")]):
                x, y = a["points"][i]
                cv_.create_text(x * k + 14, y * k + 12, text=lab, fill=C_ARENA, anchor="nw", tags="ov")
        for i, e in enumerate(self.cfg["exclude"]):
            sel = self.sel == ("exclude", i)
            self.draw_shape(e, C_EXCL, sel, fill=C_EXCL)
            c = self.center_of(e)
            cv_.create_text(c[0] * k, c[1] * k, text=T("排除"), fill=C_EXCL, tags="ov")
        for i, z in enumerate(self.cfg["zones"]):
            col = C_OBJ if z["type"] == "object" else C_CAGE
            sel = self.sel == ("zone", i)
            self.draw_shape(z, col, sel)
            if ppc:
                self.draw_ring(z, col, float(z.get("interaction_cm", 2.0)) * ppc)
            c = self.center_of(z)
            cv_.create_text(c[0] * k + 1, c[1] * k + 1, text=z["name"], fill="black", font=("Helvetica", 14, "bold"), tags="ov")
            cv_.create_text(c[0] * k, c[1] * k, text=z["name"], fill=col, font=("Helvetica", 14, "bold"), tags="ov")
        r = getattr(self, "det_result", None)
        if r is not None and self.view.get() == "frame":
            f = k / self.ps
            pts = (r["contour"].reshape(-1, 2) * f).ravel().tolist()
            if len(pts) >= 6:
                cv_.create_polygon(pts, outline=C_MOUSE, fill="", width=2, tags="ov")
            cv_.create_oval(r["cx"] * f - 4, r["cy"] * f - 4, r["cx"] * f + 4, r["cy"] * f + 4, fill=C_MOUSE, outline="", tags="ov")
        # corner handles
        for ref in self.refs():
            if ref == self.sel or ref[0] == "arena":
                for hx, hy in self.handles(ref):
                    cv_.create_rectangle(hx * k - HANDLE, hy * k - HANDLE, hx * k + HANDLE, hy * k + HANDLE,
                                         fill="white", outline="black", tags="ov")
        d = self.drag
        if d and d["mode"] == "new":
            x1, y1, x2, y2 = d["x0"] * k, d["y0"] * k, d["x"] * k, d["y"] * k
            col = {"arena": C_ARENA, "exclude": C_EXCL, "cage": C_CAGE}.get(self.tool, C_OBJ)
            if self.tool == "circle":
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                rr = (abs(x2 - x1) + abs(y2 - y1)) / 4
                cv_.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=col, width=2, tags="ov")
            cv_.create_rectangle(x1, y1, x2, y2, outline=col, dash=(4, 3), width=2, tags="ov")

    def center_of(self, z):
        if z["shape"] == "circle":
            return z["center"]
        p = np.array(z["points"], float)
        return p.mean(0)

    def draw_shape(self, z, col, sel, fill=""):
        k, w = self.k, 3 if sel else 2
        st = "gray25" if fill else ""
        if z["shape"] == "circle":
            (x, y), r = z["center"], z["radius"]
            self.cv.create_oval((x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k, outline=col, width=w, tags="ov")
        elif z["shape"] == "rect":
            x1, y1, x2, y2 = self.rect_of(z)
            self.cv.create_rectangle(x1 * k, y1 * k, x2 * k, y2 * k, outline=col, width=w, fill=fill, stipple=st, tags="ov")
        else:
            self.cv.create_polygon([c * k for p in z["points"] for c in p], outline=col, width=w, fill=fill, stipple=st, tags="ov")

    def draw_ring(self, z, col, m):
        k = self.k
        if z["shape"] == "circle":
            (x, y), r = z["center"], z["radius"] + m
            self.cv.create_oval((x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k, outline=col, dash=(5, 4), tags="ov")
        elif z["shape"] == "rect":
            x1, y1, x2, y2 = self.rect_of(z)
            self.cv.create_rectangle((x1 - m) * k, (y1 - m) * k, (x2 + m) * k, (y2 + m) * k, outline=col, dash=(5, 4), tags="ov")

    # =================================================================== save
    def save(self):
        if not self.cfg.get("arena"):
            messagebox.showwarning(T("提示"), T("还没有画场地（箱子底面），请先点“拖框画场地”"))
            return False
        try:
            self.cfg["arena"]["width_cm"] = float(self.aw.get())
            self.cfg["arena"]["height_cm"] = float(self.ah.get())
        except ValueError:
            messagebox.showwarning(T("提示"), T("场地内宽/内长需要填数字"))
            return False
        names = {z["name"] for z in self.cfg["zones"]}
        comps = self.cfg.get("comparisons") or []
        self.cfg["comparisons"] = [c for c in comps if c[0] in names and c[1] in names] or None
        self.det_params()
        mt.save_config(self.cfg, self.cfg_path)
        self.dirty = False
        self.status.set(T("已保存到 {p}", p=os.path.basename(self.cfg_path)))
        return True

    def close(self, force=False):
        if not force and self.dirty:
            r = messagebox.askyesnocancel(T("保存？"), T("设置已修改，关闭前保存吗？"))
            if r is None:
                return
            if r and not self.save():
                return
        self.cap.release()
        self.root.destroy()


def run(video, cfg_path, aw=None, ah=None):
    root = tk.Tk()
    try:
        ttk.Style().theme_use("aqua" if sys.platform == "darwin" else "clam")
    except tk.TclError:
        pass
    try:
        Editor(root, video, cfg_path, aw, ah)
    except Exception as ex:
        messagebox.showerror(T("错误"), str(ex))
        root.destroy()
        raise
    root.lift()
    root.attributes("-topmost", True)
    root.after(600, lambda: root.attributes("-topmost", False))
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python mouse_tracker_editor.py VIDEO CONFIG.json")
    run(sys.argv[1], sys.argv[2])
