"""Config layer tests: load the shipped YAML, validate, and merge overrides."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chills_oddball.config import (
    DEFAULT_CONFIG_PATH,
    Config,
    load_config,
    merge_overrides,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_raw() -> dict:
    with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "session.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Round-trip the shipped config
# ---------------------------------------------------------------------------


def test_default_config_loads_and_validates():
    cfg = load_config()
    assert isinstance(cfg, Config)
    assert cfg.session.protocol_id == "P-CHILLS-ODDBALL-01"
    assert cfg.lsl.stream_name == "Chills_Task_Markers"
    assert cfg.lsl.source_id == "CHILLS_ODDBALL_Launcher"


def test_default_config_paradigm_invariants():
    cfg = load_config()
    # ERP CORE compliance — these are paradigm-fixed.
    assert cfg.oddball.deviant_probability == pytest.approx(0.20)
    assert cfg.oddball.isi_min_ms == 1100
    assert cfg.oddball.isi_max_ms == 1500
    assert cfg.oddball.min_standards_before_first_deviant == 3
    assert cfg.oddball.min_standards_between_deviants == 3
    assert cfg.oddball.max_consecutive_standards == 8

    # Sentiometer P013 / spec.
    assert cfg.active_oddball.total_trials == 250
    assert cfg.active_oddball.practice.n_trials == 10
    assert cfg.active_oddball.practice.n_deviants == 2
    assert cfg.active_oddball.practice.hit_threshold == pytest.approx(0.75)
    assert cfg.active_oddball.practice.fa_ceiling == pytest.approx(0.50)


def test_default_config_schedule_set_balanced():
    cfg = load_config()
    assert sorted(cfg.schedule.block_duration_set_s) == [30, 90, 150, 180]
    assert cfg.schedule.n_blocks_per_condition == len(cfg.schedule.block_duration_set_s)
    assert sorted(cfg.schedule.conditions) == sorted(
        ["chills_only", "rest_only", "chills_oddball_passive", "rest_oddball_passive"]
    )


def test_default_config_ratings_panels_have_expected_items():
    cfg = load_config()
    chills_ids = [item.id for item in cfg.ratings.chills.items]
    assert chills_ids == ["success", "waves", "intensity", "quality", "keep", "notes"]
    rest_ids = [item.id for item in cfg.ratings.rest.items]
    assert rest_ids == ["alertness"]


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_rejected(tmp_path: Path):
    raw = _load_raw()
    raw["mystery_section"] = {"x": 1}
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError):
        load_config(p)


def test_unknown_nested_key_rejected(tmp_path: Path):
    raw = _load_raw()
    raw["audio"]["mystery_field"] = 1
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError):
        load_config(p)


def test_isi_min_greater_than_max_rejected(tmp_path: Path):
    raw = _load_raw()
    raw["oddball"]["isi_min_ms"] = 2000
    raw["oddball"]["isi_max_ms"] = 1500
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError, match="isi_min_ms"):
        load_config(p)


def test_seed_strategy_fixed_requires_seed(tmp_path: Path):
    raw = _load_raw()
    raw["schedule"]["seed_strategy"] = "fixed"
    raw["schedule"]["fixed_seed"] = None
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError, match="fixed_seed"):
        load_config(p)


def test_duration_set_length_must_match_n_per_condition(tmp_path: Path):
    raw = _load_raw()
    raw["schedule"]["block_duration_set_s"] = [30, 90, 150]  # 3 instead of 4
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError, match="block_duration_set_s"):
        load_config(p)


def test_response_and_abort_keys_must_differ(tmp_path: Path):
    raw = _load_raw()
    raw["active_oddball"]["abort_key"] = "space"
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError, match="response_key"):
        load_config(p)


def test_practice_deviants_must_be_less_than_trials(tmp_path: Path):
    raw = _load_raw()
    raw["active_oddball"]["practice"]["n_deviants"] = 10
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError, match="n_deviants"):
        load_config(p)


def test_conditions_must_match_paradigm_set(tmp_path: Path):
    raw = _load_raw()
    raw["schedule"]["conditions"] = [
        "chills_only",
        "rest_only",
        "chills_oddball_passive",
        "something_made_up",
    ]
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError, match="conditions"):
        load_config(p)


def test_missing_instruction_key_rejected(tmp_path: Path):
    raw = _load_raw()
    del raw["instructions"]["calibration_chills"]
    p = _write_yaml(tmp_path, raw)
    with pytest.raises(ValidationError, match="instructions"):
        load_config(p)


# ---------------------------------------------------------------------------
# Override merging
# ---------------------------------------------------------------------------


def test_merge_overrides_changes_only_specified_field():
    cfg = load_config()
    original_isi_min = cfg.oddball.isi_min_ms
    new_cfg = merge_overrides(cfg, {"audio": {"tone_volume_dbfs": -25.0}})
    assert new_cfg.audio.tone_volume_dbfs == pytest.approx(-25.0)
    # Untouched fields stay put.
    assert new_cfg.oddball.isi_min_ms == original_isi_min
    # Original is not mutated.
    assert cfg.audio.tone_volume_dbfs != pytest.approx(-25.0)


def test_merge_overrides_re_validates():
    cfg = load_config()
    with pytest.raises(ValidationError, match="isi_min_ms"):
        merge_overrides(cfg, {"oddball": {"isi_min_ms": 2000}})


def test_merge_overrides_deeply_nested():
    cfg = load_config()
    new_cfg = merge_overrides(
        cfg, {"active_oddball": {"practice": {"hit_threshold": 0.85}}}
    )
    assert new_cfg.active_oddball.practice.hit_threshold == pytest.approx(0.85)
    # Sibling field untouched.
    assert (
        new_cfg.active_oddball.practice.fa_ceiling
        == cfg.active_oddball.practice.fa_ceiling
    )


def test_merge_overrides_independent_of_input_dict():
    cfg = load_config()
    overrides = {"audio": {"tone_volume_dbfs": -25.0}}
    snapshot = copy.deepcopy(overrides)
    merge_overrides(cfg, overrides)
    assert overrides == snapshot, "merge_overrides must not mutate its input"


def test_load_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does_not_exist.yaml")
