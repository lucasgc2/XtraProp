from dataclasses import dataclass
import numpy as np

# ------------ CONSTANTS -------------------------

RHO = 1.184 #density of air
MU = 1.81e-5 #viscosity of air
MACH = 343.0 #speed of sound

# ------------ LIST AND CLASSES ------------------

@dataclass
class Airfoil:
    name: str
    re_range: [50000, 100000, 200000]

#list of airfoils:
afl_naca2412 = Airfoil(name = "naca2412",re_range = [50000, 100000, 200000])

selectedAirfoil = afl_naca2412

@dataclass
class Motor:
    name: str
    KV: float #velocity constant, rpm/V
    R_motor: float #internal resistance
    I_loadfree: float
    max_current: float
    max_power: float
    weight_g: float

motor_2027 = Motor(name="EMAX GT2820/06", KV=985.0, R_motor=0.055, I_loadfree=1.8, max_current=45, max_power=650, weight_g = 140)

@dataclass
class Battery:
    cells: int
    nominal_voltage: float
    max_voltage: float
    capacity_mah: int
    discharge_c: int
    internal_resistance: float

bat = Battery(cells=3, nominal_voltage=11.1, max_voltage=12.6, capacity_mah = 3300, discharge_c = 45, internal_resistance = 0.005)


@dataclass
class Propeller:
    diameter_inch: float
    r_hub: float
    root_chord: float
    tip_chord: float
    root_pitch: float
    tip_pitch: float
    num_elm: int = 20 #default 20 segments

    def __post_init__(self):
        r_tip = (self.diameter_inch * 0.254) / 2
        self.r_stations = np.linspace(self.r_hub, r_tip, self.num_elm)
        self.chord_distrib = np.linspace(self.root_chord, self.tip_chord, self.num_elm)
        self.twist_distrib = np.linspace(self.root_pitch, self.tip_pitch, self.num_elm)

prop_10x6 = Propeller(
    diameter_inch = 10,
    r_hub = 0.05,
    root_chord = 0.018,
    tip_chord = 0.008,
    root_pitch = np.radians(25.0),
    tip_pitch = np.radians(8.0),
    num_elm = 5
)

#-------------- FUNCTIONS --------------------------

airfoilPath = f"./airfoils/{afl_naca2412.name}/re"

def getRe():
    #i don't know how to get this yet

def getCl(alpha):
    for i in range(len(selectedAirfoil.re_range)):
        dat = np.loadtxt(airfoilPath + selectedAirfoil.re_range[i] + ".csv", delimiter = ',', skiprows = 11) #load data and skip the first 11 rows which only contain names



print(f"Generated {len(prop_10x6.r_stations)} radial stations!")
