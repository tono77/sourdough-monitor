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

    def test_cv_saturated_high_discarded(self):
        """OpenCV at 100% (saturated to lid_end) with coherent Claude disagreement → discard CV.

        Reproduces the 2026-04-17 06:00 incident: flash reflections on empty glass above
        band were read as dough, CV saturated to 100%, Claude correctly read 41%.
        """
        result = compute_measurement(
            claude_result={
                "altura_pct": 41.0, "banda_pct": 41.0, "confianza": 2,
                "burbujas": "pocas", "textura": "lisa",
            },
            cv_altura=100.0,
            baseline_altura=30.5,
        )
        assert result["altura_pct"] == 41.0
        assert result["fuente"] == "claude"

    def test_cv_saturated_low_discarded(self):
        """OpenCV at ~0% (saturated empty) with coherent Claude disagreement → discard CV."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 55.0, "banda_pct": 41.0, "confianza": 4,
                "burbujas": "muchas", "textura": "muy_activa",
            },
            cv_altura=1.0,
            baseline_altura=30.0,
        )
        assert result["altura_pct"] == 55.0
        assert result["fuente"] == "claude"

    def test_cv_high_kept_when_claude_agrees(self):
        """OpenCV at 98% is legitimate if Claude also reads high (dough actually filled jar)."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 95.0, "banda_pct": 41.0, "confianza": 5,
                "burbujas": "muchas", "textura": "muy_activa",
            },
            cv_altura=98.0,
            baseline_altura=30.0,
        )
        # Claude and CV agree (diff=3 < 20) → fused, CV not discarded
        assert "opencv" in result["fuente"]
        assert result["altura_pct"] > 90.0

    def test_cv_huge_disagreement_discarded(self):
        """CV below saturation but massively disagrees with coherent Claude → discard CV.

        Reproduces 2026-04-17 06:21 incident: CV detected band on tablecloth and
        reported altura=89.6% while Claude saw 16.5% with banda=41.0%.
        Diff=73 >= HUGE_DISAGREEMENT_THRESHOLD (40) → discard CV.
        """
        result = compute_measurement(
            claude_result={
                "altura_pct": 16.5, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "lisa",
            },
            cv_altura=89.6,
            baseline_altura=28.0,
        )
        assert result["altura_pct"] == 16.5
        assert result["fuente"] == "claude"

    def test_cv_moderate_disagreement_spatial_applies(self):
        """CV below saturation and moderate disagreement (< 40%) → spatial check still applies."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 28.0, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "lisa",
            },
            cv_altura=43.4,
            baseline_altura=28.0,
        )
        # Diff=15.4 < 40, new rule doesn't fire. Spatial check fires
        # (Claude<banda, CV>banda) → Claude discarded, CV kept.
        assert result["altura_pct"] == 43.4
        assert result["fuente"] == "opencv"

    def test_cv_saturated_kept_when_claude_incoherent(self):
        """If Claude doesn't report banda_pct, circuit breaker can't verify → keep CV."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 41.0, "confianza": 2,  # no banda_pct
                "burbujas": "pocas", "textura": "lisa",
            },
            cv_altura=100.0,
            baseline_altura=30.5,
        )
        # Circuit breaker skipped (no banda_pct), Claude discarded by normal diff>20 rule
        assert result["altura_pct"] == 100.0
        assert result["fuente"] == "opencv"


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

    def test_claude_below_band_opencv_above_huge_diff_discards_opencv(self):
        """When Claude is coherent and diff >= 40%, trust Claude (post-2026-04-17 rule).

        This inverts the older spatial-consistency heuristic: massive disagreement
        between a coherent Claude and CV is more likely a CV band-detection failure
        than translucent-dough confusion by Claude.
        """
        result = compute_measurement(
            claude_result={
                "altura_pct": 16.0, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "rugosa",
            },
            cv_altura=70.0,
            baseline_altura=30.0,
        )
        # diff=54 >= HUGE_DISAGREEMENT_THRESHOLD (40) → discard CV
        assert result["fuente"] == "claude"
        assert result["altura_pct"] == 16.0

    def test_claude_below_band_opencv_moderate_diff_discards_claude(self):
        """When diff < 40%, the spatial consistency check still discards Claude."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 25.0, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "rugosa",
            },
            cv_altura=55.0,
            baseline_altura=30.0,
        )
        # diff=30 < 40 → huge-diff rule skipped; spatial check fires → Claude discarded
        assert result["fuente"] == "opencv"
        assert result["altura_pct"] == 55.0

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
        """When Claude is discarded by spatial check (moderate diff), CV is sole source."""
        result = compute_measurement(
            claude_result={
                "altura_pct": 25.0, "banda_pct": 41.0, "confianza": 3,
                "burbujas": "pocas", "textura": "rugosa",
            },
            cv_altura=55.0,
            baseline_altura=30.0,
            ml_altura=50.0,
        )
        assert result["fuente"] == "opencv"
        assert result["altura_pct"] == 55.0


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
