"""Sample sources for simulated and hardware-backed interferometry streams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import asin, atan2, cos, degrees, radians, sin
from time import sleep

import numpy as np

SPEED_OF_LIGHT_M_S = 299_792_458.0


@dataclass(frozen=True)
class ObservationConfig:
    observing_frequency_mhz: float
    intermediate_frequency_mhz: float
    ra_deg: float
    dec_deg: float
    observer_lat_deg: float
    observer_lon_deg: float
    bandwidth_mhz: float
    bins: int
    baseline_east_m: float = 10.0
    baseline_north_m: float = 0.0
    baseline_up_m: float = 0.0
    b210_gain_db: float = 35.0
    b210_read_timeout_ms: int = 1000
    b210_device_args: str = ""

    @property
    def sample_rate_hz(self) -> float:
        return self.bandwidth_mhz * 1_000_000.0

    @property
    def observing_frequency_hz(self) -> float:
        return self.observing_frequency_mhz * 1_000_000.0

    @property
    def intermediate_frequency_hz(self) -> float:
        return self.intermediate_frequency_mhz * 1_000_000.0


class SampleSource:
    """Common interface for two-channel complex sample sources."""

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def read(self, sample_count: int) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError


class SimulatedInterferometerSource(SampleSource):
    """Deterministic two-antenna source with geometric delay and noise."""

    def __init__(self, config: ObservationConfig, seed: int = 20260516) -> None:
        self.config = config
        self._rng = np.random.default_rng(seed)
        self._sample_index = 0
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def read(self, sample_count: int) -> tuple[np.ndarray, np.ndarray]:
        if not self._running:
            raise RuntimeError("Sample source is not running.")

        rate = self.config.sample_rate_hz
        indices = np.arange(sample_count, dtype=np.float64) + self._sample_index
        self._sample_index += sample_count

        # Place a synthetic source at 11 percent of the visible passband.
        tone_hz = 0.11 * rate
        source = np.exp(2j * np.pi * tone_hz * indices / rate)

        delay_s = geometric_delay_seconds(self.config)
        phase = 2.0 * np.pi * self.config.observing_frequency_hz * delay_s
        antenna_a = source
        antenna_b = source * np.exp(-1j * phase)

        noise_scale = 0.45
        noise_a = noise_scale * (
            self._rng.normal(size=sample_count) + 1j * self._rng.normal(size=sample_count)
        )
        noise_b = noise_scale * (
            self._rng.normal(size=sample_count) + 1j * self._rng.normal(size=sample_count)
        )
        return (antenna_a + noise_a).astype(np.complex64), (antenna_b + noise_b).astype(np.complex64)


class B210SoapySource(SampleSource):
    """Two-channel Ettus B210 source using SoapySDR when available."""

    def __init__(self, config: ObservationConfig) -> None:
        self.config = config
        self._sdr = None
        self._rx_stream = None

    def start(self) -> None:
        try:
            import SoapySDR  # type: ignore
            from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "SoapySDR is not installed. Install UHD/SoapySDR or use the simulator."
            ) from exc

        sdr = None
        rx_stream = None
        try:
            device_args = {"driver": "uhd", **parse_device_args(self.config.b210_device_args)}
            sdr = run_b210_step("open B210 device", lambda: SoapySDR.Device(device_args))
            sleep(0.25)

            for channel in (0, 1):
                run_b210_step(
                    f"set channel {channel} sample rate",
                    lambda channel=channel: sdr.setSampleRate(
                        SOAPY_SDR_RX, channel, self.config.sample_rate_hz
                    ),
                )
                run_b210_step(
                    f"set channel {channel} RF bandwidth",
                    lambda channel=channel: sdr.setBandwidth(
                        SOAPY_SDR_RX, channel, self.config.sample_rate_hz
                    ),
                )
                run_b210_step(
                    f"tune channel {channel}",
                    lambda channel=channel: sdr.setFrequency(
                        SOAPY_SDR_RX, channel, self.config.intermediate_frequency_hz
                    ),
                )
                run_b210_step(
                    f"disable channel {channel} AGC",
                    lambda channel=channel: sdr.setGainMode(SOAPY_SDR_RX, channel, False),
                )
                run_b210_step(
                    f"set channel {channel} gain",
                    lambda channel=channel: sdr.setGain(
                        SOAPY_SDR_RX, channel, self.config.b210_gain_db
                    ),
                )

            rx_stream = run_b210_step(
                "create two-channel RX stream",
                lambda: sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0, 1]),
            )
            run_b210_step("activate RX stream", lambda: sdr.activateStream(rx_stream))
        except Exception:
            if sdr is not None and rx_stream is not None:
                try:
                    sdr.closeStream(rx_stream)
                except Exception:
                    pass
            raise

        self._sdr = sdr
        self._rx_stream = rx_stream

    def stop(self) -> None:
        if self._sdr is not None and self._rx_stream is not None:
            self._sdr.deactivateStream(self._rx_stream)
            self._sdr.closeStream(self._rx_stream)
        self._sdr = None
        self._rx_stream = None

    def read(self, sample_count: int) -> tuple[np.ndarray, np.ndarray]:
        if self._sdr is None or self._rx_stream is None:
            raise RuntimeError("B210 source is not running.")

        buffs = [
            np.empty(sample_count, dtype=np.complex64),
            np.empty(sample_count, dtype=np.complex64),
        ]
        timeout_us = max(self.config.b210_read_timeout_ms, 100) * 1000
        result = self._sdr.readStream(self._rx_stream, buffs, sample_count, timeoutUs=timeout_us)
        if result.ret <= 0:
            raise RuntimeError(f"B210 read failed with code {result.ret}.")
        return buffs[0][: result.ret], buffs[1][: result.ret]


def parse_device_args(raw_args: str) -> dict[str, str]:
    """Parse comma-separated SoapySDR device args such as serial=123,type=b200."""

    parsed: dict[str, str] = {}
    for item in raw_args.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"B210 device arg must be key=value: {item}")
        key, value = item.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def run_b210_step(step_name: str, action):
    """Run a Soapy/UHD call and preserve the failing setup step in the GUI error."""

    try:
        return action()
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        raise RuntimeError(f"B210 failed while trying to {step_name}: {detail}") from exc


def geometric_delay_seconds(config: ObservationConfig, when: datetime | None = None) -> float:
    """Return geometric delay for an east/north/up baseline."""

    if when is None:
        when = datetime.now(timezone.utc)

    alt_deg, az_deg = horizontal_coordinates(
        config.ra_deg,
        config.dec_deg,
        config.observer_lat_deg,
        config.observer_lon_deg,
        when,
    )
    alt = radians(alt_deg)
    az = radians(az_deg)

    east = cos(alt) * sin(az)
    north = cos(alt) * cos(az)
    up = sin(alt)
    projected_m = (
        config.baseline_east_m * east
        + config.baseline_north_m * north
        + config.baseline_up_m * up
    )
    return projected_m / SPEED_OF_LIGHT_M_S


def horizontal_coordinates(
    ra_deg: float,
    dec_deg: float,
    lat_deg: float,
    lon_deg: float,
    when: datetime,
) -> tuple[float, float]:
    """Convert RA/DEC to approximate altitude and azimuth in decimal degrees."""

    lst_deg = local_sidereal_time_degrees(when, lon_deg)
    hour_angle = radians((lst_deg - ra_deg + 540.0) % 360.0 - 180.0)
    dec = radians(dec_deg)
    lat = radians(lat_deg)

    sin_alt = sin(dec) * sin(lat) + cos(dec) * cos(lat) * cos(hour_angle)
    alt = asin(np.clip(sin_alt, -1.0, 1.0))
    az = atan2(
        -sin(hour_angle) * cos(dec),
        sin(dec) * cos(lat) - cos(dec) * sin(lat) * cos(hour_angle),
    )
    return degrees(alt), (degrees(az) + 360.0) % 360.0


def local_sidereal_time_degrees(when: datetime, lon_deg: float) -> float:
    """Approximate local apparent sidereal time for GUI/simulation use."""

    when = when.astimezone(timezone.utc)
    year = when.year
    month = when.month
    day = when.day
    if month <= 2:
        year -= 1
        month += 12

    a = year // 100
    b = 2 - a + a // 4
    day_fraction = (
        when.hour + when.minute / 60.0 + (when.second + when.microsecond / 1_000_000.0) / 3600.0
    ) / 24.0
    jd = (
        int(365.25 * (year + 4716))
        + int(30.6001 * (month + 1))
        + day
        + day_fraction
        + b
        - 1524.5
    )
    d = jd - 2451545.0
    gmst = 280.46061837 + 360.98564736629 * d
    return (gmst + lon_deg) % 360.0
