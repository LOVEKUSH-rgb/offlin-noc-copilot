from __future__ import annotations
# -*- coding: utf-8 -*-
"""
inference.py - Phase 2: Offline Inference Bridge
=================================================
Air-Gapped NOC Copilot | Offline Network Prediction System

Provides the get_remediation_advice() function that:
  1. Reads the local runbook.md and extracts the relevant SOP section
     matching the alert type (e.g. HIGH_LATENCY, PACKET_LOSS).
  2. Constructs a tightly scoped system prompt that constrains the model
     to act as a NOC Network Architect and answer ONLY from runbook rules.
  3. Calls the locally hosted Ollama phi3 model (fully air-gapped, no internet).
  4. Fails gracefully with a structured "Local AI Service Offline" response
     if the Ollama daemon is not running.

Supported Alert Types
---------------------
  "HIGH_LATENCY"  -> maps to SOP-001 in runbook.md
  "PACKET_LOSS"   -> maps to SOP-002 in runbook.md
  "UNKNOWN"       -> passes full runbook as context

Usage (standalone test)
-----------------------
  python inference.py
"""

import io
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

# Ensure stdout handles UTF-8 on Windows terminals (cp1252 fallback fix)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# -- Third-party --------------------------------------------------------------
try:
    import ollama  # pip install ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    _OLLAMA_AVAILABLE = False

# =============================================================================
#  Configuration constants
# =============================================================================

MODEL_NAME   = "phi3"                                   # Local Ollama model
RUNBOOK_PATH = Path(__file__).parent / "runbook.md"    # Sibling file in workspace

# Maps each alert type to its SOP heading regex pattern
ALERT_SOP_MAP: dict[str, str] = {
    "HIGH_LATENCY": r"SOP-001.*High Latency",
    "PACKET_LOSS":  r"SOP-002.*Packet Loss",
}

# Maximum characters of runbook context sent per query (keeps LLM prompt tight)
MAX_CONTEXT_CHARS = 4000

DIVIDER = "-" * 80


# =============================================================================
#  Runbook loader & context extractor
# =============================================================================

def _load_runbook() -> str:
    """Read and return the full runbook text. Raises FileNotFoundError if missing."""
    if not RUNBOOK_PATH.exists():
        raise FileNotFoundError(
            f"runbook.md not found at {RUNBOOK_PATH}. "
            "Ensure it is in the same directory as inference.py."
        )
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def _extract_sop_section(runbook_text: str, alert_type: str) -> str:
    """
    Extract the SOP section from the runbook that matches the given alert type.

    Strategy
    --------
    1. Look up the heading pattern from ALERT_SOP_MAP.
    2. Find the first '## SOP-XXX' heading that matches.
    3. Slice the text from that heading to the next '## ' heading (or EOF).
    4. Truncate to MAX_CONTEXT_CHARS to keep the LLM prompt manageable.

    Falls back to the full runbook (truncated) if no match is found.
    """
    pattern = ALERT_SOP_MAP.get(alert_type.upper())

    if pattern:
        # Split on level-2 headings to isolate individual SOPs
        sections = re.split(r"\n(?=## )", runbook_text)
        for section in sections:
            if re.search(pattern, section, re.IGNORECASE):
                return section[:MAX_CONTEXT_CHARS]

    # Fallback: return full runbook truncated
    return runbook_text[:MAX_CONTEXT_CHARS]


# =============================================================================
#  Prompt builders
# =============================================================================

_SYSTEM_PROMPT_TEMPLATE = textwrap.dedent("""\
    You are an expert NOC (Network Operations Centre) Network Architect with
    15+ years of experience managing MPLS carrier-grade networks.

    Your ONLY source of truth is the NOC Runbook excerpt provided below.
    You MUST NOT invent steps, tools, or commands that are not present in the
    runbook. If the runbook does not cover a specific sub-case, say so explicitly
    and recommend escalation.

    Response format rules (follow strictly):
      - Begin with a one-sentence summary of the situation.
      - List numbered, actionable mitigation steps drawn directly from the runbook.
      - Flag any step that requires NOC-lead approval with [REQUIRES APPROVAL].
      - End with a Verification block listing the commands to confirm resolution.
      - Keep the entire response under 400 words.
      - Use plain text only, no markdown headers, no bullet nesting beyond two levels.

    == NOC RUNBOOK CONTEXT (authoritative, read-only) ==
    {runbook_context}
    =====================================================
""")

_USER_PROMPT_TEMPLATE = textwrap.dedent("""\
    ACTIVE ALERT  : {alert_type}
    LIVE METRICS  :
      Latency      : {latency_ms} ms
      Packet Loss  : {packet_loss_pct}%
      Jitter       : {jitter_ms} ms
      Phase        : {phase}

    Based solely on the runbook context above, provide step-by-step mitigation
    advice for this alert. Be concise and operator-ready.
""")


def _build_prompts(
    alert_type: str,
    current_metrics: dict[str, Any],
    runbook_context: str,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) ready to send to the model."""
    system = _SYSTEM_PROMPT_TEMPLATE.format(runbook_context=runbook_context)
    user   = _USER_PROMPT_TEMPLATE.format(
        alert_type       = alert_type.upper(),
        latency_ms       = current_metrics.get("latency_ms",       "N/A"),
        packet_loss_pct  = current_metrics.get("packet_loss_pct",  "N/A"),
        jitter_ms        = current_metrics.get("jitter_ms",        "N/A"),
        phase            = current_metrics.get("phase",            "N/A"),
    )
    return system, user


# =============================================================================
#  Graceful offline response builder
# =============================================================================

def _offline_response(reason: str) -> dict[str, Any]:
    """
    Return a structured 'service offline' dict when Ollama cannot be reached.
    The caller receives a consistent schema regardless of the error cause.
    """
    return {
        "status":  "LOCAL_AI_SERVICE_OFFLINE",
        "reason":  reason,
        "advice":  (
            "[WARNING] The local Ollama inference service is not reachable.\n\n"
            "Fallback procedure:\n"
            "  1. Verify Ollama is installed:  ollama --version\n"
            "  2. Start the daemon:            ollama serve\n"
            "  3. Pull the required model:     ollama pull phi3\n"
            "  4. Re-run this query.\n\n"
            "Until the AI service is restored, refer directly to runbook.md "
            "for manual SOP guidance."
        ),
        "model":   MODEL_NAME,
        "runbook": str(RUNBOOK_PATH),
    }


# =============================================================================
#  Public API
# =============================================================================

def get_remediation_advice(
    alert_type: str,
    current_metrics: dict[str, Any],
) -> dict[str, Any]:
    """
    Query the local Ollama phi3 model for step-by-step NOC remediation advice.

    Parameters
    ----------
    alert_type : str
        Category of the active alert. Recognised values:
          "HIGH_LATENCY" -- triggers SOP-001 context from runbook
          "PACKET_LOSS"  -- triggers SOP-002 context from runbook
          Any other value passes the full runbook as context.

    current_metrics : dict
        Live telemetry snapshot. Expected keys (all optional but recommended):
          latency_ms       : float  -- current one-way latency in milliseconds
          packet_loss_pct  : float  -- current packet-loss percentage
          jitter_ms        : float  -- current jitter in milliseconds
          phase            : str   -- simulation phase ("HEALTHY" / "DEGRADING")

    Returns
    -------
    dict with keys:
        status        : "OK" | "LOCAL_AI_SERVICE_OFFLINE" | "RUNBOOK_MISSING"
        advice        : str  -- the model's remediation text (or fallback message)
        model         : str  -- model name used
        alert         : str  -- echo of alert_type
        metrics       : dict -- echo of current_metrics
        context_chars : int  -- characters of runbook context injected (on success)

    Raises
    ------
    Nothing -- all exceptions are caught and returned as structured error dicts.
    """

    # -- Guard: ollama package installed? -------------------------------------
    if not _OLLAMA_AVAILABLE:
        return {
            **_offline_response(
                "The 'ollama' Python package is not installed. "
                "Run:  pip install ollama"
            ),
            "alert":   alert_type,
            "metrics": current_metrics,
        }

    # -- Load runbook ---------------------------------------------------------
    try:
        runbook_text = _load_runbook()
    except FileNotFoundError as exc:
        return {
            "status":  "RUNBOOK_MISSING",
            "reason":  str(exc),
            "advice":  "Cannot provide advice -- runbook.md is missing from the workspace.",
            "model":   MODEL_NAME,
            "alert":   alert_type,
            "metrics": current_metrics,
        }

    # -- Extract relevant SOP section -----------------------------------------
    runbook_context = _extract_sop_section(runbook_text, alert_type)

    # -- Build prompts --------------------------------------------------------
    system_prompt, user_prompt = _build_prompts(
        alert_type, current_metrics, runbook_context
    )

    # -- Call local Ollama (may fail if daemon is not running) ----------------
    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            options={
                "temperature": 0.2,  # Low temp -> deterministic, factual output
                "num_predict": 600,  # Cap tokens to keep responses concise
            },
        )

        advice_text = response["message"]["content"].strip()

        return {
            "status":        "OK",
            "advice":        advice_text,
            "model":         MODEL_NAME,
            "alert":         alert_type,
            "metrics":       current_metrics,
            "context_chars": len(runbook_context),
        }

    # -- Connection refused (Ollama daemon not started) -----------------------
    except ConnectionRefusedError:
        return {
            **_offline_response(
                "Connection refused -- Ollama daemon is not running. "
                "Start it with: ollama serve"
            ),
            "alert":   alert_type,
            "metrics": current_metrics,
        }

    # -- Ollama-specific errors (model not pulled, bad model name, etc.) ------
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)

        # Model not found locally
        if "model" in err_msg.lower() and (
            "not found" in err_msg.lower() or "pull" in err_msg.lower()
        ):
            return {
                **_offline_response(
                    f"Model '{MODEL_NAME}' is not available locally. "
                    f"Pull it with: ollama pull {MODEL_NAME}"
                ),
                "alert":   alert_type,
                "metrics": current_metrics,
            }

        # Generic catch-all
        return {
            **_offline_response(
                f"Unexpected error communicating with Ollama: {err_msg}"
            ),
            "alert":   alert_type,
            "metrics": current_metrics,
        }


# =============================================================================
#  Pretty printer helper (for CLI / integration testing)
# =============================================================================

def _print_result(result: dict[str, Any]) -> None:
    """Render a get_remediation_advice() result to stdout in a readable format."""
    print("\n" + DIVIDER)
    print(f"  NOC COPILOT - Offline Inference Bridge  |  Model: {result.get('model')}")
    print(DIVIDER)
    print(f"  Alert Type : {result.get('alert', 'N/A')}")
    print(f"  Status     : {result.get('status', 'N/A')}")

    metrics = result.get("metrics", {})
    if metrics:
        print(
            f"  Metrics    : latency={metrics.get('latency_ms', '?')} ms  |  "
            f"loss={metrics.get('packet_loss_pct', '?')}%  |  "
            f"jitter={metrics.get('jitter_ms', '?')} ms  |  "
            f"phase={metrics.get('phase', '?')}"
        )

    if "context_chars" in result:
        print(f"  Context    : {result['context_chars']} chars of runbook injected")

    reason = result.get("reason")
    if reason:
        print(f"  Reason     : {reason}")

    print(DIVIDER)
    print("\n  REMEDIATION ADVICE:\n")
    for line in result.get("advice", "").splitlines():
        print(f"  {line}")
    print("\n" + DIVIDER + "\n")


# =============================================================================
#  Standalone smoke-test entry point
# =============================================================================

if __name__ == "__main__":
    import json

    # Test 1: HIGH_LATENCY alert (maps to SOP-001)
    print("\n[TEST 1] HIGH_LATENCY alert -- degraded metrics")
    result_1 = get_remediation_advice(
        alert_type="HIGH_LATENCY",
        current_metrics={
            "latency_ms":      162.4,
            "packet_loss_pct": 3.1,
            "jitter_ms":       28.7,
            "phase":           "DEGRADING",
        },
    )
    _print_result(result_1)

    # Test 2: PACKET_LOSS alert (maps to SOP-002)
    print("[TEST 2] PACKET_LOSS alert -- critical metrics")
    result_2 = get_remediation_advice(
        alert_type="PACKET_LOSS",
        current_metrics={
            "latency_ms":      88.3,
            "packet_loss_pct": 14.6,
            "jitter_ms":       55.2,
            "phase":           "DEGRADING",
        },
    )
    _print_result(result_2)

    # Test 3: Unknown alert type (full runbook fallback)
    print("[TEST 3] UNKNOWN alert type -- full runbook context fallback")
    result_3 = get_remediation_advice(
        alert_type="UNKNOWN",
        current_metrics={
            "latency_ms":      45.0,
            "packet_loss_pct": 0.8,
            "jitter_ms":       12.0,
            "phase":           "DEGRADING",
        },
    )
    _print_result(result_3)

    # Raw JSON dump for integration consumers
    print("  [RAW JSON -- Test 1 result for integration consumers]\n")
    safe = {k: v for k, v in result_1.items() if k != "advice"}
    print(json.dumps(safe, indent=2, default=str))
    print()
