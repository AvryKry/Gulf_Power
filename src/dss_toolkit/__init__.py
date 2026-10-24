"""dss_toolkit: reusable bricks for OpenDSS studies with DSS-Python.

Levels, from the smallest bricks to the largest:
    paths, der           - file search and OpenDSS command text (no OpenDSS needed)
    engine, network      - start/compile/solve the circuit, read its topology
    extract, timeseries  - results of a solved circuit, putting profiles/DER in and stepping time
    scenario             - what is simulated: demand, DER, time window (plain data, no OpenDSS)
    results              - results tables (pandas) and saved simulations
    reports, plots       - tables and figures built from those results
    hosting              - running scenarios and hosting capacity studies

Typical use:
    from dss_toolkit import engine as eng, extract, reports
"""
from . import paths, der, engine, network, extract, timeseries, scenario, results, reports, plots, hosting  # noqa: F401
