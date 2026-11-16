import dss

dss_engine = dss.DSS
DSSText = dss_engine.Text
DSSCircuit = dss_engine.ActiveCircuit
DSSSolution = dss_engine.ActiveCircuit.Solution
ControlQueue = dss_engine.ActiveCircuit.CtrlQueue
dss_engine.AllowForms = 0

DSSText.Command = 'Clear'
DSSText.Command = 'Set DefaultBaseFrequency=50'
DSSText.Command = 'New Circuit.Simple_LV_Network'
DSSText.Command = 'Edit vsource.source bus1=sourceBus basekv=11 pu=1.0 phases=3'

DSSText.Command = 'New transformer.LVTR Buses=[sourcebus, A.1.2.3] Conns=[delta wye] KVs=[11, 0.4] KVAs=[250 250] %Rs=0.00 xhl=2.5 %loadloss=0 '

DSSText.Command = 'new linecode.240sq nphases=3 R1=0.127 X1=0.072 R0=0.342 X0=0.089 units=km normamps = 208'
DSSText.Command = 'new linecode.16sq nphases=1 R1=1.15 X1=0.083 R0=1.2 X0=0.083 units=km normamps = 107'

DSSText.Command = 'new line.A_B bus1=A.1.2.3 bus2=B.1.2.3 length=1 phases=3 units=km linecode=240sq'
DSSText.Command = 'new line.B_L1 bus1=B.1 bus2=C.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L2 bus1=B.2 bus2=D.1 length=0.01 phases=1 units=km linecode=16sq'
DSSText.Command = 'new line.B_L3 bus1=B.3 bus2=E.1 length=0.01 phases=1 units=km linecode=16sq'

DSSText.Command = 'new load.Load_1 bus1=C.1 phases=1 kV=(0.4 3 sqrt /) kW=7 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_2 bus1=D.1 phases=1 kV=(0.4 3 sqrt /) kW=6 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'
DSSText.Command = 'new load.Load_3 bus1=E.1 phases=1 kV=(0.4 3 sqrt /) kW=8 pf=0.95 model=1 conn=wye Vminpu=0.85 Vmaxpu=1.20 status=fixed'

DSSText.Command = 'set controlmode=static'
DSSText.Command = 'set mode=snapshot'
DSSText.Command = 'Set VoltageBases=[11 0.4]'
DSSText.Command = 'calcvoltagebases'
DSSText.Command = 'Set maxcontroliter=1000'

DSSSolution.Solve()
if DSSSolution.Converged:
    print("The Circuit was Successfully Solved :-)")
    print("\n")

load_names = ["Load_1", "Load_2", "Load_3"]
# Print in a table
print("Active power (P) and Reactive power (Q) demand of the loads:")
print("---------------------------------")
print(f"| Load Name | P (kW) | Q (kVAr) |")
print("---------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    print(f"|  {load}   | {round(DSSCircuit.ActiveElement.Powers[0], 3):.3f}  |  {round(DSSCircuit.ActiveElement.Powers[1], 3):.3f}   |")
print("---------------------------------")

active_load = "Load_1" 
DSSCircuit.SetActiveElement(f"Load.{active_load}") # Set the load as an active element
bus_name = DSSCircuit.ActiveElement.Properties('bus1').Val # Extract the name of the bus connected to the load
DSSCircuit.SetActiveBus(bus_name) # Set the bus as an active element
print(f"The voltage [in p.u.] of the bus connected to {active_load} = {round(DSSCircuit.ActiveBus.puVmagAngle[0], 3)} pu") # Extract the voltage magnitude of the active bus

active_bus = "A"  # ← only change the bus name (sourcebus, A, B)
DSSCircuit.SetActiveBus(active_bus)
print(f"Voltage magnitudes at bus {active_bus}:  ")
for phase in DSSCircuit.ActiveBus.Nodes: # Loop over the phases of the bus
    print(f"Phase {phase} = {round(DSSCircuit.ActiveBus.puVmagAngle[2*phase - 2], 3)} pu") # The series 2*phase - 2 is used to extract the voltage magnitude of the phase

DSSCircuit.SetActiveElement('transformer.LVTR')
active_power = abs(DSSCircuit.ActiveElement.Powers[8:13:2]) # Range from 8 to 14 with step 2, selecting 8, 10, and 12
reactive_power = abs(DSSCircuit.ActiveElement.Powers[9:14:2]) # Range from 9 to 14 with step 2, selecting 9, 11, and 13

# Print values in a table
print("Active Power (P) and Reactive Power (Q) of the Transformer LVTR per phase:")
print("-----------------------------")
print(f"| Phase | P (kW) | Q (kVAr) |")
print("-----------------------------")
for phase, P, Q in zip(range(1, 4), active_power, reactive_power):
    print(f"|   {phase}   | {round(P, 3)}  |  {round(Q, 3)}   |")
print("-----------------------------")

line_loss = DSSCircuit.LineLosses
print(f"Results of the Power Losses: ")
print(f"Active power (P) losses = {round(abs(line_loss[0]), 3)} kW")
print(f"Reactive power (Q) losses = {round(abs(line_loss[1]), 3)} kVAr")

#Exercise 1

