# This code progresses through a series of small LV system examples for running
# power flow analysis including PV implementation and
# Power systems are created within the code manually
# These examples use the dss library, not the COM port

# Avry Krywolt, October 13, 2026

# Import the dss library and check the object type
import dss
dss_py = dss.DSS
print(dss)      # <module 'dss' from '...\\site-packages\\dss\\__init__.py'>
print(dss.DSS)  # <dss.IDSS.IDSS object at 0x...>

# Setup DSS and map DSS commands to simple fuctions rather than nested executables
DSSText = dss_py.Text
DSSCircuit = dss_py.ActiveCircuit
DSSSolution = dss_py.ActiveCircuit.Solution
ControlQuery = dss_py.ActiveCircuit.CtrlQueue
dss_py.AllowForms = True

# Clear DSS, set freq, create a new circuit, and add a source at 11kV, 1.0pu, 3 phase
DSSText.Command = 'Clear'
DSSText.Command = 'Set DefaultBaseFrequency=50'
DSSText.Command = 'New Circuit.Simple_LV_Network'
DSSText.Command = 'Edit vsource.source bus1=sourceBus basekv=11 pu=1.0 phases=3'

# Create the step down transformer from the 11kV source to the 0.4kV LV network
DSSText.Command = 'New transformer.LVTR Buses=[sourceBus, A.1.2.3] Conns=[delta, wye] KVs=[11, 0.4] KVAs=[250, 250] %Rs=0.00 xhl=2.5 %loadloss=0.00'

# Create linecodes to apply to the 400V and 230V lines
DSSText.Command = 'New Linecode.240sq nphases=3 R1=0.127 X1=0.072 R0=0.342 X0=0.089 units=km normamps=208'
DSSText.Command = 'New Linecode.16sq nphases=1 R1=1.15 X1=0.083 R0=1.2 X0=0.083 units=km normamps=107'

# Create lines using line codes - 1 1km 400V line from Bus A to B
# 3 100m 230V lines from Bus B to C, D, and E load buses
DSSText.Command = 'new line.A_B bus1=A.1.2.3 bus2=B.1.2.3 length=1 phases=3 units=km linecode=240sq'
DSSText.Command = 'new line.B_L1 bus1=B.1 bus2=C.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L2 bus1=B.2 bus2=D.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L3 bus1=B.3 bus2=E.1 length=0.01 phases=1 units=km linecode=16sq'

# Create loads at each of the buses, constant profile and constant pf

DSSText.Command = 'new load.Load_1 bus1=C.1 phases=1 kV=(0.4 3 sqrt /) kW=7 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_2 bus1=D.1 phases=1 kV=(0.4 3 sqrt /) kW=6 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_3 bus1=E.1 phases=1 kV=(0.4 3 sqrt /) kW=8 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'

# Limit control of the model with controlmode = static and mode = snapshot
# Set pu voltage bases, calculate the voltage bases of all elements
# Set the maximum control iteration to 1000, if the cap is hit on circuit control elements, an appropriate error message will appear
DSSText.Command = 'set controlmode=static'
DSSText.Command = 'set mode=snapshot'
DSSText.Command = 'Set VoltageBases=[11 0.4]'
DSSText.Command = 'calcvoltagebases'
DSSText.Command = 'Set maxcontroliter=1000'

# Run the power flow solution and receive confirmation as a printed message on convergence
DSSSolution.Solve()
if DSSSolution.Converged:
    print('\nPower flow solution converged successfully for Case 1 (Simple, no PV)')
    print('\n')


# Extract the power flow results and print as simple output
# To extract the values from each element requires setting the elemnt as active 
# and thee extracting the desired information

# Extract and print load powers
load_names = ["Load_1", "Load_2", "Load_3"]
print("---------------------------------")
print(f"| Load Name | P (kW) | Q (kVAr) |")
print("---------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    print(f"|  {load}   | {round(DSSCircuit.ActiveElement.Powers[0], 3):.3f}  |  {round(DSSCircuit.ActiveElement.Powers[1], 3):.3f}   |")
print("---------------------------------")

# Extract load bus voltages for each load
# pu Voltage, Real Component of Voltage, Imaginary Component of Voltage
print("\nBus voltages at each load:")
print("---------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    bus_name = DSSCircuit.ActiveElement.Properties('bus1').Val
    DSSCircuit.SetActiveBus(bus_name)
    print(f"|  {load}   | {round(DSSCircuit.ActiveBus.puVmagAngle[0], 3)}pu  |  {round(DSSCircuit.ActiveBus.Voltages[0], 3):.3f}V-Re  |  {round(DSSCircuit.ActiveElement.Voltages[1], 3):.3f}V-Im   |")
print("---------------------------------")

# Extract 3 phase bus voltages at the 3-phase bus
p3_bus_name = "A"
DSSCircuit.SetActiveBus(p3_bus_name)
print(f"\n\nVoltage magnitudes at bus {p3_bus_name}")
for phase in DSSCircuit.ActiveBus.Nodes:
    print(f"Bus {p3_bus_name} Phase {phase}: pu Voltage = {round(DSSCircuit.ActiveBus.puVmagAngle[2*phase-2], 3)}, Voltage = {round(DSSCircuit.ActiveBus.Voltages[2*phase-2], 3)}V-Re, {round(DSSCircuit.ActiveBus.Voltages[2*phase-1], 3):.3f}V-Im")

# Extract and print the P and Q values from the transformer
DSSCircuit.SetActiveElement('transformer.LVTR')
active_power = abs(DSSCircuit.ActiveElement.Powers[8:13:2]) # Range from 8 to 14 with step 2, selecting 8, 10, and 12
reactive_power = abs(DSSCircuit.ActiveElement.Powers[9:14:2]) # Range from 9 to 14 with step 2, selecting 9, 11, and 13

# The zip functionality used in the printing loop here could be very useful for 
# future tool functionality
print("\n\nActive Power (P) and Reactive Power (Q) of the Transformer LVTR per phase:")
print("-----------------------------")
print(f"| Phase | P (kW) | Q (kVAr) |")
print("-----------------------------")
for phase, P, Q in zip(range(1, 4), active_power, reactive_power):
    print(f"|   {phase}   | {round(P, 3)}  |  {round(Q, 3)}   |")
print("-----------------------------")

# Extract and print line losses
line_loss = DSSCircuit.LineLosses
print(f"\n\nResults of the Power Losses: ")
print(f"Active power (P) losses = {round(abs(line_loss[0]), 3)} kW")
print(f"Reactive power (Q) losses = {round(abs(line_loss[1]), 3)} kVAr")

print("\n\nCase 1 Complete\n[][][][][][][][][][][][][][]")

# Now the exercises begin, starting with the Case 2 (Expanded, no PV)
# For learning purposes, each case is programmed independently to practice
# how to use the dss_py library, thus each case results and printed in the output


# Case 2: Expanded LV grid from Case 1
# Clear DSS, set freq, create a new circuit, and add a source at 11kV, 1.0pu, 3 phase
DSSText.Command = 'Clear'
DSSText.Command = 'Set DefaultBaseFrequency=50'
DSSText.Command = 'New Circuit.Expanded_LV_Network'
DSSText.Command = 'Edit vsource.source bus1=sourceBus basekv=11 pu=1.0 phases=3'

# Create the step down transformer from the 11kV source to the 0.4kV LV network
DSSText.Command = 'New transformer.LVTR Buses=[sourceBus, A.1.2.3] Conns=[delta, wye] KVs=[11, 0.4] KVAs=[250, 250] %Rs=0.00 xhl=2.5 %loadloss=0.00'

# Create linecodes to apply to the 400V and 230V lines
DSSText.Command = 'New Linecode.240sq nphases=3 R1=0.127 X1=0.072 R0=0.342 X0=0.089 units=km normamps=208'
DSSText.Command = 'New Linecode.16sq nphases=1 R1=1.15 X1=0.083 R0=1.2 X0=0.083 units=km normamps=107'

# Create lines using line codes - 1 1km 400V line from Bus A to B
# 3 100m 230V lines from Bus B to C, D, and E load buses
DSSText.Command = 'new line.A_B bus1=A.1.2.3 bus2=B.1.2.3 length=1 phases=3 units=km linecode=240sq'
DSSText.Command = 'new line.B_F bus1=B.1.2.3 bus2=F.1.2.3 length=1 phases=3 units=km linecode=240sq'
DSSText.Command = 'new line.B_L1 bus1=B.1 bus2=C.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L2 bus1=B.2 bus2=D.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L3 bus1=B.3 bus2=E.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.F_L1 bus1=F.1 bus2=G.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.F_L2 bus1=F.2 bus2=H.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.F_L3 bus1=F.3 bus2=J.1 length=0.01 phases=1 units=km linecode=16sq'

# Create loads at each of the buses, constant profile and constant pf
DSSText.Command = 'new load.Load_1 bus1=C.1 phases=1 kV=(0.4 3 sqrt /) kW=7 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_2 bus1=D.1 phases=1 kV=(0.4 3 sqrt /) kW=6 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_3 bus1=E.1 phases=1 kV=(0.4 3 sqrt /) kW=8 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_4 bus1=G.1 phases=1 kV=(0.4 3 sqrt /) kW=7 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_5 bus1=H.1 phases=1 kV=(0.4 3 sqrt /) kW=9 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_6 bus1=J.1 phases=1 kV=(0.4 3 sqrt /) kW=8 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'

# Limit control of the model with controlmode = static and mode = snapshot
# Set pu voltage bases, calculate the voltage bases of all elements
# Set the maximum control iteration to 1000, if the cap is hit on circuit control elements, an appropriate error message will appear
DSSText.Command = 'set controlmode=static'
DSSText.Command = 'set mode=snapshot'
DSSText.Command = 'Set VoltageBases=[11 0.4]'
DSSText.Command = 'calcvoltagebases'
DSSText.Command = 'Set maxcontroliter=1000'

# Run the power flow solution and receive confirmation as a printed message on convergence
DSSSolution.Solve()
if DSSSolution.Converged:
    print('\nPower flow solution converged successfully for Case 2 (Expanded, no PV)')
    print('\n')


# Extract the power flow results and print as simple output
# To extract the values from each element requires setting the elemnt as active 
# and thee extracting the desired information

# Extract and print load powers
load_names = ["Load_1", "Load_2", "Load_3", "Load_4", "Load_5", "Load_6"]
print("---------------------------------")
print(f"| Load Name | P (kW) | Q (kVAr) |")
print("---------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    print(f"|  {load}   | {round(DSSCircuit.ActiveElement.Powers[0], 3):.3f}  |  {round(DSSCircuit.ActiveElement.Powers[1], 3):.3f}   |")
print("---------------------------------")

# Extract load bus voltages for each load
# pu Voltage, Real Component of Voltage, Imaginary Component of Voltage
print("\nBus voltages at each load:")
print("---------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    bus_name = DSSCircuit.ActiveElement.Properties('bus1').Val
    DSSCircuit.SetActiveBus(bus_name)
    print(f"|  {load}   | {round(DSSCircuit.ActiveBus.puVmagAngle[0], 3)}pu  |  {round(DSSCircuit.ActiveBus.Voltages[0], 3):.3f}V-Re  |  {round(DSSCircuit.ActiveElement.Voltages[1], 3):.3f}V-Im   |")
print("---------------------------------")

# Extract 3 phase bus voltages at the 3-phase bus
p3_bus_name = "A"
DSSCircuit.SetActiveBus(p3_bus_name)
print(f"\n\nVoltage magnitudes at bus {p3_bus_name}")
for phase in DSSCircuit.ActiveBus.Nodes:
    print(f"Bus {p3_bus_name} Phase {phase}: pu Voltage = {round(DSSCircuit.ActiveBus.puVmagAngle[2*phase-2], 3)}, Voltage = {round(DSSCircuit.ActiveBus.Voltages[2*phase-2], 3)}V-Re, {round(DSSCircuit.ActiveBus.Voltages[2*phase-1], 3):.3f}V-Im")

# Extract 3 phase bus voltages at the 3-phase bus
p3_bus_name = "F"
DSSCircuit.SetActiveBus(p3_bus_name)
print(f"\n\nVoltage magnitudes at bus {p3_bus_name}")
for phase in DSSCircuit.ActiveBus.Nodes:
    print(f"Bus {p3_bus_name} Phase {phase}: pu Voltage = {round(DSSCircuit.ActiveBus.puVmagAngle[2*phase-2], 3)}, Voltage = {round(DSSCircuit.ActiveBus.Voltages[2*phase-2], 3)}V-Re, {round(DSSCircuit.ActiveBus.Voltages[2*phase-1], 3):.3f}V-Im")

# Extract and print the P and Q values from the transformer
DSSCircuit.SetActiveElement('transformer.LVTR')
active_power = abs(DSSCircuit.ActiveElement.Powers[8:13:2]) # Range from 8 to 14 with step 2, selecting 8, 10, and 12
reactive_power = abs(DSSCircuit.ActiveElement.Powers[9:14:2]) # Range from 9 to 14 with step 2, selecting 9, 11, and 13

# The zip functionality used in the printing loop here could be very useful for 
# future tool functionality
print("\n\nActive Power (P) and Reactive Power (Q) of the Transformer LVTR per phase:")
print("-----------------------------")
print(f"| Phase | P (kW) | Q (kVAr) |")
print("-----------------------------")
for phase, P, Q in zip(range(1, 4), active_power, reactive_power):
    print(f"|   {phase}   | {round(P, 3)}  |  {round(Q, 3)}   |")
print("-----------------------------")

# Extract and print line losses
line_loss = DSSCircuit.LineLosses
print(f"\n\nResults of the Power Losses: ")
print(f"Active power (P) losses = {round(abs(line_loss[0]), 3)} kW")
print(f"Reactive power (Q) losses = {round(abs(line_loss[1]), 3)} kVAr")

print("\n\nCase 2 Complete\n[][][][][][][][][][][][][][]")

# Case 3: Expanded LV grid from Case 1, w/ PV
# Clear DSS, set freq, create a new circuit, and add a source at 11kV, 1.0pu, 3 phase
DSSText.Command = 'Clear'
DSSText.Command = 'Set DefaultBaseFrequency=50'
DSSText.Command = 'New Circuit.Expanded_LV_Network_w_PV'
DSSText.Command = 'Edit vsource.source bus1=sourceBus basekv=11 pu=1.0 phases=3'

# Create the step down transformer from the 11kV source to the 0.4kV LV network
DSSText.Command = 'New transformer.LVTR Buses=[sourceBus, A.1.2.3] Conns=[delta, wye] KVs=[11, 0.4] KVAs=[250, 250] %Rs=0.00 xhl=2.5 %loadloss=0.00'

# Create linecodes to apply to the 400V and 230V lines
DSSText.Command = 'New Linecode.240sq nphases=3 R1=0.127 X1=0.072 R0=0.342 X0=0.089 units=km normamps=208'
DSSText.Command = 'New Linecode.16sq nphases=1 R1=1.15 X1=0.083 R0=1.2 X0=0.083 units=km normamps=107'

# Create lines using line codes - 1 1km 400V line from Bus A to B
# 3 100m 230V lines from Bus B to C, D, and E load buses
DSSText.Command = 'new line.A_B bus1=A.1.2.3 bus2=B.1.2.3 length=1 phases=3 units=km linecode=240sq'
DSSText.Command = 'new line.B_F bus1=B.1.2.3 bus2=F.1.2.3 length=1 phases=3 units=km linecode=240sq'
DSSText.Command = 'new line.B_L1 bus1=B.1 bus2=C.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L2 bus1=B.2 bus2=D.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L3 bus1=B.3 bus2=E.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.F_L1 bus1=F.1 bus2=G.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.F_L2 bus1=F.2 bus2=H.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.F_L3 bus1=F.3 bus2=J.1 length=0.01 phases=1 units=km linecode=16sq'

# Create loads at each of the buses, constant profile and constant pf
DSSText.Command = 'new load.Load_1 bus1=C.1 phases=1 kV=(0.4 3 sqrt /) kW=7 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_2 bus1=D.1 phases=1 kV=(0.4 3 sqrt /) kW=6 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_3 bus1=E.1 phases=1 kV=(0.4 3 sqrt /) kW=8 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_4 bus1=G.1 phases=1 kV=(0.4 3 sqrt /) kW=7 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_5 bus1=H.1 phases=1 kV=(0.4 3 sqrt /) kW=9 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_6 bus1=J.1 phases=1 kV=(0.4 3 sqrt /) kW=8 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'

# Create PV sources at each of the new house load buses
DSSText.Command = 'new PVSystem.PV4 bus1=G.1 phases=1 kva=5 pmpp=5 pf=1 kv=(0.4 3 sqrt /) model=1'
DSSText.Command = 'new PVSystem.PV5 bus1=H.1 phases=1 kva=5 pmpp=5 pf=1 kv=(0.4 3 sqrt /) model=1'
DSSText.Command = 'new PVSystem.PV6 bus1=J.1 phases=1 kva=5 pmpp=5 pf=1 kv=(0.4 3 sqrt /) model=1'

# Limit control of the model with controlmode = static and mode = snapshot
# Set pu voltage bases, calculate the voltage bases of all elements
# Set the maximum control iteration to 1000, if the cap is hit on circuit control elements, an appropriate error message will appear
DSSText.Command = 'set controlmode=static'
DSSText.Command = 'set mode=snapshot'
DSSText.Command = 'Set VoltageBases=[11 0.4]'
DSSText.Command = 'calcvoltagebases'
DSSText.Command = 'Set maxcontroliter=1000'

# Run the power flow solution and receive confirmation as a printed message on convergence
DSSSolution.Solve()
if DSSSolution.Converged:
    print('\nPower flow solution converged successfully for Case 3 (Expanded, w/ PV)')
    print('\n')


# Extract the power flow results and print as simple output
# To extract the values from each element requires setting the elemnt as active 
# and thee extracting the desired information

# Extract and print load powers
load_names = ["Load_1", "Load_2", "Load_3", "Load_4", "Load_5", "Load_6"]
print("---------------------------------")
print(f"| Load Name | P (kW) | Q (kVAr) |")
print("---------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    print(f"|  {load}   | {round(DSSCircuit.ActiveElement.Powers[0], 3):.3f}  |  {round(DSSCircuit.ActiveElement.Powers[1], 3):.3f}   |")
print("---------------------------------")

# Extract load bus voltages for each load
# pu Voltage, Real Component of Voltage, Imaginary Component of Voltage
print("\nBus voltages at each load:")
print("---------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    bus_name = DSSCircuit.ActiveElement.Properties('bus1').Val
    DSSCircuit.SetActiveBus(bus_name)
    print(f"|  {load}   | {round(DSSCircuit.ActiveBus.puVmagAngle[0], 3)}pu  |  {round(DSSCircuit.ActiveBus.Voltages[0], 3):.3f}V-Re  |  {round(DSSCircuit.ActiveElement.Voltages[1], 3):.3f}V-Im   |")
print("---------------------------------")

# Extract 3 phase bus voltages at the 3-phase bus
p3_bus_name = "A"
DSSCircuit.SetActiveBus(p3_bus_name)
print(f"\n\nVoltage magnitudes at bus {p3_bus_name}")
for phase in DSSCircuit.ActiveBus.Nodes:
    print(f"Bus {p3_bus_name} Phase {phase}: pu Voltage = {round(DSSCircuit.ActiveBus.puVmagAngle[2*phase-2], 3)}, Voltage = {round(DSSCircuit.ActiveBus.Voltages[2*phase-2], 3)}V-Re, {round(DSSCircuit.ActiveBus.Voltages[2*phase-1], 3):.3f}V-Im")

# Extract 3 phase bus voltages at the 3-phase bus
p3_bus_name = "F"
DSSCircuit.SetActiveBus(p3_bus_name)
print(f"\n\nVoltage magnitudes at bus {p3_bus_name}")
for phase in DSSCircuit.ActiveBus.Nodes:
    print(f"Bus {p3_bus_name} Phase {phase}: pu Voltage = {round(DSSCircuit.ActiveBus.puVmagAngle[2*phase-2], 3)}, Voltage = {round(DSSCircuit.ActiveBus.Voltages[2*phase-2], 3)}V-Re, {round(DSSCircuit.ActiveBus.Voltages[2*phase-1], 3):.3f}V-Im")

# Extract and print the P and Q values from the transformer
DSSCircuit.SetActiveElement('transformer.LVTR')
active_power = abs(DSSCircuit.ActiveElement.Powers[8:13:2]) # Range from 8 to 14 with step 2, selecting 8, 10, and 12
reactive_power = abs(DSSCircuit.ActiveElement.Powers[9:14:2]) # Range from 9 to 14 with step 2, selecting 9, 11, and 13

# The zip functionality used in the printing loop here could be very useful for 
# future tool functionality
print("\n\nActive Power (P) and Reactive Power (Q) of the Transformer LVTR per phase:")
print("-----------------------------")
print(f"| Phase | P (kW) | Q (kVAr) |")
print("-----------------------------")
for phase, P, Q in zip(range(1, 4), active_power, reactive_power):
    print(f"|   {phase}   | {round(P, 3)}  |  {round(Q, 3)}   |")
print("-----------------------------")

# Extract and print line losses
line_loss = DSSCircuit.LineLosses
print(f"\n\nResults of the Power Losses: ")
print(f"Active power (P) losses = {round(abs(line_loss[0]), 3)} kW")
print(f"Reactive power (Q) losses = {round(abs(line_loss[1]), 3)} kVAr")

print("\n\nCase 3 Complete\n[][][][][][][][][][][][][][]")


# Cases 4 and 5 completed in separate .py file (tut_1_alternate_LV_power_flow.py)