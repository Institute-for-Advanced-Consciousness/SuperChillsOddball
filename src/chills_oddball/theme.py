"""IACS color palette for GUI chrome.

Two visual modes coexist in the app:

  Chrome mode — intake, volume check, instructions, pre-block screens,
                ratings panels, active-oddball intro / post-practice /
                engagement, completion. Uses the IACS palette below: a
                purple accent (#5d5179) on a dark grey background, with
                off-white text. This is what the operator and the
                participant see between blocks.

  Task mode  — anything where the participant should be focused on the
                stimulus stream (block in-progress "eyes closed" screens,
                active-oddball main block). Stays pure black background
                with pure white text — maximum contrast, minimum visual
                distraction. Defined here so the two modes are wired
                consistently across stages.
"""

from __future__ import annotations

# --- Chrome palette -----------------------------------------------------

ACCENT = "#5d5179"          # IACS purple — primary brand color
ACCENT_LIGHT = "#8a7ca5"    # lighter purple for active states / hover
ACCENT_DARK = "#3d3550"     # darker purple for buttons / pressed states
CHROME_BG = "#1a1a1a"       # dark grey — chrome background
SURFACE = "#252525"         # slightly lighter — text boxes, panels
SURFACE_RAISED = "#2f2735"  # purple-tinted raised surface (radio buttons,
                            # slider troughs)
DIVIDER = "#3a3540"         # subtle separator
TEXT = "#e8e6ec"            # off-white — chrome body text
TEXT_MUTED = "#9b95a3"      # RA footer, captions, hints
TEXT_ACCENT = "#a89bc4"     # purple-tinted — emphasized chrome text

# --- Task palette (pure contrast) --------------------------------------

TASK_BG = "#000000"
TASK_TEXT = "#FFFFFF"

# --- Button styles -----------------------------------------------------

PRIMARY_BUTTON = dict(
    bg=ACCENT,
    fg="#FFFFFF",
    activebackground=ACCENT_LIGHT,
    activeforeground="#FFFFFF",
    relief="flat",
    borderwidth=0,
    cursor="hand2",
)

SECONDARY_BUTTON = dict(
    bg=ACCENT_DARK,
    fg=TEXT,
    activebackground=ACCENT,
    activeforeground="#FFFFFF",
    relief="flat",
    borderwidth=0,
    cursor="hand2",
)
