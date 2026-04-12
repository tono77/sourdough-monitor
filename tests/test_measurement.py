"""Tests for measurement fusion and growth calculation."""

from sourdough.services.measurement import compute_measurement


class TestFusion:

    def test_claude_only(self):
        result = compute_measurement(
            claude_result={"altura_y_pct": 45.0, "confianza": 4, "burbujas": "pocas", "textura": "rugosa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["altura_pct"] == 45.0
        assert result["fuente"] == "claude"

    def test_opencv_only(self):
        result = compute_measurement(
            claude_result={"burbujas": "pocas", "textura": "lisa"},
            cv_altura=42.0,
            baseline_altura=30.0,
        )
        assert result["altura_pct"] == 42.0
        assert result["fuente"] == "opencv"

    def test_both_fused(self):
        result = compute_measurement(
            claude_result={"altura_y_pct": 50.0, "confianza": 3, "burbujas": "muchas", "textura": "muy_activa"},
            cv_altura=40.0,
            baseline_altura=30.0,
        )
        # Weight: claude=3, opencv=3 → average = (3*50 + 3*40) / 6 = 45.0
        assert result["altura_pct"] == 45.0
        assert result["fuente"] == "fusionado"

    def test_high_confidence_favors_claude(self):
        result = compute_measurement(
            claude_result={"altura_y_pct": 50.0, "confianza": 5, "burbujas": "pocas", "textura": "lisa"},
            cv_altura=40.0,
            baseline_altura=30.0,
        )
        # Weight: claude=5, opencv=3 → (5*50 + 3*40) / 8 = 46.25 → 46.2
        assert result["altura_pct"] == 46.2

    def test_low_confidence_favors_opencv(self):
        result = compute_measurement(
            claude_result={"altura_y_pct": 50.0, "confianza": 1, "burbujas": "pocas", "textura": "lisa"},
            cv_altura=40.0,
            baseline_altura=30.0,
        )
        # Weight: claude=1, opencv=3 → (1*50 + 3*40) / 4 = 42.5
        assert result["altura_pct"] == 42.5

    def test_both_none(self):
        result = compute_measurement(
            claude_result={"burbujas": "ninguna", "textura": "lisa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["altura_pct"] is None
        assert result["crecimiento_pct"] is None
        assert result["fuente"] is None


class TestGrowthCalculation:

    def test_no_growth(self):
        result = compute_measurement(
            claude_result={"altura_pct": 30.0, "confianza": 4, "burbujas": "ninguna", "textura": "lisa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["crecimiento_pct"] == 0.0

    def test_doubled(self):
        """30% → 60% = 100% growth (doubled)."""
        result = compute_measurement(
            claude_result={"altura_pct": 60.0, "confianza": 4, "burbujas": "muchas", "textura": "muy_activa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["crecimiento_pct"] == 100.0

    def test_tripled(self):
        """20% → 60% = 200% growth (tripled)."""
        result = compute_measurement(
            claude_result={"altura_pct": 60.0, "confianza": 4, "burbujas": "muchas", "textura": "muy_activa"},
            cv_altura=None,
            baseline_altura=20.0,
        )
        assert result["crecimiento_pct"] == 200.0

    def test_slight_decline(self):
        """40% → 38% = -5% (slight decline after peak)."""
        result = compute_measurement(
            claude_result={"altura_pct": 38.0, "confianza": 3, "burbujas": "pocas", "textura": "rugosa"},
            cv_altura=None,
            baseline_altura=40.0,
        )
        assert result["crecimiento_pct"] == -5.0

    def test_no_baseline(self):
        """First measurement of session — no baseline yet."""
        result = compute_measurement(
            claude_result={"altura_pct": 30.0, "confianza": 4, "burbujas": "ninguna", "textura": "lisa"},
            cv_altura=None,
            baseline_altura=None,
        )
        assert result["altura_pct"] == 30.0
        assert result["crecimiento_pct"] is None  # can't compute without baseline

    def test_zero_baseline_safe(self):
        """Edge case: baseline at 0% (empty jar)."""
        result = compute_measurement(
            claude_result={"altura_pct": 30.0, "confianza": 4, "burbujas": "pocas", "textura": "lisa"},
            cv_altura=None,
            baseline_altura=0.0,
        )
        assert result["crecimiento_pct"] is None  # avoid division by zero


class TestBackwardsCompatibility:

    def test_nivel_pct_equals_crecimiento(self):
        result = compute_measurement(
            claude_result={"altura_pct": 60.0, "confianza": 4, "burbujas": "muchas", "textura": "muy_activa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["nivel_pct"] == result["crecimiento_pct"]

    def test_altura_y_pct_equals_altura(self):
        result = compute_measurement(
            claude_result={"altura_pct": 45.0, "confianza": 3, "burbujas": "pocas", "textura": "lisa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["altura_y_pct"] == result["altura_pct"]

    def test_qualitative_passthrough(self):
        result = compute_measurement(
            claude_result={"altura_pct": 50.0, "confianza": 5, "burbujas": "muchas", "textura": "muy_activa", "notas": "Masa activa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["burbujas"] == "muchas"
        assert result["textura"] == "muy_activa"
        assert result["notas"] == "Masa activa"
        assert result["confianza"] == 5

    def test_extracts_from_comparative_mode(self):
        """Claude comparative mode returns altura_actual_pct instead of altura_pct."""
        result = compute_measurement(
            claude_result={"altura_actual_pct": 55.0, "confianza": 4, "burbujas": "pocas", "textura": "rugosa"},
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["altura_pct"] == 55.0
        assert result["crecimiento_pct"] == 83.3
