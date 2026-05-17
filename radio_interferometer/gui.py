"""Tkinter GUI for the radio interferometry FX correlator."""

from __future__ import annotations

from math import ceil
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import __version__
from .correlator import CorrelatorConfig, FXCorrelator, estimate_peak_snr
from .sources import (
    B210ReadOverflow,
    B210SoapySource,
    ObservationConfig,
    SampleSource,
    SimulatedInterferometerSource,
)

GUI_REFRESH_MS = 80
MAX_BLOCKS_PER_UPDATE = 2048


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
        self._blocks_per_update = 1
        self._overflow_count = 0

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
            ("observing_frequency_mhz", "Observing freq (MHz)", "4800.0"),
            ("intermediate_frequency_mhz", "B210 tune IF (MHz)", "1150.0"),
            ("ra_deg", "Source RA (deg)", "83.6331"),
            ("dec_deg", "Source DEC (deg)", "22.0145"),
            ("observer_lat_deg", "Observer lat (deg)", "-33.8688"),
            ("observer_lon_deg", "Observer lon (deg)", "151.2093"),
            ("bandwidth_mhz", "Bandwidth (MHz)", "30.72"),
            ("bins", "FX bins", "2048"),
            ("averaging_blocks", "X-corr smoothing blocks", "8196"),
            ("baseline_east_m", "Baseline east (m)", "6.0"),
            ("baseline_north_m", "Baseline north (m)", "0.0"),
            ("baseline_up_m", "Baseline up (m)", "0.0"),
            ("b210_gain_db", "B210 gain (dB)", "70.0"),
            ("b210_read_timeout_ms", "B210 read timeout (ms)", "1000"),
            ("b210_device_args", "B210 device args", "num_recv_frames=256"),
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
        self.peak_vline = self.ax_spectrum.axvline(0.0, color="#111111", lw=1.0, ls="--", alpha=0.7)
        (self.peak_marker,) = self.ax_spectrum.plot(
            [], [], marker="o", ms=6, color="#111111", linestyle="None"
        )
        self.snr_text = self.ax_spectrum.text(
            0.02,
            0.94,
            "Peak: --\nSNR: --",
            transform=self.ax_spectrum.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.75},
        )

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
                CorrelatorConfig(
                    sample_rate_hz=config.sample_rate_hz,
                    bins=config.bins,
                    averaging_blocks=config.averaging_blocks,
                )
            )
            source.start()
        except Exception as exc:
            messagebox.showerror("Unable to start", str(exc))
            self.status.set(f"Start failed: {exc}")
            return

        self._latest_config = config
        self._source = source
        self._correlator = correlator
        self._blocks_per_update = self._calculate_blocks_per_update(config)
        self._overflow_count = 0
        self._running = True
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status.set(f"Running; X-corr smoothing {config.averaging_blocks} blocks")
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
            result = None
            processed = 0
            for _ in range(self._blocks_per_update):
                try:
                    antenna_a, antenna_b = self._source.read(self._correlator.config.bins)
                except B210ReadOverflow:
                    self._overflow_count += 1
                    continue
                result = self._correlator.process(antenna_a, antenna_b)
                processed += 1

            if result is not None:
                self._draw_result(result)

            if self._overflow_count:
                self.status.set(
                    f"Running; recovered {self._overflow_count} B210 overflow(s). "
                    f"Processed {processed}/{self._blocks_per_update} blocks."
                )
            else:
                self.status.set(f"Running; processed {processed} blocks/update")
        except Exception as exc:
            self.stop()
            messagebox.showerror("Runtime error", str(exc))
            return

        self.after(GUI_REFRESH_MS, self._update_loop)

    def _draw_result(self, result) -> None:
        config = self._latest_config
        if config is None:
            return

        sky_freq_mhz = config.observing_frequency_mhz + result.frequency_offsets_hz / 1_000_000.0
        interferogram_mag = np.abs(result.interferogram)
        spectrum_mag = np.abs(result.cross_spectrum)
        phase = np.angle(result.cross_spectrum)
        peak_snr = estimate_peak_snr(spectrum_mag)
        peak_freq_mhz = float(sky_freq_mhz[peak_snr.index])

        self.interferogram_line.set_data(result.lag_bins, interferogram_mag)
        self.ax_interferogram.set_xlim(float(result.lag_bins.min()), float(result.lag_bins.max()))
        self.ax_interferogram.set_ylim(0, max(float(interferogram_mag.max()) * 1.15, 1e-6))

        self.spectrum_line.set_data(sky_freq_mhz, spectrum_mag)
        self.phase_line.set_data(sky_freq_mhz, phase)
        self.peak_marker.set_data([peak_freq_mhz], [peak_snr.peak_value])
        self.peak_vline.set_xdata([peak_freq_mhz, peak_freq_mhz])
        self.snr_text.set_text(
            f"Peak: {peak_freq_mhz:.6f} MHz\n"
            f"SNR: {peak_snr.snr:.2f}\n"
            f"Noise: {peak_snr.noise_floor:.3g}"
        )
        self.ax_spectrum.set_xlim(float(sky_freq_mhz.min()), float(sky_freq_mhz.max()))
        self.ax_spectrum.set_ylim(0, max(float(spectrum_mag.max()) * 1.15, 1e-6))
        self.ax_phase.set_ylim(-np.pi, np.pi)

        self.canvas.draw_idle()

    def _read_config(self) -> ObservationConfig:
        values: dict[str, float | int | str] = {}
        for key, var in self.inputs.items():
            raw = var.get().strip()
            if key == "b210_device_args":
                values[key] = raw
            elif key in {"bins", "averaging_blocks", "b210_read_timeout_ms"}:
                values[key] = int(raw)
            else:
                values[key] = float(raw)

        if values["bandwidth_mhz"] <= 0:
            raise ValueError("Bandwidth must be positive.")
        if values["bins"] < 8:
            raise ValueError("FX bins must be at least 8.")
        if values["bins"] & (values["bins"] - 1):
            raise ValueError("FX bins should be a power of two for realtime FFT performance.")
        if values["averaging_blocks"] < 1:
            raise ValueError("Averaging blocks must be at least 1.")
        if not -90 <= values["observer_lat_deg"] <= 90:
            raise ValueError("Observer latitude must be between -90 and 90 degrees.")
        if not -90 <= values["dec_deg"] <= 90:
            raise ValueError("Source DEC must be between -90 and 90 degrees.")
        if values["b210_read_timeout_ms"] < 100:
            raise ValueError("B210 read timeout must be at least 100 ms.")
        if values["b210_gain_db"] < 0:
            raise ValueError("B210 gain must not be negative.")

        return ObservationConfig(**values)

    def _make_source(self, config: ObservationConfig) -> SampleSource:
        if self.source_mode.get() == "B210 / SoapySDR":
            return B210SoapySource(config)
        return SimulatedInterferometerSource(config)

    def _calculate_blocks_per_update(self, config: ObservationConfig) -> int:
        if self.source_mode.get() != "B210 / SoapySDR":
            return 1

        samples_per_update = config.sample_rate_hz * (GUI_REFRESH_MS / 1000.0)
        blocks = ceil(samples_per_update / config.bins)
        return max(1, min(MAX_BLOCKS_PER_UPDATE, blocks))


def main() -> None:
    app = InterferometryApp()
    app.mainloop()
