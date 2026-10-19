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

