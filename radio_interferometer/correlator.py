"""FX correlator primitives."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CorrelatorConfig:
    """Runtime configuration for the FX correlator."""

    sample_rate_hz: float
    bins: int
    averaging_blocks: int = 32

    @property
    def integration_alpha(self) -> float:
        return 1.0 / self.averaging_blocks


@dataclass
class CorrelatorResult:
    """A single integrated correlator update."""

    frequency_offsets_hz: np.ndarray
    cross_spectrum: np.ndarray
    interferogram: np.ndarray
    lag_bins: np.ndarray


@dataclass(frozen=True)
class PeakSnr:
    """Peak and signal-to-noise estimate for a magnitude spectrum."""

    index: int
    peak_value: float
    noise_floor: float
    snr: float


class FXCorrelator:
    """Two-input FX correlator with exponential integration."""

    def __init__(self, config: CorrelatorConfig) -> None:
        if config.bins < 8:
            raise ValueError("FX bin count must be at least 8.")
        if config.sample_rate_hz <= 0:
            raise ValueError("Sample rate must be positive.")
        if config.averaging_blocks < 1:
            raise ValueError("Averaging blocks must be at least 1.")

        self.config = config
        self._window = np.hanning(config.bins).astype(np.float64)
        self._window_power = np.sum(self._window**2)
        self._integrated_cross: np.ndarray | None = None
        self.frequency_offsets_hz = np.fft.fftshift(
            np.fft.fftfreq(config.bins, d=1.0 / config.sample_rate_hz)
        )
        self.lag_bins = np.arange(-config.bins // 2, config.bins // 2)

    def reset(self) -> None:
        self._integrated_cross = None

    def process(self, antenna_a: np.ndarray, antenna_b: np.ndarray) -> CorrelatorResult:
        """Correlate two complex sample blocks and return integrated products."""

        count = self.config.bins
        a = self._prepare_block(antenna_a, count)
        b = self._prepare_block(antenna_b, count)

        spectrum_a = np.fft.fft(a * self._window)
        spectrum_b = np.fft.fft(b * self._window)
        cross = spectrum_a * np.conj(spectrum_b) / self._window_power

        if self._integrated_cross is None:
            self._integrated_cross = cross
        else:
            alpha = self.config.integration_alpha
            self._integrated_cross = (1.0 - alpha) * self._integrated_cross + alpha * cross

        shifted_cross = np.fft.fftshift(self._integrated_cross)
        interferogram = np.fft.fftshift(np.fft.ifft(self._integrated_cross))

        return CorrelatorResult(
            frequency_offsets_hz=self.frequency_offsets_hz.copy(),
            cross_spectrum=shifted_cross.copy(),
            interferogram=interferogram,
            lag_bins=self.lag_bins.copy(),
        )

    @staticmethod
    def _prepare_block(samples: np.ndarray, count: int) -> np.ndarray:
        data = np.asarray(samples, dtype=np.complex64)
        if data.size < count:
            padded = np.zeros(count, dtype=np.complex64)
            padded[: data.size] = data
            return padded
        return data[:count]


def estimate_peak_snr(magnitudes: np.ndarray, exclusion_bins: int = 3) -> PeakSnr:
    """Find the strongest bin and estimate SNR against the surrounding noise floor."""

    values = np.asarray(magnitudes, dtype=np.float64)
    if values.size == 0:
        raise ValueError("Cannot estimate SNR from an empty spectrum.")
    if exclusion_bins < 0:
        raise ValueError("Exclusion bins must not be negative.")

    peak_index = int(np.nanargmax(values))
    peak_value = float(values[peak_index])

    mask = np.ones(values.size, dtype=bool)
    start = max(0, peak_index - exclusion_bins)
    stop = min(values.size, peak_index + exclusion_bins + 1)
    mask[start:stop] = False
    noise_values = values[mask]
    if noise_values.size == 0:
        noise_values = values

    noise_floor = float(np.nanmedian(noise_values))
    if not np.isfinite(noise_floor) or noise_floor <= 0.0:
        noise_floor = float(np.nanmean(noise_values))
    if not np.isfinite(noise_floor) or noise_floor <= 0.0:
        noise_floor = 1e-12

    return PeakSnr(
        index=peak_index,
        peak_value=peak_value,
        noise_floor=noise_floor,
        snr=peak_value / noise_floor,
    )
