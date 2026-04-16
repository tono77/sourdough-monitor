"""Tests for measurement fusion and growth calculation."""

from sourdough.services.measurement import compute_measurement


class TestFusion:

    def test_claude_only(self):
        """Without OpenCV, Claude is used as fallback."""
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

    def test_both_fused_when_close(self):
        """When Claude and OpenCV agree (diff <= 20), fuse with weights: opencv=5, claude=3."""
        result = compute_measurement(
            claude_result={"altura_y_pct": 50.0, "confianza": 3, "burbujas": "muchas", "textura": "muy_activa"},
            cv_altura=45.0,
            baseline_altura=30.0,
        )
        # Weight: opencv=5, claude=3 → (5*45 + 3*50) / 8 = 46.875 → 46.9
        assert result["altura_pct"] == 46.9
        assert "fusionado" in result["fuente"]

    def test_opencv_primary_when_disagree(self):
        """When Claude disagrees with OpenCV by >20%, discard Claude, keep OpenCV."""
        result = compute_measurement(
            claude_result={"altura_y_pct": 50.0, "confianza": 5, "burbujas": "pocas", "textura": "lisa"},
            cv_altura=80.0,
            baseline_altura=30.0,
        )
        # diff=30 > 20 → Claude discarded, only opencv
        assert result["altura_pct"] == 80.0
        assert result["fuente"] == "opencv"

    def test_opencv_favored_in_fusion(self):
        """OpenCV has higher weight (5) than Claude (3) in fusion."""
        result = compute_measurement(
            claude_result={"altura_y_pct": 50.0, "confianza": 3, "burbujas": "pocas", "textura": "lisa"},
            cv_altura=40.0,
            baseline_altura=30.0,
        )
        # Weight: opencv=5, claude=3 → (5*40 + 3*50) / 8 = 43.75 → 43.8
        assert result["altura_pct"] == 43.8

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
        """First measurement of session — no baseline yet, growth = 0%."""
        result = compute_measurement(
            claude_result={"altura_pct": 30.0, "confianza": 4, "burbujas": "ninguna", "textura": "lisa"},
            cv_altura=None,
            baseline_altura=None,
        )
        assert result["altura_pct"] == 30.0
        assert result["crecimiento_pct"] == 0.0  # first measurement = 0% growth

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

    def test_qualitative_passthrough_claude_only(self):
        """When Claude is sole source, its notes pass through."""
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


class TestSpatialConsistency:
    """Tests for the translucent dough override logic."""

    def test_claude_below_band_opencv_above_discards_claude(self):
        """When Claude says mass < band but OpenCV says mass > band, discard Claude."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 16.0, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "rugosa",
            },
            cv_altura=70.0,
            baseline_altura=30.0,
        )
        # Claude discarded (spatial check + disagreement), should use opencv
        assert result["fuente"] == "opencv"
        assert result["altura_pct"] == 70.0

    def test_claude_above_band_keeps_claude(self):
        """When Claude and OpenCV roughly agree, fuse normally."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 65.0, "banda_pct": 41.0, "confianza": 4,
                "burbujas": "muchas", "textura": "muy_activa",
            },
            cv_altura=70.0,
            baseline_altura=30.0,
        )
        assert "fusionado" in result["fuente"]

    def test_claude_below_band_no_opencv_keeps_claude(self):
        """Without OpenCV, can't validate — keep Claude as fallback."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 16.0, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "lisa",
            },
            cv_altura=None,
            baseline_altura=30.0,
        )
        assert result["fuente"] == "claude"
        assert result["altura_pct"] == 16.0

    def test_opencv_alone_after_claude_discarded(self):
        """When Claude is discarded, OpenCV is sole source (ML excluded from fusion)."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 16.0, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "rugosa",
            },
            cv_altura=70.0,
            baseline_altura=30.0,
            ml_altura=65.0,
        )
        assert result["fuente"] == "opencv"
        assert result["altura_pct"] == 70.0


class TestCycleAwareNotes:
    """Tests for new cycle note generation."""

    def test_new_cycle_notes(self):
        result = compute_measurement(
            claude_result={"altura_pct": 25.0, "confianza": 4, "burbujas": "ninguna", "textura": "lisa"},
            cv_altura=None,
            baseline_altura=None,
            is_new_cycle=True,
        )
        assert "Inicio de nuevo ciclo" in result["notas"]
        assert "bajando" not in result["notas"]

    def test_normal_decline_says_bajando(self):
        result = compute_measurement(
            claude_result={"altura_pct": 30.0, "confianza": 4, "burbujas": "pocas", "textura": "rugosa"},
            cv_altura=25.0,  # triggers non-claude source → generated notes
            baseline_altura=40.0,
        )
        # crecimiento = ((~28 - 40) / 40) * 100 ≈ -30%  → "bajando"
        assert "bajando" in result["notas"]
