"""The prompts must describe the ACTUAL port target from config, not a
hardcoded one. Hardware-day finding: with "MI300X, gfx942" baked into the
prompt text, the agent set HIP_ARCHITECTURES gfx942 on a gfx1100 Radeon pod —
a binary the GPU could not run, discovered only when the tests failed."""

from __future__ import annotations

from bridge.agent import load_prompts
from tests.conftest import REPO_ROOT

PROMPTS = str(REPO_ROOT / "prompts")


def test_prompts_render_mi300x_target():
    p = load_prompts(PROMPTS, offload_arch="gfx942")
    for text in p.values():
        assert "{{target_desc}}" not in text and "{{offload_arch}}" not in text
        assert "gfx942" in text
    assert "MI300X" in p["diagnose"]
    assert "warp size 64" in p["diagnose"]
    assert "--offload-arch=gfx942" in p["diagnose"]


def test_prompts_render_rdna3_target():
    p = load_prompts(PROMPTS, offload_arch="gfx1100")
    for text in p.values():
        assert "{{target_desc}}" not in text and "{{offload_arch}}" not in text
        assert "gfx1100" in text
        # the pod bug: the OTHER arch must not be named as the target
        assert "gfx942" not in text
    assert "MI300X" not in p["diagnose"]
    assert "warp size 32" in p["diagnose"]
    assert "--offload-arch=gfx1100" in p["diagnose"]


def test_default_stays_mi300x_for_existing_callers():
    assert "MI300X" in load_prompts(PROMPTS)["diagnose"]
