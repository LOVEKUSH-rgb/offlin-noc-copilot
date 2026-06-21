# 📘 NOC Operator Runbook — Air-Gapped MPLS Network
**Version:** 1.0  
**Last Updated:** 2026-06-21  
**Classification:** Internal Operations  
**Scope:** MPLS Core & Edge Network Telemetry Anomaly Response

---

## Table of Contents

1. [SOP-001: High Latency Spikes](#sop-001-high-latency-spikes)
2. [SOP-002: Severe Packet Loss](#sop-002-severe-packet-loss)
3. [Escalation Matrix](#escalation-matrix)
4. [Glossary](#glossary)

---

## SOP-001: High Latency Spikes

**Trigger Condition:** RTT or one-way latency exceeds **150 ms** on any MPLS Label Switched Path (LSP), or the AI Copilot raises a `PRECURSOR_WARNING` flag.  
**Severity:** P2 – High  
**Owner:** NOC Tier-2 Engineer  
**SLA:** Acknowledge within 5 min · Mitigate within 30 min

---

### 🔍 Step 1 — Confirm the Alert

```bash
# Pull live latency snapshot from the monitoring stack
show mpls traffic-eng tunnels brief
ping mpls pseudowire <pw-id> repeat 50 timeout 2
```

- Confirm the alert is **not a false positive** (single packet anomaly vs. sustained trend).
- Check if the `PRECURSOR_WARNING` was raised for **≥ 2 consecutive intervals** before acting.
- Cross-reference with **baseline dashboard**: normal RTT should be `< 30 ms`.

> **Checkpoint:** If latency is transient (< 3 readings) and self-recovered, log the event and move to **Monitoring** status. No further action required.

---

### 🗺️ Step 2 — Isolate the Affected Segment

```bash
# Identify the LSP with the highest latency
show mpls traffic-eng tunnels tabular | include Latency
traceroute mpls traffic-eng tunnel <tunnel-id> source <loopback>
```

1. Record the **hop where latency first blooms** in the traceroute output.
2. Check interface statistics on that hop:

```bash
show interface <int-id> | include error|input|output|drop
show mpls ldp neighbor <peer-ip> detail
```

3. Identify if congestion is **on-net** (router queue depth) or **off-net** (transport/WAN).

---

### ⚙️ Step 3 — Remediate

| Root Cause | Action |
|---|---|
| **Queue congestion on P router** | Apply DSCP re-marking; trigger RSVP-TE pre-emption on lower-priority LSPs |
| **Physical interface errors** | Run `loopback internal` test; escalate to field team if BER > 10⁻⁶ |
| **MPLS forwarding table mismatch** | `clear mpls forwarding-table` on affected node — **warn NOC lead first** |
| **WAN provider degradation** | Open provider ticket; failover traffic to secondary LSP if available |
| **CPU/memory spike on router** | Check `show processes cpu sorted` · kill rogue process or reload standby RP |

```bash
# Force traffic to backup LSP
mpls traffic-eng reoptimize tunnel <tunnel-id>

# Verify RSVP bandwidth reservation post-change
show mpls traffic-eng link-management bandwidth-allocation
```

---

### ✅ Step 4 — Verify & Close

```bash
ping mpls pseudowire <pw-id> repeat 100 timeout 2
show mpls traffic-eng tunnels brief | include <tunnel-id>
```

- Confirm **RTT < 30 ms** for at least **5 consecutive polling intervals**.
- Ensure `PRECURSOR_WARNING` is no longer firing in the AI copilot output.
- Update the incident ticket with root cause, action taken, and resolution time.
- If issue recurs within 24 hours → escalate to **P1** and engage vendor TAC.

---

## SOP-002: Severe Packet Loss

**Trigger Condition:** Packet loss exceeds **5%** on any monitored LSP or customer VPN, or jitter exceeds **50 ms**.  
**Severity:** P1 – Critical  
**Owner:** NOC Tier-2 / Tier-3 Engineer  
**SLA:** Acknowledge within 2 min · Mitigate within 15 min

---

### 🔍 Step 1 — Confirm & Quantify the Loss

```bash
# Run extended ping to measure loss percentage
ping <destination-ip> repeat 500 size 1500 timeout 2

# Check interface-level drop counters
show interface <int-id> counters errors
show interface <int-id> | include drops|input errors|output errors
```

- Distinguish between **random loss** (hardware/noise) and **burst loss** (congestion or loop).
- Check if loss is **unidirectional** (asymmetric routing) or **bidirectional** (physical link).

```bash
# Bidirectional confirmation
ip sla <sla-id> type udp-jitter dest-addr <ip> dest-port 5000 num-packets 100
show ip sla statistics <sla-id>
```

> **Checkpoint:** Loss < 1% and not escalating → monitor for 10 minutes. Loss ≥ 5% → proceed immediately.

---

### 🗺️ Step 2 — Trace the Drop Point

```bash
# Extended traceroute with loss measurement
traceroute <destination> probe 5 timeout 2 ttl 1 30

# Check MPLS OAM for LSP integrity
ping mpls ipv4 <prefix/mask> repeat 100 exp 6
```

1. Identify the **exact hop** where packet count drops (< 100% receipt rate in traceroute).
2. Check for **microbursts** on that interface:

```bash
show interface <int-id> counters | include input queue|output queue
show queue <int-id>
```

3. Inspect the **FIB/CEF** for black-holing:

```bash
show ip cef <destination-ip> detail
show mpls forwarding-table <prefix> detail
```

---

### ⚙️ Step 3 — Remediate

| Root Cause | Action |
|---|---|
| **Output queue drops (congestion)** | Increase queue depth or apply CBWFQ / LLQ QoS policy to prioritize critical traffic |
| **CEF/FIB black-hole** | `no ip cef` → re-enable; or `clear ip cef <prefix>` |
| **Duplex/speed mismatch** | Force speed/duplex to match on both ends; check for CRC errors |
| **SFP / optic degradation** | Check `show interface transceiver detail` for Rx power; replace SFP if Rx < -23 dBm |
| **MPLS label loop** | `debug mpls packets` (brief); check TTL expiry in forwarding table |
| **Link flapping** | `show log | include flap|down|up` — apply dampening; open physical ticket |

```bash
# Apply emergency QoS to protect real-time traffic (voice/video)
policy-map EMERGENCY-LLQ
  class VOIP
    priority 512
  class class-default
    fair-queue

interface <int-id>
  service-policy output EMERGENCY-LLQ
```

```bash
# If physical issue confirmed — initiate failover
no shutdown interface <backup-int>
ip route <prefix> <backup-next-hop> 10   ! floating static for instant failover
```

---

### ✅ Step 4 — Verify & Close

```bash
# Post-fix validation
ping <destination-ip> repeat 500 size 1500 timeout 2
show ip sla statistics <sla-id> | include Packet Loss
show interface <int-id> counters errors
```

- Confirm **loss ≤ 0.1%** across **3 successive ping runs**.
- Confirm **jitter < 10 ms** for voice-class traffic.
- Verify the AI Copilot simulation shows `HEALTHY` phase restored in telemetry stream.
- File a **Post-Incident Report (PIR)** within 4 hours of resolution.
- Schedule a **root-cause review** within 48 hours.

---

## Escalation Matrix

| Tier | Role | Contact Method | Trigger |
|---|---|---|---|
| T1 NOC | First Responder | Phone / Chat | Any alert fires |
| T2 NOC | Network Engineer | PagerDuty | T1 cannot isolate within 10 min |
| T3 / Core | Senior Network Architect | Phone (24/7 hotline) | P1 unresolved after 15 min |
| Vendor TAC | Cisco / Nokia TAC | Ticket + Phone | Hardware confirmed faulty |
| Management | NOC Manager | Email + SMS | Customer-impacting > 30 min |

---

## Glossary

| Term | Definition |
|---|---|
| **LSP** | Label Switched Path — the virtual circuit through an MPLS network |
| **RTT** | Round-Trip Time — time for a packet to travel to a destination and back |
| **RSVP-TE** | Resource Reservation Protocol — Traffic Engineering extension |
| **FIB** | Forwarding Information Base — the router's active forwarding table |
| **CEF** | Cisco Express Forwarding — hardware-accelerated packet switching |
| **BER** | Bit Error Rate — ratio of error bits to total transmitted bits |
| **DSCP** | Differentiated Services Code Point — QoS marking in IP header |
| **CBWFQ** | Class-Based Weighted Fair Queuing — QoS scheduling mechanism |
| **LLQ** | Low Latency Queuing — strict priority queue for real-time traffic |
| **SFP** | Small Form-factor Pluggable — optical transceiver module |
| **PIR** | Post-Incident Report — formal documentation of incident and resolution |
