"""Block-list and oddball-sequence generators.

- `generate_session_schedule`: 4 blocks per condition x 4 conditions = 16,
  duration set assigned 1:1 within each condition, no back-to-back same
  condition. Calibration always first, active oddball always last.
- `generate_oddball_sequence`: rejection-sampled sequence enforcing
  min-standards-before-first-deviant, min-standards-between-deviants,
  max-consecutive-standards. Fails loudly if unsatisfiable.
"""
