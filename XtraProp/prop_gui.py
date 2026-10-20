"""Desktop GUI for the propeller / motor / battery model.

Run:  python prop_gui.py
Needs bemt_model.py, i18n.py and an Airfoils/<name>/re<Re>.csv folder next to it.
Presets and the chosen language are saved to presets.json in the same folder.
Optional files next to this script: icon.ico, icon.png (app icon), logo_black.png (panel logo).
"""
import csv
import dataclasses
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

import bemt_model as m
import i18n
from i18n import t

APP_ID = "propcalc.propeller-performance"       # Windows taskbar grouping id
ASSET_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(ASSET_DIR, "icon.ico")  # Windows: multi-size .ico (title bar + taskbar)
ICON_PNG = os.path.join(ASSET_DIR, "icon.png")  # macOS / Linux, or Windows if no .ico
LOGO_PNG = os.path.join(ASSET_DIR, "logo_black.png")

CATEGORIES = [            # (preset key, component class)
    ("motors", m.Motor),
    ("batteries", m.Battery),
    ("propellers", m.Propeller),
]


# ------------------------------------------------------------------
# Dialog for creating / editing a preset
# ------------------------------------------------------------------

class PresetDialog(tk.Toplevel):
    def __init__(self, parent, cls, title, initial=None):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.cls = cls
        self.result = None
        self.vars = {}

        frm = ttk.Frame(self, padding=14)
        frm.grid(sticky="nsew")
        for row, f in enumerate(dataclasses.fields(cls)):
            if initial is not None and f.name in initial:
                value = initial[f.name]
            elif f.default is not dataclasses.MISSING:
                value = f.default
            else:
                value = ""
            ttk.Label(frm, text=i18n.field_label(f.name)).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            kind = f.metadata.get("airfoil")
            if kind:
                # pick from the airfoil library instead of typing a name
                airfoils = m.list_airfoils()
                if kind == "tip":
                    choices = [t("af.same")] + airfoils
                    value = value or t("af.same")
                else:
                    choices = airfoils
                    if not value and airfoils:
                        value = "naca2412" if "naca2412" in airfoils else airfoils[0]
                var = tk.StringVar(value=str(value))
                entry = ttk.Combobox(frm, textvariable=var, values=choices, state="readonly", width=20)
            else:
                var = tk.StringVar(value=str(value))
                entry = ttk.Entry(frm, textvariable=var, width=22)
            entry.grid(row=row, column=1, pady=3)
            if row == 0:
                entry.focus_set()
            self.vars[f.name] = (var, f)

        btns = ttk.Frame(frm)
        btns.grid(row=len(self.vars), column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text=t("btn.cancel"), command=self.destroy).pack(side="right")
        ttk.Button(btns, text=t("btn.save"), command=self._save).pack(side="right", padx=(0, 6))
        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

        self.wait_visibility()   # Linux: grab fails on a window that isn't mapped yet
        self.grab_set()
        self.wait_window()

    def _save(self):
        data = {}
        for name, (var, f) in self.vars.items():
            text = var.get().strip()
            kind = f.metadata.get("airfoil")
            if kind == "tip":
                data[name] = "" if text == t("af.same") else text
                continue
            if kind == "root" and text not in m.list_airfoils():
                messagebox.showerror(t("dlg.invalid_value"),
                                     t("err.airfoil_missing", name=text) if text else t("err.pick_root"),
                                     parent=self)
                return
            try:
                if f.type is str:
                    if not text:
                        raise ValueError
                    data[name] = text
                elif f.type is int:
                    data[name] = int(round(float(text)))
                else:
                    data[name] = float(text)
            except ValueError:
                messagebox.showerror(t("dlg.invalid_value"),
                                     t("err.invalid_field", label=i18n.field_label(name), text=text), parent=self)
                return
        try:
            self.cls(**data)   # runs the class's own sanity checks
        except Exception as exc:
            messagebox.showerror(t("dlg.invalid_values"), str(exc), parent=self)
            return
        self.result = data
        self.destroy()


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.presets = m.load_presets()
        self.settings = self.presets.setdefault("settings", {})
        i18n.set_language(self.settings.get("language", "en"))

        self.geometry("1250x900")
        self.minsize(1000, 720)
        self._set_icon()
        self._logo_img = self._load_logo()

        self._init_vars()
        self.runs = []                 # plotted runs (for overlay and export)
        self.queue = queue.Queue()
        self.worker = None
        self.side = self.right = None
        self._build_ui()

    # ---------------- setup ----------------

    def _set_icon(self):
        """Use icon.ico / icon.png next to this script, if present.
        Applies to the main window and every dialog it opens."""
        try:
            if sys.platform == "win32" and os.path.exists(ICON_ICO):
                self.iconbitmap(default=ICON_ICO)
            elif os.path.exists(ICON_PNG):
                self._icon_img = tk.PhotoImage(file=ICON_PNG)   # keep a reference
                self.iconphoto(True, self._icon_img)
        except tk.TclError as exc:
            print(f"Could not load app icon: {exc}")

    def _load_logo(self):
        if not os.path.exists(LOGO_PNG):
            return None
        try:
            return tk.PhotoImage(file=LOGO_PNG)
        except tk.TclError as exc:
            print(f"Could not load logo: {exc}")
            return None

    def _init_vars(self):
        """Values that must survive a language switch (the widgets are rebuilt)."""
        self.selection = {key: tk.StringVar() for key, _ in CATEGORIES}
        self.lang_var = tk.StringVar(value=i18n.LANGUAGES[i18n.get_language()])
        self.atm_v = {
            "altitude": tk.StringVar(value="0"),
            "temperature": tk.StringVar(value="25"),
            "rho": tk.StringVar(value=f"{m.RHO:.4g}"),
        }
        self.mode = tk.StringVar(value="airspeed")
        self.v = {
            "as_throttle": tk.StringVar(value="43"),
            "as_vmax": tk.StringVar(value="20"),
            "th_min": tk.StringVar(value="10"),
            "th_max": tk.StringVar(value="100"),
            "th_airspeed": tk.StringVar(value="0"),
            "points": tk.StringVar(value="20"),
            # competition / fuse limit on battery current, remembered between sessions ("" = none)
            "current_limit": tk.StringVar(value=str(self.settings.get("current_limit", ""))),
        }
        self.overlay = tk.BooleanVar(value=False)

    def _build_ui(self):
        """(Re)build every widget in the current language."""
        for frame in (self.side, self.right):
            if frame is not None:
                frame.destroy()
        self.title(t("app.title"))
        self.combos = {}
        self._build_controls()
        self._build_plot()
        self._set_status(self._summary(self.runs[-1]) if self.runs else t("status.ready"))
        self._refresh_combos()
        self._update_mode()

    def _change_language(self, _event=None):
        code = next(c for c, name in i18n.LANGUAGES.items() if name == self.lang_var.get())
        if code == i18n.get_language():
            return
        if self.worker and self.worker.is_alive():
            self.lang_var.set(i18n.LANGUAGES[i18n.get_language()])
            messagebox.showinfo(t("dlg.busy"), t("dlg.busy_msg"), parent=self)
            return
        i18n.set_language(code)
        self.settings["language"] = code
        m.save_presets(self.presets)
        self.after_idle(self._build_ui)   # don't destroy the combobox inside its own event

    # ---------------- layout ----------------

    def _build_controls(self):
        side = self.side = ttk.Frame(self, padding=10)
        side.pack(side="left", fill="y")

        # logo first, at the bottom, so the status box can't push it off-screen
        if self._logo_img is not None:
            tk.Label(side, image=self._logo_img, background="white", borderwidth=0).pack(
                side="bottom", fill="x", pady=(8, 0), ipady=6)

        # --- language ---
        lang = ttk.Frame(side)
        lang.pack(fill="x", pady=(0, 8))
        ttk.Label(lang, text=t("lang.label")).pack(side="left")
        lang_cb = ttk.Combobox(lang, textvariable=self.lang_var, state="readonly", width=10,
                               values=list(i18n.LANGUAGES.values()))
        lang_cb.pack(side="right")
        lang_cb.bind("<<ComboboxSelected>>", self._change_language)

        # --- components ---
        comp = ttk.LabelFrame(side, text=t("frame.config"), padding=8)
        comp.pack(fill="x")
        row = 0
        for i, (key, cls) in enumerate(CATEGORIES):
            ttk.Label(comp, text=t("cat." + key)).grid(row=row, column=0, columnspan=4, sticky="w",
                                                      pady=(6 if i else 0, 0))
            combo = ttk.Combobox(comp, textvariable=self.selection[key], state="readonly", width=30)
            combo.grid(row=row + 1, column=0, sticky="we")
            self.combos[key] = combo
            ttk.Button(comp, text=t("btn.new"), width=7,
                       command=lambda k=key: self._new_preset(k)).grid(row=row + 1, column=1, padx=(4, 0))
            ttk.Button(comp, text=t("btn.edit"), width=7,
                       command=lambda k=key: self._edit_preset(k)).grid(row=row + 1, column=2, padx=(2, 0))
            ttk.Button(comp, text=t("btn.delete"), width=7,
                       command=lambda k=key: self._delete_preset(k)).grid(row=row + 1, column=3, padx=(2, 0))
            row += 2
            if key == "propellers":
                # which airfoils the selected propeller uses (set in its preset)
                self.prop_info = ttk.Label(comp, font=("TkDefaultFont", 8), foreground="grey")
                self.prop_info.grid(row=row, column=0, columnspan=4, sticky="w")
                combo.bind("<<ComboboxSelected>>", lambda e: self._update_prop_info())
                row += 1

        # airfoil library: import / rescan the Airfoils folder
        ttk.Label(comp, text=t("cat.airfoils")).grid(row=row, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.lib_info = ttk.Label(comp)
        self.lib_info.grid(row=row + 1, column=0, sticky="w")
        ttk.Button(comp, text=t("btn.import"), command=self._import_airfoil).grid(
            row=row + 1, column=1, columnspan=2, padx=(4, 0), sticky="we")
        ttk.Button(comp, text="↻", width=4, command=self._refresh_combos).grid(row=row + 1, column=3, padx=(2, 0))

        # --- atmosphere ---
        atm = ttk.LabelFrame(side, text=t("frame.atmosphere"), padding=8)
        atm.pack(fill="x", pady=(10, 0))
        for r, key in enumerate(("rho", "altitude", "temperature")):
            ttk.Label(atm, text=t("atm." + key)).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(atm, textvariable=self.atm_v[key], width=10).grid(row=r, column=1, sticky="e", padx=(10, 0))
        atm.columnconfigure(0, weight=1)
        abtn = ttk.Frame(atm)
        abtn.grid(row=3, column=0, columnspan=2, sticky="we", pady=(6, 0))
        ttk.Button(abtn, text=t("btn.density"), command=self._compute_density).pack(
            side="left", fill="x", expand=True)
        ttk.Button(abtn, text=t("btn.isa"), command=self._isa_day).pack(side="left", padx=(4, 0))
        ttk.Label(atm, text=t("atm.hint"), foreground="grey", font=("TkDefaultFont", 8),
                  wraplength=320).grid(row=4, column=0, columnspan=2, sticky="w")

        # --- sweep ---
        sweep = ttk.LabelFrame(side, text=t("frame.sweep"), padding=8)
        sweep.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(sweep, text=t("sweep.airspeed"), value="airspeed", variable=self.mode,
                        command=self._update_mode).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(sweep, text=t("sweep.throttle"), value="throttle", variable=self.mode,
                        command=self._update_mode).grid(row=0, column=1, sticky="w")

        self.as_frame = ttk.Frame(sweep)
        self._field(self.as_frame, 0, t("sweep.throttle_pct"), "as_throttle")
        self._field(self.as_frame, 1, t("sweep.vmax"), "as_vmax")
        self.th_frame = ttk.Frame(sweep)
        self._field(self.th_frame, 0, t("sweep.tmin"), "th_min")
        self._field(self.th_frame, 1, t("sweep.tmax"), "th_max")
        self._field(self.th_frame, 2, t("sweep.airspeed_ms"), "th_airspeed")
        for fr in (self.as_frame, self.th_frame):
            fr.grid(row=1, column=0, columnspan=2, sticky="we", pady=(6, 0))
        common = ttk.Frame(sweep)
        common.grid(row=2, column=0, columnspan=2, sticky="we")
        self._field(common, 0, t("sweep.points"), "points")
        self._field(common, 1, t("sweep.limit"), "current_limit")
        ttk.Label(common, text=t("sweep.limit_hint"), foreground="grey", font=("TkDefaultFont", 8),
                  wraplength=320).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(sweep, text=t("sweep.overlay"), variable=self.overlay).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # --- actions ---
        act = ttk.Frame(side)
        act.pack(fill="x", pady=(10, 0))
        self.run_btn = ttk.Button(act, text=t("btn.run"), command=self._run)
        self.run_btn.pack(side="left", fill="x", expand=True)
        if self.worker and self.worker.is_alive():
            self.run_btn.state(["disabled"])
        ttk.Button(act, text=t("btn.clear"), command=self._clear).pack(side="left", padx=4)
        ttk.Button(act, text=t("btn.export"), command=self._export).pack(side="left")

        self.progress = ttk.Progressbar(side, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 0))

        self.status = tk.Text(side, height=7, width=44, wrap="word", relief="flat",
                              background=self.cget("background"), font=("TkDefaultFont", 9))
        self.status.pack(fill="both", expand=True, pady=(8, 0))

    def _field(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=self.v[key], width=10).grid(row=row, column=1, sticky="e", padx=(10, 0))
        parent.columnconfigure(0, weight=1)

    def _build_plot(self):
        right = self.right = ttk.Frame(self, padding=(0, 10, 10, 10))
        right.pack(side="left", fill="both", expand=True)
        self.fig = Figure(figsize=(8, 8), constrained_layout=True)
        self.ax_t, self.ax_r, self.ax_i = self.fig.subplots(3, 1, sharex=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        NavigationToolbar2Tk(self.canvas, right).update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self._redraw()

    def _update_mode(self):
        if self.mode.get() == "airspeed":
            self.th_frame.grid_remove()
            self.as_frame.grid()
        else:
            self.as_frame.grid_remove()
            self.th_frame.grid()

    def _set_status(self, text):
        self.status.configure(state="normal")
        self.status.delete("1.0", "end")
        self.status.insert("1.0", text)
        self.status.configure(state="disabled")

    # ---------------- presets ----------------

    def _refresh_combos(self):
        for key, _ in CATEGORIES:
            names = sorted(self.presets.get(key, {}))
            self.combos[key]["values"] = names
            if self.selection[key].get() not in names:
                self.selection[key].set(names[0] if names else "")
        airfoils = m.list_airfoils()
        self.lib_info.configure(text=t("lib.count", n=len(airfoils)))
        self._update_prop_info()
        if not airfoils:
            self._set_status(t("status.no_airfoils", folder=m.AIRFOIL_DIR))

    def _update_prop_info(self):
        prop = self.presets.get("propellers", {}).get(self.selection["propellers"].get())
        if not prop:
            self.prop_info.configure(text="")
            return
        root, tip = prop.get("root_airfoil", ""), prop.get("tip_airfoil", "")
        if tip and tip != root:
            text = t("prop.airfoil_two", root=root or "?", tip=tip)
        else:
            text = t("prop.airfoil_one", root=root or "?")
        available = set(m.list_airfoils())
        missing = [n for n in (root, tip) if n and n not in available]
        if missing:
            text += "   " + t("prop.missing", names=", ".join(missing))
        self.prop_info.configure(text=text, foreground="#b03030" if missing or not root else "grey")

    def _cls(self, key):
        return next(c for k, c in CATEGORIES if k == key)

    def _store(self, key, data, old_name=None):
        group = self.presets.setdefault(key, {})
        if data["name"] != old_name and data["name"] in group:
            if not messagebox.askyesno(t("dlg.overwrite"), t("dlg.overwrite_msg", name=data["name"]), parent=self):
                return
        if old_name and old_name != data["name"]:
            group.pop(old_name, None)
        group[data["name"]] = data
        m.save_presets(self.presets)
        self._refresh_combos()
        self.selection[key].set(data["name"])
        self._update_prop_info()

    def _new_preset(self, key):
        current = self.presets.get(key, {}).get(self.selection[key].get())
        template = dict(current, name=current["name"] + t("copy_suffix")) if current else None
        dlg = PresetDialog(self, self._cls(key), t("new." + key), template)
        if dlg.result:
            self._store(key, dlg.result)

    def _edit_preset(self, key):
        name = self.selection[key].get()
        if not name:
            return
        dlg = PresetDialog(self, self._cls(key), t("edit.title", name=name), self.presets[key][name])
        if dlg.result:
            self._store(key, dlg.result, old_name=name)

    def _delete_preset(self, key):
        name = self.selection[key].get()
        if name and messagebox.askyesno(t("dlg.delete"), t("dlg.delete_msg", name=name), parent=self):
            self.presets[key].pop(name, None)
            m.save_presets(self.presets)
            self._refresh_combos()

    # ---------------- airfoil import ----------------

    def _import_airfoil(self):
        """Import an airfoil folder (one polar file per Reynolds number), or a parent
        folder whose subfolders are each an airfoil."""
        folder = filedialog.askdirectory(parent=self, title=t("dlg.pick_folder"), mustexist=True)
        if not folder:
            return
        folder = os.path.normpath(folder)

        if m.polar_files_in(folder):
            jobs = [(folder, True)]            # (folder, ask for a name)
        else:
            subs = sorted(os.path.join(folder, d) for d in os.listdir(folder)
                          if os.path.isdir(os.path.join(folder, d)) and m.polar_files_in(os.path.join(folder, d)))
            if not subs:
                messagebox.showerror(t("dlg.no_polars"), t("dlg.no_polars_msg", folder=folder), parent=self)
                return
            names = ", ".join(os.path.basename(s) for s in subs)
            if not messagebox.askyesno(t("dlg.import_many"),
                                       t("dlg.import_many_msg", n=len(subs), names=names), parent=self):
                return
            jobs = [(s, False) for s in subs]

        imported, problems = [], []
        for path, ask_name in jobs:
            try:
                result = self._import_one_folder(path, ask_name)
            except Exception as exc:
                problems.append(f"{os.path.basename(path)}: {exc}")
                continue
            if result:
                imported.append(result)

        self._refresh_combos()
        lines = [t("status.imported", name=af.name, res=", ".join(f"{r:,}" for r in af.re_values))
                 for af in imported]
        if problems:
            lines += ["", t("status.skipped")] + problems
            messagebox.showwarning(t("dlg.skipped"), "\n".join(problems), parent=self)
        if lines:
            self._set_status("\n".join(lines))

    def _import_one_folder(self, folder, ask_name):
        default = re.sub(r"[^\w\-. ]", "_", os.path.basename(folder))
        if ask_name:
            name = simpledialog.askstring(t("dlg.airfoil_name"), t("dlg.airfoil_name_msg"),
                                          initialvalue=default, parent=self)
            if not name:
                return None
            name = re.sub(r"[^\w\-. ]", "_", name.strip())
        else:
            name = default

        files = {}
        for p in m.polar_files_in(folder):
            re_num = m.guess_reynolds(p) or simpledialog.askinteger(
                t("dlg.reynolds"), t("dlg.reynolds_msg", name=name, file=os.path.basename(p)),
                parent=self, minvalue=1)
            if not re_num:
                return None
            if re_num in files:
                raise ValueError(t("err.duplicate_re", re=re_num, a=os.path.basename(files[re_num]),
                                   b=os.path.basename(p)))
            files[re_num] = p

        target = os.path.normpath(os.path.join(m.AIRFOIL_DIR, name))
        replace = False
        if m.airfoil_exists(name) and target != folder:
            if not messagebox.askyesno(t("dlg.airfoil_exists"), t("dlg.airfoil_exists_msg", name=name),
                                       parent=self):
                return None
            replace = True
        return m.import_airfoil(name, files, replace=replace)

    # ---------------- atmosphere ----------------

    def _atm_inputs(self):
        try:
            alt = float(self.atm_v["altitude"].get())
            temp = float(self.atm_v["temperature"].get())
        except ValueError:
            raise ValueError(t("err.alt_temp"))
        return alt, temp

    def _compute_density(self):
        try:
            alt, temp = self._atm_inputs()
            atm = m.atmosphere_from(alt, temp)
        except ValueError as exc:
            messagebox.showerror(t("dlg.atmosphere"), str(exc), parent=self)
            return
        self.atm_v["rho"].set(f"{atm.rho:.4f}")

    def _isa_day(self):
        try:
            alt, _ = self._atm_inputs()
            self.atm_v["temperature"].set(f"{m.isa_temperature_c(alt):.1f}")
        except ValueError as exc:
            messagebox.showerror(t("dlg.atmosphere"), str(exc), parent=self)
            return
        self._compute_density()

    def _atmosphere(self):
        alt, temp = self._atm_inputs()
        try:
            rho = float(self.atm_v["rho"].get())
        except ValueError:
            raise ValueError(t("err.number", label=t("atm.rho")))
        return m.atmosphere_from(alt, temp, rho=rho)

    # ---------------- running ----------------

    def _num(self, key, label, lo=None, hi=None):
        try:
            val = float(self.v[key].get())
        except ValueError:
            raise ValueError(t("err.number", label=label))
        if (lo is not None and val < lo) or (hi is not None and val > hi):
            raise ValueError(t("err.range", label=label, lo=lo, hi=hi))
        return val

    def _run(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            comps = {}
            for key, cls in CATEGORIES:
                name = self.selection[key].get()
                if not name:
                    raise ValueError(t("sel." + key))
                comps[key] = m.from_preset(cls, self.presets[key][name])
            airfoil = m.prop_airfoil(comps["propellers"])
            atm = self._atmosphere()
            n = int(self._num("points", t("sweep.points"), 2, 500))
            limit_text = self.v["current_limit"].get().strip()
            limit = self._num("current_limit", t("sweep.limit"), 0.1, 10000) if limit_text else None
            if self.settings.get("current_limit", "") != limit_text:
                self.settings["current_limit"] = limit_text
                m.save_presets(self.presets)
            mode = self.mode.get()
            if mode == "airspeed":
                params = dict(throttle=self._num("as_throttle", t("sweep.throttle_pct"), 0, 100) / 100,
                              v_max=self._num("as_vmax", t("sweep.vmax"), 0.1, 300), n=n)
            else:
                params = dict(airspeed=self._num("th_airspeed", t("sweep.airspeed_ms"), 0, 300),
                              t_min=self._num("th_min", t("sweep.tmin"), 0, 100) / 100,
                              t_max=self._num("th_max", t("sweep.tmax"), 0, 100) / 100, n=n)
        except Exception as exc:
            messagebox.showerror(t("dlg.cant_run"), str(exc), parent=self)
            return

        prop, motor, bat = comps["propellers"], comps["motors"], comps["batteries"]
        label = f"{prop.name} · {motor.name} · {bat.name} · {airfoil.name}"
        if mode == "airspeed":
            label += f" @ {params['throttle'] * 100:.0f}%"
        else:
            label += f" @ {params['airspeed']:g} m/s"
        label += f", ρ={atm.rho:.3f}"

        self.progress.configure(maximum=n, value=0)
        self.run_btn.state(["disabled"])
        self._set_status(t("status.running_" + mode, label=label))

        def work():
            try:
                fn = m.airspeed_sweep if mode == "airspeed" else m.throttle_sweep
                pts = fn(prop, airfoil, motor, bat, atm=atm,
                         progress=lambda i: self.queue.put(("progress", i)), **params)
                self.queue.put(("done", dict(mode=mode, label=label, points=pts, motor=motor, atm=atm,
                                             limit=limit)))
            except Exception as exc:
                self.queue.put(("error", exc))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.after(50, self._poll)

    def _poll(self):
        finished = False
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self.progress.configure(value=payload)
                elif kind == "done":
                    finished = True
                    self._add_run(payload)
                elif kind == "error":
                    finished = True
                    messagebox.showerror(t("dlg.model_error"), str(payload), parent=self)
                    self._set_status(t("status.error", error=payload))
        except queue.Empty:
            pass
        if finished:
            self.run_btn.state(["!disabled"])
        else:
            self.after(50, self._poll)

    def _add_run(self, run):
        if not self.overlay.get() or (self.runs and self.runs[-1]["mode"] != run["mode"]):
            self.runs = []
        self.runs.append(run)
        self._redraw()
        self._set_status(self._summary(run))

    def _summary(self, run):
        pts, motor = run["points"], run["motor"]
        is_airspeed = run["mode"] == "airspeed"
        unit = "m/s" if is_airspeed else "%"

        def xval(p):
            return p.airspeed if is_airspeed else p.throttle * 100

        best = max(pts, key=lambda p: p.thrust)
        lines = [run["label"], "",
                 t("sum.max_thrust", T=best.thrust, g=best.thrust / 9.81 * 1000, x=xval(best), unit=unit),
                 t("sum.detail", rpm=best.rpm, im=best.I_motor, ib=best.I_battery),
                 t("sum.power", p=best.shaft_power, mach=best.tip_mach)]
        over_i = [p for p in pts if p.I_motor > motor.max_current]
        over_p = [p for p in pts if p.shaft_power > motor.max_power]
        if over_i:
            lines.append(t("sum.over_current", lim=motor.max_current, x=xval(over_i[0]), unit=unit))
        if over_p:
            lines.append(t("sum.over_power", lim=motor.max_power, x=xval(over_p[0]), unit=unit))
        limit = run.get("limit")
        if limit:
            peak = max(p.I_battery for p in pts)
            first_over = next((i for i, p in enumerate(pts) if p.I_battery > limit), None)
            if first_over is None:
                lines.append(t("sum.within_limit", lim=limit, peak=peak))
            else:
                lines.append(t("sum.over_limit", lim=limit, x=xval(pts[first_over]), unit=unit))
                if not is_airspeed and first_over > 0:
                    # throttle sweep: interpolate where battery current crosses the limit
                    a, b = pts[first_over - 1], pts[first_over]
                    f = (limit - a.I_battery) / (b.I_battery - a.I_battery)
                    lines.append(t("sum.limit_throttle", x=xval(a) + f * (xval(b) - xval(a)),
                                   T=a.thrust + f * (b.thrust - a.thrust)))
        if max(p.tip_mach for p in pts) > 0.7:
            lines.append(t("sum.mach"))
        wm = [p for p in pts if p.thrust < 0]
        if wm:
            lines.append(t("sum.windmill", x=xval(wm[0]), unit=unit))
        return "\n".join(lines)

    # ---------------- plotting ----------------

    def _redraw(self):
        for ax in (self.ax_t, self.ax_r, self.ax_i):
            ax.clear()
            ax.grid(True, alpha=0.3)
        mode = self.runs[-1]["mode"] if self.runs else self.mode.get()

        for run in self.runs:
            pts = run["points"]
            x = [p.airspeed for p in pts] if mode == "airspeed" else [p.throttle * 100 for p in pts]
            line, = self.ax_t.plot(x, [p.thrust for p in pts], "-o", ms=3, label=run["label"])
            color = line.get_color()
            self.ax_r.plot(x, [p.rpm for p in pts], "-o", ms=3, color=color)
            self.ax_i.plot(x, [p.I_motor for p in pts], "-o", ms=3, color=color)
            self.ax_i.plot(x, [p.I_battery for p in pts], ":", color=color)

        if self.runs:
            motor = self.runs[-1]["motor"]
            self.ax_i.axhline(motor.max_current, color="black", linestyle="--", linewidth=1,
                              label=t("plot.max_current", name=motor.name, amps=motor.max_current))
            for limit in sorted({r["limit"] for r in self.runs if r.get("limit")}):
                self.ax_i.axhline(limit, color="#c0392b", linestyle="-.", linewidth=1.5,
                                  label=t("plot.limit", amps=limit))
            self.ax_i.plot([], [], "k-", label=t("plot.motor_current"))
            self.ax_i.plot([], [], "k:", label=t("plot.battery_current"))
            self.ax_i.legend(fontsize=8, loc="best")
            self.ax_t.legend(fontsize=8, loc="best")
        self.ax_t.axhline(0, color="grey", linewidth=0.8)
        self.ax_t.set_ylabel(t("plot.thrust"))
        self.ax_r.set_ylabel(t("plot.rpm"))
        self.ax_i.set_ylabel(t("plot.current"))
        self.ax_i.set_xlabel(t("plot.x_" + mode))
        self.ax_t.set_title(t("plot.title_" + mode))
        self.canvas.draw_idle()

    def _clear(self):
        self.runs = []
        self._redraw()

    def _export(self):
        if not self.runs:
            messagebox.showinfo(t("dlg.nothing_export"), t("dlg.nothing_export_msg"), parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")], initialfile=t("file.sweep_csv"))
        if not path:
            return
        rows = []
        for run in self.runs:
            for r in m.to_rows(run["points"]):
                rows.append({"run": run["label"], "air_density": run["atm"].rho,
                             "current_limit": run.get("limit") or "", **r})
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self._set_status(t("status.exported", n=len(rows), path=path))


if __name__ == "__main__":
    if sys.platform == "win32":
        # Without this, Windows shows the Python icon in the taskbar instead of ours.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    App().mainloop()
