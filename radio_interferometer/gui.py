"""Tkinter GUI for the radio interferometry FX correlator."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import __version__
from .correlator import CorrelatorConfig, FXCorrelator
from .sources import B210SoapySource, ObservationConfig, SampleSource, SimulatedInterferometerSource


class InterferometryApp(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"Radio Interferometry FX Correlator v{__version__}")
        self.geometry("1180x780")
        self.minsize(980, 680)

        self._source: SampleSource | None = None
        self._correlator: FXCorrelator | None = None
        self._running = False
        self._latest_config: ObservationConfig | None = None

        self._build_controls()
        self._build_plots()

    def _build_controls(self) -> None:
        panel = ttk.Frame(self, padding=10)
        panel.pack(side=tk.LEFT, fill=tk.Y)

        self.source_mode = tk.StringVar(value="Simulator")
        ttk.Label(panel, text="Source").grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Combobox(
            panel,
            textvariable=self.source_mode,
            values=("Simulator", "B210 / SoapySDR"),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="ew", pady=(0, 8))

        self.inputs: dict[str, tk.StringVar] = {}
        fields = [
            ("observing_frequency_mhz", "Observing freq (MHz)", "1420.405751"),
            ("intermediate_frequency_mhz", "B210 tune IF (MHz)", "150.0"),
            ("ra_deg", "Source RA (deg)", "83.6331"),
            ("dec_deg", "Source DEC (deg)", "22.0145"),
            ("observer_lat_deg", "Observer lat (deg)", "-33.8688"),
            ("observer_lon_deg", "Observer lon (deg)", "151.2093"),
            ("bandwidth_mhz", "Bandwidth (MHz)", "2.0"),
            ("bins", "FX bins", "1024"),
            ("baseline_east_m", "Baseline east (m)", "10.0"),
            ("baseline_north_m", "Baseline north (m)", "0.0"),
            ("baseline_up_m", "Baseline up (m)", "0.0"),
        ]
        for row, (key, label, default) in enumerate(fields, start=1):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=3)
            value = tk.StringVar(value=default)
            self.inputs[key] = value
            ttk.Entry(panel, textvariable=value, width=18).grid(row=row, column=1, sticky="ew", pady=3)

        button_row = len(fields) + 1
        self.start_button = ttk.Button(panel, text="Start", command=self.start)
        self.start_button.grid(row=button_row, column=0, sticky="ew", pady=(14, 3))
        self.stop_button = ttk.Button(panel, text="Stop", command=self.stop, state=tk.DISABLED)
        self.stop_button.grid(row=button_row, column=1, sticky="ew", pady=(14, 3))

        self.reset_button = ttk.Button(panel, text="Reset Avg", command=self.reset_average)
        self.reset_button.grid(row=button_row + 1, column=0, columnspan=2, sticky="ew", pady=3)

        ttk.Separator(panel).grid(row=button_row + 2, column=0, columnspan=2, sticky="ew", pady=12)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(panel, textvariable=self.status, wraplength=240).grid(
            row=button_row + 3, column=0, columnspan=2, sticky="w"
        )
        panel.columnconfigure(1, weight=1)

    def _build_plots(self) -> None:
        plot_frame = ttk.Frame(self, padding=(0, 10, 10, 10))
        plot_frame.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH)

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.ax_interferogram = self.figure.add_subplot(211)
        self.ax_spectrum = self.figure.add_subplot(212)
        self.ax_phase = self.ax_spectrum.twinx()

        self.ax_interferogram.set_title("Realtime Interferogram")
        self.ax_interferogram.set_xlabel("Lag bin")
        self.ax_interferogram.set_ylabel("|Correlation|")
        self.ax_spectrum.set_title("Cross-Correlation Spectrum")
        self.ax_spectrum.set_xlabel("Sky frequency (MHz)")
        self.ax_spectrum.set_ylabel("|Cross power|")
        self.ax_phase.set_ylabel("Phase (rad)")

        (self.interferogram_line,) = self.ax_interferogram.plot([], [], color="#1f77b4", lw=1.4)
        (self.spectrum_line,) = self.ax_spectrum.plot([], [], color="#2ca02c", lw=1.3)
        (self.phase_line,) = self.ax_phase.plot([], [], color="#d62728", lw=1.0, alpha=0.78)

        self.figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas, plot_frame)

    def start(self) -> None:
        try:
            config = self._read_config()
            source = self._make_source(config)
            correlator = FXCorrelator(
                CorrelatorConfig(sample_rate_hz=config.sample_rate_hz, bins=config.bins)
            )
            source.start()
        except Exception as exc:
            messagebox.showerror("Unable to start", str(exc))
            self.status.set(f"Start failed: {exc}")
            return

        self._latest_config = config
        self._source = source
        self._correlator = correlator
        self._running = True
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status.set("Running")
        self.after(20, self._update_loop)

    def stop(self) -> None:
        self._running = False
        if self._source is not None:
            try:
                self._source.stop()
            except Exception as exc:
                self.status.set(f"Stopped with source warning: {exc}")
            else:
                self.status.set("Stopped")
        self._source = None
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

    def reset_average(self) -> None:
        if self._correlator is not None:
            self._correlator.reset()
            self.status.set("Averaging reset")

    def _update_loop(self) -> None:
        if not self._running or self._source is None or self._correlator is None:
            return

        try:
            antenna_a, antenna_b = self._source.read(self._correlator.config.bins)
            result = self._correlator.process(antenna_a, antenna_b)
            self._draw_result(result)
            self.status.set("Running")
        except Exception as exc:
            self.stop()
            messagebox.showerror("Runtime error", str(exc))
            return

        self.after(60, self._update_loop)

    def _draw_result(self, result) -> None:
        config = self._latest_config
        if config is None:
            return

        sky_freq_mhz = config.observing_frequency_mhz + result.frequency_offsets_hz / 1_000_000.0
        interferogram_mag = np.abs(result.interferogram)
        spectrum_mag = np.abs(result.cross_spectrum)
        phase = np.angle(result.cross_spectrum)

        self.interferogram_line.set_data(result.lag_bins, interferogram_mag)
        self.ax_interferogram.set_xlim(float(result.lag_bins.min()), float(result.lag_bins.max()))
        self.ax_interferogram.set_ylim(0, max(float(interferogram_mag.max()) * 1.15, 1e-6))

        self.spectrum_line.set_data(sky_freq_mhz, spectrum_mag)
        self.phase_line.set_data(sky_freq_mhz, phase)
        self.ax_spectrum.set_xlim(float(sky_freq_mhz.min()), float(sky_freq_mhz.max()))
        self.ax_spectrum.set_ylim(0, max(float(spectrum_mag.max()) * 1.15, 1e-6))
        self.ax_phase.set_ylim(-np.pi, np.pi)

        self.canvas.draw_idle()

    def _read_config(self) -> ObservationConfig:
        values: dict[str, float | int] = {}
        for key, var in self.inputs.items():
            raw = var.get().strip()
            if key == "bins":
                values[key] = int(raw)
            else:
                values[key] = float(raw)

        if values["bandwidth_mhz"] <= 0:
            raise ValueError("Bandwidth must be positive.")
        if values["bins"] < 8:
            raise ValueError("FX bins must be at least 8.")
        if values["bins"] & (values["bins"] - 1):
            raise ValueError("FX bins should be a power of two for realtime FFT performance.")
        if not -90 <= values["observer_lat_deg"] <= 90:
            raise ValueError("Observer latitude must be between -90 and 90 degrees.")
        if not -90 <= values["dec_deg"] <= 90:
            raise ValueError("Source DEC must be between -90 and 90 degrees.")

        return ObservationConfig(**values)

    def _make_source(self, config: ObservationConfig) -> SampleSource:
        if self.source_mode.get() == "B210 / SoapySDR":
            return B210SoapySource(config)
        return SimulatedInterferometerSource(config)


def main() -> None:
    app = InterferometryApp()
    app.mainloop()
