# This code executes tutorial 2 functionality from Team Nando and reads in txt files
# from AusNet Services given by Team Nando in the tutorial GitHub 
# Power systems are created using imported .txt files from AusNet Services included in Team Nando GitHub
# Bus coordinates file created by Claude using the rest of the files and the Tut 2 Team Nando as reference
# These examples use the dss library, not the COM port

# Load data is also included in .npy format, but only for active power
# Thus, kvar profiles using a randomly selected power factor between 0.9 and 0.98

# This script was created using the Team Nando Tut 2 as a reference, and implementing
# the library of functions known as dss_toolkit, created by Gulf Power, residing in src/

# Avry Krywolt, October 22, 2026

# Import the dss library and check the object type
import dss
dss_py = dss.DSS
print(dss)
print("\n")      # <module 'dss' from '...\\site-packages\\dss\\__init__.py'>
print(dss.DSS)  # <dss.IDSS.IDSS object at 0x...>
print("\n") 

# Import other libraries necessary for this script
import math
import sys
import random
from random import choice
from dss_toolkit import engine as eng, hosting, network as net, paths, plots, reports, scenario, timeseries as ts
import pandas
import numpy

# Script inputs, change these to change the data used for the script or the implementation strategies
DATA_FOLDER_NAME = "tut_2_data"
MASTER_FILE_NAME = "LVcircuit-master.txt"
LOAD_DATA_FILE = "Residential load data 30-min resolution.npy"      # (profiles, days, steps) in kW
ANNUAL_PV_FILE = "Residential PV data 30-min resolution.npy"
VOLTAGE_BASES_KV = (22, 0.4)
LIMITS_PU = (0.94, 1.10)
TRANSFORMER_RATING_KVA = 175.0
STUB_PREFIXES = ()
PENETRATIONS = [0, 20, 40, 60, 80, 100 ]
SCENARIO_OPTIONS = dict(seed=9, pv_kva=10.0, pf_range=(0.9, 0.98))
SIM_DAYS = list(range(242, 260))
SIM_PV_PENETRATION = 55
REUSE_CIRCUIT = False                          
VERIFY_REUSE = False                           
RESULTS_FOLDER = "results/tut2"
HOSTING_CAP_RES_FOLDER = "results/tut2/hosting_capacity"
SEASON_PV_FILES = {"Summer": ("Residential_PV_profiles_Summer.npy", 21), # (file with 3 profiles, day to study)
                   "Autumn": ("Residential_PV_profiles_Autumn.npy", 59),
                   "Winter": ("Residential_PV_profiles_Winter.npy", 199),
                   "Spring": ("Residential_PV_profiles_Spring.npy", 229)}

# Establish a list of summary columns for the initial simulation
SUMMARY_COLUMNS = [("Window", "window", "s"), ("PV %", "penetration", "d"), ("PV systems", "n_pv", "d"),
                   ("Non-compliant", "n_noncompliant", "d"), ("Over", "n_over", "d"), ("Under", "n_under", "d"),
                   ("V min (pu)", "v_min", ".4f"), ("V max (pu)", "v_max", ".4f"), ("Peak |S| (kVA)", "s_peak", ".1f"),
                   ("Utilisation (%)", "utilisation", ".1f"), ("Min P (kW)", "p_min", ".1f")]

# FUNCTION to print results from the input table into the terminal
def print_summary(table, title):
    """Print a results table (DataFrame from hosting.run_study) with the columns above."""
    rows = [[reports.fmt(r[k], f) for _, k, f in SUMMARY_COLUMNS] for r in table.to_dict("records")]
    reports.print_table([h for h, _, _ in SUMMARY_COLUMNS], rows, title)

# Read, compile, and map the LV network with no applied PV
master_file = paths.locate_file(MASTER_FILE_NAME, DATA_FOLDER_NAME, verbose=False)
engine = eng.start_engine()
print(f"Circuit '{eng.compile_circuit(engine, master_file)}' read from {master_file.name}\n")
plots.apply_style()
plots.show_or_save(plots.plot_network_map(engine, STUB_PREFIXES, "Figure 1. No PV Network (0% Penetration)", "short"), paths.figure_path("Initial Network Map", RESULTS_FOLDER), show=False)

# load the profile data from npy files and  the shape, if final input is True
data_load = ts.load_profile_data(paths.locate_file(LOAD_DATA_FILE, DATA_FOLDER_NAME, verbose=False), to_print=False)
data_pv = ts.load_profile_data(paths.locate_file(ANNUAL_PV_FILE, DATA_FOLDER_NAME, verbose=False), to_print=False)

# NOTE This section is somewhat isolated from the simulation days and the hosting capacity experiment
# Plot the profile data for PV and load systems
# profiles are printed for the selected day
# Change the selected day or select a range
# Load profile is printed for all 342 customers, unless the first index is changed
profile_day = 16
customer_selection = 95
plots.show_or_save(plots.plot_time_series(data_load[:, profile_day, :], f"All load profiles, day {profile_day}",
                            "Active power (kW)", colour="#2a78d6", alpha=0.15), paths.figure_path(f"fig_ALL_load_profiles_day{profile_day}.png", RESULTS_FOLDER), False)
plots.show_or_save(plots.plot_time_series(data_pv[profile_day, :], f"PV profile, day {profile_day}",
                            "PV Output (pu)", colour="#d2310d", alpha=0.15), paths.figure_path(f"fig_PV_profile_day{profile_day}.png", RESULTS_FOLDER), False)

# Initial Simulation Section - Run sequence of selected days in SIM_DAYS
# with set SIM_PV_PENETRATION and assess the power flow results

# Setup the hosting capacity time series evaluation with the StudySetup data structure
setup = hosting.StudySetup(master_file=str(master_file), voltage_bases_kv=VOLTAGE_BASES_KV, limits=LIMITS_PU,
                           transformer_rating_kva=TRANSFORMER_RATING_KVA)

# Setup customers as a list of all Load names
customers = hosting.study_customers(engine, setup)

# Setup scenarios for the simulation days
# Set simulation pv penetration, can change
sim_scenarios = [scenario.random_scenario(customers, data_load, data_pv, scenario.TimeWindow.days(day), SIM_PV_PENETRATION, **SCENARIO_OPTIONS) 
                 for day in SIM_DAYS]

# Return a summary table of the sim_scenarios run and a full list of the simulations
# run which can be accesed and reloaded later
csv_path = paths.figure_path("simulation_results.csv", RESULTS_FOLDER) 
if csv_path and csv_path.exists():
    csv_path.unlink()
sim_summary, sim_run_simulations = hosting.run_study(engine, setup, sim_scenarios, csv_path, paths.figure_path("simulations", RESULTS_FOLDER), keep_simulations=True, reuse_circuit=REUSE_CIRCUIT)

# Print the summary table from the run simulations
# COMMENTED print_summary(sim_summary, f"Part A: days {SIM_DAYS} at {SIM_PV_PENETRATION} % penetration (annual PV data)")

# plot the PV curves across SIM_DAYS
plots.show_or_save(plots.plot_panels({f"Day {d}": s["V"] for d, s in zip(SIM_DAYS, sim_run_simulations)}, "Customer voltage (pu)",
                       limits=LIMITS_PU, title=f"Customer voltages, {SIM_PV_PENETRATION} % PV penetration"), paths.figure_path("fig_voltage_profiles_of_sim_days.png", RESULTS_FOLDER), show=False)

# plot the voltage curves of the customer buses across SIM_DAYS
plots.show_or_save(plots.plot_time_series(data_pv[SIM_DAYS], "PV profiles of the simulated days", "PV output (pu)",
                            labels=[f"Day {d}" for d in SIM_DAYS]), paths.figure_path("fig_pv_profiles_of_sim_days.png", RESULTS_FOLDER), show=False)

# Illustrated the locations of the added PV
# Added PV only dependent on the Scenario Setup seed and the PV penetration
# Standard across all days and run simulations
pv_map_scenario = sim_scenarios[0]
plots.show_or_save(plots.plot_der_map(engine, pv_map_scenario, STUB_PREFIXES,
                                      f"Figure 2. PV placement, {SIM_PV_PENETRATION} % penetration", labels="short"),
                   paths.figure_path(f"Network Map W PV - {SIM_PV_PENETRATION}pct.png", RESULTS_FOLDER), show=False)

# Verify correct use of scenario demand with simulated demand (only one selected customer amd simulation to check)
# Can change the simulation being verified and the customer being verified
sim_number_to_check = 9
customer_to_check = 28
sim_to_check = sim_run_simulations[sim_number_to_check]
customer = sim_to_check["loads"][customer_to_check]
scenario_load = sim_to_check["scenario"].demand[customer][0]
simulated_load = sim_to_check["P"][customer_to_check]
plots.show_or_save(plots.plot_time_series([scenario_load, simulated_load], f"Demand check, {customer}", "Active power (kW)",
                            labels=["scenario profile", "simulated (OpenDSS)"], styles=["-", "--"]), paths.figure_path("fig_scenario-simulation_demand_check.png", RESULTS_FOLDER), show=False)
print(f"Largest difference between scenario and simulated demand of {customer}: {numpy.abs(scenario_load - simulated_load).max():.2e} kW")

## INCOMPLETE
## HOSTING CAPACITY EXERCISE SECTION SECTION

# Establish the results file location for the hosting capacity CSV redsults
hosting_csv_path = paths.figure_path("hosting_capacity_results.csv", HOSTING_CAP_RES_FOLDER) 
if hosting_csv_path and hosting_csv_path.exists():
    hosting_csv_path.unlink()