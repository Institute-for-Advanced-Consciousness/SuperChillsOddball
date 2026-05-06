"""Smoke tests for the Tk app controller (Step 8 stage shells)."""

from __future__ import annotations

import pytest


@pytest.fixture
def app(shared_app):
    return shared_app


def test_app_constructs_and_registers_all_stages(app):
    names = sorted(app.stages.keys())
    assert names == sorted(
        [
            "intake",
            "volume_check",
            "instructions",
            "calibration_chills",
            "block_runner",
            "ratings_chills",
            "ratings_rest",
            "active_oddball",
            "completion",
        ]
    )


def test_show_stage_unknown_raises(app):
    with pytest.raises(KeyError, match="unknown stage"):
        app.show_stage("nope")


def test_main_self_check_returns_zero(capsys):
    """End-to-end self-check on this dev box: every line should be OK."""
    from chills_oddball.app import main

    rc = main(["--self-check"])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    # Every line in the self-check should report OK (or be info we don't grade on).
    assert "FAIL" not in output, f"self-check reported FAIL:\n{output}"
    assert "config loaded" in output
    assert "audio assets present" in output
    assert "LSL outlet opens" in output
    assert rc == 0


def test_main_self_check_fails_when_config_missing(tmp_path):
    """Pointing --config at a non-existent file must exit non-zero."""
    from chills_oddball.app import main

    rc = main(["--self-check", "--config", str(tmp_path / "nope.yaml")])
    assert rc == 1
