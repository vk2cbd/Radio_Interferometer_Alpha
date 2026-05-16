# Radio Interferometry FX Correlator

Initial Python 3 application for a two-input radio interferometer using an FX
correlator. The program provides a Tkinter GUI for observing parameters and
shows live plots for:

- Lag-domain interferogram from the inverse FFT of the cross spectrum.
- Cross-correlation spectrum amplitude and phase.

The current build includes a deterministic simulated two-antenna source so the
GUI and correlator can be tested without hardware. A B210 source adapter is
included as a starting point for UHD/SoapySDR integration.

## Ubuntu Setup

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

For development checks:

```bash
pip install -e ".[dev]"
pytest
```

For an Ettus B210 hardware path, install the UHD/SoapySDR stack for your Ubuntu
release and make sure the B210 is visible before selecting `B210 / SoapySDR` in
the GUI.

## Version Control

This directory is a Git repository. The first version is intended as a retained
baseline for future changes and should be pushed to `vk2cbd/test` on GitHub.

## Current Inputs

- Observing frequency in MHz.
- Intermediate frequency in MHz, used as the SDR tune frequency for hardware.
- Source RA and DEC in decimal degrees.
- Observer latitude and longitude in decimal degrees.
- Bandwidth in MHz.
- Number of FX frequency bins.
- Baseline east/north/up in meters for geometric phase simulation.

## Notes

The correlator currently expects two complex streams with matching sample rate.
The simulator generates a narrowband source plus noise and applies a geometric
delay based on the source and observer coordinates. The hardware adapter is
kept intentionally small so later work can choose the preferred B210 driver
stack and buffering strategy.
