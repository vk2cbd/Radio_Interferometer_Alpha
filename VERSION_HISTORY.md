# Version History

## 0.1.8-dev - Cross-Correlation Peak Marker and SNR

- Branched from the frozen `v0.1.7` baseline.
- Added a realtime peak marker on the cross-correlation spectrum.
- Added a realtime SNR estimate using the strongest cross-correlation bin and
  the median non-peak spectrum level.
- Updated default bandwidth to 30.72 MHz, FX bins to 2048, smoothing to 8196
  blocks, B210 gain to 70 dB, and B210 device args to `num_recv_frames=256`.

## 0.1.7 - Clear Cross-Correlation Smoothing Control

- Renamed the averaging GUI field to `X-corr smoothing blocks`.
- Show the active smoothing block count in the run status.

## 0.1.6 - GUI Averaging Control

- Added an averaging blocks GUI parameter for reducing correlation plot noise.
- Use the averaging value to set the FX correlator integration length.

## 0.1.5 - Updated 4800 MHz Default

- Set the default observing frequency to 4800 MHz.
- Kept the default B210 IF tune frequency at 1150 MHz.
- Kept the default east baseline at 6 m.

## 0.1.4 - Updated Observing Defaults

- Set the default observing frequency to 8500 MHz.
- Set the default B210 IF tune frequency to 1150 MHz.
- Set the default east baseline to 6 m.

## 0.1.3 - B210 Overflow Recovery

- Drain and integrate multiple B210 FFT blocks per GUI refresh so the SDR
  receive buffer is less likely to overflow.
- Treat individual B210 RX overflow reports as recoverable runtime events.

## 0.1.2 - B210 Timed Stream Start

- Start the two-channel B210 RX stream with a future hardware timestamp so UHD
  can align both channels.

## 0.1.1 - B210 Startup Diagnostics

- Switched B210 startup to manual gain instead of automatic gain mode.
- Added B210 gain, read timeout, and device argument GUI inputs.
- Added clearer B210 startup error messages that identify the failing setup step.
- Added B210 hardware troubleshooting notes.

## 0.1.0 - Initial FX Correlator Baseline

- Added Tkinter GUI for interferometry input parameters.
- Added two-input FX correlator with realtime integrated cross spectrum.
- Added lag-domain interferogram display.
- Added simulated two-antenna source with coordinate-based geometric delay.
- Added initial Ettus B210/SoapySDR source adapter.
- Added Ubuntu setup notes and dependency file.
