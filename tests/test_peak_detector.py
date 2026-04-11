"""Tests for peak detection algorithm — pure logic, no DB."""

from sourdough.models import Measurement
from sourdough.services.peak_detector import detect_peak


def _m(nivel: float) -> Measurement:
    """Shorthand to create a measurement with just nivel_pct."""
    return Measurement(nivel_pct=nivel)


class TestPeakDetector:

    def test_no_peak_with_insufficient_data(self):
        assert not detect_peak(
            recent=[_m(10), _m(5)],
            baseline_nivel=0, max_nivel=10,
            peak_already_exists=False,
        )

    def test_no_peak_if_already_exists(self):
        assert not detect_peak(
            recent=[_m(5), _m(10), _m(15)],
            baseline_nivel=0, max_nivel=15,
            peak_already_exists=True,
        )

    def test_detects_two_consecutive_declines(self):
        # prev2=50, prev=45, curr=40 → decline of 10 from prev2 to curr
        assert detect_peak(
            recent=[_m(40), _m(45), _m(50)],
            baseline_nivel=0, max_nivel=50,
            peak_already_exists=False,
        )

    def test_no_peak_if_insufficient_growth(self):
        # Growth from baseline is only 5 (< MIN_GROWTH=10)
        assert not detect_peak(
            recent=[_m(2), _m(3), _m(5)],
            baseline_nivel=0, max_nivel=5,
            peak_already_exists=False,
        )

    def test_no_peak_with_noise(self):
        # Decline of only 2 total (< MIN_DECLINE=3)
        assert not detect_peak(
            recent=[_m(48), _m(49), _m(50)],
            baseline_nivel=0, max_nivel=50,
            peak_already_exists=False,
        )

    def test_no_peak_when_still_rising(self):
        assert not detect_peak(
            recent=[_m(50), _m(45), _m(40)],
            baseline_nivel=0, max_nivel=50,
            peak_already_exists=False,
        )

    def test_handles_none_baseline(self):
        assert not detect_peak(
            recent=[_m(40), _m(45), _m(50)],
            baseline_nivel=None, max_nivel=50,
            peak_already_exists=False,
        )

    def test_handles_none_nivel_in_measurements(self):
        assert not detect_peak(
            recent=[Measurement(nivel_pct=None), _m(45), _m(50)],
            baseline_nivel=0, max_nivel=50,
            peak_already_exists=False,
        )

    def test_real_fermentation_scenario(self):
        """Simulate: 0% → 20% → 50% → 80% → 75% → 70% (peak at 80%)"""
        # Recent is newest-first
        assert detect_peak(
            recent=[_m(70), _m(75), _m(80)],
            baseline_nivel=0, max_nivel=80,
            peak_already_exists=False,
        )
