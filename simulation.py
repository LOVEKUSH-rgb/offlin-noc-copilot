# -*- coding: utf-8 -*-
"""
simulation.py - Phase 1: Network Telemetry Simulation Engine
=============================================================
Air-Gapped NOC Copilot | Offline Network Prediction System

Simulates a continuous stream of MPLS network telemetry metrics.
  - Phase A (HEALTHY):   10 loops of normal, low-latency traffic.
  - Phase B (DEGRADING): Metrics steadily climb toward a 200 ms ceiling,
                         modelling a realistic failure precursor.

Predictive Tracker
------------------
  Every iteration, the last TREND_WINDOW (5) latency readings are fitted
  to a linear model via least-squares regression (numpy.polyfit).
  The resulting slope is used to project latency LOOKAHEAD (5) intervals
  into the future.  If the projection exceeds WARNING_THRESHOLD (150 ms),
  a PRECURSOR_WARNING flag is printed immediately.

Usage
-----
  python simulation.py                  # run full 60-loop simulation
  python simulation.py --loops 30       # custom loop count
  python simulation.py --realtime       # 1-second cadence (operator mode)
"""

import argparse
import random
import time
from datetime import datetime

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
#  Configuration constants
# ─────────────────────────────────────────────────────────────────────────────
HEALTHY_LOOPS      = 10       # How many loops stay in the "HEALTHY" phase
HEALTHY_LAT_MIN    = 14.0     # Lower bound for healthy latency (ms)
HEALTHY_LAT_MAX    = 28.0     # Upper bound for healthy latency (ms)
HEALTHY_PKT_MAX    = 0.5      # Max packet-loss % during healthy phase
HEALTHY_JIT_MAX    = 4.0      # Max jitter (ms) during healthy phase

DEGRADE_TARGET_LAT = 200.0   # Peak latency the degradation ramps toward (ms)
DEGRADE_PKT_MAX    = 25.0    # Peak packet-loss % at full degradation
DEGRADE_JIT_MAX    = 70.0    # Peak jitter (ms) at full degradation

WARNING_THRESHOLD  = 150.0   # Latency (ms) whose projected breach triggers a flag
TREND_WINDOW       = 5        # Number of past data points used for regression
LOOKAHEAD          = 5        # Intervals ahead to project with the trend line

TICK_FAST          = 0.25     # Seconds between ticks in test/demo mode
TICK_REALTIME      = 1.0      # Seconds between ticks in operator/realtime mode

DIVIDER            = "-" * 95


# ─────────────────────────────────────────────────────────────────────────────
#  Metric generators
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    """ISO-8601 timestamp string, second precision."""
    return datetime.now().isoformat(timespec="seconds")


def generate_healthy_metrics(loop_idx: int) -> dict:
    """
    Return a telemetry snapshot representative of a healthy MPLS link.
    All values are drawn from tight, low-noise distributions.
    """
    return {
        "timestamp":       _now(),
        "loop":            loop_idx,
        "latency_ms":      round(random.uniform(HEALTHY_LAT_MIN, HEALTHY_LAT_MAX), 2),
        "packet_loss_pct": round(random.uniform(0.0, HEALTHY_PKT_MAX), 3),
        "jitter_ms":       round(random.uniform(1.0, HEALTHY_JIT_MAX), 2),
        "phase":           "HEALTHY",
    }


def generate_degraded_metrics(loop_idx: int, step: int, total_steps: int) -> dict:
    """
    Return a telemetry snapshot with progressively worsening metrics.

    `step`        : how many degradation ticks have elapsed (starts at 0).
    `total_steps` : total number of degradation ticks in the run.

    The degradation follows a linear ramp from HEALTHY_LAT_MAX → DEGRADE_TARGET_LAT,
    with realistic stochastic noise layered on top.
    """
    # progress goes 0.0 → 1.0 as the simulation advances through the bad phase
    progress = step / max(total_steps - 1, 1)

    base_lat = HEALTHY_LAT_MAX + progress * (DEGRADE_TARGET_LAT - HEALTHY_LAT_MAX)
    noise    = random.gauss(mu=0.0, sigma=6.0)   # Gaussian noise for realism
    latency  = round(max(HEALTHY_LAT_MIN, min(DEGRADE_TARGET_LAT + 20, base_lat + noise)), 2)

    # Packet loss and jitter degrade proportionally, also with noise
    pkt_loss = round(min(DEGRADE_PKT_MAX, progress * DEGRADE_PKT_MAX + random.uniform(0, 3)), 3)
    jitter   = round(min(DEGRADE_JIT_MAX, progress * DEGRADE_JIT_MAX + random.uniform(0, 5)), 2)

    return {
        "timestamp":       _now(),
        "loop":            loop_idx,
        "latency_ms":      latency,
        "packet_loss_pct": pkt_loss,
        "jitter_ms":       jitter,
        "phase":           "DEGRADING",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Predictive Tracker
# ─────────────────────────────────────────────────────────────────────────────

def check_precursor_warning(df: pd.DataFrame) -> tuple[bool, float]:
    """
    Fit a linear trend to the last TREND_WINDOW latency readings and project
    LOOKAHEAD intervals into the future.

    Returns
    -------
    (warning_fired : bool, projected_latency : float)
        warning_fired      – True if the projection exceeds WARNING_THRESHOLD
        projected_latency  – The extrapolated latency value LOOKAHEAD ticks ahead

    Algorithm
    ---------
      x = [0, 1, 2, ..., TREND_WINDOW-1]        (relative time indices)
      y = last TREND_WINDOW values of latency_ms
      coefficients = np.polyfit(x, y, deg=1)     (least-squares linear fit)
      slope, intercept = coefficients

      The last observed point sits at x = TREND_WINDOW - 1.
      Projecting LOOKAHEAD steps ahead:
          x_future = (TREND_WINDOW - 1) + LOOKAHEAD
          projected = slope * x_future + intercept
    """
    if len(df) < TREND_WINDOW:
        # Not enough history yet — cannot make a reliable projection
        return False, float("nan")

    recent = df["latency_ms"].tail(TREND_WINDOW).values          # shape (TREND_WINDOW,)
    x      = np.arange(TREND_WINDOW, dtype=float)                # [0, 1, 2, 3, 4]

    slope, intercept = np.polyfit(x, recent, deg=1)

    x_future  = float(TREND_WINDOW - 1 + LOOKAHEAD)             # e.g., 4 + 5 = 9
    projected = slope * x_future + intercept

    warning = projected > WARNING_THRESHOLD
    return warning, round(projected, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def _phase_icon(phase: str) -> str:
    return "[OK] " if phase == "HEALTHY" else "[!!]"


def print_header(total_loops: int, degradation_steps: int) -> None:
    print("\n" + DIVIDER)
    print("  AIR-GAPPED NOC COPILOT  |  Phase 1 - Network Telemetry Simulation Engine")
    print(DIVIDER)
    print(f"  Healthy loops      : {HEALTHY_LOOPS}")
    print(f"  Degradation loops  : {degradation_steps}")
    print(f"  Total loops        : {total_loops}")
    print(f"  Warning threshold  : {WARNING_THRESHOLD} ms")
    print(f"  Trend window       : {TREND_WINDOW} data points")
    print(f"  Lookahead horizon  : {LOOKAHEAD} intervals")
    print(DIVIDER)
    print(
        f"  {'TIMESTAMP':<20}  {'LOOP':>4}  {'PHASE':<9}  "
        f"{'LATENCY':>10}  {'PKT LOSS':>9}  {'JITTER':>8}  PREDICTION"
    )
    print(DIVIDER)


def print_row(row: dict, warning: bool, projected: float) -> None:
    """Pretty-print one telemetry row with the live prediction column."""
    icon = _phase_icon(row["phase"])

    if np.isnan(projected):
        pred_col = f"{'(collecting...)':>20}"
    elif warning:
        pred_col = (
            f"  proj={projected:>7.1f} ms  [PRECURSOR_WARNING]"
            f" - breach of {WARNING_THRESHOLD:.0f} ms projected in {LOOKAHEAD} intervals!"
        )
    else:
        pred_col = f"  proj={projected:>7.1f} ms  [OK] within limits"

    print(
        f"  {row['timestamp']:<20}  {row['loop']:>4}  "
        f"{icon}{row['phase']:<9}  "
        f"{row['latency_ms']:>7.1f} ms  "
        f"{row['packet_loss_pct']:>7.3f}%  "
        f"{row['jitter_ms']:>6.1f} ms"
        + pred_col
    )


def print_summary(df: pd.DataFrame) -> None:
    """Print descriptive statistics for the full run."""
    print("\n" + DIVIDER)
    print("  RUN SUMMARY - Descriptive Statistics")
    print(DIVIDER)

    for phase in ["HEALTHY", "DEGRADING"]:
        subset = df[df["phase"] == phase]
        if subset.empty:
            continue
        print(f"\n  Phase: {phase}  ({len(subset)} readings)")
        stats = subset[["latency_ms", "packet_loss_pct", "jitter_ms"]].describe().round(2)
        print(stats.to_string())

    warnings_fired = df.get("warning_fired", pd.Series(dtype=bool)).sum()
    print(f"\n  PRECURSOR_WARNING events fired : {warnings_fired}")
    print(DIVIDER + "\n")


# ─────────────────────────────────────────────────────────────────────────────
#  Main simulation loop
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(max_loops: int = 60, realtime: bool = False) -> pd.DataFrame:
    """
    Execute the full telemetry simulation and return the complete DataFrame.

    Parameters
    ----------
    max_loops : int
        Total number of telemetry ticks to simulate (default 60).
    realtime : bool
        If True, use a 1-second tick interval (operator mode).
        If False, use 0.25-second tick interval (demo/test mode).

    Returns
    -------
    pd.DataFrame
        Full record of all simulated telemetry rows, including
        a 'warning_fired' boolean column and 'projected_latency' column.
    """
    tick          = TICK_REALTIME if realtime else TICK_FAST
    degrade_steps = max_loops - HEALTHY_LOOPS
    degrade_step  = 0
    records: list[dict] = []

    print_header(max_loops, degrade_steps)

    for i in range(max_loops):
        # ── Generate metrics ─────────────────────────────────────────────────
        if i < HEALTHY_LOOPS:
            row = generate_healthy_metrics(i)
        else:
            row = generate_degraded_metrics(i, degrade_step, degrade_steps)
            degrade_step += 1

        # ── Append to history and run predictive check ────────────────────────
        records.append(row)
        df = pd.DataFrame(records)
        warning, projected = check_precursor_warning(df)

        # ── Annotate record with prediction results ───────────────────────────
        records[-1]["warning_fired"]      = warning
        records[-1]["projected_latency"]  = projected

        # ── Console output ────────────────────────────────────────────────────
        print_row(row, warning, projected)

        time.sleep(tick)

    # ── Final DataFrame (rebuild with annotation columns) ─────────────────────
    final_df = pd.DataFrame(records)
    print_summary(final_df)
    return final_df


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Air-Gapped NOC Copilot — Phase 1 Telemetry Simulation"
    )
    parser.add_argument(
        "--loops", type=int, default=60,
        help="Total number of simulation ticks (default: 60)"
    )
    parser.add_argument(
        "--realtime", action="store_true",
        help="Use 1-second tick interval for realistic operator mode"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_simulation(max_loops=args.loops, realtime=args.realtime)
