# XtraProp

**[Español](#español)** · **[English](#english)**

---

## Español

> Desarrollado para el estudio de hélices y la optimización del rendimiento para el **XtraChallenge 2027**.

Herramienta de escritorio para predecir el empuje, las rpm y la corriente de un sistema de propulsión eléctrica (motor + batería + hélice) en función del acelerador y de la velocidad del aire. Combina un modelo de hélice basado en la teoría del elemento de pala con cantidad de movimiento (BEMT) con un modelo sencillo de motor DC y batería, todo dentro de una interfaz bilingüe (español / inglés) para que el equipo pueda comparar configuraciones rápidamente.

### Características

- **Barridos de acelerador** a velocidad fija y **barridos de velocidad** a acelerador fijo
- Gráficas de empuje, rpm, corriente del motor y corriente de la batería, con **superposición** de cálculos para comparar configuraciones
- **Preajustes** de motores, baterías y hélices, que se crean y editan en la aplicación y se guardan en `presets.json`
- **Forma real de la pala**: tablas de cuerda y ángulo de pala a lo largo del radio, importadas directamente de los archivos de geometría de APC (`.PE0`) o de la base de datos de UIUC
- **Perfiles en la raíz y en la punta** para cada hélice, con la zona de transición configurable
- **Validado frente a datos de túnel de viento** (UIUC): ver [Precisión](#precisión)
- **Biblioteca de perfiles** importada desde archivos de polares de XFLR5 / XFOIL, una carpeta por perfil
- Ajustes de **atmósfera**: densidad del aire introducida directamente o calculada a partir de la altitud y la temperatura
- **Límite de corriente de competición** comprobado sobre la corriente de la batería, indicando el acelerador con el que se alcanza
- **Rendimiento del variador** configurable y aviso cuando la corriente prevista se acerca al límite
- Avisos por superar la corriente o la potencia nominal del motor, Mach en punta elevado y efecto molino
- **Exportación a CSV** de todos los puntos de funcionamiento
- Interfaz en **español / inglés**, intercambiable en cualquier momento

### Requisitos

- Python 3.9 o superior, con Tkinter (incluido en los instaladores estándar de Python para Windows y macOS; en Linux instala `python3-tk`)
- numpy, scipy y matplotlib

```bash
pip install numpy scipy matplotlib
```

### Estructura del proyecto

```
XtraProp/
  prop_gui.py        La aplicación (ejecuta este archivo)
  run_gui.bat        Lanzador para Windows
  bemt_model.py      Modelo de hélice, motor y batería; sin código de interfaz
  i18n.py            Textos de la interfaz en inglés y español
  presets.json       Motores, baterías, hélices y ajustes guardados
  Airfoils/          Biblioteca de perfiles: una carpeta por perfil
    NACA4412 Ncrit5/
      re50000.csv
      re200000.csv
  icon.ico           Icono de la aplicación para Windows (opcional)
  logo_black.png     Logo del equipo en el panel lateral (opcional)
validation/          Comparación con datos de túnel de viento y pruebas automáticas (ver Precisión)
```

### Ejecución

```bash
python prop_gui.py
```

o simplemente abre ```run_gui.bat``` en Windows.

### Uso de la aplicación

#### 1. Elige una configuración

Selecciona un **motor**, una **batería** y una **hélice** en los desplegables. Las líneas bajo la hélice muestran qué perfiles usa y si su forma de pala viene de una tabla o de una estimación lineal; se vuelven rojas si algún perfil no está en la biblioteca.

Cada desplegable tiene los botones **Nuevo**, **Editar** y **Borrar**. **Nuevo** abre un formulario relleno con una copia de la selección actual, que es la forma más rápida de crear una variante. Los cambios se guardan en `presets.json` al momento.

| Componente | Campos |
|---|---|
| Motor | KV (rpm/V), resistencia del bobinado (Ω), corriente en vacío (A), corriente máx. (A), potencia máx. (W), peso (g) |
| Batería | celdas, tensión nominal, tensión a plena carga, capacidad (mAh), tasa de descarga (C), resistencia interna (Ω) |
| Hélice | diámetro (pulg.), radio del buje (m), cuerda en la raíz y en la punta (m), ángulo de pala en la raíz y en la punta (°), perfil en la raíz y en la punta, paso geométrico (pulg.), número de palas, número de elementos de pala, inicio y fin de la transición de perfil (r/R), tabla de forma de pala |

**Torsión de la hélice.** Si el *paso geométrico* es mayor que 0, la pala sigue una hélice geométrica exacta para ese paso (ángulo de pala = atan(P / 2πr)) y se ignoran los ángulos de raíz y punta. Pon 0 para usar en su lugar una torsión lineal entre los ángulos de raíz y punta.

**Tabla de forma de pala (recomendado).** Las palas reales son más anchas hacia el 30–40% del radio y se estrechan hacia la punta, algo que una cuerda lineal no puede representar. En el formulario de la hélice, pulsa **Importar geometría…** y elige:

- un archivo **`.PE0` de APC** (se descargan uno a uno en [apcprop.com → Propeller Technical Data](https://www.apcprop.com/propeller-technical-data/)): rellena también el diámetro, el radio del buje y los perfiles, o
- un archivo **`*_geom.txt` de UIUC** o cualquier tabla con tres columnas: r/R, cuerda/R y ángulo de pala (°).

Con una tabla cargada, se ignoran la cuerda y los ángulos de raíz/punta y el paso geométrico. **Usar valores de raíz/punta** vuelve a la estimación lineal. Todas las hélices APC incluidas usan ya la tabla de APC.

**La cuerda** (sin tabla) varía linealmente de la raíz a la punta.

**Perfiles.** El perfil de la raíz se usa hasta el **inicio de la transición** y el de la punta desde el **fin de la transición** (fracciones del radio; 0 y 1 = interpolar a lo largo de toda la pala), con la sustentación y la resistencia interpoladas linealmente entre ambos. Elige "(igual que la raíz)" para una pala con un solo perfil. En los archivos de APC que indican E63 en la raíz, la aplicación usa el perfil de la punta en toda la pala: APC engrosa mucho la raíz, y las polares del E63 delgado sobrestiman el empuje (ver [Precisión](#precisión)).

#### 2. Biblioteca de perfiles

Pulsa **Importar…** y elige:

- **una carpeta de perfil** con un archivo de polar por número de Reynolds, o
- **una carpeta superior** cuyas subcarpetas sean cada una un perfil, para importarlos todos a la vez.

Los archivos se copian en `Airfoils/<nombre>/re<Reynolds>.csv`. El botón **↻** vuelve a leer la carpeta si añades archivos a mano.

**Formato de las polares.** `.csv`, `.txt` o `.dat`, con las tres primeras columnas numéricas como ángulo de ataque (°), Cl y Cd. Las líneas de cabecera se omiten automáticamente, así que las exportaciones CSV de XFLR5 y las polares de XFOIL funcionan tal cual. El número de Reynolds se lee del nombre del archivo (`re100000.csv`, o el `..._Re0.100_...` de XFLR5, en millones) o de la cabecera del archivo (`Re = 0.100 e 6`); si no lo encuentra, la aplicación lo pregunta.

Usa al menos tres números de Reynolds que cubran el rango de funcionamiento de tu hélice; las hélices pequeñas trabajan sobre todo entre 20.000 y 100.000. Fuera del rango tabulado de ángulo, y por encima del Reynolds más alto, se mantienen los valores más cercanos. Por debajo del Reynolds más bajo, la resistencia crece como (Re / Re_mín)^-0,5, la ley de bajo Reynolds que usa QPROP.

**Ncrit.** Para hélices, usa polares calculadas con **Ncrit 5**: en la validación dieron resultados claramente mejores que con Ncrit 9. Las carpetas `… Ncrit5` de la biblioteca son de este tipo.

#### 3. Atmósfera

- Escribe la **densidad del aire** directamente (por defecto 1.184 kg/m³, nivel del mar a 25 °C), o
- introduce la **altitud** y la **temperatura** y pulsa **Densidad desde alt. + temp.**, o
- pulsa **Día ISA** para usar la temperatura de la atmósfera estándar a esa altitud.

La temperatura también fija la viscosidad del aire (usada para el número de Reynolds) y la velocidad del sonido (usada para el Mach en punta).

#### 4. Calcula un barrido

- **Barrido de velocidad:** acelerador fijo, velocidad del aire desde 0 hasta el máximo que indiques.
- **Barrido de acelerador:** velocidad fija, acelerador entre el mínimo y el máximo que indiques.

**Puntos** fija cuántos puntos de funcionamiento se calculan. Un barrido de 20 puntos tarda alrededor de un segundo.

**Límite de corriente (A)** es un límite opcional en el lado de la batería, como un fusible de competición. Se recuerda entre sesiones. Déjalo vacío si no hay límite.

**Rendimiento del variador (%)** (por defecto 95) tiene en cuenta las pérdidas del variador: la corriente de la batería es acelerador × corriente del motor ÷ rendimiento. Se recuerda entre sesiones.

Marca **Superponer a cálculos anteriores** para añadir el siguiente cálculo a las gráficas existentes en lugar de sustituirlas. **Limpiar gráfica** borra todos los cálculos y **Exportar CSV…** guarda todos los puntos de funcionamiento de todos los cálculos representados.

#### 5. Interpreta los resultados

Las gráficas muestran empuje, rpm y corriente (línea continua = corriente del motor, punteada = corriente de la batería). Las líneas horizontales marcan la corriente nominal del motor (negra discontinua) y el límite de corriente (roja de trazo y punto).

El resumen bajo el botón Calcular indica el empuje máximo y el punto de funcionamiento en que se da, además de cualquiera de estos avisos:

| Mensaje | Significado |
|---|---|
| La corriente del motor supera … | Por encima de la corriente máxima del motor |
| La potencia en el eje supera … | Por encima de la potencia máxima del motor |
| La corriente de la batería supera el límite … | Se supera el límite de corriente; en un barrido de acelerador la aplicación también estima el acelerador con el que se alcanza |
| A menos del 15% del límite | La corriente prevista está cerca del límite; el modelo puede subestimar la potencia, así que deja margen |
| Mach en punta mayor que 0.7 | La compresibilidad no está modelada, así que los resultados son optimistas |
| El empuje se vuelve negativo (la hélice actúa como molino) | El flujo de aire mueve la hélice; por encima de esta velocidad la hélice produce resistencia |

#### Columnas del CSV exportado

`run` (cálculo), `air_density` (densidad del aire), `current_limit` (límite de corriente), `esc_efficiency` (rendimiento del variador, 0–1), `throttle` (acelerador, 0–1), `airspeed` (velocidad, m/s), `thrust` (empuje, N), `torque` (par, N·m), `rpm`, `I_motor` (A), `I_battery` (A), `shaft_power` (potencia en el eje, W), `elec_power` (potencia eléctrica, W), `prop_efficiency` (rendimiento de la hélice), `tip_mach` (Mach en punta), `windmilling` (efecto molino).

### Cómo funciona el modelo

**Hélice (BEMT).** La pala se divide en elementos entre el radio del buje y el de la punta. Para cada elemento, el programa itera sobre las velocidades inducidas axial y tangencial hasta que las cargas del elemento de pala (a partir del Cl y el Cd del perfil con el ángulo de ataque y el número de Reynolds locales) coinciden con la teoría de cantidad de movimiento. La formulación se resuelve en *velocidades* inducidas en lugar de factores de inducción, por lo que sigue siendo válida en el caso estático (velocidad nula). Incluye el factor de pérdidas en punta de Prandtl.

**Motor.** Modelo estándar de motor DC: fuerza contraelectromotriz a partir del KV, constante de par Kt = 1/KV (en unidades SI), par = Kt × (I − I₀), y caída de tensión en la resistencia del bobinado y de la batería.

**Variador y batería.** El variador (ESC) se modela como una etapa PWM: el motor ve acelerador × tensión a plena carga, y la corriente de la batería es acelerador × corriente del motor ÷ rendimiento del variador.

**Punto de funcionamiento.** Para cada acelerador y velocidad, la aplicación busca la velocidad de giro con la que el par del motor iguala al de la hélice mediante un método de búsqueda de raíces con intervalo (método de Brent), de modo que cada punto obtenido es un equilibrio real entre motor y hélice.

#### Limitaciones

- Sin correcciones por compresibilidad ni por Mach en punta (atención al aviso de Mach en punta)
- Sin tabla de forma de pala, la cuerda es lineal entre raíz y punta; la interpolación entre perfiles es siempre lineal
- Fuera del rango tabulado de ángulo se mantienen los datos del perfil; el comportamiento tras la entrada en pérdida depende de la calidad de tus polares
- Se usa la tensión de la batería a plena carga; no se modela la caída de tensión con el estado de carga
- El rendimiento del variador es constante
- El lado del motor (KV, I₀, resistencia) aún no se ha validado con medidas; ver [Precisión](#precisión)
- No se modelan la flexión de la pala, el bloqueo del buje o del cono ni la interferencia con el fuselaje

### Precisión

La carpeta `validation/` compara el modelo con medidas en túnel de viento de cinco hélices APC Thin Electric (9×4.5, 9×6, 10×5, 10×7 y 11×5.5) de la [base de datos de hélices de UIUC](https://m-selig.ae.illinois.edu/props/volume-1/propDB-volume-1.html), usando el mismo código que la aplicación. Error medio absoluto:

| Error medio (5 hélices) | Antes de esta versión | Ahora |
|---|---|---|
| Empuje estático | 14,3% | 6,7% |
| Potencia estática | 16,9% | 4,5% |
| Empuje en función de la velocidad (RMS) | 11,4% | 7,4% |
| Potencia en función de la velocidad (RMS) | 15,0% | 8,7% |
| Velocidad de empuje nulo | 11,8% | 3,5% |

"Antes" son las hélices APC tal como estaban configuradas (cuerda constante de 2 cm, paso constante, polares Ncrit 9). "Ahora" es la tabla de forma de pala de APC con NACA 4412 (Ncrit 5) en toda la pala y la corrección de resistencia a bajo Reynolds. El empuje sigue sobrestimado en torno a un 7% de media y la potencia puede quedar hasta un ~10% por debajo en alguna hélice, así que deja margen respecto a los límites de corriente.

Para repetir la validación y las pruebas de robustez (convergencia, límites físicos, casos extremos, importación de geometría y 600 configuraciones aleatorias):

```bash
cd validation
python validate.py      # escribe results/summary.csv y las gráficas de comparación
python robustness.py    # 15 comprobaciones automáticas
```

**Hélices Aero-naut CAM.** No hay geometría publicada de estas palas, así que su forma se ha **ajustado** a las medidas en túnel de viento de UIUC (volumen 3, Dantsker et al. 2020): cuatro parámetros por pala (cuerda máxima, estrechamiento, paso efectivo y torsión), con el estrechamiento y la torsión compartidos por toda la familia, ajustados con el mismo código que la aplicación (`validation/fit_aeronaut.py`). Son formas *efectivas*: reproducen el rendimiento medido, pero no son una medida de la pala real. La 14×6.5, que UIUC no midió, se interpola entre la 14×6 y la 14×8; el mismo método predice la 12×6.5 (no usada en el ajuste) con un error del ~3% en empuje y ~1,5% en potencia.

| Error medio (6 hélices Aero-naut, todos los datos de UIUC) | Antes | Ahora |
|---|---|---|
| Empuje estático | 6,9% | 2,7% |
| Potencia estática | 14,2% | 1,6% |
| Empuje en función de la velocidad (RMS) | 15,8% | 3,3% |
| Potencia en función de la velocidad (RMS) | 19,3% | 4,4% |

En las series a las rpm más altas, que no se usaron en el ajuste, el error es del ~4% en empuje y en potencia. En una prueba independiente en banco (base de datos de Tyto Robotics: Hacker A30-14L V4 + CAM Carbon Z 10×6, 4S), el par previsto coincide con el medido (±0,3%); el empuje medido en ese banco es un ~25% menor que el de UIUC a la misma potencia, probablemente por el montaje del banco, y la corriente prevista queda un 14–20% por encima de la medida (del lado seguro). El motor Hacker A30-14L V4 se ha añadido a los preajustes. Para repetirlo: `python fit_aeronaut.py --family`, `python check_aeronaut.py`, `python compare_aeronaut.py` y `python tyto_check.py`.

### Uso del modelo desde un script

`bemt_model.py` no depende de la interfaz gráfica, así que se puede usar directamente para estudios por lotes:

```python
import bemt_model as m

presets = m.load_presets()
prop = m.from_preset(m.Propeller, presets["propellers"]["14 x 10 APC Thin Electric"])
motor = m.from_preset(m.Motor, presets["motors"]["XtraChallenge 2027 - EMAX GT2820/06"])
battery = m.from_preset(m.Battery, presets["batteries"]["3S 3300mAh 45C"])
airfoil = m.prop_airfoil(prop)
atm = m.atmosphere_from(altitude_m=500, temperature_c=20)

point = m.motor_battery(prop, airfoil, motor, battery, throttle=1.0, airspeed=0.0, atm=atm,
                        esc_efficiency=0.95)
print(f"{point.thrust:.2f} N a {point.rpm:.0f} rpm, {point.I_battery:.1f} A")

sweep = m.airspeed_sweep(prop, airfoil, motor, battery, throttle=0.6, v_max=25, n=30, atm=atm)
```

### Personalización

**Idioma.** Usa el desplegable *Language / Idioma* en la parte superior del panel lateral; la elección se recuerda. Todos los textos de la interfaz están en `i18n.py`, con un diccionario por idioma. Para corregir una frase, edita el texto ahí. Para añadir un idioma, añade su código y nombre a `LANGUAGES` y un diccionario correspondiente a `STRINGS`; cualquier texto que falte se muestra en inglés.

**Icono de la aplicación.** Coloca `icon.ico` (Windows; incluye los tamaños de 16, 32, 48 y 256 px) y/o `icon.png` (macOS / Linux) junto a `prop_gui.py`.

**Logo del panel lateral.** Sustituye `logo_black.png`. Se muestra a su tamaño real, así que mantenlo en unos 320 px de ancho o menos. Borra el archivo para ocultar el logo.

### Crear un ejecutable independiente

Para compartir la aplicación con miembros del equipo que no tienen Python instalado:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico prop_gui.py
```

Copia la carpeta `Airfoils`, `icon.ico`, `icon.png` y `logo_black.png` junto al ejecutable generado en `dist/`. `presets.json` se crea ahí en el primer arranque; copia uno existente para compartir los preajustes del equipo.

### Solución de problemas

| Problema | Solución |
|---|---|
| "No se encontraron perfiles" al arrancar | La carpeta `Airfoils` debe estar junto a `prop_gui.py`. Usa **Importar…** o el botón **↻** después de añadir archivos. |
| La línea de la hélice muestra "No están en la biblioteca" | Se ha renombrado o eliminado una carpeta de perfil. Vuelve a importarla o edita la hélice para elegir otro perfil. |
| `ModuleNotFoundError: No module named 'tkinter'` | En Linux: `sudo apt install python3-tk` (o el equivalente de tu distribución). |
| El empuje parece demasiado alto o bajo | Comprueba que las dimensiones de la hélice están en las unidades indicadas (diámetro en pulgadas, cuerda y radio del buje en metros) y que las polares cubren el rango de Reynolds de la pala. |
| La barra de tareas muestra el icono de Python en Windows | Asegúrate de que `icon.ico` está junto a `prop_gui.py` y abre la aplicación con `python prop_gui.py` (o con el `.exe` empaquetado). |

---

## English

> Developed for propeller studies and performance optimization for the **XtraChallenge 2027**.

A desktop tool for predicting the thrust, rpm and current of an electric propulsion setup (motor + battery + propeller) across throttle and airspeed. It combines a blade element momentum theory (BEMT) propeller model with a simple DC motor and battery model, and wraps it in a bilingual (English / Spanish) GUI so the team can compare setups quickly.

### Features

- **Throttle sweeps** at a fixed airspeed and **airspeed sweeps** at a fixed throttle
- Plots of thrust, rpm, motor current and battery current, with run-to-run **overlay** for comparing setups
- **Presets** for motors, batteries and propellers, created and edited in the app and saved to `presets.json`
- **Real blade shapes**: chord and blade-angle tables along the radius, imported straight from APC geometry files (`.PE0`) or the UIUC database
- **Root and tip airfoils** per propeller, with an adjustable transition zone
- **Validated against wind-tunnel data** (UIUC): see [Accuracy](#accuracy)
- **Airfoil library** imported from XFLR5 / XFOIL polar files, one folder per airfoil
- **Atmosphere** settings: air density entered directly or computed from altitude and temperature
- **Competition current limit** checked against battery current, with the throttle at which it is reached
- Adjustable **ESC efficiency**, and a warning when predicted current gets close to the limit
- Warnings for motor current and power ratings, high tip Mach number and windmilling
- **CSV export** of every operating point
- **English / Spanish** interface, switchable at any time

### Requirements

- Python 3.9 or newer, with Tkinter (included in the standard Python installers for Windows and macOS; on Linux install `python3-tk`)
- numpy, scipy and matplotlib

```bash
pip install numpy scipy matplotlib
```

### Project layout

```
XtraProp/
  prop_gui.py        The application (run this)
  run_gui.bat        Windows launcher
  bemt_model.py      Propeller, motor and battery model; no GUI code
  i18n.py            English and Spanish interface text
  presets.json       Saved motors, batteries, propellers and settings
  Airfoils/          Airfoil library: one folder per airfoil
    NACA4412 Ncrit5/
      re50000.csv
      re200000.csv
  icon.ico           App icon for Windows (optional)
  logo_black.png     Team logo shown in the side panel (optional)
validation/          Wind-tunnel comparison and automated tests (see Accuracy)
```

### Running

```bash
python prop_gui.py
```

or simply open ```run_gui.bat``` on Windows.

### Using the app

#### 1. Choose a configuration

Pick a **motor**, **battery** and **propeller** from the dropdowns. The lines under the propeller show which airfoils it uses and whether its blade shape comes from a table or a linear estimate; they turn red if an airfoil is missing from the library.

Each dropdown has **New**, **Edit** and **Del** buttons. **New** opens a form pre-filled with a copy of the current selection, which is the quickest way to make a variant. Changes are saved to `presets.json` immediately.

| Component | Fields |
|---|---|
| Motor | KV (rpm/V), winding resistance (Ω), no-load current (A), max current (A), max power (W), weight (g) |
| Battery | cells, nominal voltage, full-charge voltage, capacity (mAh), C rating, internal resistance (Ω) |
| Propeller | diameter (in), hub radius (m), root and tip chord (m), root and tip blade angle (°), root and tip airfoil, geometric pitch (in), number of blades, number of blade elements, airfoil blend start and end (r/R), blade shape table |

**Propeller twist.** If *Geometric pitch* is greater than 0, the blade follows a true helix for that pitch (blade angle = atan(P / 2πr)) and the root/tip angles are ignored. Set it to 0 to use a linear twist between the root and tip angles instead.

**Blade shape table (recommended).** Real blades are widest around 30–40% of the radius and narrow towards the tip, which a linear chord can't represent. In the propeller form, click **Import geometry…** and choose:

- an **APC `.PE0` file** (downloadable one by one from [apcprop.com → Propeller Technical Data](https://www.apcprop.com/propeller-technical-data/)): this also fills in the diameter, hub radius and airfoils, or
- a **UIUC `*_geom.txt` file**, or any table with three columns: r/R, chord/R and blade angle (°).

With a table loaded, the root/tip chord and blade angles and the geometric pitch are ignored. **Use root/tip values** goes back to the linear estimate. All the included APC props already use APC's table.

**Chord** (without a table) varies linearly from root to tip.

**Airfoils.** The root airfoil is used up to the **blend start** and the tip airfoil from the **blend end** (fractions of the radius; 0 and 1 = blend along the whole blade), with lift and drag blended linearly in between. Choose "(same as root)" for a single-airfoil blade. For APC files that name E63 at the root, the app uses the tip section along the whole blade: APC thickens the root heavily, and thin-E63 polars over-predict thrust (see [Accuracy](#accuracy)).

#### 2. Airfoil library

Click **Import…** and choose either:

- **an airfoil folder** containing one polar file per Reynolds number, or
- **a parent folder** whose subfolders are each an airfoil, to import them all at once.

Files are copied into `Airfoils/<name>/re<Reynolds>.csv`. The **↻** button rescans the folder if you add files by hand.

**Polar file format.** `.csv`, `.txt` or `.dat`, with the first three numeric columns being angle of attack (°), Cl and Cd. Header lines are skipped automatically, so XFLR5 CSV exports and XFOIL polar files work as they are. The Reynolds number is read from the file name (`re100000.csv`, or XFLR5's `..._Re0.100_...` in millions) or from the file header (`Re = 0.100 e 6`); if neither is found, the app asks for it.

Use at least three Reynolds numbers that cover your propeller's operating range; small props run mostly between 20,000 and 100,000. Outside the tabulated angle range, and above the highest Reynolds number, the nearest values are held constant. Below the lowest Reynolds number, drag rises as (Re / Re_min)^-0.5, the low-Reynolds law QPROP uses.

**Ncrit.** For propellers, use polars computed with **Ncrit 5**: they gave clearly better results than Ncrit 9 in validation. The `… Ncrit5` folders in the library are of this kind.

#### 3. Atmosphere

- Type the **air density** directly (default 1.184 kg/m³, sea level at 25 °C), or
- enter **altitude** and **temperature** and click **Density from alt + temp**, or
- click **ISA day** to use the standard-atmosphere temperature for that altitude.

Temperature also sets the air viscosity (used for Reynolds number) and the speed of sound (used for tip Mach).

#### 4. Run a sweep

- **Airspeed sweep:** fixed throttle, airspeed from 0 to the maximum you set.
- **Throttle sweep:** fixed airspeed, throttle between the minimum and maximum you set.

**Points** sets how many operating points are calculated. A 20-point sweep takes about a second.

**Current limit (A)** is an optional battery-side limit, such as a competition fuse. It is remembered between sessions. Leave it blank for none.

**ESC efficiency (%)** (default 95) accounts for ESC losses: battery current = throttle × motor current ÷ efficiency. It is remembered between sessions.

Tick **Overlay on previous runs** to add the next run to the existing plots instead of replacing them. **Clear plot** removes all runs, and **Export CSV…** saves every operating point of every plotted run.

#### 5. Read the results

The plots show thrust, rpm and current (solid line = motor current, dotted = battery current). Horizontal lines mark the motor's current rating (black dashed) and the current limit (red dash-dot).

The summary under the Run button lists the peak thrust and the operating point where it occurs, plus any of these warnings:

| Message | Meaning |
|---|---|
| Motor current exceeds … | Above the motor's max current rating |
| Shaft power exceeds … | Above the motor's max power rating |
| Battery current exceeds the limit … | Over the current limit; in a throttle sweep the app also estimates the throttle where the limit is reached |
| Within 15% of the limit | Predicted current is close to the limit; the model can under-predict power, so keep a margin |
| Tip Mach above 0.7 | Compressibility is not modelled, so results are optimistic |
| Thrust turns negative (windmilling) | The airflow is driving the propeller; above this airspeed the prop produces drag |

#### Exported CSV columns

`run`, `air_density`, `current_limit`, `esc_efficiency` (0–1), `throttle` (0–1), `airspeed` (m/s), `thrust` (N), `torque` (N·m), `rpm`, `I_motor` (A), `I_battery` (A), `shaft_power` (W), `elec_power` (W), `prop_efficiency`, `tip_mach`, `windmilling`.

### How the model works

**Propeller (BEMT).** The blade is split into elements between the hub and tip radius. For each element the solver iterates on the axial and swirl induced velocities until blade element loads (from the airfoil Cl and Cd at the local angle of attack and Reynolds number) match momentum theory. This formulation is solved for induced *velocities* rather than induction factors, so it stays valid in the static case (zero airspeed). Prandtl's tip-loss factor is included.

**Motor.** A standard DC motor model: back-EMF from KV, torque constant Kt = 1/KV (in SI units), torque = Kt × (I − I₀), and voltage drop across the winding and battery resistance.

**ESC and battery.** The ESC is modelled as a PWM stage: the motor sees throttle × full-charge voltage, and battery current is throttle × motor current ÷ ESC efficiency.

**Operating point.** For each throttle and airspeed, the app finds the speed at which motor torque equals propeller torque using a bracketed root finder (Brent's method), so every reported point is a true balance of motor and propeller.

#### Limitations

- No compressibility or tip Mach corrections (watch the tip Mach warning)
- Without a blade shape table the chord is linear from root to tip; airfoil blending is always linear
- Airfoil data is held constant outside the tabulated angle range; post-stall behaviour is only as good as your polars
- Uses the battery's full-charge voltage; voltage sag with state of charge is not modelled
- ESC efficiency is constant
- The motor side (KV, I₀, resistance) has not been validated against measurements yet; see [Accuracy](#accuracy)
- No blade flexing, hub/spinner blockage or fuselage interference

### Accuracy

The `validation/` folder compares the model with wind-tunnel measurements of five APC Thin Electric props (9×4.5, 9×6, 10×5, 10×7 and 11×5.5) from the [UIUC Propeller Database](https://m-selig.ae.illinois.edu/props/volume-1/propDB-volume-1.html), using the same code as the app. Average absolute error:

| Average error (5 props) | Before this version | Now |
|---|---|---|
| Static thrust | 14.3% | 6.7% |
| Static power | 16.9% | 4.5% |
| Thrust vs. airspeed (RMS) | 11.4% | 7.4% |
| Power vs. airspeed (RMS) | 15.0% | 8.7% |
| Zero-thrust airspeed | 11.8% | 3.5% |

"Before" is the APC props as they were set up (2 cm constant chord, constant pitch, Ncrit 9 polars). "Now" is APC's blade shape table with NACA 4412 (Ncrit 5) along the whole blade and the low-Reynolds drag correction. Thrust is still over-predicted by about 7% on average, and power can come out up to ~10% low for some props, so keep a margin on current limits.

To rerun the validation and the robustness tests (convergence, physical limits, edge cases, geometry import and 600 random setups):

```bash
cd validation
python validate.py      # writes results/summary.csv and the comparison plots
python robustness.py    # 15 automated checks
```

**Aero-naut CAM props.** No geometry has been published for these blades, so their shape has been **fitted** to UIUC's wind-tunnel measurements (Volume 3, Dantsker et al. 2020): four parameters per blade (maximum chord, taper, effective pitch and washout), with taper and washout shared across the family, fitted through the same code as the app (`validation/fit_aeronaut.py`). They are *effective* shapes: they reproduce the measured performance but are not a measurement of the real blade. The 14×6.5, which UIUC didn't test, is interpolated between the 14×6 and 14×8; the same method predicts the 12×6.5 (not used in fitting) to within ~3% on thrust and ~1.5% on power.

| Average error (6 Aero-naut props, all UIUC data) | Before | Now |
|---|---|---|
| Static thrust | 6.9% | 2.7% |
| Static power | 14.2% | 1.6% |
| Thrust vs. airspeed (RMS) | 15.8% | 3.3% |
| Power vs. airspeed (RMS) | 19.3% | 4.4% |

On the highest-rpm runs, which were held out of the fit, the error is ~4% on thrust and power. In an independent thrust-stand test (Tyto Robotics database: Hacker A30-14L V4 + CAM Carbon Z 10×6, 4S), predicted torque matches the measurement (±0.3%); that stand measured ~25% less thrust than UIUC at the same power, most likely because of the stand setup, and predicted current comes out 14–20% above the measurement (the safe side). The Hacker A30-14L V4 motor has been added to the presets. To rerun: `python fit_aeronaut.py --family`, `python check_aeronaut.py`, `python compare_aeronaut.py` and `python tyto_check.py`.

### Using the model from a script

`bemt_model.py` has no GUI dependencies, so it can be used directly for batch studies:

```python
import bemt_model as m

presets = m.load_presets()
prop = m.from_preset(m.Propeller, presets["propellers"]["14 x 10 APC Thin Electric"])
motor = m.from_preset(m.Motor, presets["motors"]["XtraChallenge 2027 - EMAX GT2820/06"])
battery = m.from_preset(m.Battery, presets["batteries"]["3S 3300mAh 45C"])
airfoil = m.prop_airfoil(prop)
atm = m.atmosphere_from(altitude_m=500, temperature_c=20)

point = m.motor_battery(prop, airfoil, motor, battery, throttle=1.0, airspeed=0.0, atm=atm,
                        esc_efficiency=0.95)
print(f"{point.thrust:.2f} N at {point.rpm:.0f} rpm, {point.I_battery:.1f} A")

sweep = m.airspeed_sweep(prop, airfoil, motor, battery, throttle=0.6, v_max=25, n=30, atm=atm)
```

### Customising

**Language.** Use the *Language / Idioma* dropdown at the top of the side panel; the choice is remembered. All interface text lives in `i18n.py` as one dictionary per language. To fix wording, edit the text there. To add a language, add its code and name to `LANGUAGES` and a matching dictionary to `STRINGS`; any missing text falls back to English.

**App icon.** Put `icon.ico` (Windows; include 16, 32, 48 and 256 px sizes) and/or `icon.png` (macOS / Linux) next to `prop_gui.py`.

**Side-panel logo.** Replace `logo_black.png`. It is shown at its actual size, so keep it about 320 px wide or less. Delete the file to hide the logo.

### Building a standalone executable

To share the app with team members who don't have Python installed:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico prop_gui.py
```

Copy the `Airfoils` folder, `icon.ico`, `icon.png` and `logo_black.png` next to the generated executable in `dist/`. `presets.json` is created there on first run; copy an existing one across to share your team's presets.

### Troubleshooting

| Problem | Fix |
|---|---|
| "No airfoils found" on start-up | The `Airfoils` folder must sit next to `prop_gui.py`. Use **Import…** or the **↻** button after adding files. |
| Propeller line shows "Not in library" | An airfoil folder was renamed or removed. Re-import it or edit the propeller to pick another. |
| `ModuleNotFoundError: No module named 'tkinter'` | On Linux: `sudo apt install python3-tk` (or your distribution's equivalent). |
| Thrust looks far too high or too low | Check that prop dimensions are in the stated units (diameter in inches, chord and hub radius in metres) and that the polars cover the blade's Reynolds number range. |
| Taskbar shows the Python icon on Windows | Make sure `icon.ico` is next to `prop_gui.py` and launch the app with `python prop_gui.py` (or the packaged `.exe`). |
