# Avry_dev data folders (public test feeders only)

Used by `Avry_dev_1_verification_validation.py`. Nothing here is BC Hydro data.

## ieee123_data/ — validation (IEEE 123 node test feeder)

| File | What it is | Source |
|---|---|---|
| `IEEE123Master.dss`, `IEEE123Loads.DSS`, `IEEE123Regulators.DSS`, `IEEE123Switches.dss`, `BusCoords.dat` | OpenDSS model of the feeder, unchanged | OpenDSS test cases, `Version8/Distrib/IEEETestCases/123Bus/` (github.com/dss-extensions/electricdss-tst) |
| `IEEELineCodes.DSS` | Line codes. The 123Bus folder only holds a one-line file pointing to `../IEEELineCodes.DSS`; the real file from `IEEETestCases/` is put here instead so the folder stands alone | same repository, `Version8/Distrib/IEEETestCases/IEEELineCodes.DSS` |
| `reference/ieee123_radial_power_flow.txt` | Published solved results: voltage (magnitude, angle) of every node and phase, branch currents and losses | IEEE PES Distribution Test Feeders, 123-node feeder, Kersting's radial power flow program output (`powerflow.txt`, copy in github.com/hafezbazrafshan/three-phase-modeling) |
| `reference/ieee123_system_totals.csv` | Input power and losses per phase and in total | the feeder's results sheet (`IEEE 123 Node Test Feeder Letterhead.doc`, same sources) |
| `reference/ieee123_regulator_taps.csv` | Regulator taps of the published solution | worked out from the voltage ratio across each regulator in the report (e.g. RG1: 1.044 / 1.000 = 7 steps of 0.625 %); the tap table in the .doc could not be read cleanly. Holding these taps reproduces the published voltages to 0.0004 pu on average |

Report names that differ from OpenDSS bus names (set in the script, `REFERENCE_NODE_NAMES`):
RG1 = 150r, RG2 = 9r, RG3 = 25r, RG4 = 160r.

## european_lv_data/ — GIS overlay (IEEE European LV test feeder)

OpenDSS model of the 906-bus, 55-customer European LV test feeder, unchanged, with its 100 one-minute
load profiles (`Daily_1min_100profiles/`). Source: OpenDSS test cases,
`Version8/Distrib/IEEETestCases/LVTestCase/` (same repository). The feeder has no measured values,
so it is used only for the GIS overlay. `Buscoords.txt` is in British National Grid metres
(EPSG:27700): the network lands at about 53.432 N, 2.138 W (Greater Manchester, UK).

## Verification network

The script also uses the LV test circuit of Tutorial 3 (`examples/Tut 3/tut_3_data/`), already in the repo.
