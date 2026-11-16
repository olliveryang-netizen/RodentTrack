#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RodentTrack graphical interface: choose video/folder -> draw regions and set threshold -> analyse -> view results.
Run: double-click a start_* script, press F5 in IDLE on this file (or on mouse_tracker.py),
or run `python mouse_tracker_gui.py` in a terminal.
Each step runs mouse_tracker.py in a separate process (avoids GUI conflicts on macOS).
"""
import csv
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import i18n  # noqa: E402
from i18n import T  # noqa: E402

NEEDED = {"cv2": "opencv-python", "numpy": "numpy", "pandas": "pandas", "matplotlib": "matplotlib"}
TRACKER = os.path.join(HERE, "mouse_tracker.py")
PREFS = i18n.PREFS
EXAMPLES = os.path.join(HERE, "examples", "configs")


def missing_packages():
    importlib.invalidate_caches()
    return [pip for mod, pip in NEEDED.items() if importlib.util.find_spec(mod) is None]


def video_types():
    return [(T("视频文件"), "*.mp4 *.MP4 *.mov *.MOV *.avi *.AVI *.m4v *.M4V *.mkv"), (T("所有文件"), "*")]


class App:
    def __init__(self, root):
        self.root = root
        root.title(T("RodentTrack · 啮齿动物行为视频分析"))
        root.minsize(900, 660)
        self.q = queue.Queue()
        self.proc = None
        self.on_done = None
        self.alive = True
        p = self.load_prefs()

        self.video = tk.StringVar(value=p.get("video", ""))
        self.folder = tk.StringVar(value=p.get("folder", ""))
        self.config = tk.StringVar(value=p.get("config", ""))
        self.outdir = tk.StringVar(value=p.get("outdir", ""))
        self.aw = tk.StringVar(value=p.get("aw", "40"))
        self.ah = tk.StringVar(value=p.get("ah", "40"))
        self.t0 = tk.StringVar(value=p.get("t0", "0"))
        self.t1 = tk.StringVar(value=p.get("t1", ""))
        self.binv = tk.StringVar(value=p.get("bin", "60"))
        self.make_video = tk.BooleanVar(value=p.get("make_video", True))
        self.status = tk.StringVar(value=T("就绪"))
        self.lang = tk.StringVar(value=i18n.LANG_NAMES[i18n.get_lang()])
        self.build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        root.after(400, self.check_packages)

    def build(self):
        root = self.root
        pad = dict(padx=6, pady=4)
        top = ttk.Frame(root)
        top.pack(fill="x", padx=10, pady=(8, 0))
        ttk.Label(top, text="RodentTrack", font=("Helvetica", 15, "bold")).pack(side="left")
        ttk.Label(top, text=T("  拖框画区域 → 一键分析 → 得到接触时间、潜伏期、轨迹和热图"), foreground="#555").pack(side="left")
        cb = ttk.Combobox(top, textvariable=self.lang, values=list(i18n.LANG_NAMES.values()), width=9, state="readonly")
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", self.switch_lang)
        ttk.Label(top, text="Language / 语言").pack(side="right", padx=4)

        f = ttk.LabelFrame(root, text=T("1. 选择视频和配置"))
        f.pack(fill="x", padx=10, pady=(8, 4))
        f.columnconfigure(1, weight=1)
        self.row(f, 0, T("单个视频"), self.video, [(T("选择视频…"), self.pick_video)])
        self.row(f, 1, T("视频文件夹(批量)"), self.folder, [(T("选择文件夹…"), self.pick_folder)])
        self.row(f, 2, T("配置文件(区域/阈值)"), self.config, [(T("打开已有…"), self.pick_config), (T("新建…"), self.new_config)])
        self.row(f, 3, T("结果保存到"), self.outdir, [(T("选择…"), self.pick_out)])

        g = ttk.LabelFrame(root, text=T("2. 实验参数"))
        g.pack(fill="x", padx=10, pady=4)
        items = [(T("场地内宽(cm)"), self.aw), (T("场地内长(cm)"), self.ah), (T("从第几秒开始"), self.t0),
                 (T("分析到第几秒(空=结尾)"), self.t1), (T("分时段统计(秒/段)"), self.binv)]
        for i, (lab, var) in enumerate(items):
            ttk.Label(g, text=lab).grid(row=0, column=2 * i, sticky="e", **pad)
            ttk.Entry(g, textvariable=var, width=7).grid(row=0, column=2 * i + 1, sticky="w", **pad)
        ttk.Checkbutton(g, text=T("输出标注视频(用于核对，会慢一些)"), variable=self.make_video).grid(
            row=1, column=0, columnspan=6, sticky="w", **pad)

        b = ttk.LabelFrame(root, text=T("3. 运行（按顺序）"))
        b.pack(fill="x", padx=10, pady=4)
        self.buttons = []
        steps = [(T("① 设置区域和阈值"), self.do_setup, True), (T("② 分析单个视频"), self.do_analyze, True),
                 (T("③ 批量分析文件夹"), self.do_batch, True), (T("打开结果文件夹"), self.open_out, False),
                 (T("停止"), self.stop, False)]
        for i, (txt, cmd, lock) in enumerate(steps):
            bt = ttk.Button(b, text=txt, command=cmd)
            bt.grid(row=0, column=i, padx=5, pady=6, sticky="ew")
            b.columnconfigure(i, weight=1)
            if lock:
                self.buttons.append(bt)
        ttk.Label(b, text=T("在设置窗口里用鼠标拖框画场地和物体，拖白色角点调整；再点“★ 自动设定阈值”，最后点“保存并关闭”。"),
                  foreground="#555").grid(row=1, column=0, columnspan=5, sticky="w", padx=6, pady=(0, 6))

        r = ttk.LabelFrame(root, text=T("4. 结果（完整数据见结果文件夹里的 CSV 和图片）"))
        r.pack(fill="both", expand=True, padx=10, pady=4)
        self.tree = ttk.Treeview(r, show="headings", height=6)
        xs = ttk.Scrollbar(r, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=xs.set)
        self.tree.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        xs.pack(fill="x", padx=6)
        self.log = tk.Text(r, height=9, wrap="word", font=("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Label(root, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

    def switch_lang(self, _e=None):
        code = {v: k for k, v in i18n.LANG_NAMES.items()}[self.lang.get()]
        if code == i18n.get_lang():
            return
        if self.proc is not None:
            messagebox.showinfo(T("提示"), T("上一个步骤还在运行"))
            self.lang.set(i18n.LANG_NAMES[i18n.get_lang()])
            return
        self.save_prefs()
        i18n.set_lang(code, save=True)
        self.alive = False
        for w in self.root.winfo_children():
            w.destroy()
        App(self.root)

    # ---------------------------------------------------------------- dependencies
    def check_packages(self, ask=True):
        miss = missing_packages()
        if not miss:
            return True
        msg = T("这台电脑的 Python 还缺少以下组件，分析视频需要它们：\n\n  {m}\n\n现在自动安装吗？（需要联网，约 1–3 分钟，只需一次）",
                m=", ".join(miss))
        if ask and messagebox.askyesno(T("需要安装组件"), msg):
            self.install(miss)
        else:
            self.write(T("\n缺少组件：{m}。请重新打开本窗口并选择“是”自动安装。\n", m=", ".join(miss)))
        return False

    def install(self, pkgs):
        self.write(T("\n▶ 正在安装：{m}（请稍候，不要关闭窗口）\n", m=" ".join(pkgs)))
        self.launch([sys.executable, "-m", "pip", "install", "--upgrade"] + pkgs, self.after_install)

    def after_install(self):
        if missing_packages():
            self.write(T("\n安装后仍然缺少组件。请把上面的信息截图，在 GitHub Issues 里提问。\n"))
        else:
            self.write(T("\n✔ 组件安装完成，可以开始了：先点“新建…”建一个配置文件，再点“① 设置区域和阈值”。\n"))
            messagebox.showinfo(T("完成"), T("组件安装完成，可以开始分析了。"))

    # ---------------------------------------------------------------- UI helpers
    def row(self, parent, r, label, var, btns):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="ew", padx=6, pady=4)
        for j, (t, c) in enumerate(btns):
            ttk.Button(parent, text=t, command=c).grid(row=r, column=2 + j, padx=3, pady=4)

    def write(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def load_prefs(self):
        try:
            with open(PREFS, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_prefs(self):
        p = self.load_prefs()
        p.update(video=self.video.get(), folder=self.folder.get(), config=self.config.get(), outdir=self.outdir.get(),
                 aw=self.aw.get(), ah=self.ah.get(), t0=self.t0.get(), t1=self.t1.get(), bin=self.binv.get(),
                 make_video=self.make_video.get(), lang=i18n.get_lang())
        try:
            with open(PREFS, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------------------------------------------------------------- file pickers
    def pick_video(self):
        p = filedialog.askopenfilename(title=T("选择视频"), filetypes=video_types(),
                                       initialdir=os.path.dirname(self.video.get()) or None)
        if p:
            self.video.set(p)
            if not self.outdir.get():
                self.outdir.set(os.path.join(os.path.dirname(p), "results"))

    def pick_folder(self):
        p = filedialog.askdirectory(title=T("选择放视频的文件夹"), initialdir=self.folder.get() or None)
        if p:
            self.folder.set(p)
            if not self.outdir.get():
                self.outdir.set(os.path.join(p, "results"))

    def pick_config(self):
        p = filedialog.askopenfilename(title=T("选择配置文件"), filetypes=[(T("配置文件"), "*.json"), (T("所有文件"), "*")],
                                       initialdir=os.path.dirname(self.config.get()) or EXAMPLES)
        if p:
            self.config.set(p)
            try:
                with open(p, encoding="utf-8") as f:
                    c = json.load(f)
                a = c.get("analysis", {})
                self.t0.set(str(a.get("start_s", 0) or 0))
                self.t1.set("" if a.get("end_s") in (None, "") else str(a["end_s"]))
                self.binv.set(str(a.get("bin_s", 60) or 60))
                if c.get("arena"):
                    self.aw.set(str(c["arena"]["width_cm"]))
                    self.ah.set(str(c["arena"]["height_cm"]))
            except Exception:
                pass

    def new_config(self):
        base = os.path.dirname(self.video.get()) or self.folder.get() or HERE
        p = filedialog.asksaveasfilename(title=T("新建配置文件（例如 NOR第1批.json）"), defaultextension=".json",
                                         filetypes=[(T("配置文件"), "*.json")], initialdir=base,
                                         initialfile=T("实验配置.json"))
        if p:
            self.config.set(p)
            self.write(T("新配置：{p}\n下一步点“① 设置区域和阈值”。\n", p=p))

    def pick_out(self):
        p = filedialog.askdirectory(title=T("结果保存到"))
        if p:
            self.outdir.set(p)

    # ---------------------------------------------------------------- validate and write parameters
    def num(self, var, name, allow_empty=False):
        v = var.get().strip()
        if v == "" and allow_empty:
            return None
        try:
            return float(v)
        except ValueError:
            raise ValueError(T("“{n}”需要填数字", n=name))

    def need(self, video=False, folder=False, config_exists=True):
        try:
            if video and not os.path.isfile(self.video.get()):
                raise ValueError(T("请先选择一个视频"))
            if folder and not os.path.isdir(self.folder.get()):
                raise ValueError(T("请先选择视频文件夹"))
            if not self.config.get():
                raise ValueError(T("请先选择或新建一个配置文件"))
            if config_exists and not os.path.isfile(self.config.get()):
                raise ValueError(T("配置文件还不存在，请先点“① 设置区域和阈值”，画好后点“保存并关闭”"))
            aw, ah = self.num(self.aw, T("场地内宽")), self.num(self.ah, T("场地内长"))
            t0, t1 = self.num(self.t0, T("开始秒数")), self.num(self.t1, T("结束秒数"), True)
            bn = self.num(self.binv, T("分时段"))
        except ValueError as e:
            messagebox.showwarning(T("提示"), str(e))
            return None
        return aw, ah, t0, t1, bn

    def write_analysis_params(self, t0, t1, bn):
        p = self.config.get()
        with open(p, encoding="utf-8") as f:
            c = json.load(f)
        a = c.setdefault("analysis", {})
        a["start_s"], a["end_s"], a["bin_s"] = t0, t1, bn
        with open(p, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)

    # ---------------------------------------------------------------- steps
    def do_setup(self):
        v = self.need(video=True, config_exists=False)
        cfgp = self.config.get().replace("\\", "/")
        if v and "/examples/configs/" in cfgp:
            if not messagebox.askyesno(T("提示"), T("当前选的是示例配置，里面的场地和物体位置是按示例视频画的，和你的视频对不上。\n\n"
                                                     "建议点“否”，再点“新建…”建立自己的配置。\n仍要继续吗？")):
                return
        if v:
            aw, ah = v[0], v[1]
            self.run(["setup", self.video.get(), "-c", self.config.get(), "--arena-w", str(aw), "--arena-h", str(ah)],
                     T("正在打开设置窗口（读取视频需要几秒；如果没看到窗口，请在任务栏/程序坞里点 Python 图标）…"),
                     self.after_setup)

    def after_setup(self):
        try:
            with open(self.config.get(), encoding="utf-8") as f:
                c = json.load(f)
            if c.get("arena"):
                self.aw.set(str(c["arena"]["width_cm"]))
                self.ah.set(str(c["arena"]["height_cm"]))
            self.write(T("设置已保存：{n} 个物体/网笼。下一步点“② 分析单个视频”。\n", n=len(c.get("zones", []))))
        except Exception:
            self.write(T("设置窗口已关闭（没有保存）。\n"))

    def do_analyze(self):
        v = self.need(video=True)
        if not v:
            return
        self.write_analysis_params(*v[2:])
        out = self.outdir.get() or os.path.join(os.path.dirname(self.video.get()), "results")
        self.outdir.set(out)
        args = ["analyze", self.video.get(), "-c", self.config.get(), "-o", out] + (["--video"] if self.make_video.get() else [])
        base = os.path.splitext(os.path.basename(self.video.get()))[0]
        self.run(args, T("开始分析…"), lambda: self.show_single(os.path.join(out, i18n.result_file(base))))

    def do_batch(self):
        v = self.need(folder=True)
        if not v:
            return
        self.write_analysis_params(*v[2:])
        out = self.outdir.get() or os.path.join(self.folder.get(), "results")
        self.outdir.set(out)
        args = ["batch", self.folder.get(), "-c", self.config.get(), "-o", out] + (["--video"] if self.make_video.get() else [])
        self.run(args, T("开始批量分析…"), lambda: self.show_table(os.path.join(out, i18n.batch_file())))

    def open_out(self):
        p = self.outdir.get()
        if not p or not os.path.isdir(p):
            messagebox.showinfo(T("提示"), T("结果文件夹还不存在，请先分析"))
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", p])
        elif sys.platform.startswith("win"):
            os.startfile(p)
        else:
            subprocess.Popen(["xdg-open", p])

    # ---------------------------------------------------------------- subprocess
    def run(self, args, hint, on_done=None):
        if self.proc is not None:
            messagebox.showinfo(T("提示"), T("上一个步骤还在运行"))
            return
        if not self.check_packages():
            return
        self.save_prefs()
        self.write(f"\n▶ {hint}\n")
        self.launch([sys.executable, "-u", TRACKER, "--lang", i18n.get_lang()] + args, on_done)

    def launch(self, cmd, on_done=None):
        self.status.set(T("运行中…"))
        for bt in self.buttons:
            bt.state(["disabled"])
        self.on_done = on_done
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", RODENTTRACK_LANG=i18n.get_lang())
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HERE, env=env)
        threading.Thread(target=self.reader, args=(self.proc,), daemon=True).start()

    def reader(self, proc):
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace")
            if "QFontDatabase" in line or "Qt no longer ships fonts" in line:
                continue
            self.q.put(("out", line))
        proc.wait()
        self.q.put(("done", proc.returncode))

    def poll(self):
        if not self.alive:
            return
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "out":
                    self.write(val)
                else:
                    self.proc = None
                    for bt in self.buttons:
                        bt.state(["!disabled"])
                    if val == 0:
                        self.status.set(T("完成"))
                        if self.on_done:
                            self.on_done()
                    else:
                        self.status.set(T("出错（代码 {c}），请看上面的信息", c=val))
                    self.on_done = None
        except queue.Empty:
            pass
        except tk.TclError:   # window rebuilt after a language switch
            return
        self.root.after(100, self.poll)

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            self.write(T("\n已停止\n"))

    def close(self):
        self.save_prefs()
        self.stop()
        self.root.destroy()

    # ---------------------------------------------------------------- result table
    def read_csv(self, path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def show_single(self, path):
        if not os.path.exists(path):
            return
        rows = self.read_csv(path)
        k, v = T("指标"), T("数值")
        self.fill_tree([{r[k]: r[v] for r in rows}])
        self.write(T("\n结果已保存在：{p}\n"
                     "  *_{r}    全部指标\n  *_{b}  每个时段的距离、接触次数和时间\n"
                     "  *_track.csv   逐帧轨迹坐标\n  *_trajectory.png / *_heatmap.png  轨迹图和热图\n",
                     p=self.outdir.get(), r=i18n.result_file(""), b=i18n.bins_file("")))

    def show_table(self, path):
        if os.path.exists(path):
            self.fill_tree(self.read_csv(path))
            self.write(T("\n汇总表：{p}\n", p=path))

    def fill_tree(self, rows):
        if not rows:
            return
        keys = list(rows[0].keys())
        cols = [k for k in i18n.show_keys() if k in keys]
        zone_suffixes = i18n.show_zone_suffixes()
        for k in keys:   # bouts, time and latency for every object/cage, and the discrimination indices
            if any(k.endswith(" " + s) for s in zone_suffixes) or k.startswith(i18n.index_prefixes()):
                cols.append(k)
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c)
            w = max(90, (14 if i18n.get_lang() == "zh" else 9) * len(c) + 12)
            self.tree.column(c, width=max(w, 170) if c == cols[0] else w, anchor="center", stretch=False)
        for r in rows:
            self.tree.insert("", "end", values=[r.get(c, "") for c in cols])


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("aqua" if sys.platform == "darwin" else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
