from __future__ import annotations

# ── stdlib ───────────────────────────────────────────────────────────────────
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure sibling workspace modules are always importable
sys.path.insert(0, str(Path(__file__).parent))

# ── third-party ───────────────────────────────────────────────────────────────
import pandas as pd
import streamlit as st

# ── Phase 1 & Phase 2 modules ─────────────────────────────────────────────────
from simulation import (
    DEGRADE_TARGET_LAT,
    HEALTHY_LOOPS,
    HEALTHY_LAT_MAX,
    LOOKAHEAD,
    TREND_WINDOW,
    WARNING_THRESHOLD,
    check_precursor_warning,
    generate_degraded_metrics,
    generate_healthy_metrics,
)
from inference import MODEL_NAME, get_remediation_advice

# =============================================================================
#  Page configuration — MUST be first Streamlit call
# =============================================================================
st.set_page_config(
    page_title="NOC Copilot | Live Dashboard",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "Air-Gapped NOC Copilot — Phase 3 Live Intelligence Dashboard",
    },
)

# =============================================================================
#  Custom CSS — Premium dark glassmorphism theme
# =============================================================================
st.markdown("""
<style>
/* ── Google Fonts (falls back gracefully if air-gapped) ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Global reset ── */
html, body, [class*="css"] {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    background-color: #070b17;
    color: #e2e8f0;
}
.stApp {
    background: radial-gradient(ellipse at 20% 20%, #0d1433 0%, #070b17 60%),
                radial-gradient(ellipse at 80% 80%, #0a1628 0%, #070b17 60%);
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: rgba(10, 15, 35, 0.97) !important;
    border-right: 1px solid rgba(99, 179, 237, 0.12);
}
section[data-testid="stSidebar"] * { color: #94a3b8; }
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] b { color: #e2e8f0; }
section[data-testid="stSidebar"] .stSlider > label { color: #94a3b8; }

/* ── Dashboard header ── */
.dash-header {
    background: linear-gradient(135deg, rgba(99,179,237,0.07) 0%, rgba(139,92,246,0.04) 100%);
    border: 1px solid rgba(99, 179, 237, 0.14);
    border-radius: 16px;
    padding: 22px 32px;
    margin-bottom: 22px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.dash-title    { font-size: 1.45rem; font-weight: 700; color: #f1f5f9; margin: 0; letter-spacing: -0.01em; }
.dash-subtitle { font-size: 0.82rem; color: #475569; margin: 5px 0 0; }
.dash-badge {
    background: rgba(99,179,237,0.12);
    border: 1px solid rgba(99,179,237,0.25);
    border-radius: 20px;
    padding: 5px 16px;
    font-size: 0.7rem;
    color: #63b3ed;
    font-weight: 600;
    letter-spacing: 0.09em;
    text-transform: uppercase;
}

/* ── Status banners ── */
.status-ready {
    background: linear-gradient(135deg, rgba(30,41,59,0.6), rgba(15,23,42,0.6));
    border: 1px dashed rgba(99,179,237,0.2);
    border-radius: 14px;
    padding: 20px 32px;
    text-align: center;
}
.status-ready h2 { color: #475569; margin: 0; font-size: 1.35rem; font-weight: 600; }

.status-healthy {
    background: linear-gradient(135deg, rgba(16,185,129,0.12) 0%, rgba(5,150,105,0.05) 100%);
    border: 1px solid rgba(16,185,129,0.35);
    border-radius: 14px;
    padding: 20px 32px;
    text-align: center;
}
.status-healthy h2 { color: #10b981; margin: 0; font-size: 1.35rem; font-weight: 700; letter-spacing: 0.02em; }
.status-healthy p  { color: #6ee7b7; margin: 6px 0 0; font-size: 0.82rem; }

.status-critical {
    background: linear-gradient(135deg, rgba(239,68,68,0.18) 0%, rgba(220,38,38,0.06) 100%);
    border: 2px solid rgba(239, 68, 68, 0.65);
    border-radius: 14px;
    padding: 20px 32px;
    text-align: center;
    animation: critical-pulse 1.1s ease-in-out infinite;
}
.status-critical h2 { color: #f87171; margin: 0; font-size: 1.35rem; font-weight: 700; letter-spacing: 0.02em; }
.status-critical p  { color: #fbbf24; margin: 7px 0 0; font-size: 0.84rem; font-weight: 500; }

@keyframes critical-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.45), inset 0 0 30px rgba(239, 68, 68, 0.04); }
    50%       { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0),  inset 0 0 30px rgba(239, 68, 68, 0.08); }
}

.status-elevated {
    background: linear-gradient(135deg, rgba(245,158,11,0.12) 0%, rgba(217,119,6,0.05) 100%);
    border: 1px solid rgba(245, 158, 11, 0.45);
    border-radius: 14px;
    padding: 20px 32px;
    text-align: center;
    animation: amber-pulse 1.8s ease-in-out infinite;
}
.status-elevated h2 { color: #fbbf24; margin: 0; font-size: 1.35rem; font-weight: 700; }
.status-elevated p  { color: #94a3b8; margin: 6px 0 0; font-size: 0.82rem; }

@keyframes amber-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.35); }
    50%       { box-shadow: 0 0 0 7px rgba(245, 158, 11, 0); }
}

/* ── Metric cards ── */
.metric-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(99, 179, 237, 0.1);
    border-radius: 14px;
    padding: 18px 20px;
    text-align: center;
    transition: border-color 0.3s, transform 0.2s;
    min-height: 100px;
}
.metric-card:hover { border-color: rgba(99, 179, 237, 0.3); transform: translateY(-2px); }
.metric-value {
    font-size: 1.9rem; font-weight: 700;
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    line-height: 1.1;
}
.metric-unit  { font-size: 0.9rem; font-weight: 400; opacity: 0.7; }
.metric-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.1em; color: #64748b; margin-top: 6px; }
.metric-sub   { font-size: 0.72rem; color: #334155; margin-top: 3px; }

/* ── Chart section ── */
.chart-header {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: #64748b;
    margin-bottom: 8px;
    padding-left: 2px;
}
.chart-label-accent { color: #63b3ed; font-weight: 600; }

/* ── AI advice panel ── */
.advice-wrap {
    background: rgba(5, 10, 25, 0.85);
    border: 1px solid rgba(99, 179, 237, 0.15);
    border-left: 3px solid #63b3ed;
    border-radius: 10px;
    padding: 18px 22px;
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.79rem;
    line-height: 1.75;
    color: #cbd5e1;
    white-space: pre-wrap;
    max-height: 340px;
    overflow-y: auto;
}
.advice-wrap::-webkit-scrollbar { width: 4px; }
.advice-wrap::-webkit-scrollbar-track { background: transparent; }
.advice-wrap::-webkit-scrollbar-thumb { background: rgba(99,179,237,0.2); border-radius: 4px; }
.advice-idle { border-left-color: #334155; color: #334155; }
.advice-offline { border-left-color: #f59e0b; }
.advice-meta {
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #63b3ed;
    margin-bottom: 12px;
    font-family: 'Inter', sans-serif;
}
.advice-meta-offline { color: #f59e0b; }

/* ── Event log ── */
.log-panel {
    background: rgba(3, 6, 18, 0.9);
    border: 1px solid rgba(99, 179, 237, 0.08);
    border-radius: 10px;
    padding: 14px 16px;
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.71rem;
    line-height: 1.65;
    max-height: 340px;
    overflow-y: auto;
}
.log-panel::-webkit-scrollbar { width: 3px; }
.log-panel::-webkit-scrollbar-thumb { background: rgba(99,179,237,0.15); border-radius: 4px; }
.log-ok   { color: #22c55e; }
.log-warn { color: #f59e0b; }
.log-info { color: #475569; }

/* ── Section headers ── */
.section-title {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #475569;
    margin-bottom: 10px;
    font-weight: 600;
}

/* ── Streamlit component overrides ── */
.stButton > button {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: #f8fafc !important;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.82rem;
    padding: 9px 18px;
    width: 100%;
    transition: all 0.2s ease;
    letter-spacing: 0.02em;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(37, 99, 235, 0.35);
    background: linear-gradient(135deg, #3b82f6, #2563eb);
}
div[data-testid="stProgressBar"] > div > div { background: linear-gradient(90deg, #3b82f6, #8b5cf6); }
.stProgress { margin-top: 4px; }
hr { border-color: rgba(99,179,237,0.1) !important; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
#  Session State — initialise keys that may not exist yet
# =============================================================================
_DEFAULTS: dict = {
    "running":        False,
    "loop_idx":       0,
    "degrade_step":   0,
    "records":        [],
    "event_log":      [],          # list of (css_class, message)
    "warning_shown":  False,       # True once the first PRECURSOR_WARNING fires
    "advice":         None,        # dict returned by get_remediation_advice()
    "total_loops":    40,
    "tick":           0.5,
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _reset_state() -> None:
    for k in _DEFAULTS:
        st.session_state[k] = _DEFAULTS[k].copy() if isinstance(_DEFAULTS[k], list) else _DEFAULTS[k]


# =============================================================================
#  Sidebar — controls & configuration panel
# =============================================================================
with st.sidebar:
    st.markdown("### 🛰️  NOC Copilot")
    st.markdown(
        "<div style='font-size:0.78rem;color:#475569;margin-top:-8px;margin-bottom:16px'>"
        "Air-Gapped Network Intelligence</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    st.markdown("**⚙️  Simulation Controls**")
    cfg_loops = st.slider(
        "Total Ticks", min_value=20, max_value=100, value=40, step=5,
        help="Total number of telemetry intervals to simulate",
    )
    cfg_tick = st.select_slider(
        "Tick Speed",
        options=[0.25, 0.5, 1.0, 2.0],
        value=0.5,
        format_func=lambda x: f"{x}s / tick",
    )

    st.divider()
    st.markdown("**📡  Engine Config**")
    st.markdown(f"""
    <div style="font-size:0.77rem; color:#475569; line-height:2.0;">
      Healthy phase    <span style="float:right;color:#94a3b8"><b>{HEALTHY_LOOPS}</b> ticks</span><br>
      Degrade target   <span style="float:right;color:#94a3b8"><b>{DEGRADE_TARGET_LAT:.0f} ms</b></span><br>
      Warn threshold   <span style="float:right;color:#f59e0b"><b>{WARNING_THRESHOLD:.0f} ms</b></span><br>
      Trend window     <span style="float:right;color:#94a3b8"><b>{TREND_WINDOW} pts</b></span><br>
      Lookahead        <span style="float:right;color:#94a3b8"><b>{LOOKAHEAD} ticks</b></span><br>
      AI model         <span style="float:right;color:#63b3ed"><b>{MODEL_NAME} (local)</b></span>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.markdown("**▶  Run Controls**")
    c_start, c_stop = st.columns(2)
    with c_start:
        btn_start = st.button("▶ Start", disabled=st.session_state.running,  key="btn_start")
    with c_stop:
        btn_stop  = st.button("⏹ Stop",  disabled=not st.session_state.running, key="btn_stop")
    btn_reset = st.button("↺  Reset Simulation", key="btn_reset")

    if btn_start:
        _reset_state()
        st.session_state.running     = True
        st.session_state.total_loops = cfg_loops
        st.session_state.tick        = cfg_tick
        st.rerun()

    if btn_stop:
        st.session_state.running = False
        st.rerun()

    if btn_reset:
        _reset_state()
        st.rerun()

    st.divider()
    st.markdown("""
    <div style="font-size:0.68rem; color:#1e293b; text-align:center; line-height:1.9;">
      Phase 1 — Simulation Engine  ✅<br>
      Phase 2 — Inference Bridge   ✅<br>
      Phase 3 — Live Dashboard     ✅
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
#  Dashboard header
# =============================================================================
_now_str = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
st.markdown(f"""
<div class="dash-header">
  <div>
    <p class="dash-title">🛰️  Air-Gapped NOC Copilot</p>
    <p class="dash-subtitle">Phase 3 — Live MPLS Network Telemetry Intelligence &nbsp;·&nbsp; {_now_str}</p>
  </div>
  <span class="dash-badge">&#9679; Offline Mode</span>
</div>
""", unsafe_allow_html=True)


# =============================================================================
#  Run One Simulation Tick
#  (Streamlit re-executes this entire script on every rerun; one tick per pass)
# =============================================================================
if st.session_state.running:
    _i     = st.session_state.loop_idx
    _total = st.session_state.total_loops
    _deg_steps = max(_total - HEALTHY_LOOPS, 1)

    if _i >= _total:
        # Simulation complete
        st.session_state.running = False
        st.session_state.event_log.append(
            ("log-info", f"[{datetime.now().strftime('%H:%M:%S')}] ── Simulation complete ({_total} ticks) ──")
        )
    else:
        # Generate the next telemetry row
        if _i < HEALTHY_LOOPS:
            _row = generate_healthy_metrics(_i)
        else:
            _row = generate_degraded_metrics(_i, st.session_state.degrade_step, _deg_steps)
            st.session_state.degrade_step += 1

        # Append and run predictive check against accumulated history
        st.session_state.records.append(_row)
        _df_live = pd.DataFrame(st.session_state.records)
        _warning, _projected = check_precursor_warning(_df_live)

        _row["warning_fired"]     = _warning
        _row["projected_latency"] = _projected

        # Build event log entry
        _ts = datetime.now().strftime("%H:%M:%S")
        if _warning:
            _cls = "log-warn"
            _msg = (
                f"[{_ts}]  PRECURSOR_WARNING  "
                f"tick={_i:>3}  lat={_row['latency_ms']:>7.2f} ms  "
                f"proj={_projected:>7.1f} ms"
            )
        else:
            _cls = "log-ok"
            _msg = (
                f"[{_ts}]  OK                 "
                f"tick={_i:>3}  lat={_row['latency_ms']:>7.2f} ms  "
                f"phase={_row['phase']}"
            )
        st.session_state.event_log.append((_cls, _msg))

        # Fetch AI advice exactly once on the first PRECURSOR_WARNING tick
        if _warning and not st.session_state.warning_shown:
            st.session_state.warning_shown = True
            _alert_type = (
                "HIGH_LATENCY"
                if _row["latency_ms"] >= WARNING_THRESHOLD * 0.65
                else "PACKET_LOSS"
            )
            with st.spinner("🤖  Querying local phi3 — fetching remediation advice..."):
                st.session_state.advice = get_remediation_advice(
                    _alert_type,
                    {
                        "latency_ms":      _row["latency_ms"],
                        "packet_loss_pct": _row["packet_loss_pct"],
                        "jitter_ms":       _row["jitter_ms"],
                        "phase":           _row["phase"],
                    },
                )
            st.session_state.event_log.append((
                "log-warn",
                f"[{_ts}]  AI advice fetched  alert={_alert_type}  "
                f"status={st.session_state.advice.get('status','?')}",
            ))

        st.session_state.loop_idx += 1


# =============================================================================
#  Derive display state from accumulated records
# =============================================================================
_records = st.session_state.records
_df      = pd.DataFrame(_records) if _records else pd.DataFrame(
    columns=["latency_ms", "packet_loss_pct", "jitter_ms", "phase", "warning_fired", "projected_latency"]
)
_latest        = _df.iloc[-1].to_dict() if not _df.empty else {}
_warning_now   = bool(_latest.get("warning_fired", False))
_projected_now = _latest.get("projected_latency", float("nan"))
_phase_now     = _latest.get("phase", "—")
_lat_now       = float(_latest.get("latency_ms", 0))
_loss_now      = float(_latest.get("packet_loss_pct", 0))
_jit_now       = float(_latest.get("jitter_ms", 0))
_loop_now      = int(_latest.get("loop", -1)) + 1
_warn_count    = int(_df["warning_fired"].sum()) if "warning_fired" in _df.columns else 0


# =============================================================================
#  Status Banner
# =============================================================================
if not _records:
    st.markdown("""
    <div class="status-ready">
      <h2>⚡  SYSTEM READY &nbsp;—&nbsp; PRESS START TO BEGIN SIMULATION</h2>
    </div>""", unsafe_allow_html=True)

elif _warning_now:
    import math
    _proj_str = (
        f"  ·  Projected latency in {LOOKAHEAD} intervals: <b>{_projected_now:.1f} ms</b>"
        if not math.isnan(_projected_now) else ""
    )
    st.markdown(f"""
    <div class="status-critical">
      <h2>🚨&nbsp; CRITICAL: DEGRADATION PREDICTED</h2>
      <p>PRECURSOR_WARNING ACTIVE &nbsp;·&nbsp; Breach of <b>{WARNING_THRESHOLD:.0f} ms</b>
         threshold is imminent{_proj_str}</p>
    </div>""", unsafe_allow_html=True)

elif st.session_state.warning_shown:
    st.markdown("""
    <div class="status-elevated">
      <h2>⚠️&nbsp; ELEVATED RISK &nbsp;—&nbsp; MONITORING CLOSELY</h2>
      <p>Warning condition was active — trend is being tracked</p>
    </div>""", unsafe_allow_html=True)

else:
    _tick_str = f"Tick {_loop_now} / {st.session_state.total_loops}"
    st.markdown(f"""
    <div class="status-healthy">
      <h2>✅&nbsp; NETWORK HEALTHY &nbsp;—&nbsp; ALL SYSTEMS NOMINAL</h2>
      <p>{_tick_str} &nbsp;·&nbsp; No anomalies detected</p>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# =============================================================================
#  Metric Cards Row
# =============================================================================
def _color(val: float, warn: float, crit: float) -> str:
    if val >= crit:  return "#ef4444"
    if val >= warn:  return "#f59e0b"
    return "#10b981"

_c1, _c2, _c3, _c4 = st.columns(4)

with _c1:
    _col = _color(_lat_now, WARNING_THRESHOLD * 0.5, WARNING_THRESHOLD)
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:{_col}">
        {_lat_now:.1f}<span class="metric-unit"> ms</span>
      </div>
      <div class="metric-label">Latency</div>
      <div class="metric-sub">Warn at {WARNING_THRESHOLD:.0f} ms</div>
    </div>""", unsafe_allow_html=True)

with _c2:
    _col = _color(_loss_now, 2.0, 5.0)
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:{_col}">
        {_loss_now:.2f}<span class="metric-unit"> %</span>
      </div>
      <div class="metric-label">Packet Loss</div>
      <div class="metric-sub">Warn at 2.00 %</div>
    </div>""", unsafe_allow_html=True)

with _c3:
    _col = _color(_jit_now, 15.0, 40.0)
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:{_col}">
        {_jit_now:.1f}<span class="metric-unit"> ms</span>
      </div>
      <div class="metric-label">Jitter</div>
      <div class="metric-sub">Warn at 15 ms</div>
    </div>""", unsafe_allow_html=True)

with _c4:
    _phase_col = (
        "#10b981" if _phase_now == "HEALTHY"
        else "#ef4444" if _phase_now == "DEGRADING"
        else "#475569"
    )
    _running_dot = (
        '<span style="color:#22c55e;animation:none">&#9679;</span>&nbsp;'
        if st.session_state.running else
        '<span style="color:#475569">&#9632;</span>&nbsp;'
    )
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:{_phase_col};font-size:1.2rem;margin-top:4px">
        {_phase_now}
      </div>
      <div class="metric-label">{_running_dot}Phase</div>
      <div class="metric-sub">
        Tick {_loop_now}/{st.session_state.total_loops} &nbsp;·&nbsp; {_warn_count} warning(s)
      </div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# =============================================================================
#  Live Line Charts
# =============================================================================
_ch1, _ch2 = st.columns(2)

with _ch1:
    st.markdown(
        '<div class="chart-header">📈 Latency <span class="chart-label-accent">(ms)</span>'
        f' &nbsp;—&nbsp; {WARNING_THRESHOLD:.0f} ms warning threshold shown</div>',
        unsafe_allow_html=True,
    )
    if not _df.empty:
        _chart_lat = pd.DataFrame({
            "Latency (ms)":        _df["latency_ms"].values,
            "Warning Threshold":   [WARNING_THRESHOLD] * len(_df),
        })
        st.line_chart(_chart_lat, color=["#63b3ed", "#ef4444"], height=230)
    else:
        st.markdown(
            '<div style="height:230px;display:flex;align-items:center;justify-content:center;'
            'color:#1e293b;font-size:0.8rem">Awaiting telemetry…</div>',
            unsafe_allow_html=True,
        )

with _ch2:
    st.markdown(
        '<div class="chart-header">📉 Packet Loss <span class="chart-label-accent">(%)</span>'
        ' &nbsp;&amp;&nbsp; Jitter <span class="chart-label-accent">(ms)</span></div>',
        unsafe_allow_html=True,
    )
    if not _df.empty:
        _chart_loss = pd.DataFrame({
            "Packet Loss (%)": _df["packet_loss_pct"].values,
            "Jitter (ms)":     _df["jitter_ms"].values,
        })
        st.line_chart(_chart_loss, color=["#f59e0b", "#a78bfa"], height=230)
    else:
        st.markdown(
            '<div style="height:230px;display:flex;align-items:center;justify-content:center;'
            'color:#1e293b;font-size:0.8rem">Awaiting telemetry…</div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)


# =============================================================================
#  AI Remediation Advice  +  Telemetry Event Log
# =============================================================================
_adv_col, _log_col = st.columns([3, 2])

with _adv_col:
    st.markdown('<div class="section-title">🤖 AI Remediation Advice — Local phi3 Model</div>',
                unsafe_allow_html=True)
    _advice = st.session_state.advice

    if _advice is None and not st.session_state.warning_shown:
        # Idle state
        st.markdown("""
        <div class="advice-wrap advice-idle">Monitoring network telemetry stream...
No PRECURSOR_WARNING detected yet.

Advice will appear here automatically when the predictive tracker
projects a breach of the 150 ms latency threshold.</div>""",
            unsafe_allow_html=True)

    elif _advice is None:
        # Fetching (spinner shown during actual call above)
        st.markdown("""<div class="advice-wrap">
<span style="color:#63b3ed">Querying phi3 model — please wait...</span></div>""",
            unsafe_allow_html=True)

    elif _advice.get("status") == "OK":
        _meta = (
            f"phi3  ·  Alert: {_advice.get('alert','?')}  ·  "
            f"{_advice.get('context_chars','?')} chars of runbook context injected  ·  "
            f"Fetched at first PRECURSOR_WARNING"
        )
        _txt = _advice.get("advice", "")
        st.markdown(f"""
        <div class="advice-wrap">
          <div class="advice-meta">{_meta}</div>{_txt}
        </div>""", unsafe_allow_html=True)

    else:
        # Graceful offline fallback
        _meta    = f"STATUS: {_advice.get('status','?')}"
        _reason  = _advice.get("reason", "")
        _txt     = _advice.get("advice", "")
        st.markdown(f"""
        <div class="advice-wrap advice-offline">
          <div class="advice-meta advice-meta-offline">{_meta}  ·  {_reason}</div>{_txt}
        </div>""", unsafe_allow_html=True)


with _log_col:
    st.markdown('<div class="section-title">📋 Telemetry Event Log</div>',
                unsafe_allow_html=True)
    _logs = st.session_state.event_log
    if _logs:
        # Show most-recent 35 entries, newest at top
        _log_html = "\n".join(
            f'<div class="{cls}">{msg}</div>'
            for cls, msg in reversed(_logs[-35:])
        )
        st.markdown(f'<div class="log-panel">{_log_html}</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="log-panel"><span style="color:#1e293b">No events yet.</span></div>',
            unsafe_allow_html=True,
        )


# =============================================================================
#  Progress Bar
# =============================================================================
st.markdown("<br>", unsafe_allow_html=True)
if _records:
    _prog = min(len(_records) / max(st.session_state.total_loops, 1), 1.0)
    _prog_label = (
        f"Simulation complete — {len(_records)} ticks"
        if not st.session_state.running and len(_records) >= st.session_state.total_loops
        else f"Simulating: tick {len(_records)} / {st.session_state.total_loops}"
    )
    st.progress(_prog, text=_prog_label)


# =============================================================================
#  Footer
# =============================================================================
st.markdown("""
<div style="text-align:center;font-size:0.68rem;color:#1e293b;padding:20px 0 8px;letter-spacing:0.04em;">
  Air-Gapped NOC Copilot &nbsp;·&nbsp; Phase 3 &nbsp;·&nbsp;
  All inference runs locally on phi3 via Ollama &nbsp;·&nbsp; No internet connection required
</div>
""", unsafe_allow_html=True)


# =============================================================================
#  Live Loop Driver — sleep then trigger next tick via st.rerun()
#  (Must be last, after all UI elements are rendered)
# =============================================================================
if st.session_state.running:
    time.sleep(st.session_state.tick)
    st.rerun()
