"""Audio scheduler + tone synthesis helpers.

ToneScheduler runs a persistent sounddevice OutputStream and emits LSL
markers from inside the audio callback at the exact sample where each tone
begins. Targets <2 ms onset jitter for ERP epoching.
"""
