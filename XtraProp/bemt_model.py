"""Propeller (BEMT) + motor + battery performance model.

No global "selected" objects: every function takes the propeller, airfoil,
motor and battery it should use, so the GUI (or any script) can mix and match.
"""
from dataclasses import dataclass, asdict, field, fields
import json
import math
import os
import re
import shutil

import numpy as np
from scipy.optimize import brentq

from i18n import t


# ------------ CONSTANTS -------------------------

RHO = 1.184             # density of air [kg/m^3]
MU = 1.81e-5            # dynamic viscosity of air [Pa.s]
SPEED_OF_SOUND = 343.0  # [m/s]
PI = math.pi
INCH = 0.0254           # [m]

BEMT_TOL = 1e-5         # convergence tolerance on induced velocities [m/s]
BEMT_ITERATIONS = 200
BEMT_RELAX = 0.5        # under-relaxation for the induced-velocity update

# Below the lowest Reynolds number in an airfoil's polars, drag is scaled as Re^exponent
# (QPROP's low-Re law). Set to 0 to hold drag constant instead (the old behaviour).
LOW_RE_DRAG_EXPONENT = -0.5
DEFAULT_ESC_EFFICIENCY = 0.95   # battery power = motor electrical power / ESC efficiency
CURRENT_MARGIN = 0.15           # warn when predicted battery current is within 15% of the limit

R_AIR = 287.05          # specific gas constant of air [J/(kg.K)]
GAMMA = 1.4


@dataclass
class Atmosphere:
    rho: float = RHO                     # density [kg/m^3]
    mu: float = MU                       # dynamic viscosity [Pa.s]
    speed_of_sound: float = SPEED_OF_SOUND

    def __post_init__(self):
        if not 0.01 <= self.rho <= 5.0:
            raise ValueError(t("err.rho"))


def isa_pressure(altitude_m):
    """ISA static pressure [Pa], troposphere (valid up to 11 km)."""
    if not -500 <= altitude_m <= 11000:
        raise ValueError(t("err.altitude"))
    return 101325.0 * (1 - 2.25577e-5 * altitude_m) ** 5.25588


def isa_temperature_c(altitude_m):
    """ISA standard temperature [°C] at altitude."""
    return 15.0 - 0.0065 * altitude_m


def atmosphere_from(altitude_m, temperature_c, rho=None):
    """Atmosphere from altitude and actual air temperature.
    Viscosity from Sutherland's law, speed of sound from temperature.
    If rho is given it overrides the computed density."""
    T = temperature_c + 273.15
    if T <= 150:
        raise ValueError(t("err.temp_low"))
    density = isa_pressure(altitude_m) / (R_AIR * T) if rho is None else rho
    mu = 1.716e-5 * (T / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 110.4)
    return Atmosphere(rho=density, mu=mu, speed_of_sound=math.sqrt(GAMMA * R_AIR * T))


STANDARD_ATMOSPHERE = Atmosphere()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AIRFOIL_DIR = os.path.join(BASE_DIR, "Airfoils")
PRESET_FILE = os.path.join(BASE_DIR, "presets.json")


# ------------ COMPONENTS -------------------------

@dataclass
class Motor:
    name: str
    KV: float            # [rpm/V]
    R_motor: float       # winding resistance [ohm]
    I_loadfree: float    # no-load current [A]
    max_current: float   # [A]
    max_power: float     # [W]
    weight_g: float

    def __post_init__(self):
        if self.KV <= 0 or self.R_motor <= 0:
            raise ValueError(t("err.motor"))


@dataclass
class Battery:
    name: str
    cells: int
    nominal_voltage: float
    max_voltage: float
    capacity_mah: float
    discharge_c: float
    internal_resistance: float

    def __post_init__(self):
        if self.max_voltage <= 0:
            raise ValueError(t("err.bat_voltage"))
        if self.internal_resistance < 0:
            raise ValueError(t("err.bat_ir"))


@dataclass
class Propeller:
    name: str
    diameter_inch: float
    r_hub: float          # [m]
    root_chord: float     # [m]
    tip_chord: float      # [m]
    root_pitch: float     # blade angle at root [deg] (linear twist)
    tip_pitch: float      # blade angle at tip [deg] (linear twist)
    root_airfoil: str = field(default="", metadata={"airfoil": "root"})  # folder name in Airfoils/
    tip_airfoil: str = field(default="", metadata={"airfoil": "tip"})    # "" = same as root
    pitch_inch: float = 0.0   # >0: constant geometric pitch, overrides root/tip angles
    blades: int = 2
    num_elm: int = 20
    # Where the root airfoil starts blending into the tip airfoil, as a fraction of the tip
    # radius. 0 / 1 = blend over the whole blade (from the hub to the tip).
    blend_start: float = 0.0
    blend_end: float = 1.0
    # Optional blade-shape table: rows of [r/R, chord/R, blade angle (deg)], hub to tip.
    # When present it replaces the root/tip chord, blade angles and geometric pitch.
    geometry: list = field(default_factory=list, metadata={"hidden": True})
    geometry_source: str = field(default="", metadata={"hidden": True})

    def __post_init__(self):
        self.r_tip = self.diameter_inch * INCH / 2
        if not 0 < self.r_hub < self.r_tip:
            raise ValueError(t("err.hub", r_tip=self.r_tip))
        if not self.geometry and (self.root_chord <= 0 or self.tip_chord <= 0):
            raise ValueError(t("err.chord"))
        if self.blades < 1 or self.num_elm < 2:
            raise ValueError(t("err.blades"))
        if not 0 <= self.blend_start < self.blend_end <= 1:
            raise ValueError(t("err.blend"))

        edges = np.linspace(self.r_hub, self.r_tip, int(self.num_elm) + 1)
        self.r_mid = 0.5 * (edges[:-1] + edges[1:])
        self.dr = np.diff(edges)
        frac = (self.r_mid - self.r_hub) / (self.r_tip - self.r_hub)

        # airfoil blend weight: 0 = root airfoil, 1 = tip airfoil
        b0 = max(self.blend_start * self.r_tip, self.r_hub)
        b1 = max(self.blend_end * self.r_tip, b0 + 1e-9)
        self.span_frac = np.clip((self.r_mid - b0) / (b1 - b0), 0.0, 1.0)

        if self.geometry:
            table = np.asarray(self.geometry, dtype=float)
            validate_geometry(table)
            rr = self.r_mid / self.r_tip
            self.chord_mid = np.interp(rr, table[:, 0], table[:, 1]) * self.r_tip
            self.twist_mid = np.interp(rr, table[:, 0], table[:, 2])
            return

        self.chord_mid = self.root_chord + frac * (self.tip_chord - self.root_chord)
        if self.pitch_inch > 0:
            # helical blade: beta = atan(P / (2 pi r))
            self.twist_mid = np.degrees(np.arctan(self.pitch_inch * INCH / (2 * PI * self.r_mid)))
        else:
            self.twist_mid = self.root_pitch + frac * (self.tip_pitch - self.root_pitch)


# Airfoil names used in geometry files -> library folders to try, best first.
# APC's "APC12" section is equivalent to NACA 4412 (stated in APC's PE0 files).
AIRFOIL_ALIASES = {
    "E63": ["E63 Ncrit5", "Eppler E63"],
    "APC12": ["NACA4412 Ncrit5", "naca4412"],
    "NACA4412": ["NACA4412 Ncrit5", "naca4412"],
    "CLARKY": ["Clark Y Ncrit5", "Clark Y"],
}


def apc_airfoil_rule(root, tip):
    """APC files name E63 as the root section, but APC scales it to the much thicker root of the
    blade. Polars of the thin E63 then over-predict lift: in validation against UIUC wind-tunnel
    data, E63 -> NACA 4412 over-predicted static thrust by ~9% on average, while NACA 4412 along
    the whole blade was the best overall match (validation/validate.py). So for APC files with an
    E63 root, use the tip section along the whole blade."""
    if _norm(root) == "E63" and tip:
        return tip, tip
    return root, tip


def _norm(name):
    return re.sub(r"[\s_\-]", "", name).upper()


def match_airfoil(name, library):
    """Best library folder for an airfoil name from a geometry file, or "" if none fits."""
    if not name:
        return ""
    by_norm = {_norm(a): a for a in library}
    for candidate in AIRFOIL_ALIASES.get(_norm(name), []) + [name]:
        if candidate in library:
            return candidate
        if _norm(candidate) in by_norm:
            return by_norm[_norm(candidate)]
    for a in library:                           # e.g. "E63" -> "E63 Ncrit5"
        if _norm(a).startswith(_norm(name)) or _norm(name) in _norm(a):
            return a
    return ""


def validate_geometry(table):
    """Raise ValueError unless table is rows of [r/R, chord/R, angle] with r/R increasing in (0, 1]."""
    table = np.asarray(table, dtype=float)
    if table.ndim != 2 or table.shape[1] != 3 or len(table) < 2:
        raise ValueError(t("err.geom_shape"))
    r = table[:, 0]
    if np.any(np.diff(r) <= 0) or r[0] <= 0 or r[-1] > 1.002:
        raise ValueError(t("err.geom_radius"))
    if np.any(table[:, 1] < 0) or not np.any(table[:, 1] > 0):
        raise ValueError(t("err.geom_chord"))
    if np.any(np.abs(table[:, 2]) > 89):
        raise ValueError(t("err.geom_angle"))


def read_geometry_file(path):
    """Read a blade-shape file. Supports:
      - APC .PE0 files (apcprop.com technical data): STATION, CHORD and TWIST columns in inches/degrees,
        plus RADIUS, HUBTRA (hub transition) and AIRFOIL1/AIRFOIL2 lines.
      - UIUC propeller database *_geom.txt files and plain CSV/text tables: r/R, c/R, beta (deg).
    Returns a dict with: geometry (rows of [r/R, c/R, beta]), and when known diameter_inch,
    r_hub (m), blend_start, blend_end, root_airfoil, tip_airfoil (names as written in the file).
    """
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    info = {}

    if re.search(r"STATION", text) and re.search(r"TWIST", text) and re.search(r"RADIUS:", text):
        # --- APC PE0 ---
        radius = float(re.search(r"RADIUS:\s*([\d.]+)", text).group(1))
        hubtra = re.search(r"HUBTRA:\s*([\d.]+)", text)
        rows = []
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 9:
                try:
                    nums = [float(p) for p in parts[:9]]
                except ValueError:
                    continue
                rows.append((nums[0], nums[1], nums[8]))     # station, chord, twist
        if len(rows) < 2:
            raise ValueError(t("err.geom_shape"))
        rows = np.array(rows)
        r_start = float(hubtra.group(1)) if hubtra else 0.15 * radius
        keep = rows[:, 0] >= r_start - 1e-9
        start_row = [r_start, np.interp(r_start, rows[:, 0], rows[:, 1]), np.interp(r_start, rows[:, 0], rows[:, 2])]
        rows = np.vstack([start_row, rows[keep & (rows[:, 0] > r_start + 1e-9)]])
        # the last station can sit a hair past the quoted (rounded) radius: clip it to the tip
        table = np.column_stack([np.minimum(rows[:, 0] / radius, 1.0), rows[:, 1] / radius, rows[:, 2]])
        info.update(diameter_inch=2 * radius, r_hub=r_start * INCH)
        for key, name in (("AIRFOIL1", "root"), ("AIRFOIL2", "tip")):
            mt = re.search(key + r":\s*([\d.]+)\s*,\s*([^\s(]+)", text)
            if mt:
                info[f"{name}_airfoil"] = mt.group(2)
                info["blend_start" if name == "root" else "blend_end"] = min(float(mt.group(1)) / radius, 1.0)
        if "root_airfoil" in info and "tip_airfoil" in info:
            info["root_airfoil"], info["tip_airfoil"] = apc_airfoil_rule(info["root_airfoil"], info["tip_airfoil"])
        if info.get("blend_end", 1.0) <= info.get("blend_start", 0.0):
            info["blend_end"] = min(info["blend_start"] + 0.01, 1.0)
    else:
        # --- r/R, c/R, beta table (UIUC or plain) ---
        rows = []
        for line in text.splitlines():
            parts = [p for p in re.split(r"[,;\s]+", line.strip()) if p]
            if len(parts) < 3:
                continue
            try:
                rows.append([float(x) for x in parts[:3]])
            except ValueError:
                continue
        table = np.array(rows)
        if len(table) < 2:
            raise ValueError(t("err.geom_shape"))
        info["r_hub_frac"] = float(table[0, 0])

    validate_geometry(table)
    info["geometry"] = [[round(float(a), 5), round(float(b), 5), round(float(c), 3)] for a, b, c in table]
    return info


# ------------ PRESETS -------------------------

DEFAULT_PRESETS = {
    "motors": {
        "EMAX GT2820/06": dict(name="EMAX GT2820/06", KV=985.0, R_motor=0.055, I_loadfree=1.8,
                               max_current=45, max_power=650, weight_g=140),
    },
    "batteries": {
        "3S 3300mAh 45C": dict(name="3S 3300mAh 45C", cells=3, nominal_voltage=11.1, max_voltage=12.6,
                               capacity_mah=3300, discharge_c=45, internal_resistance=0.005),
    },
    "propellers": {
        "10 x 6": dict(name="10 x 6", diameter_inch=10, r_hub=0.05, root_chord=0.018, tip_chord=0.008,
                       root_pitch=25.0, tip_pitch=8.0, root_airfoil="naca2412", tip_airfoil="",
                       pitch_inch=0.0, blades=2, num_elm=20),
        "10 x 6 (constant pitch)": dict(name="10 x 6 (constant pitch)", diameter_inch=10, r_hub=0.012,
                                        root_chord=0.018, tip_chord=0.008, root_pitch=25.0, tip_pitch=8.0,
                                        root_airfoil="naca2412", tip_airfoil="",
                                        pitch_inch=6.0, blades=2, num_elm=20),
    },
}


def load_presets():
    """Read presets.json (created with defaults on first run)."""
    if not os.path.exists(PRESET_FILE):
        save_presets(DEFAULT_PRESETS)
    with open(PRESET_FILE, encoding="utf-8") as f:
        data = json.load(f)
    for key, default in DEFAULT_PRESETS.items():
        data.setdefault(key, dict(default))
    # presets saved before airfoils belonged to the propeller: give them one
    available = list_airfoils()
    fallback = "naca2412" if "naca2412" in available else (available[0] if available else "")
    changed = False
    for prop in data["propellers"].values():
        if "root_airfoil" not in prop:
            prop["root_airfoil"] = fallback
            prop.setdefault("tip_airfoil", "")
            changed = True
    if changed:
        save_presets(data)
    return data


def save_presets(presets):
    tmp = PRESET_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2)
    os.replace(tmp, PRESET_FILE)


# ------------ AIRFOILS -------------------------

_POLAR_FILE = re.compile(r"^re(\d+)\.(csv|txt|dat)$", re.IGNORECASE)
_airfoil_cache = {}


class Airfoil:
    """A set of polars (alpha, Cl, Cd) at several Reynolds numbers."""

    def __init__(self, name, polars):
        self.name = name
        self.re_values = sorted(polars)
        self.polars = [polars[r] for r in self.re_values]

    def coeffs(self, alpha_deg, re_num, span_frac=0.0):
        """Cl, Cd interpolated in alpha, then in Re.
        Above the highest tabulated Re the values are held constant. Below the lowest, Cl is held
        and Cd is scaled as (Re / Re_min)^LOW_RE_DRAG_EXPONENT, the low-Re drag law QPROP uses,
        because skin friction keeps rising as Re falls (small props run mostly below 50,000).
        span_frac is ignored: a single airfoil is the same along the whole blade."""
        cls = [np.interp(alpha_deg, p[:, 0], p[:, 1]) for p in self.polars]
        cds = [np.interp(alpha_deg, p[:, 0], p[:, 2]) for p in self.polars]
        cl = float(np.interp(re_num, self.re_values, cls))
        cd = float(np.interp(re_num, self.re_values, cds))
        re_min = self.re_values[0]
        if LOW_RE_DRAG_EXPONENT and 0 < re_num < re_min:
            cd *= (re_num / re_min) ** LOW_RE_DRAG_EXPONENT
        return cl, cd


class BlendedAirfoil:
    """Root airfoil at the hub, tip airfoil at the tip, linear blend of Cl and Cd in between.
    Acts like an Airfoil, so it can be passed anywhere an Airfoil is expected."""

    def __init__(self, root, tip):
        self.root = root
        self.tip = tip
        self.name = root.name if root is tip else f"{root.name} → {tip.name}"

    def coeffs(self, alpha_deg, re_num, span_frac=0.0):
        cl_r, cd_r = self.root.coeffs(alpha_deg, re_num)
        if self.tip is self.root:
            return cl_r, cd_r
        cl_t, cd_t = self.tip.coeffs(alpha_deg, re_num)
        w = min(max(span_frac, 0.0), 1.0)
        return cl_r + w * (cl_t - cl_r), cd_r + w * (cd_t - cd_r)


def read_polar(path):
    """Read alpha, Cl, Cd from an XFLR5 / XFOIL style file, skipping header lines."""
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = [p for p in re.split(r"[,;\s]+", line.strip()) if p]
            if len(parts) < 3:
                continue
            try:
                rows.append([float(x) for x in parts[:3]])
            except ValueError:
                continue
    if len(rows) < 2:
        raise ValueError(t("err.no_polar", file=os.path.basename(path)))
    arr = np.array(rows)
    arr = arr[np.argsort(arr[:, 0])]
    _, keep = np.unique(arr[:, 0], return_index=True)
    return arr[keep]


def _polar_files(name):
    folder = os.path.join(AIRFOIL_DIR, name)
    found = {}
    if os.path.isdir(folder):
        for fn in os.listdir(folder):
            mt = _POLAR_FILE.match(fn)
            if mt:
                found[int(mt.group(1))] = os.path.join(folder, fn)
    return found


def list_airfoils():
    if not os.path.isdir(AIRFOIL_DIR):
        return []
    return sorted(d for d in os.listdir(AIRFOIL_DIR) if _polar_files(d))


def load_airfoil(name, reload=False):
    if reload or name not in _airfoil_cache:
        files = _polar_files(name)
        if not files:
            raise FileNotFoundError(t("err.no_polar_files", name=name))
        _airfoil_cache[name] = Airfoil(name, {re_num: read_polar(p) for re_num, p in files.items()})
    return _airfoil_cache[name]


POLAR_EXTENSIONS = (".csv", ".txt", ".dat")
_RE_IN_NAME = re.compile(r"(?<![a-z])re[_\s=-]*(\d+(?:\.\d+)?)", re.IGNORECASE)
_RE_IN_HEADER = re.compile(r"\bRe\s*=\s*(\d+(?:\.\d+)?)\s*(e\s*6)?", re.IGNORECASE)


def _to_reynolds(text, millions_hint):
    value = float(text)
    # XFLR5/XFOIL write Re in millions ("Re0.050", "Re = 0.050 e 6")
    if millions_hint or value < 100:
        value *= 1e6
    return int(round(value))


def guess_reynolds(path):
    """Reynolds number from the file name (re50000, Re0.050) or the polar header.
    Returns None if it can't be found."""
    found = _RE_IN_NAME.search(os.path.splitext(os.path.basename(path))[0])
    if found:
        return _to_reynolds(found.group(1), False)
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            head = f.read(4000)
    except OSError:
        return None
    found = _RE_IN_HEADER.search(head)
    if found:
        return _to_reynolds(found.group(1), bool(found.group(2)))
    return None


def polar_files_in(folder):
    """Polar files directly inside a folder (not recursive)."""
    return sorted(os.path.join(folder, fn) for fn in os.listdir(folder)
                  if fn.lower().endswith(POLAR_EXTENSIONS) and os.path.isfile(os.path.join(folder, fn)))


def airfoil_exists(name):
    return bool(_polar_files(name))


def import_airfoil(name, files_by_re, replace=False):
    """Copy polar files into Airfoils/<name>/re<Re>.<ext>. files_by_re: {Re: path}.
    replace=True removes the airfoil's existing polar files first."""
    for path in files_by_re.values():
        read_polar(path)  # validate before copying anything
    folder = os.path.join(AIRFOIL_DIR, name)
    sources = {os.path.abspath(p) for p in files_by_re.values()}
    if replace:
        for old in _polar_files(name).values():
            if os.path.abspath(old) not in sources:
                os.remove(old)
    os.makedirs(folder, exist_ok=True)
    for re_num, path in files_by_re.items():
        ext = os.path.splitext(path)[1].lower() or ".csv"
        dest = os.path.join(folder, f"re{int(re_num)}{ext}")
        if os.path.abspath(path) != os.path.abspath(dest):
            shutil.copyfile(path, dest)
    return load_airfoil(name, reload=True)


# ------------ BEMT -------------------------

def calc_thrust(prop, airfoil, v_inf, omega, atm=STANDARD_ATMOSPHERE):
    """Blade element momentum theory, solved for induced velocities (valid at v_inf = 0).
    Returns (thrust [N], torque [Nm]). Negative torque = windmilling."""
    B, R = prop.blades, prop.r_tip
    RHO, MU = atm.rho, atm.mu
    T = Q = 0.0

    for r, dr, c, beta, frac in zip(prop.r_mid, prop.dr, prop.chord_mid, prop.twist_mid, prop.span_frac):
        vi = vt = 0.0
        for _ in range(BEMT_ITERATIONS):
            va = v_inf + vi
            vtan = omega * r - vt
            W = math.hypot(va, vtan)
            phi = math.atan2(va, vtan)
            Cl, Cd = airfoil.coeffs(beta - math.degrees(phi), RHO * W * c / MU, frac)

            sin_phi, cos_phi = math.sin(phi), math.cos(phi)
            Cn = Cl * cos_phi - Cd * sin_phi
            Ct = Cl * sin_phi + Cd * cos_phi

            f = 0.5 * B * (R - r) / (r * max(abs(sin_phi), 1e-6))     # Prandtl tip loss
            F = max(2.0 / PI * math.acos(min(math.exp(-f), 1.0)), 1e-3)

            dTdr = 0.5 * RHO * W**2 * B * c * Cn
            dQdr = 0.5 * RHO * W**2 * B * c * Ct * r

            disc = (v_inf / 2) ** 2 + dTdr / (4 * PI * r * RHO * F)
            vi_new = -v_inf / 2 + math.sqrt(max(disc, 0.0))
            vt_new = dQdr / (4 * PI * r**2 * RHO * F * max(v_inf + vi_new, 1e-6))
            vt_new = max(min(vt_new, 0.5 * omega * r), -0.5 * omega * r)

            converged = abs(vi_new - vi) < BEMT_TOL and abs(vt_new - vt) < BEMT_TOL
            vi += BEMT_RELAX * (vi_new - vi)
            vt += BEMT_RELAX * (vt_new - vt)
            if converged:
                break

        T += dTdr * dr
        Q += dQdr * dr
    return T, Q


# ------------ MOTOR / BATTERY -------------------------

@dataclass
class OperatingPoint:
    throttle: float
    airspeed: float
    thrust: float        # [N]
    torque: float        # [Nm]
    rpm: float
    I_motor: float       # [A]
    I_battery: float     # [A]
    shaft_power: float   # [W]
    elec_power: float    # battery output [W]
    prop_efficiency: float   # T*V / P_shaft (0 when static)
    tip_mach: float
    windmilling: bool


def motor_battery(prop, airfoil, motor, battery, throttle, airspeed, atm=STANDARD_ATMOSPHERE,
                  esc_efficiency=DEFAULT_ESC_EFFICIENCY):
    """Find the speed where motor torque equals propeller torque.
    esc_efficiency (0-1] scales battery current: the ESC draws motor power / efficiency."""
    if not 0 < esc_efficiency <= 1:
        raise ValueError(t("err.esc"))
    kv = motor.KV * 2 * PI / 60          # [rad/s per V]
    kt = 1.0 / kv                        # [Nm per A]
    V = throttle * battery.max_voltage   # ESC output voltage (simple PWM model)
    R = motor.R_motor + battery.internal_resistance

    if V <= 0:
        return OperatingPoint(throttle, airspeed, 0, 0, 0, 0, 0, 0, 0, 0, 0, False)

    def residual(omega):
        motor_torque = kt * ((V - omega / kv) / R - motor.I_loadfree)
        return motor_torque - calc_thrust(prop, airfoil, airspeed, omega, atm)[1]

    omega_lo, omega_hi = 1.0, kv * V
    windmilling = bool(residual(omega_hi) >= 0.0)
    if windmilling:
        omega = omega_hi     # prop needs no motor torque even at no-load speed
    elif residual(omega_lo) <= 0.0:
        omega = omega_lo     # motor cannot turn this prop at all
    else:
        omega = brentq(residual, omega_lo, omega_hi, xtol=1e-3)

    T, Q = calc_thrust(prop, airfoil, airspeed, omega, atm)
    T, Q = float(T), float(Q)
    I_motor = motor.I_loadfree + Q / kt if windmilling else (V - omega / kv) / R
    # PWM ESC: battery current = duty cycle x motor current, plus ESC losses
    # (when windmilling the motor feeds power back and the ESC loses a share of it)
    I_battery = throttle * I_motor / esc_efficiency if I_motor >= 0 else throttle * I_motor * esc_efficiency
    shaft = Q * omega
    eff = T * airspeed / shaft if shaft > 1e-9 and T > 0 else 0.0
    return OperatingPoint(
        throttle=throttle, airspeed=airspeed, thrust=T, torque=Q,
        rpm=omega * 60 / (2 * PI), I_motor=I_motor, I_battery=I_battery,
        shaft_power=shaft, elec_power=battery.max_voltage * I_battery,
        prop_efficiency=eff,
        tip_mach=math.hypot(omega * prop.r_tip, airspeed) / atm.speed_of_sound,
        windmilling=windmilling,
    )


# ------------ SWEEPS -------------------------

def throttle_sweep(prop, airfoil, motor, battery, airspeed, t_min, t_max, n,
                   atm=STANDARD_ATMOSPHERE, progress=None, esc_efficiency=DEFAULT_ESC_EFFICIENCY):
    pts = []
    for i, t in enumerate(np.linspace(t_min, t_max, n)):
        pts.append(motor_battery(prop, airfoil, motor, battery, float(t), airspeed, atm, esc_efficiency))
        if progress:
            progress(i + 1)
    return pts


def airspeed_sweep(prop, airfoil, motor, battery, throttle, v_max, n,
                   atm=STANDARD_ATMOSPHERE, progress=None, esc_efficiency=DEFAULT_ESC_EFFICIENCY):
    pts = []
    for i, v in enumerate(np.linspace(0.0, v_max, n)):
        pts.append(motor_battery(prop, airfoil, motor, battery, throttle, float(v), atm, esc_efficiency))
        if progress:
            progress(i + 1)
    return pts


def prop_airfoil(prop):
    """The (possibly blended) airfoil named in a propeller preset."""
    if not prop.root_airfoil:
        raise ValueError(t("err.no_root_airfoil", name=prop.name))
    available = list_airfoils()
    for name in {prop.root_airfoil, prop.tip_airfoil} - {""}:
        if name not in available:
            raise ValueError(t("err.airfoil_missing", name=name))
    root = load_airfoil(prop.root_airfoil)
    tip = load_airfoil(prop.tip_airfoil) if prop.tip_airfoil else root
    return BlendedAirfoil(root, tip)


def to_rows(points):
    """Operating points as CSV-ready dicts."""
    return [asdict(p) for p in points]


def from_preset(cls, data):
    """Build a component from a preset dict, ignoring unknown keys."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})
