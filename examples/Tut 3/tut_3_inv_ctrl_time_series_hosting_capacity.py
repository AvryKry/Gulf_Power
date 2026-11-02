# This code executes tutorial 3 functionality from Team Nando and reads in txt files
# from AusNet Services given by Team Nando in the tutorial GitHub 
# Power systems are created locally and using imported .txt files from AusNet Services included in Team Nando GitHub
# Bus coordinates file created by Claude using the rest of the files and the Tut 2 Team Nando as reference
# These examples use the dss_py library

# Load data is also included in .npy format, but only for active power
# Thus, kvar profiles using a randomly selected power factor between 0.9 and 0.98

# This script was created using the Team Nando Tut 3 as a reference, and implementing
# the library of functions known as dss_toolkit, created by Gulf Power, residing in src/

# Avry Krywolt, October 26, 2026

# Import other libraries necessary for this script
import math
import sys
import random
from random import choice
from dss_toolkit import engine as eng, hosting, network as net, paths, plots, reports, scenario, timeseries as ts
import pandas
import numpy

## NOTE for creating this script - goal should be to pair down scripts from Tut and 3
# and include the functionality of Tut 3, all using dss_toolkit, and doing so as simple as possible and with as much reductions to code length and complexity as possible
# Do not use seasonal profiles, and do not select the day to study
# Instead, use all 365 days of PV profiles, and have the script evaluate the power flow under worst, best, and medium scenarios
# Worst being the one with greatest peak (most violations) and best being the one with almost no generation
# Have every profile ranked, then evaluate on 25 day intervals along the ranked list
# Include the option (matched pv-load profile day selection) to choose whether to match the load profile day with teh selected pv profile day, or to randomize the load profile day (with seed 1)
# Include a second independant seed (seed 2) to randomize the 31 loads to one of the 342 profided daily load profiles
# The seed can be adjusted to see different scenarios, but can also be kept constant
# In the case of constant seed 1 and constant seed 2, results should be identical
# Results should also be identical if the load profile day is chosen to match the pv profile day, and seed 2 is kept constant
# Otherwise, if load profile day is independent of pv profile day, changing either seed 1 or seed 2 independently or together should give entirely unique results
# There should also be a selection (PV selection) to run the power flow without PV, with PV, with PV and inverter control (volt-watt), and with PV and inverter control (volt-var)
# You should be able to run 1-4 of the PV selection options, and if more than 1 is run, the 4 runs under different PV conditions should be directly compared
# You should also be able to select (PV build selection) between randomized PV according to a penetration percentage with generalized specifications for each generator, and specified pv locations and ratings inside a dictionary list defined at the top of the script
# The output csv used in Tut 2 was good but will be too simple to accomodate all the variables in this script, add fields, restructure, and reorganize, but ensure that the key outputs (in simulation_results.csd from Tut 2) are retained
# Output files should continue to be saved to a folder (results/tut3) in a similar arrangement to Tut 2, and figures should not be shown in terminal or output, only acccessed inside the folder

# the functionality should be applied to the simple circuit (created locally) and the compiled circuit (LVcircuit-master.txt) in entirely different scripts to reduce clutter and aid in readability, but each should hold the complete fucntionality as described above
