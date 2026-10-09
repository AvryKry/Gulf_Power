from dss import DSS

DSS.Text.Command = "clear"
DSS.Text.Command = "new circuit.demo basekv=12.47 pu=1.0 phases=3 bus1=source"
DSS.Text.Command = "new line.l1 bus1=source bus2=load1 phases=3 r1=0.3 x1=0.4 length=1 units=km"
DSS.Text.Command = "new load.ld1 bus1=load1 phases=3 kv=12.47 kw=1000 pf=0.95"
DSS.Text.Command = "set voltagebases=[12.47]"
DSS.Text.Command = "calcvoltagebases"

circuit = DSS.ActiveCircuit
circuit.Solution.Solve()

print("Converged:", circuit.Solution.Converged)
print("Buses:", circuit.AllBusNames)
print("Voltage (pu):", circuit.AllBusVmagPu)