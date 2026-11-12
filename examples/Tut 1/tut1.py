import os
print("Working directory:", os.getcwd())
added_path = ""
if os.getenv("COLAB_RELEASE_TAG"):
    !git clone --depth=1 -q https://github.com/Team-Nando/Tutorial-DERHostingCapacity-1-AdvancedTools_LV
    !pip install dss-python==0.15.3
    added_path = '/Tutorial-DERHostingCapacity-1-AdvancedTools_LV'
import dss
my_directory = os.getcwd() + added_path
print(f"The direction is located in the following path: my_directory = {my_directory}")

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