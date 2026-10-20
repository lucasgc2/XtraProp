from dataclasses import dataclass, field
import matplotlib.pyplot as plt
import numpy as np
import math
import os
from scipy.optimize import brentq


# ------------ CONSTANTS -------------------------

RHO = 1.184             # density of air [kg/m^3]
MU = 1.81e-5            # dynamic viscosity of air [Pa.s]
SPEED_OF_SOUND = 343.0  # [m/s]
PI = math.pi
INCH = 0.0254           # [m]

BEMT_TOL = 1e-5         # convergence tolerance on induced velocities [m/s]
BEMT_ITERATIONS = 200
BEMT_RELAX = 0.5        # under-relaxation factor for the induced-velocity update

# ------------ INIT ------------------------------

airfoil_data_cache = {}
script_dir = os.path.dirname(os.path.abspath(__file__))

# ------------ LISTS AND CLASSES -----------------

@dataclass
class Airfoil:
    name: str
    re_range: tuple = (50000, 100000, 200000)


# list of airfoils:
afl_naca2412 = Airfoil(name="naca2412", re_range=(50000, 100000, 200000))

selectedAirfoil = afl_naca2412

for re_val in selectedAirfoil.re_range:  # file loading
    file_path = os.path.join(script_dir, "Airfoils", selectedAirfoil.name, f"re{re_val}.csv")
    airfoil_data_cache[re_val] = np.loadtxt(file_path, delimiter=',', skiprows=11)


@dataclass
class Motor:
    name: str
    KV: float           # velocity constant [rpm/V]
    R_motor: float      # winding resistance [ohm]
    I_loadfree: float   # no-load current [A]
    max_current: float  # [A]
    max_power: float    # [W]
    weight_g: float


motor_2027 = Motor(name="EMAX GT2820/06", KV=985.0, R_motor=0.055, I_loadfree=1.8,
                   max_current=45, max_power=650, weight_g=140)

selectedMotor = motor_2027


@dataclass
class Battery:
    cells: int
    nominal_voltage: float
    max_voltage: float
    capacity_mah: int
    discharge_c: int
    internal_resistance: float


bat = Battery(cells=3, nominal_voltage=11.1, max_voltage=12.6, capacity_mah=3300,
              discharge_c=45, internal_resistance=0.005)


@dataclass
class Propeller:
    name: str
    diameter_inch: float
    r_hub: float        # [m]
    root_chord: float   # [m]
    tip_chord: float    # [m]
    root_pitch: float   # blade angle at root [deg]
    tip_pitch: float    # blade angle at tip [deg]
    blades: int = 2
    num_elm: int = 20   # number of blade elements

    r_edges: np.ndarray = field(init=False, repr=False)
    r_mid: np.ndarray = field(init=False, repr=False)
    dr: np.ndarray = field(init=False, repr=False)
    chord_mid: np.ndarray = field(init=False, repr=False)
    twist_mid: np.ndarray = field(init=False, repr=False)

    def __post_init__(self):
        self.r_tip = (self.diameter_inch * INCH) / 2
        # element edges from hub to tip, evaluated at element midpoints
        self.r_edges = np.linspace(self.r_hub, self.r_tip, self.num_elm + 1)
        self.r_mid = 0.5 * (self.r_edges[:-1] + self.r_edges[1:])
        self.dr = np.diff(self.r_edges)
        # linear chord / twist from root to tip
        frac = (self.r_mid - self.r_hub) / (self.r_tip - self.r_hub)
        self.chord_mid = self.root_chord + frac * (self.tip_chord - self.root_chord)
        self.twist_mid = self.root_pitch + frac * (self.tip_pitch - self.root_pitch)


prop_10x6 = Propeller(
    name="10 x 6",
    blades=2,
    diameter_inch=10,
    r_hub=0.01,
    root_chord=0.018,
    tip_chord=0.008,
    root_pitch=80,
    tip_pitch=10,
    num_elm=20,
)

selectedProp = prop_10x6

# -------------- AIRFOIL LOOKUP --------------------------

def _polar_lookup(alpha_deg, re, column):
    """Interpolate a polar column (1 = Cl, 2 = Cd) in alpha, then in Re.
    Outside the tabulated alpha / Re range np.interp holds the end value."""
    re_range = selectedAirfoil.re_range
    values = [np.interp(alpha_deg, airfoil_data_cache[rv][:, 0], airfoil_data_cache[rv][:, column])
              for rv in re_range]
    return np.interp(re, re_range, values)


def getCl(alpha_deg, re):
    return _polar_lookup(alpha_deg, re, 1)


def getCd(alpha_deg, re):
    return _polar_lookup(alpha_deg, re, 2)

# ------------------- BEMT -------------------------------

def calc_thrust(v_inf, omega):
    """Blade element momentum theory, solved for induced velocities so it
    is well-defined in the static case (v_inf = 0).
    Returns (thrust [N], torque [Nm]). Negative torque = windmilling."""
    p = selectedProp
    B, R = p.blades, p.r_tip
    T = 0.0
    Q = 0.0

    for r, dr, c, beta in zip(p.r_mid, p.dr, p.chord_mid, p.twist_mid):
        vi = 0.0  # axial induced velocity at the disk [m/s]
        vt = 0.0  # tangential (swirl) induced velocity at the disk [m/s]

        for _ in range(BEMT_ITERATIONS):
            va = v_inf + vi
            vtan = omega * r - vt
            W = math.hypot(va, vtan)
            phi = math.atan2(va, vtan)
            alpha = beta - math.degrees(phi)

            re = RHO * W * c / MU
            Cl = getCl(alpha, re)
            Cd = getCd(alpha, re)

            sin_phi, cos_phi = math.sin(phi), math.cos(phi)
            Cn = Cl * cos_phi - Cd * sin_phi
            Ct = Cl * sin_phi + Cd * cos_phi

            # Prandtl tip-loss factor
            f = 0.5 * B * (R - r) / (r * max(abs(sin_phi), 1e-6))
            F = max(2.0 / PI * math.acos(min(math.exp(-f), 1.0)), 1e-3)

            # blade element loads per unit span
            dTdr = 0.5 * RHO * W**2 * B * c * Cn
            dQdr = 0.5 * RHO * W**2 * B * c * Ct * r

            # momentum theory: dT/dr = 4 pi r rho F (v_inf + vi) vi  -> solve quadratic for vi
            disc = (v_inf / 2) ** 2 + dTdr / (4 * PI * r * RHO * F)
            vi_new = -v_inf / 2 + math.sqrt(max(disc, 0.0))
            # angular momentum: dQ/dr = 4 pi r^2 rho F (v_inf + vi) vt
            vt_new = dQdr / (4 * PI * r**2 * RHO * F * max(v_inf + vi_new, 1e-6))
            vt_new = max(min(vt_new, 0.5 * omega * r), -0.5 * omega * r)

            converged = abs(vi_new - vi) < BEMT_TOL and abs(vt_new - vt) < BEMT_TOL
            vi = (1 - BEMT_RELAX) * vi + BEMT_RELAX * vi_new
            vt = (1 - BEMT_RELAX) * vt + BEMT_RELAX * vt_new
            if converged:
                break

        T += dTdr * dr
        Q += dQdr * dr

    return T, Q

# ---------------------- MOTOR / BATTERY -----------------------

def motorBattery(throttle, airspeed):
    """Find the rpm where motor torque equals propeller torque.
    Returns (thrust [N], rpm, motor current [A], battery current [A], tip Mach)."""
    kv = selectedMotor.KV * 2 * PI / 60      # [rad/s per V]
    kt = 1.0 / kv                            # [Nm per A]
    V = throttle * bat.max_voltage           # ESC output voltage (simple PWM model)
    R = selectedMotor.R_motor + bat.internal_resistance

    def motor_current(omega):
        return (V - omega / kv) / R

    def residual(omega):
        motor_torque = kt * (motor_current(omega) - selectedMotor.I_loadfree)
        return motor_torque - calc_thrust(airspeed, omega)[1]

    omega_lo = 1.0
    omega_hi = kv * V                        # ideal no-load speed

    if residual(omega_hi) >= 0.0:
        # prop needs no motor torque even at no-load speed: it is windmilling
        omega = omega_hi
    else:
        omega = brentq(residual, omega_lo, omega_hi, xtol=1e-3)

    T, Q = calc_thrust(airspeed, omega)
    if omega == omega_hi:
        I_motor = selectedMotor.I_loadfree + Q / kt   # windmilling: below no-load current
    else:
        I_motor = motor_current(omega)
    I_battery = throttle * I_motor
    tip_mach = math.hypot(omega * selectedProp.r_tip, airspeed) / SPEED_OF_SOUND
    rpm = omega * 60 / (2 * PI)
    return T, rpm, I_motor, I_battery, tip_mach

# -------------------------- GRAPHING AND DEBUG ----------------------------

def run_throttle_sweep(v_inf=0.0, num_datapoints=15):
    throttles = np.linspace(0.1, 1.0, num_datapoints)
    thrusts, rpms, currents = [], [], []

    print("Running throttle sweep...")
    for d in throttles:
        t, rpm, i_mot, _, _ = motorBattery(throttle=d, airspeed=v_inf)
        thrusts.append(t)
        rpms.append(rpm)
        currents.append(i_mot)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

    ax1.plot(throttles * 100, thrusts, 'b-o', linewidth=2)
    ax1.set_ylabel('Thrust (N)')
    ax1.set_title(f"{selectedMotor.name} + {selectedProp.name} "
                  f"({selectedAirfoil.name}) at {v_inf} m/s")
    ax1.grid(True)

    ax2.plot(throttles * 100, rpms, 'g-s', linewidth=2)
    ax2.set_ylabel('RPM')
    ax2.grid(True)

    ax3.plot(throttles * 100, currents, 'r-^', linewidth=2, label='Motor current')
    ax3.axhline(y=selectedMotor.max_current, color='black', linestyle='--',
                label=f'Max current ({selectedMotor.max_current} A)')
    ax3.set_xlabel('Throttle (%)')
    ax3.set_ylabel('Current (A)')
    ax3.grid(True)
    ax3.legend()

    plt.tight_layout()
    plt.show()


def run_airspeed_sweep(throttle, max_airspeed, num_datapoints):
    airspeeds = np.linspace(0.0, max_airspeed, num_datapoints)
    thrusts, currents, rpms = [], [], []

    print(f"Running airspeed sweep at {throttle * 100:.1f}% throttle up to {max_airspeed} m/s...")
    for v in airspeeds:
        t, rpm, i_mot, _, _ = motorBattery(throttle=throttle, airspeed=v)
        thrusts.append(t)
        currents.append(i_mot)
        rpms.append(rpm)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

    ax1.plot(airspeeds, thrusts, 'b-', linewidth=2, label='Thrust')
    ax1.axhline(0.0, color='grey', linewidth=0.8)
    ax1.set_ylabel('Thrust (N)')
    ax1.set_title(f'Performance at {throttle * 100:.0f}% throttle '
                  f'({selectedMotor.name} + {selectedProp.name})')
    ax1.grid(True)
    ax1.legend(loc='upper right')

    ax2.plot(airspeeds, rpms, 'g-', linewidth=2, label='RPM')
    ax2.set_ylabel('RPM')
    ax2.grid(True)
    ax2.legend(loc='upper right')

    ax3.plot(airspeeds, currents, 'r-', linewidth=2, label='Motor current')
    ax3.axhline(y=selectedMotor.max_current, color='black', linestyle='--',
                label=f'Max current ({selectedMotor.max_current} A)')
    ax3.set_xlabel('Airspeed (m/s)')
    ax3.set_ylabel('Current (A)')
    ax3.grid(True)
    ax3.legend(loc='upper right')

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    thrust, rpm, i_mot, i_bat, mach = motorBattery(throttle=0.6, airspeed=0.0)
    print(f"Static @60%: Thrust {thrust:.2f} N | RPM {rpm:.0f} | "
          f"Motor {i_mot:.2f} A | Battery {i_bat:.2f} A | Tip Mach {mach:.2f}")
    # run_throttle_sweep()
    run_airspeed_sweep(1, 20, 40)