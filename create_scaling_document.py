#!/usr/bin/env python3
"""
Generate a comprehensive, beautifully styled, enterprise-grade Word document (.docx)
detailing the 10,000+ Devices Scaling Architecture and Phase-by-Phase Upgrade Roadmap
for the InHydro IoT Device Management Platform.
"""

import os
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

DOCX_OUTPUT_PATH = r"c:\Users\anujk\Desktop\iot_inhydro_device\InHydro_10000_Devices_Architecture_and_Upgrade_Plan.docx"

# Helper for XML cell shading
def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

# Helper for cell padding/margins
def set_cell_margins(cell, top=120, bottom=120, left=160, right=160):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def add_callout_box(doc, title, text, border_hex="0284C7", bg_hex="F0F9FF"):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, bg_hex)
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)
    
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="none"/>'
        f'<w:left w:val="single" w:sz="36" w:space="0" w:color="{border_hex}"/>'
        f'<w:bottom w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    r_t = p.add_run(f"📌 {title}\n")
    r_t.font.name = "Arial"
    r_t.font.size = Pt(10)
    r_t.font.bold = True
    r_t.font.color.rgb = RGBColor(15, 23, 42)
    
    r_b = p.add_run(text)
    r_b.font.name = "Arial"
    r_b.font.size = Pt(9.5)
    r_b.font.color.rgb = RGBColor(51, 65, 85)
    doc.add_paragraph().paragraph_format.space_after = Pt(6)

def style_row_header(row, col_titles, bg_hex="0F172A", text_color=RGBColor(255, 255, 255)):
    for i, title in enumerate(col_titles):
        cell = row.cells[i]
        set_cell_background(cell, bg_hex)
        set_cell_margins(cell, top=120, bottom=120, left=140, right=140)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(title)
        r.font.name = "Arial"
        r.font.size = Pt(9)
        r.font.bold = True
        r.font.color.rgb = text_color

def style_row_data(row, values, is_even=False):
    bg_hex = "F8FAFC" if is_even else "FFFFFF"
    for i, val in enumerate(values):
        cell = row.cells[i]
        set_cell_background(cell, bg_hex)
        set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(val)
        r.font.name = "Arial"
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(30, 41, 59)

def main():
    doc = Document()
    
    # Page setup: Margins
    for section in doc.sections:
        section.top_margin = Inches(0.7)
        section.bottom_margin = Inches(0.7)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)
        
    # -------------------------------------------------------------------------
    # DOCUMENT COVER / HEADER
    # -------------------------------------------------------------------------
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(3)
    r_title = p_title.add_run("INHYDRO IOT ENTERPRISE PLATFORM")
    r_title.font.name = "Arial"
    r_title.font.size = Pt(22)
    r_title.font.bold = True
    r_title.font.color.rgb = RGBColor(15, 23, 42) # Slate-900

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(10)
    r_sub = p_sub.add_run("10,000+ Real-Time Concurrent Devices: Full-Stack Architecture, Performance Optimization & Upgrade Roadmap")
    r_sub.font.name = "Arial"
    r_sub.font.size = Pt(12)
    r_sub.font.bold = True
    r_sub.font.color.rgb = RGBColor(16, 185, 129) # Emerald-600

    # Executive Metadata Table
    meta_table = doc.add_table(rows=2, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_headers = [
        ("Platform Target", "10,000+ Concurrent IoT Devices"),
        ("Throughput Goal", "5,000 Telemetry Msg/sec"),
        ("Frontend Latency", "60 FPS Zero-Lag Virtualized UI"),
        ("Document Status", "Engineering Upgrade Plan v3.0")
    ]
    for i, (k, v) in enumerate(meta_headers):
        ck = meta_table.cell(0, i)
        cv = meta_table.cell(1, i)
        set_cell_background(ck, "0F172A")
        set_cell_background(cv, "F1F5F9")
        set_cell_margins(ck, 80, 80, 100, 100)
        set_cell_margins(cv, 80, 80, 100, 100)
        
        pk = ck.paragraphs[0]
        pk.paragraph_format.space_after = Pt(0)
        rk = pk.add_run(k)
        rk.font.name = "Arial"
        rk.font.size = Pt(8)
        rk.font.bold = True
        rk.font.color.rgb = RGBColor(255, 255, 255)
        
        pv = cv.paragraphs[0]
        pv.paragraph_format.space_after = Pt(0)
        rv = pv.add_run(v)
        rv.font.name = "Arial"
        rv.font.size = Pt(8)
        rv.font.color.rgb = RGBColor(30, 41, 59)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # -------------------------------------------------------------------------
    # SECTION 1: EXECUTIVE SUMMARY & OBJECTIVES
    # -------------------------------------------------------------------------
    h1 = doc.add_heading(level=1)
    r_h1 = h1.add_run("1. Executive Summary & Core Engineering Objectives")
    r_h1.font.name = "Arial"
    r_h1.font.color.rgb = RGBColor(15, 23, 42)
    
    p = doc.add_paragraph()
    p.add_run(
        "Current system successfully operates agricultural controllers (Almora, Monit, Cold Storage, ITC Polyhouse) "
        "across tens to hundreds of devices. However, scaling the platform to 10,000 active devices generating telemetry "
        "every 2 to 5 seconds produces massive data velocity: approximately 2,000 to 5,000 telemetry messages per second, "
        "totaling 170 to 430 million data points daily. Without an enterprise architectural transformation, standard single-node "
        "Express/MongoDB backends and browser DOM rendering will suffer severe bottlenecks (100% CPU lock, memory leaks, dropped packets, and browser tab freezes).\n\n"
        "This specification establishes the blueprint for an ultra-high-throughput, zero-lag edge-to-cloud ecosystem that ensures smooth "
        "60 FPS frontend performance, sub-100ms API responses, and resilient distributed telemetry ingestion under 10,000+ active devices."
    )
    
    add_callout_box(
        doc,
        "CORE PERFORMANCE BENCHMARKS (10,000 DEVICES TARGET)",
        "• Network Ingress: 5,000 packets/second (~5–10 MB/sec stream ingress).\n"
        "• Database Write Optimization: 90% reduction in disk I/O through in-memory micro-batching.\n"
        "• Client DOM Footprint: Constant 15–20 DOM nodes rendered regardless of 10,000 list items.\n"
        "• Client Memory Ceiling: < 85 MB RAM usage on browser tabs.\n"
        "• Historical Query Speed: < 150 ms query times across 60 days of data via automated downsampling.",
        border_hex="059669", bg_hex="ECFDF5"
    )

    # -------------------------------------------------------------------------
    # SECTION 2: BOTTLENECK AUDIT (CURRENT VS 10K LOAD)
    # -------------------------------------------------------------------------
    h2 = doc.add_heading(level=1)
    r_h2 = h2.add_run("2. Current System Bottleneck Audit vs. 10,000 Devices Load")
    r_h2.font.name = "Arial"
    r_h2.font.color.rgb = RGBColor(15, 23, 42)

    p = doc.add_paragraph()
    p.add_run(
        "The following engineering table outlines the fundamental constraints of the current architecture when subjected "
        "to 10,000 devices and details the precise technical remediation required:"
    )

    tbl_audit = doc.add_table(rows=7, cols=4)
    tbl_audit.alignment = WD_TABLE_ALIGNMENT.CENTER
    col_widths = [1.2, 1.8, 1.8, 2.2]
    
    style_row_header(tbl_audit.rows[0], ["Architectural Layer", "Current Mechanism", "Failure Point @ 10,000 Devices", "Enterprise Upgrade Target"])
    
    audit_data = [
        ("Real-time Broadcast", "Global Server-Sent Events (SSE) broadcasting all device packets to all clients.", "5,000 events/sec sent to every browser tab. Immediate browser memory bloat and total tab crash.", "Channel & Room-based WebSockets. Clients subscribe exclusively to viewport-visible devices (20–50 items)."),
        ("Database Writes", "Direct Mongoose single-document save() / updateOne() per MQTT message.", "5,000 distinct write locks/sec. MongoDB disk I/O queues overflow; severe connection pool exhaustion.", "In-memory 500ms Micro-Batch Buffer with bulkWrite() / insertMany() + MongoDB Time-Series collection."),
        ("Live State Tracking", "Updating device live stats and heartbeat directly in MongoDB on every packet.", "Massive database write amplification and index thrashing for ephemeral real-time numbers.", "Redis Cluster In-Memory Hot State (HSET device:id). Sub-millisecond lookups; zero MongoDB load."),
        ("Frontend DOM Tree", "Rendering hundreds/thousands of individual React DOM Card and Table nodes.", "DOM node count reaches 40,000+. Browser layout recalculations and garbage collection freeze UI.", "Virtual Scrolling (@tanstack/react-virtual). DOM maintains exactly 15–20 cards regardless of list size."),
        ("Client State Lookup", "Array searches (devices.find(), devices.map()) across state lists.", "Iterating 10,000-element arrays on every incoming packet blocks JavaScript main thread.", "Normalized State Dictionary (devicesById[id]) providing instant O(1) constant-time updates."),
        ("Historical Analytics", "Querying raw telemetry collections on demand with heavy in-memory filtering.", "Scanning millions of uncompressed records causes 504 Gateway Timeouts and heavy RAM usage.", "Pre-computed automated rollup tables (1-min, 1-hour) + LTTB (Largest-Triangle-Three-Buckets) downsampling.")
    ]
    for idx, row_vals in enumerate(audit_data):
        style_row_data(tbl_audit.rows[idx+1], row_vals, is_even=(idx%2==1))
        
    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # -------------------------------------------------------------------------
    # SECTION 3: TARGET ENTERPRISE ARCHITECTURE BLUEPRINT
    # -------------------------------------------------------------------------
    h3 = doc.add_heading(level=1)
    r_h3 = h3.add_run("3. Target Enterprise Architecture Blueprint")
    r_h3.font.name = "Arial"
    r_h3.font.color.rgb = RGBColor(15, 23, 42)

    p = doc.add_paragraph()
    p.add_run(
        "To achieve seamless linear scalability, the system transitions to a multi-tiered decoupled architecture. "
        "The edge ingestion, state caching, persistence storage, and client distribution layers operate independently:\n"
    )

    arch_points = [
        ("Tier 1: Edge & Clustered MQTT Layer", "10,000 devices communicate over MQTT with Keep-Alive to an EMQX or NanoMQ clustered broker capable of handling 1,000,000+ concurrent connections."),
        ("Tier 2: Ingestion Stream & In-Memory Hot Cache", "Worker threads consume MQTT packets, immediately update Redis Cluster in-memory key-value state (<0.5ms), and push historical payloads to an in-memory batching queue."),
        ("Tier 3: Database Persistence Engine", "A dedicated DB Worker flushes batched payloads every 500ms via MongoDB bulkWrite() into native Time-Series collections with automated 90-day TTL data retention."),
        ("Tier 4: Selective Real-Time Pub/Sub Gateway", "WebSocket Gateway (Socket.io with Redis Adapter) partitions real-time traffic into granular rooms. Operators only receive live updates for devices currently rendered on screen."),
        ("Tier 5: Virtualized Ultra-Responsive Frontend", "React frontend utilizes virtual scrolling, normalized O(1) dictionary stores, background Web Worker stream decoders, and Canvas-based trend charts running at locked 60 FPS.")
    ]
    for t_title, t_desc in arch_points:
        p_t = doc.add_paragraph()
        p_t.paragraph_format.left_indent = Inches(0.2)
        p_t.paragraph_format.space_after = Pt(3)
        r_tt = p_t.add_run(f"• {t_title}: ")
        r_tt.font.name = "Arial"
        r_tt.font.size = Pt(9.5)
        r_tt.font.bold = True
        r_tt.font.color.rgb = RGBColor(15, 23, 42)
        r_td = p_t.add_run(t_desc)
        r_td.font.name = "Arial"
        r_td.font.size = Pt(9.5)
        r_td.font.color.rgb = RGBColor(71, 85, 105)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # -------------------------------------------------------------------------
    # SECTION 4: PHASE 1 - REAL-TIME COMMUNICATION UPGRADE
    # -------------------------------------------------------------------------
    h4 = doc.add_heading(level=1)
    r_h4 = h4.add_run("4. Phase 1: Real-Time Communication & Viewport Subscriptions")
    r_h4.font.name = "Arial"
    r_h4.font.color.rgb = RGBColor(15, 23, 42)

    p = doc.add_paragraph()
    p.add_run(
        "The single most critical vulnerability at scale is indiscriminate packet broadcasting. "
        "Phase 1 eliminates global broadcasting by implementing Viewport-Aware Room Subscriptions:\n"
    )

    add_callout_box(
        doc,
        "PHASE 1 CORE MECHANISM: VIEWPORT SUBSCRIPTION",
        "1. When an operator opens the Devices page displaying 24 items per page, the frontend client emits:\n"
        "   socket.emit('subscribe_viewport', ['DEV_001', 'DEV_002', ..., 'DEV_024'])\n"
        "2. The WebSocket server joins the socket only to those specific 24 rooms.\n"
        "3. Telemetry arriving from the remaining 9,976 devices is discarded for this connection.\n"
        "4. When the user changes pagination, sorts, or filters, previous rooms are unsubscribed and new rooms registered.\n"
        "5. Network and CPU consumption on the client drops from 5,000 msgs/sec down to 10–20 msgs/sec (99.6% reduction).",
        border_hex="0284C7", bg_hex="F0F9FF"
    )

    p_delta = doc.add_paragraph()
    p_delta.add_run(
        "Additionally, Delta Payload Compression is implemented. Instead of repeating full static metadata (client name, location code, model, unit) "
        "in every packet, telemetry frames only transmit changed dynamic values: "
    )
    r_code = p_delta.add_run('{"id":"PH-01","t":24.5,"h":68.2,"p":1}')
    r_code.font.name = "Consolas"
    r_code.font.size = Pt(8.5)
    r_code.font.color.rgb = RGBColor(16, 185, 129)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # -------------------------------------------------------------------------
    # SECTION 5: PHASE 2 - INGESTION PIPELINE & DB BATCHING
    # -------------------------------------------------------------------------
    h5 = doc.add_heading(level=1)
    r_h5 = h5.add_run("5. Phase 2: Ingestion Pipeline Micro-Batching & Hot State Caching")
    r_h5.font.name = "Arial"
    r_h5.font.color.rgb = RGBColor(15, 23, 42)

    p = doc.add_paragraph()
    p.add_run(
        "Phase 2 isolates the MongoDB disk engine from high-frequency telemetry writes:\n\n"
        "1. Redis In-Memory Hot State Engine:\n"
        "   Every incoming telemetry frame updates a Redis Hash key (device:{id}). Live status, current temperature, humidity, "
        "   active relays, and heartbeat timestamps reside exclusively in RAM. REST endpoints such as GET /api/devices or GET /api/devices/:id/live "
        "   query Redis directly, returning in under 2ms without querying MongoDB.\n\n"
        "2. Micro-Batch Database Persistence Buffer:\n"
        "   Historical telemetry frames are appended to an in-memory sliding buffer. A flush trigger executes every 500ms or when the buffer "
        "   reaches 500 documents, issuing a single MongoDB insertMany() operation. This collapses 5,000 distinct disk operations into 10 bulk writes per second, "
        "   reducing disk I/O load by 99%.\n\n"
        "3. Native MongoDB Time-Series Collections:\n"
        "   The telemetry collection transitions to MongoDB native Time-Series format with secondary compound indexes on { deviceId: 1, created_at: -1 } "
        "   and an automated 90-day TTL expiration, ensuring database size stays constant and deterministic."
    )

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # -------------------------------------------------------------------------
    # SECTION 6: PHASE 3 - FRONTEND ZERO-LAG VIRTUALIZATION ENGINE
    # -------------------------------------------------------------------------
    h6 = doc.add_heading(level=1)
    r_h6 = h6.add_run("6. Phase 3: Frontend Zero-Lag Virtualization & Rendering")
    r_h6.font.name = "Arial"
    r_h6.font.color.rgb = RGBColor(15, 23, 42)

    p = doc.add_paragraph()
    p.add_run(
        "Phase 3 guarantees that the browser interface never drops frames, stutters, or leaks memory even when navigating 10,000 devices:\n"
    )

    f_points = [
        ("DOM Virtualization (@tanstack/react-virtual)", "Replaces standard map() rendering on DevicesPage and LiveMonitoring. The virtualizer calculates scroll offset and renders only the 15 to 25 items within the visible viewport. Total DOM nodes remain permanently capped below 100."),
        ("Normalized State Store", "Migrates frontend state from arrays to a normalized dictionary object (devicesById). Packet updates execute as O(1) direct property assignments, eliminating costly array traversals."),
        ("Background Web Worker", "Incoming WebSocket binary/JSON packets are offloaded to a dedicated Web Worker thread (telemetryWorker.js). Parsing, unit conversions, and threshold alarm checks occur off the main thread, keeping UI interactions fluid at 60 FPS."),
        ("Canvas / WebGL Trend Charts", "For multi-device or dense historical charting, heavy SVG DOM nodes (Recharts) are upgraded to Canvas-based rendering (uPlot or ECharts with LTTB decimation), rendering 100,000 data points in under 15ms.")
    ]
    for f_title, f_desc in f_points:
        p_f = doc.add_paragraph()
        p_f.paragraph_format.left_indent = Inches(0.2)
        p_f.paragraph_format.space_after = Pt(3)
        r_ft = p_f.add_run(f"• {f_title}: ")
        r_ft.font.name = "Arial"
        r_ft.font.size = Pt(9.5)
        r_ft.font.bold = True
        r_ft.font.color.rgb = RGBColor(15, 23, 42)
        r_fd = p_f.add_run(f_desc)
        r_fd.font.name = "Arial"
        r_fd.font.size = Pt(9.5)
        r_fd.font.color.rgb = RGBColor(71, 85, 105)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # -------------------------------------------------------------------------
    # SECTION 7: PHASE 4 - ANALYTICS DOWNSAMPLING & PRE-AGGREGATION
    # -------------------------------------------------------------------------
    h7 = doc.add_heading(level=1)
    r_h7 = h7.add_run("7. Phase 4: Automated Downsampling & Rollup Aggregation Pipeline")
    r_h7.font.name = "Arial"
    r_h7.font.color.rgb = RGBColor(15, 23, 42)

    p = doc.add_paragraph()
    p.add_run(
        "A fleet of 10,000 devices creates over 1 billion records every 3 days. Querying raw data for a 7-day or 30-day analytics report "
        "would crash server memory. Phase 4 establishes an automated multi-tier aggregation pipeline:\n\n"
        "1. 1-Minute & 1-Hour Rollup Pipeline:\n"
        "   Scheduled background aggregation workers summarize raw points into 1-minute averages (Avg, Min, Max Temp/Humidity/CO2) and 1-hour rolls. "
        "   1-minute rollups retain for 30 days; 1-hour rollups retain for 2 years.\n\n"
        "2. LTTB (Largest-Triangle-Three-Buckets) Visual Downsampling:\n"
        "   When rendering trend charts on the frontend, the analytics API reduces query payloads to exactly 500 visual data points "
        "   using the mathematical LTTB algorithm. Peak excursions and anomalies are 100% preserved while bandwidth drops by 98%.\n\n"
        "3. Streaming File Exports:\n"
        "   CSV/Excel exports utilize Node.js readable streams piped directly to HTTP response buffers, preventing server out-of-memory crashes during multi-million-row exports."
    )

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # -------------------------------------------------------------------------
    # SECTION 8: PHASE 5 - CLUSTERING, INFRASTRUCTURE & DEVOPS
    # -------------------------------------------------------------------------
    h8 = doc.add_heading(level=1)
    r_h8 = h8.add_run("8. Phase 5: High-Availability Clustering & DevOps Infrastructure")
    r_h8.font.name = "Arial"
    r_h8.font.color.rgb = RGBColor(15, 23, 42)

    tbl_infra = doc.add_table(rows=6, cols=3)
    tbl_infra.alignment = WD_TABLE_ALIGNMENT.CENTER
    style_row_header(tbl_infra.rows[0], ["Infrastructure Component", "100 Devices (Current)", "10,000 Devices (Enterprise Target)"])
    
    infra_data = [
        ("MQTT Broker", "Standalone Mosquitto / Cloud Broker", "EMQX Enterprise Cluster (Multi-node with auto-failover, load balancing, and 1M+ connection capacity)"),
        ("Backend Node.js Runtime", "Single-threaded Express Process", "PM2 Cluster Mode (utilizing all CPU cores) / Kubernetes Pods with Horizontal Pod Autoscaler (HPA)"),
        ("Caching & Pub/Sub Layer", "In-memory JavaScript Map", "Redis Cluster (6 nodes: 3 masters + 3 replicas) with Redis Adapter for Socket.io synchronization"),
        ("Database Architecture", "Standalone MongoDB instance", "MongoDB Sharded Cluster with partitioned Time-Series collections and replica set failover"),
        ("Load Balancer & Edge Proxy", "Direct Express port exposure", "Nginx / Cloudflare reverse proxy with SSL offloading, gzip/brotli compression, and WebSocket sticky sessions")
    ]
    for idx, row_vals in enumerate(infra_data):
        style_row_data(tbl_infra.rows[idx+1], row_vals, is_even=(idx%2==1))

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # -------------------------------------------------------------------------
    # SECTION 9: IMPLEMENTATION ROADMAP & PHASE-BY-PHASE EXECUTION MATRIX
    # -------------------------------------------------------------------------
    h9 = doc.add_heading(level=1)
    r_h9 = h9.add_run("9. Sequential Implementation Execution Roadmap")
    r_h9.font.name = "Arial"
    r_h9.font.color.rgb = RGBColor(15, 23, 42)

    p = doc.add_paragraph()
    p.add_run(
        "The upgrade will be executed strictly phase-by-phase with verification milestones after each step to prevent "
        "regressions or service disruptions:"
    )

    tbl_exec = doc.add_table(rows=6, cols=5)
    tbl_exec.alignment = WD_TABLE_ALIGNMENT.CENTER
    style_row_header(tbl_exec.rows[0], ["Phase", "Milestone / Deliverable", "Scope of Changes", "Key Libraries / Tech", "Verification Test"])
    
    exec_data = [
        ("Phase 1", "Selective Real-Time PubSub & Viewport Streaming", "Replace global SSE with WebSocket Rooms. Client subscribes only to visible page cards. Add delta compression.", "Socket.io, Redis PubSub Adapter", "Stress test: 10,000 virtual device simulator streaming; client tab receives only 24 msgs/sec."),
        ("Phase 2", "High-Throughput Ingestion & DB Micro-Batching", "Implement 500ms / 500-doc bulkWrite buffer. Move live device state to Redis Hash. Convert to Time-Series DB.", "Redis (ioredis), MongoDB Time-Series", "DB write load drops from 5,000 writes/sec to 10 bulk writes/sec. Zero dropped telemetry frames."),
        ("Phase 3", "Frontend Zero-Lag Virtualization Engine", "Add @tanstack/react-virtual to DevicesPage and LiveMonitoring. Normalize state to O(1) dictionary. Add Web Worker.", "@tanstack/react-virtual, Web Worker API", "Simulate 10,000 devices in state. Verify browser RAM < 85MB and smooth 60 FPS scrolling."),
        ("Phase 4", "Analytics Downsampling & Pre-Aggregation", "Implement 1-minute and 1-hour rollup aggregation cron jobs. Add LTTB downsampling to /analytics API endpoint.", "MongoDB Aggregation Pipeline, LTTB Algorithm", "7-day and 30-day historical chart loading time verified < 150ms across millions of records."),
        ("Phase 5", "Clustering, Infrastructure & Production Readiness", "Setup PM2 cluster mode, Nginx WebSocket configuration, EMQX broker cluster, and production health telemetry.", "PM2, EMQX, Nginx, Docker", "End-to-end full load test with 10,000 simulated devices publishing concurrently without degradation.")
    ]
    for idx, row_vals in enumerate(exec_data):
        style_row_data(tbl_exec.rows[idx+1], row_vals, is_even=(idx%2==1))

    doc.add_paragraph().paragraph_format.space_after = Pt(14)

    # -------------------------------------------------------------------------
    # SIGN-OFF BLOCK
    # -------------------------------------------------------------------------
    p_sign = doc.add_paragraph()
    p_sign.paragraph_format.space_before = Pt(16)
    r_s = p_sign.add_run("APPROVED FOR IMPLEMENTATION: InHydro IoT Engineering Team")
    r_s.font.name = "Arial"
    r_s.font.size = Pt(10)
    r_s.font.bold = True
    r_s.font.color.rgb = RGBColor(16, 185, 129)

    doc.save(DOCX_OUTPUT_PATH)
    print(f"SUCCESS: Document generated at {DOCX_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
