# This code operates an simple example of a PV network using DSS through the COM 
# port. Results with COM are compared to dss_python library. Learning COM coudl be
# important if dss_python has limitations in applications to our problem formation

# Avry Krywolt, October 8, 2026

# Start OpenDSS via COM interface, then check the object type
import win32com.client
dss_com = win32com.client.Dispatch("OpenDSSEngine.DSS") 
print(dss_com)  # Should print <COMObject OpenDSSEngine.DSS>

# Import the dss library and check the object type
import dss
dss_py = dss.DSS
print(dss)      # <module 'dss' from '...\\site-packages\\dss\\__init__.py'>
print(dss.DSS)  # <dss.IDSS.IDSS object at 0x...>

# Import other necessary libraries
import time # to capture the time taken to run the simulations
import matplotlib.pyplot as plt # to plot the results
import numpy as np # to handle numerical data


# Initialize network data in a list of ordered text commands (this is how OpenDSS 
# interprets the commands given in Python as OpenDSS executables)
# Order matters, it is the order the instructions will be executed
text_commands = [
    'clear',
    'set DefaultBaseFrequency=50',
    'new circuit.test_lv_feeder bus1=slack basekv=0.4 pu=1.0 angle=0 frequency=50 phases=3',    
    'new line.slack-B1 phases=3 bus1=slack bus2=B1 r1=0.1 x1=0.1 r0=0.05 x0=0.05 length=1',
    'new line.B1-B2 phases=3 bus1=B1 bus2=B2 r1=0.1 x1=0.1 r0=0.05 x0=0.05 length=1',
    'new line.B2-B3 phases=3 bus1=B2 bus2=B3 r1=0.1 x1=0.1 r0=0.05 x0=0.05 length=1',
    'new loadshape.demand npts=24 interval=1.0 mult={1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 5.0, 3.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 5.0, 7.0, 7.0, 5.0, 3.0, 1.0, 1.0,}',
    'new loadshape.solar  npts=24 interval=1.0 mult={0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.3, 0.5, 0.7, 0.8, 1.0, 0.8, 0.7, 0.5, 0.3, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,}',   
    'new load.house phases=1 bus1=B3.1 kv=0.23 kw=1 kvar=0 vmaxpu=1.5 vminpu=0.8 daily=demand',
    'new generator.pv_system phases=1 bus1=B3.2 kv=0.23 kw=5 pf=1 vmaxpu=1.5 vminpu=0.8 daily=solar',
    'reset',
    'set ControlMode=Time',
    'set Mode=Daily StepSize=1h Number=1 Time=(0,0)',
    'set VoltageBases=[0.4]',
    'calcv',    
]

# Now run the COM model by an initialization, followed by looping through the 
# text commands in order to build the model in COM
start_com = time.time()
dss_com.Start(0)
dss_com.AllowForms = True

for cmd in text_commands:
    dss_com.Text.Command = cmd

# Declare the simulation hours and nested dictionaries to organize the data
# from the simulation results.
n_hours = 24
data_com = {
    'PV System': {'element_name': 'generator.pv_system', 'Power (kW)': [], 'Voltage (V)': []},
    'House': {'element_name': 'load.house', 'Power (kW)': [], 'Voltage (V)': []}
}

# Run the COM simulation for each hour, and record each data point within the
# nested dictionaries data structure
for t in range(n_hours):
    dss_com.ActiveCircuit.Solution.Solve()
    
    for element in data_com.keys():
        dss_com.ActiveCircuit.SetActiveElement(data_com[element]['element_name'])
        data_com[element]['Power (kW)'].append(dss_com.ActiveCircuit.ActiveElement.Powers[0])
        data_com[element]['Voltage (V)'].append(dss_com.ActiveCircuit.ActiveElement.VoltagesMagAng[0])

# Capture the simulation run time for the COM simulation
end_com = time.time() 

# Use the matlab engine and pyplot to plot the results from the COM simulation
# Initialize the figure and axes for the plots
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.subplots_adjust(hspace=0.2, wspace=0.2)
plt.suptitle('Using COM interface')

# Interpret the keys from the data storage strcuture to make parsing and plotting easier
# by removing the element name and leaving only the element type (e.g., 'PV System' or 'House')
primary_keys = list(data_com.keys())
inner_keys = [key for key in data_com[primary_keys[0]].keys() if key != 'element_name']

# Iterate over rows: PV row 1, House row 2
# Iterate over columns: Power column 1, Voltage column 2
# Add axis labels and titles for the first row and first column 
# Plot each data point for each element and each property (Power and Voltage)
for i, primary_key in enumerate(primary_keys):
    for j, inner_key in enumerate(inner_keys):
        ax = axes[i, j]  # Select subplot
        # Set column title for the first row only
        if i == 0: ax.set_title(inner_key, fontsize=12, fontweight='bold')
        # Set row label for the first column only
        if j == 0: ax.set_ylabel(primary_key, rotation=90, fontsize=12, fontweight='bold')
            

        # Example placeholder for empty data
        ax.plot(data_com[primary_key][inner_key])  # Replace with actual data if available
        ax.set_xticks([0, 6, 12, 18, 24])
        ax.grid(True)
        
plt.show()




### ENTIRE PROCESS REPEATED IN dss_python
start_dss = time.time()  # to capture the starting time for dss via python
dss_py.Start(0)

for cmd in text_commands:
    dss_py.Text.Command = cmd
    
n_hours = 24 
data_python = {
    'PV System': {'element_name': 'generator.pv_system', 'Power (kW)': [], 'Voltage (V)': []},
    'House': {'element_name': 'load.house', 'Power (kW)': [], 'Voltage (V)': []}
}
for t in range(n_hours):
    dss_py.ActiveCircuit.Solution.Solve()
    
    for element in data_python.keys():
        dss_py.ActiveCircuit.SetActiveElement(data_python[element]['element_name'])
        data_python[element]['Power (kW)'].append(dss_py.ActiveCircuit.ActiveElement.Powers[0])
        data_python[element]['Voltage (V)'].append(dss_py.ActiveCircuit.ActiveElement.VoltagesMagAng[0])

end_dss = time.time()

fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.subplots_adjust(hspace=0.2, wspace=0.2)
plt.suptitle('Using DSS-Python library')

primary_keys = list(data_python.keys())
inner_keys = [key for key in data_python[primary_keys[0]].keys() if key != 'element_name']

for i, primary_key in enumerate(primary_keys):
    for j, inner_key in enumerate(inner_keys):
        ax = axes[i, j]  # Select subplot
        # Set column title for the first row only
        if i == 0: ax.set_title(inner_key, fontsize=12, fontweight='bold')
        # Set row label for the first column only
        if j == 0: ax.set_ylabel(primary_key, rotation=90, fontsize=12, fontweight='bold')
            

        ax.plot(data_python[primary_key][inner_key])  # Replace with actual data if available
        ax.set_xticks([0, 6, 12, 18, 24])
        
plt.show()

print(np.array(data_com['PV System']['Voltage (V)']) - np.array(data_python['PV System']['Voltage (V)']))
print(np.array(data_com['PV System']['Power (kW)']) - np.array(data_python['PV System']['Power (kW)']))
print(end_com-start_com, 'seconds')
print(end_dss-start_dss, 'seconds')