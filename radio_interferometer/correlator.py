"""FX correlator primitives."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CorrelatorConfig:
    """Runtime configuration for the FX correlator."""

    sample_rate_hz: float
    bins: int
    integration_alpha: float = 0.18


@dataclass
class CorrelatorResult:
    """A single integrated correlator update."""

    frequency_offsets_hz: np.ndarray
    cross_spectrum: np.ndarray
    interferogram: np.ndarray
    lag_bins: np.ndarray


class FXCorrelator:
    """Two-input FX correlator with exponential integration."""

    def __init__(self, config: CorrelatorConfig) -> None:
        if config.bins < 8:
            raise ValueError("FX bin count must be at least 8.")
        if config.sample_rate_hz <= 0:
            raise ValueError("Sample rate must be positive.")
        if not 0 < config.integration_alpha <= 1:
            raise ValueError("Integration alpha must be in the range (0, 1].")

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
