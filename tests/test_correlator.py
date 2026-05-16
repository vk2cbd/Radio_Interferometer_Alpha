import numpy as np

from radio_interferometer.correlator import CorrelatorConfig, FXCorrelator


def test_fx_correlator_returns_requested_bin_count() -> None:
    bins = 128
    correlator = FXCorrelator(CorrelatorConfig(sample_rate_hz=1_000_000.0, bins=bins))
    indices = np.arange(bins)
    signal = np.exp(2j * np.pi * 0.125 * indices).astype(np.complex64)

    result = correlator.process(signal, signal)

    assert result.cross_spectrum.shape == (bins,)
    assert result.interferogram.shape == (bins,)
    assert result.frequency_offsets_hz.shape == (bins,)
    assert result.lag_bins[0] == -bins // 2
    assert result.lag_bins[-1] == bins // 2 - 1


def test_fx_correlator_pads_short_blocks() -> None:
    correlator = FXCorrelator(CorrelatorConfig(sample_rate_hz=2_000_000.0, bins=64))
    short_block = np.ones(16, dtype=np.complex64)

    result = correlator.process(short_block, short_block)

    assert result.cross_spectrum.shape == (64,)
    assert np.all(np.isfinite(result.cross_spectrum))


def test_fx_correlator_rejects_invalid_config() -> None:
    try:
        FXCorrelator(CorrelatorConfig(sample_rate_hz=0.0, bins=64))
    except ValueError as exc:
        assert "Sample rate" in str(exc)
    else:
        raise AssertionError("Expected invalid sample rate to raise ValueError")
