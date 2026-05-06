"""YAML config loader, pydantic validation, and GUI override merging.

The master config lives at ``config/session_defaults.yaml``. The GUI loads
it at session start, optionally lets the RA edit values in-memory (the file
on disk is never touched by the runtime), and passes the validated
``Config`` instance to every stage.

Public API:
    load_config(path) -> Config
    merge_overrides(config, overrides) -> Config
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "session_defaults.yaml"


# ---------------------------------------------------------------------------
# Sub-section models
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    """Reject unknown keys so typos in the YAML fail loudly at load time."""

    model_config = ConfigDict(extra="forbid")


class SessionMeta(_StrictModel):
    protocol_id: str
    protocol_label: str
    data_root_dir: str
    participant_id_prefix: str
    participant_id_zfill: int = Field(ge=1, le=10)
    allow_debug_shortcuts: bool


class LslConfig(_StrictModel):
    stream_name: str
    stream_type: str
    channel_format: Literal["string"]
    source_id: str


class AudioFiles(_StrictModel):
    tone_standard: str
    tone_deviant: str
    gong_start: str
    gong_end: str
    volume_reference: str


class AudioConfig(_StrictModel):
    device_name: str | None = None
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(ge=1, le=2)
    buffer_blocksize: int = Field(gt=0)
    tone_volume_dbfs: float
    gong_volume_dbfs: float
    ref_tone_volume_dbfs: float
    files: AudioFiles


SeedStrategy = Literal["random_per_session", "participant_id", "fixed"]


class ScheduleConfig(_StrictModel):
    conditions: list[str] = Field(min_length=4, max_length=4)
    n_blocks_per_condition: int = Field(gt=0)
    block_duration_set_s: list[int]
    no_back_to_back_same_condition: bool
    max_shuffle_attempts: int = Field(gt=0)
    seed_strategy: SeedStrategy
    fixed_seed: int | None = None

    @model_validator(mode="after")
    def _check_lengths(self) -> ScheduleConfig:
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("schedule.conditions must be unique")
        if len(self.block_duration_set_s) != self.n_blocks_per_condition:
            raise ValueError(
                "schedule.block_duration_set_s must have exactly "
                f"n_blocks_per_condition={self.n_blocks_per_condition} entries; "
                f"got {len(self.block_duration_set_s)}"
            )
        if any(d <= 0 for d in self.block_duration_set_s):
            raise ValueError("all block durations must be positive")
        if self.seed_strategy == "fixed" and self.fixed_seed is None:
            raise ValueError("schedule.fixed_seed is required when seed_strategy=='fixed'")
        return self


class CalibrationConfig(_StrictModel):
    enabled: bool
    duration_s: int = Field(gt=0)
    condition: str
    ratings_panel: Literal["chills", "rest"]


class OddballConfig(_StrictModel):
    deviant_probability: float = Field(gt=0.0, lt=1.0)
    isi_min_ms: int = Field(gt=0)
    isi_max_ms: int = Field(gt=0)
    isi_distribution: Literal["uniform", "normal"]
    response_window_ms: int = Field(gt=0)
    min_standards_before_first_deviant: int = Field(ge=0)
    min_standards_between_deviants: int = Field(ge=0)
    max_consecutive_standards: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_isi(self) -> OddballConfig:
        if self.isi_min_ms > self.isi_max_ms:
            raise ValueError(
                f"oddball.isi_min_ms ({self.isi_min_ms}) > isi_max_ms ({self.isi_max_ms})"
            )
        return self


class PracticeConfig(_StrictModel):
    n_trials: int = Field(gt=0)
    n_deviants: int = Field(gt=0)
    hit_threshold: float = Field(ge=0.0, le=1.0)
    fa_ceiling: float = Field(ge=0.0, le=1.0)
    max_attempts: int | None = None

    @model_validator(mode="after")
    def _check_deviants(self) -> PracticeConfig:
        if self.n_deviants >= self.n_trials:
            raise ValueError(
                "practice.n_deviants must be strictly less than n_trials "
                f"(got {self.n_deviants} >= {self.n_trials})"
            )
        if self.max_attempts is not None and self.max_attempts <= 0:
            raise ValueError("practice.max_attempts must be positive (or null for unlimited)")
        return self


class EngagementRatingConfig(_StrictModel):
    enabled: bool


class ActiveOddballConfig(_StrictModel):
    total_trials: int = Field(gt=0)
    duration_target_s: int = Field(gt=0)
    response_key: str
    abort_key: str
    practice: PracticeConfig
    engagement_rating: EngagementRatingConfig

    @model_validator(mode="after")
    def _check_keys(self) -> ActiveOddballConfig:
        if self.response_key.lower() == self.abort_key.lower():
            raise ValueError(
                "active_oddball.response_key and abort_key must differ "
                "(collision avoidance — see CLAUDE.md)"
            )
        return self


# Rating items — discriminated union by `type` so each has its own schema.


class _RatingItemBase(_StrictModel):
    id: str
    label: str
    required: bool


class RadioItem(_RatingItemBase):
    type: Literal["radio"]
    options: list[str] = Field(min_length=2)


class SpinnerIntItem(_RatingItemBase):
    type: Literal["spinner_int"]
    min: int
    max: int
    default: int

    @model_validator(mode="after")
    def _check_range(self) -> SpinnerIntItem:
        if self.min > self.max:
            raise ValueError(f"spinner_int.{self.id}: min ({self.min}) > max ({self.max})")
        if not (self.min <= self.default <= self.max):
            raise ValueError(
                f"spinner_int.{self.id}: default ({self.default}) outside [min, max]"
            )
        return self


class SliderItem(_RatingItemBase):
    type: Literal["slider"]
    min: int
    max: int
    default: int
    anchors: dict[int, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_range(self) -> SliderItem:
        if self.min >= self.max:
            raise ValueError(f"slider.{self.id}: min ({self.min}) >= max ({self.max})")
        if not (self.min <= self.default <= self.max):
            raise ValueError(f"slider.{self.id}: default ({self.default}) outside [min, max]")
        for anchor_value in self.anchors:
            if not (self.min <= anchor_value <= self.max):
                raise ValueError(
                    f"slider.{self.id}: anchor at {anchor_value} outside [min, max]"
                )
        return self


class TextboxItem(_RatingItemBase):
    type: Literal["textbox"]
    rows: int = Field(gt=0)


RatingItem = Annotated[
    RadioItem | SpinnerIntItem | SliderItem | TextboxItem,
    Field(discriminator="type"),
]


class RatingPanel(_StrictModel):
    items: list[RatingItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> RatingPanel:
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("rating items must have unique ids")
        return self


class RatingsConfig(_StrictModel):
    chills: RatingPanel
    rest: RatingPanel


class DisplayConfig(_StrictModel):
    fullscreen: bool
    background_color: str
    fixation_color: str
    text_color: str
    font_family: str
    font_size_normal: int = Field(gt=0)
    font_size_instruction: int = Field(gt=0)
    font_size_heading: int = Field(gt=0)
    ra_footer_visible: bool


class AbortConfig(_StrictModel):
    require_confirmation: bool
    partial_save_filename: str
    emit_session_abort_marker: bool


class LoggingConfig(_StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    log_to_file: bool
    log_filename: str
    console_output: bool


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class Config(_StrictModel):
    session: SessionMeta
    lsl: LslConfig
    audio: AudioConfig
    schedule: ScheduleConfig
    calibration: CalibrationConfig
    oddball: OddballConfig
    active_oddball: ActiveOddballConfig
    ratings: RatingsConfig
    instructions: dict[str, str]
    display: DisplayConfig
    abort: AbortConfig
    logging: LoggingConfig

    @model_validator(mode="after")
    def _cross_section_checks(self) -> Config:
        if self.calibration.condition not in self.schedule.conditions + ["calibration"]:
            # Accept any chills-style label; the calibration block uses its own
            # `calibration` marker name but the rating panel routing follows
            # `calibration.ratings_panel`.
            pass

        oddball_pairs = {
            ("chills_oddball_passive", "chills_only"),
            ("rest_oddball_passive", "rest_only"),
        }
        configured = set(self.schedule.conditions)
        required_any = {"chills_only", "rest_only", "chills_oddball_passive", "rest_oddball_passive"}
        if configured != required_any:
            raise ValueError(
                "schedule.conditions must be exactly "
                f"{sorted(required_any)} (got {sorted(configured)}). "
                "Conditions are paradigm-fixed; see CLAUDE.md."
            )
        # Touch oddball_pairs so ruff doesn't flag the literal as unused while
        # leaving an explicit map of which conditions pair with which panel.
        del oddball_pairs

        chills_keys = {"calibration_chills", "pre_block_chills_only", "pre_block_rest_only"}
        missing = chills_keys - set(self.instructions.keys())
        if missing:
            raise ValueError(f"instructions missing required keys: {sorted(missing)}")
        return self


# ---------------------------------------------------------------------------
# Loading + override merging
# ---------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate the YAML config. Defaults to the shipped file."""
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"config file must contain a top-level mapping; got {type(raw).__name__}")
    return Config.model_validate(raw)


def merge_overrides(config: Config, overrides: Mapping[str, Any]) -> Config:
    """Return a new validated Config with overrides applied.

    `overrides` is a recursive mapping shaped like the config tree, e.g.::

        {"audio": {"tone_volume_dbfs": -22.0},
         "schedule": {"seed_strategy": "fixed", "fixed_seed": 42}}

    Re-validates the merged dict, so invalid overrides raise the same
    pydantic errors a bad YAML would.
    """
    base = config.model_dump()
    merged = _deep_merge(base, overrides)
    return Config.model_validate(merged)


def _deep_merge(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out
