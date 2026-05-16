from datetime import datetime, timezone

import numpy as np

from radio_interferometer.sources import (
    ObservationConfig,
    SimulatedInterferometerSource,
    geometric_delay_seconds,
    horizontal_coordinates,
    parse_device_args,
)


def make_config() -> ObservationConfig:
    return ObservationConfig(
        observing_frequency_mhz=1420.405751,
        intermediate_frequency_mhz=150.0,
        ra_deg=83.6331,
        dec_deg=22.0145,
        observer_lat_deg=-33.8688,
        observer_lon_deg=151.2093,
        bandwidth_mhz=2.0,
        bins=256,
        baseline_east_m=10.0,
    )


def test_simulated_source_reads_two_complex_channels() -> None:
    source = SimulatedInterferometerSource(make_config())
    source.start()

    antenna_a, antenna_b = source.read(256)

    assert antenna_a.dtype == np.complex64
    assert antenna_b.dtype == np.complex64
    assert antenna_a.shape == (256,)
    assert antenna_b.shape == (256,)


def test_geometric_delay_is_finite() -> None:
    delay = geometric_delay_seconds(
        make_config(),
        datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert np.isfinite(delay)
    assert abs(delay) < 1e-6


def test_horizontal_coordinates_are_in_expected_ranges() -> None:
    alt_deg, az_deg = horizontal_coordinates(
        ra_deg=83.6331,
        dec_deg=22.0145,
        lat_deg=-33.8688,
        lon_deg=151.2093,
        when=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert -90.0 <= alt_deg <= 90.0
    assert 0.0 <= az_deg < 360.0


def test_parse_device_args() -> None:
    assert parse_device_args("serial=1234, type=b200") == {
        "serial": "1234",
        "type": "b200",
    }
