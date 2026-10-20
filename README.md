# Propeller Performance

A desktop tool for predicting the thrust, rpm and current of an electric propulsion setup (motor + battery + propeller) across throttle and airspeed. It combines a blade element momentum theory (BEMT) propeller model with a simple DC motor and battery model, and wraps it in a bilingual (English / Spanish) GUI so the team can compare setups quickly.

## Features

- **Throttle sweeps** at a fixed airspeed and **airspeed sweeps** at a fixed throttle
- Plots of thrust, rpm, motor current and battery current, with run-to-run **overlay** for comparing setups
- **Presets** for motors, batteries and propellers, created and edited in the app and saved to `presets.json`
- **Root and tip airfoils** per propeller, blended along the span
- **Airfoil library** imported from XFLR5 / XFOIL polar files, one folder per airfoil
- **Atmosphere** settings: air density entered directly or computed from altitude and temperature
- **Competition current limit** checked against battery current, with the throttle at which it is reached
- Warnings for motor current and power ratings, high tip Mach number and windmilling
- **CSV export** of every operating point
- **English / Spanish** interface, switchable at any time

## Requirements

- Python 3.9 or newer, with Tkinter (included in the standard Python installers for Windows and macOS; on Linux install `python3-tk`)
- numpy, scipy and matplotlib

```bash
pip install numpy scipy matplotlib
```

## Project layout

```
prop_gui.py        The application (run this)
bemt_model.py      Propeller, motor and battery model; no GUI code
i18n.py            English and Spanish interface text
presets.json       Saved motors, batteries, propellers and settings (created on first run)
Airfoils/          Airfoil library: one folder per airfoil
  naca2412/
    re50000.csv
    re100000.csv
    re200000.csv
icon.ico           App icon for Windows (optional)
icon.png           App icon for macOS / Linux (optional)
logo_black.png     Team logo shown in the side panel (optional)
```

## Running

```bash
python prop_gui.py
```

On first run the app creates `presets.json` with an example motor (EMAX GT2820/06), battery (3S 3300 mAh) and two 10×6 propellers.

## Using the app

### 1. Choose a configuration

Pick a **motor**, **battery** and **propeller** from the dropdowns. The line under the propeller shows which airfoils it uses; it turns red if one of them is missing from the library.

Each dropdown has **New**, **Edit** and **Del** buttons. **New** opens a form pre-filled with a copy of the current selection, which is the quickest way to make a variant. Changes are saved to `presets.json` immediately.

| Component | Fields |
|---|---|
| Motor | KV (rpm/V), winding resistance (Ω), no-load current (A), max current (A), max power (W), weight (g) |
| Battery | cells, nominal voltage, full-charge voltage, capacity (mAh), C rating, internal resistance (Ω) |
| Propeller | diameter (in), hub radius (m), root and tip chord (m), root and tip blade angle (°), root and tip airfoil, geometric pitch (in), number of blades, number of blade elements |

**Propeller twist.** If *Geometric pitch* is greater than 0, the blade follows a true helix for that pitch (blade angle = atan(P / 2πr)) and the root/tip angles are ignored. Set it to 0 to use a linear twist between the root and tip angles instead.

**Chord** varies linearly from root to tip. For manufacturer props, take the chord near the root and near the tip from the manufacturer's geometry data (APC publishes these for its propellers).

**Airfoils.** The root airfoil is used at the hub, the tip airfoil at the tip, and lift and drag are blended linearly in between. Choose "(same as root)" for a single-airfoil blade.

### 2. Airfoil library

Click **Import…** and choose either:

- **an airfoil folder** containing one polar file per Reynolds number, or
- **a parent folder** whose subfolders are each an airfoil, to import them all at once.

Files are copied into `Airfoils/<name>/re<Reynolds>.csv`. The **↻** button rescans the folder if you add files by hand.

**Polar file format.** `.csv`, `.txt` or `.dat`, with the first three numeric columns being angle of attack (°), Cl and Cd. Header lines are skipped automatically, so XFLR5 CSV exports and XFOIL polar files work as they are. The Reynolds number is read from the file name (`re100000.csv`, or XFLR5's `..._Re0.100_...` in millions) or from the file header (`Re = 0.100 e 6`); if neither is found, the app asks for it.

Use at least three Reynolds numbers that cover your propeller's operating range. Outside the tabulated range of angle or Reynolds number, the nearest values are held constant.

### 3. Atmosphere

- Type the **air density** directly (default 1.184 kg/m³, sea level at 25 °C), or
- enter **altitude** and **temperature** and click **Density from alt + temp**, or
- click **ISA day** to use the standard-atmosphere temperature for that altitude.

Temperature also sets the air viscosity (used for Reynolds number) and the speed of sound (used for tip Mach).

### 4. Run a sweep

- **Airspeed sweep:** fixed throttle, airspeed from 0 to the maximum you set.
- **Throttle sweep:** fixed airspeed, throttle between the minimum and maximum you set.

**Points** sets how many operating points are calculated. A 20-point sweep takes about a second.

**Current limit (A)** is an optional battery-side limit, such as a competition fuse. It is remembered between sessions. Leave it blank for none.

Tick **Overlay on previous runs** to add the next run to the existing plots instead of replacing them. **Clear plot** removes all runs, and **Export CSV…** saves every operating point of every plotted run.

### 5. Read the results

The plots show thrust, rpm and current (solid line = motor current, dotted = battery current). Horizontal lines mark the motor's current rating (black dashed) and the current limit (red dash-dot).

The summary under the Run button lists the peak thrust and the operating point where it occurs, plus any of these warnings:

| Message | Meaning |
|---|---|
| Motor current exceeds … | Above the motor's max current rating |
| Shaft power exceeds … | Above the motor's max power rating |
| Battery current exceeds the limit … | Over the current limit; in a throttle sweep the app also estimates the throttle where the limit is reached |
| Tip Mach above 0.7 | Compressibility is not modelled, so results are optimistic |
| Thrust turns negative (windmilling) | The airflow is driving the propeller; above this airspeed the prop produces drag |

### Exported CSV columns

`run`, `air_density`, `current_limit`, `throttle` (0–1), `airspeed` (m/s), `thrust` (N), `torque` (N·m), `rpm`, `I_motor` (A), `I_battery` (A), `shaft_power` (W), `elec_power` (W), `prop_efficiency`, `tip_mach`, `windmilling`.

## How the model works

**Propeller (BEMT).** The blade is split into elements between the hub and tip radius. For each element the solver iterates on the axial and swirl induced velocities until blade element loads (from the airfoil Cl and Cd at the local angle of attack and Reynolds number) match momentum theory. This formulation is solved for induced *velocities* rather than induction factors, so it stays valid in the static case (zero airspeed). Prandtl's tip-loss factor is included.

**Motor.** A standard DC motor model: back-EMF from KV, torque constant Kt = 1/KV (in SI units), torque = Kt × (I − I₀), and voltage drop across the winding and battery resistance.

**ESC and battery.** The ESC is modelled as an ideal PWM stage: the motor sees throttle × full-charge voltage, and battery current is throttle × motor current.

**Operating point.** For each throttle and airspeed, the app finds the speed at which motor torque equals propeller torque using a bracketed root finder (Brent's method), so every reported point is a true balance of motor and propeller.

### Limitations

- No compressibility or tip Mach corrections (watch the tip Mach warning)
- Linear chord and airfoil blending between root and tip
- Airfoil data is held constant outside the tabulated angle and Reynolds range; post-stall behaviour is only as good as your polars
- Uses the battery's full-charge voltage; voltage sag with state of charge is not modelled
- The ESC is treated as lossless
- No blade flexing, hub/spinner blockage or fuselage interference

## Using the model from a script

`bemt_model.py` has no GUI dependencies, so it can be used directly for batch studies:

```python
import bemt_model as m

presets = m.load_presets()
prop = m.from_preset(m.Propeller, presets["propellers"]["10 x 6"])
motor = m.from_preset(m.Motor, presets["motors"]["EMAX GT2820/06"])
battery = m.from_preset(m.Battery, presets["batteries"]["3S 3300mAh 45C"])
airfoil = m.prop_airfoil(prop)
atm = m.atmosphere_from(altitude_m=500, temperature_c=20)

point = m.motor_battery(prop, airfoil, motor, battery, throttle=1.0, airspeed=0.0, atm=atm)
print(f"{point.thrust:.2f} N at {point.rpm:.0f} rpm, {point.I_battery:.1f} A")

sweep = m.airspeed_sweep(prop, airfoil, motor, battery, throttle=0.6, v_max=25, n=30, atm=atm)
```

## Customising

**Language.** Use the *Language / Idioma* dropdown at the top of the side panel; the choice is remembered. All interface text lives in `i18n.py` as one dictionary per language. To fix wording, edit the text there. To add a language, add its code and name to `LANGUAGES` and a matching dictionary to `STRINGS`; any missing text falls back to English.

**App icon.** Put `icon.ico` (Windows; include 16, 32, 48 and 256 px sizes) and/or `icon.png` (macOS / Linux) next to `prop_gui.py`.

**Side-panel logo.** Replace `logo_black.png`. It is shown at its actual size, so keep it about 320 px wide or less. Delete the file to hide the logo.

## Building a standalone executable

To share the app with team members who don't have Python installed:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico prop_gui.py
```

Copy the `Airfoils` folder, `icon.ico`, `icon.png` and `logo_black.png` next to the generated executable in `dist/`. `presets.json` is created there on first run; copy an existing one across to share your team's presets.

## Troubleshooting

| Problem | Fix |
|---|---|
| "No airfoils found" on start-up | The `Airfoils` folder must sit next to `prop_gui.py`. Use **Import…** or the **↻** button after adding files. |
| Propeller line shows "Not in library" | An airfoil folder was renamed or removed. Re-import it or edit the propeller to pick another. |
| `ModuleNotFoundError: No module named 'tkinter'` | On Linux: `sudo apt install python3-tk` (or your distribution's equivalent). |
| Thrust looks far too high or too low | Check that prop dimensions are in the stated units (diameter in inches, chord and hub radius in metres) and that the polars cover the blade's Reynolds number range. |
| Taskbar shows the Python icon on Windows | Make sure `icon.ico` is next to `prop_gui.py` and launch the app with `python prop_gui.py` (or the packaged `.exe`). |
