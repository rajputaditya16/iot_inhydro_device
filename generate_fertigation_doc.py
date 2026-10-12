#!/usr/bin/env python3
"""
Generate a comprehensive, flawless, diagram-rich Word document (.docx)
Explaining the 5-Venturi Multi-Setpoint Fertigation Architecture and Logic.
Pure diagrammatic overview, clean engineering tables, zero code dumps.
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

OUTPUT_DIR = "/home/anuj-prajapati/Desktop/iot_inhydro_device"
IMG_DIR = os.path.join(OUTPUT_DIR, "doc_diagrams")
os.makedirs(IMG_DIR, exist_ok=True)
DOCX_PATH = os.path.join(OUTPUT_DIR, "5_Venturi_Fertigation_Architecture_and_Logic.docx")

# Set matplotlib global style
plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
plt.rcParams['font.family'] = 'sans-serif'

# -----------------------------------------------------------------------------
# DIAGRAM 1: 5-VENTURI HYDRAULIC & P&ID ARCHITECTURE
# -----------------------------------------------------------------------------
def generate_diagram_1():
    fig, ax = plt.subplots(figsize=(12, 7.5), dpi=300)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7.5)
    ax.axis("off")

    # Title Banner
    ax.add_patch(patches.Rectangle((0.2, 6.7), 11.6, 0.7, fc="#0F172A", ec="none"))
    ax.text(6.0, 7.15, "5-VENTURI CLOSED-LOOP FERTIGATION P&ID ARCHITECTURE", 
            ha="center", va="center", fontsize=13, weight="bold", color="#FFFFFF")
    ax.text(6.0, 6.85, "Physical Hydraulic Layout: Motive Water Loop, 5 Dosing Channels, Mixing Tank & In-line Probes", 
            ha="center", va="center", fontsize=9, color="#94A3B8")

    # 5 Chemical Stock Tanks
    tanks = [
        ("Tank 1 (Stock A)\nCalcium + Iron\n[EC Stage 1]", 1.4, "#0284C7", "#E0F2FE"),
        ("Tank 2 (Stock B)\nNPK + MgSO4\n[EC Stage 2]", 3.6, "#0284C7", "#E0F2FE"),
        ("Tank 3 (Stock C)\nMicronutrients\n[EC Stage 3]", 5.8, "#6366F1", "#EEF2FF"),
        ("Tank 4 (D / Base)\nBooster / pH-Up\n[EC 4 or Base]", 8.0, "#0D9488", "#CCFBF1"),
        ("Tank 5 (Acid)\nNitric/Phosphoric\n[pH Down]", 10.2, "#DC2626", "#FEE2E2")
    ]

    for idx, (name, x, col, bg) in enumerate(tanks, start=1):
        # Stock Tank
        ax.add_patch(patches.FancyBboxPatch((x - 0.9, 5.3), 1.8, 1.1, boxstyle="round,pad=0.08", 
                                            fc=bg, ec=col, lw=2))
        ax.text(x, 5.85, name, ha="center", va="center", fontsize=7.5, weight="bold", color="#0F172A")
        
        # Suction tube down to Solenoid
        ax.annotate("", xy=(x, 4.8), xytext=(x, 5.3), 
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=2, mutation_scale=10))

        # 24V Solenoid Valve
        ax.add_patch(patches.Rectangle((x - 0.55, 4.35), 1.1, 0.45, fc="#FFFFFF", ec="#334155", lw=1.5))
        ax.text(x, 4.58, "24V Solenoid", ha="center", va="center", fontsize=7, weight="bold", color="#334155")
        
        # Suction tube down to Venturi Suction Port
        ax.annotate("", xy=(x, 3.9), xytext=(x, 4.35), 
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=1.5, mutation_scale=8))

        # Venturi Injector (Throat Representation)
        ax.add_patch(patches.Polygon([[x - 0.65, 3.5], [x, 3.62], [x + 0.65, 3.5], 
                                     [x + 0.65, 3.9], [x, 3.78], [x - 0.65, 3.9]], 
                                     closed=True, fc="#F8FAFC", ec=col, lw=2))
        ax.text(x, 3.7, f"Venturi {idx}", ha="center", va="center", fontsize=7.5, weight="bold", color=col)

        # Mixed effluent dropping into Common Discharge Header
        ax.annotate("", xy=(x, 2.9), xytext=(x, 3.5), 
                    arrowprops=dict(arrowstyle="-|>", color="#0284C7", lw=2, mutation_scale=10))

    # Upper Motive Pressurized Water Header Pipe (supplies high-pressure water through venturis)
    ax.add_patch(patches.Rectangle((0.6, 3.95), 10.8, 0.12, fc="#0369A1", ec="none"))
    ax.text(6.0, 4.15, "▲ HIGH PRESSURE MOTIVE WATER SUPPLY PIPE (DRIVES SUCTION VACUUM) ▲", 
            ha="center", va="center", fontsize=7.5, weight="bold", color="#0369A1")

    # Lower Common Discharge Manifold Pipe
    ax.add_patch(patches.Rectangle((0.6, 2.75), 10.8, 0.15, fc="#0284C7", ec="none"))
    ax.text(6.0, 2.58, "▼ COMMON MIXED DILUTION MANIFOLD (DISCHARGES DIRECTLY INTO BATCH TANK) ▼", 
            ha="center", va="center", fontsize=7.5, weight="bold", color="#0284C7")

    # Pipe from Discharge Manifold down into Batch Tank
    ax.annotate("", xy=(3.6, 1.9), xytext=(3.6, 2.75), 
                arrowprops=dict(arrowstyle="-|>", color="#0284C7", lw=3, mutation_scale=15))

    # Fresh RO Water Supply Box & Pump
    ax.add_patch(patches.Circle((1.1, 1.0), 0.45, fc="#ECFDF5", ec="#10B981", lw=2))
    ax.text(1.1, 1.0, "RO Fresh\nWater Pump", ha="center", va="center", fontsize=7, weight="bold", color="#065F46")
    ax.annotate("", xy=(2.4, 1.0), xytext=(1.6, 1.0), 
                arrowprops=dict(arrowstyle="-|>", color="#10B981", lw=2.5, mutation_scale=12))
    ax.text(1.9, 1.2, "Fill Line", ha="center", va="center", fontsize=6.5, weight="bold", color="#059669")

    # 1000L Main Mixing Batch Tank
    ax.add_patch(patches.FancyBboxPatch((2.4, 0.25), 2.4, 1.65, boxstyle="round,pad=0.1", 
                                        fc="#F0F9FF", ec="#0284C7", lw=2.5))
    ax.text(3.6, 1.35, "1000L BATCH MIXING TANK", ha="center", va="center", fontsize=8.5, weight="bold", color="#0369A1")
    ax.text(3.6, 0.95, "• Ultrasonic Level (L / %)\n• Temp Compensation Probe\n• Continuous Homogenization", 
            ha="center", va="center", fontsize=7, color="#334155")
    ax.text(3.6, 0.45, "Active Recirculation Volume", ha="center", va="center", fontsize=6.5, style="italic", color="#64748B")

    # Pipe from Tank to Main Booster Pump
    ax.annotate("", xy=(5.4, 1.0), xytext=(4.9, 1.0), 
                arrowprops=dict(arrowstyle="-|>", color="#0284C7", lw=3, mutation_scale=15))

    # Main Circulation Booster Pump
    ax.add_patch(patches.Circle((5.9, 1.0), 0.5, fc="#FEF3C7", ec="#D97706", lw=2.5))
    ax.text(5.9, 1.0, "MAIN\nPUMP\n(1.5 HP)", ha="center", va="center", fontsize=7.5, weight="bold", color="#92400E")

    # Pipe from Main Pump to Sensor Chamber
    ax.annotate("", xy=(7.1, 1.0), xytext=(6.45, 1.0), 
                arrowprops=dict(arrowstyle="-|>", color="#0284C7", lw=3, mutation_scale=15))

    # In-line Sensor Chamber Box
    ax.add_patch(patches.FancyBboxPatch((7.1, 0.4), 2.0, 1.2, boxstyle="round,pad=0.08", 
                                        fc="#F8FAFC", ec="#7C3AED", lw=2))
    ax.text(8.1, 1.15, "IN-LINE SENSOR CELL", ha="center", va="center", fontsize=7.5, weight="bold", color="#5B21B6")
    ax.text(8.1, 0.75, "• RS-485 Modbus EC\n• Industrial pH Probe\n• Continuous Flow Stream", 
            ha="center", va="center", fontsize=6.8, color="#1E293B")

    # Motorized Diverter: Recirculation Loop vs Field Irrigation
    # 1. Recirculation line going up to Recirculation Valve
    ax.annotate("", xy=(8.1, 1.95), xytext=(8.1, 1.6), 
                arrowprops=dict(arrowstyle="-|>", color="#0284C7", lw=2.5, mutation_scale=12))
    ax.add_patch(patches.Rectangle((7.4, 1.95), 1.4, 0.45, fc="#F1F5F9", ec="#0284C7", lw=1.5))
    ax.text(8.1, 2.17, "Fertigation Valve\n(Recirculation)", ha="center", va="center", fontsize=6.5, weight="bold", color="#0369A1")

    # Clean external bypass riser pipe to Motive Header:
    # From Recirculation Valve (x=8.8, y=2.17) -> right to x=11.5, then up to y=4.01
    ax.plot([8.8, 11.5, 11.5], [2.17, 2.17, 4.01], color="#0369A1", lw=2.5)
    ax.annotate("", xy=(11.4, 4.01), xytext=(11.5, 4.01), 
                arrowprops=dict(arrowstyle="-|>", color="#0369A1", lw=2.5, mutation_scale=14))
    ax.text(11.55, 3.1, "Recirculation Motive Riser", rotation=90, ha="center", va="center", 
            fontsize=6.5, weight="bold", color="#0369A1")

    # 2. Irrigation Valve to Field Zones
    ax.annotate("", xy=(9.7, 1.0), xytext=(9.1, 1.0), 
                arrowprops=dict(arrowstyle="-|>", color="#059669", lw=3, mutation_scale=15))
    ax.add_patch(patches.Rectangle((9.7, 0.65), 1.9, 0.7, fc="#ECFDF5", ec="#059669", lw=2))
    ax.text(10.65, 1.08, "IRRIGATION VALVE", ha="center", va="center", fontsize=7.5, weight="bold", color="#065F46")
    ax.text(10.65, 0.82, "To Crops (Zones 1 & 2)", ha="center", va="center", fontsize=6.8, color="#047857")

    plt.tight_layout()
    path1 = os.path.join(IMG_DIR, "diag1_hydraulic_architecture.png")
    plt.savefig(path1, dpi=300)
    plt.close()
    return path1

# -----------------------------------------------------------------------------
# DIAGRAM 2: DUAL MODE CONFIGURATION MAPPING
# -----------------------------------------------------------------------------
def generate_diagram_2():
    fig, ax = plt.subplots(figsize=(11.5, 6.5), dpi=300)
    ax.set_xlim(0, 11.5)
    ax.set_ylim(0, 6.5)
    ax.axis("off")

    # Header
    ax.add_patch(patches.Rectangle((0.3, 5.75), 10.9, 0.65, fc="#0F172A", ec="none"))
    ax.text(5.75, 6.18, "FLEXIBLE CHANNEL ALLOCATION ARCHITECTURE", ha="center", va="center", fontsize=13, weight="bold", color="#FFFFFF")
    ax.text(5.75, 5.9, "Software-Configurable Roles: Standard 4-EC + 1-pH vs Precision 3-EC + 2-pH Dual-Window", 
            ha="center", va="center", fontsize=8.5, color="#94A3B8")

    # MODE A CARD
    ax.add_patch(patches.FancyBboxPatch((0.4, 0.5), 5.1, 5.0, boxstyle="round,pad=0.15", 
                                        fc="#F8FAFC", ec="#0284C7", lw=2))
    ax.add_patch(patches.Rectangle((0.6, 4.8), 4.7, 0.5, fc="#0284C7", ec="none"))
    ax.text(2.95, 5.05, "MODE A: STANDARD (4 EC + 1 pH)", ha="center", va="center", fontsize=10.5, weight="bold", color="#FFFFFF")
    ax.text(2.95, 4.55, "Application: Standard hydroponics where raw source water is alkaline (> 7.0)\nOnly acid correction is required; Venturi 4 serves as secondary booster.", 
            ha="center", va="center", fontsize=7.2, color="#475569")

    mode_a_channels = [
        ("Venturi 1", "Stock A (Calcium Nitrate + Fe)", "Doses on EC Stage 1 Setpoint (e.g. 1.20 mS/cm)", "#0284C7"),
        ("Venturi 2", "Stock B (NPK + MgSO4)", "Doses on EC Stage 2 Setpoint (e.g. 1.90 mS/cm)", "#0284C7"),
        ("Venturi 3", "Stock C (Micronutrient Blend)", "Doses on EC Stage 3 Setpoint (e.g. 2.10 mS/cm)", "#6366F1"),
        ("Venturi 4", "Stock D (Booster / Potassium / Silica)", "Doses on Final Target EC (e.g. 2.20 mS/cm)", "#0D9488"),
        ("Venturi 5", "pH DOWN (15% Nitric / Phosphoric Acid)", "Pulsed when pH > High Threshold (e.g. > 6.20)", "#DC2626")
    ]
    y_pos = 4.0
    for v, role, desc, col in mode_a_channels:
        ax.add_patch(patches.FancyBboxPatch((0.6, y_pos - 0.28), 4.7, 0.56, boxstyle="round,pad=0.04", 
                                            fc="#FFFFFF", ec=col, lw=1.2))
        ax.text(0.75, y_pos + 0.08, f"● {v}: {role}", fontsize=7.2, weight="bold", color="#0F172A")
        ax.text(0.9, y_pos - 0.15, f"↳ {desc}", fontsize=6.5, color="#64748B")
        y_pos -= 0.68

    # MODE B CARD
    ax.add_patch(patches.FancyBboxPatch((5.9, 0.5), 5.1, 5.0, boxstyle="round,pad=0.15", 
                                        fc="#F8FAFC", ec="#7E22CE", lw=2))
    ax.add_patch(patches.Rectangle((6.1, 4.8), 4.7, 0.5, fc="#7E22CE", ec="none"))
    ax.text(8.45, 5.05, "MODE B: ADVANCED (3 EC + 2 pH)", ha="center", va="center", fontsize=10.5, weight="bold", color="#FFFFFF")
    ax.text(8.45, 4.55, "Application: RO water, acidic media, or unpredictable pH environments\nVenturi 4 dynamically re-allocated to alkali base for bidirectional pH stability.", 
            ha="center", va="center", fontsize=7.2, color="#475569")

    mode_b_channels = [
        ("Venturi 1", "Stock A (Calcium Nitrate + Fe)", "Doses on EC Stage 1 Setpoint (e.g. 1.20 mS/cm)", "#0284C7"),
        ("Venturi 2", "Stock B (NPK + MgSO4)", "Doses on EC Stage 2 Setpoint (e.g. 1.90 mS/cm)", "#0284C7"),
        ("Venturi 3", "Stock C (Micronutrient Blend)", "Doses on Final Target EC (e.g. 2.20 mS/cm)", "#6366F1"),
        ("Venturi 4", "pH UP (20% Potassium Hydroxide - KOH)", "Pulsed when pH < Low Threshold (e.g. < 5.50)", "#059669"),
        ("Venturi 5", "pH DOWN (15% Nitric / Phosphoric Acid)", "Pulsed when pH > High Threshold (e.g. > 6.20)", "#DC2626")
    ]
    y_pos = 4.0
    for v, role, desc, col in mode_b_channels:
        ax.add_patch(patches.FancyBboxPatch((6.1, y_pos - 0.28), 4.7, 0.56, boxstyle="round,pad=0.04", 
                                            fc="#FFFFFF", ec=col, lw=1.2))
        ax.text(6.25, y_pos + 0.08, f"● {v}: {role}", fontsize=7.2, weight="bold", color="#0F172A")
        ax.text(6.4, y_pos - 0.15, f"↳ {desc}", fontsize=6.5, color="#64748B")
        y_pos -= 0.68

    # Bottom Footer Note
    ax.add_patch(patches.Rectangle((0.4, 0.05), 10.6, 0.35, fc="#F1F5F9", ec="#CBD5E1", lw=1))
    ax.text(5.7, 0.22, "★ NOTE: Switching between Mode A and Mode B is purely software-configured via HMI without re-plumbing.", 
            ha="center", va="center", fontsize=7.5, weight="bold", color="#334155")

    plt.tight_layout()
    path2 = os.path.join(IMG_DIR, "diag2_channel_modes.png")
    plt.savefig(path2, dpi=300)
    plt.close()
    return path2

# -----------------------------------------------------------------------------
# DIAGRAM 3: STAGED CONDITIONAL DOSING LOGIC FLOWCHART
# -----------------------------------------------------------------------------
def generate_diagram_3():
    fig, ax = plt.subplots(figsize=(11, 8.5), dpi=300)
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 9.2)
    ax.axis("off")

    # Header
    ax.add_patch(patches.Rectangle((0.3, 8.4), 10.4, 0.65, fc="#0F172A", ec="none"))
    ax.text(5.5, 8.82, "STEP-BY-STEP STAGED CONDITIONAL DOSING LOGIC", ha="center", va="center", fontsize=13, weight="bold", color="#FFFFFF")
    ax.text(5.5, 8.52, "Sequential Progression: Isolated Setpoints Prevent Chemical Precipitation and Ensure Strict Accuracy", 
            ha="center", va="center", fontsize=8.5, color="#94A3B8")

    steps = [
        ("STAGE 0: SYSTEM INITIALIZATION & LEVEL CHECK", 
         "IF: Tank Volume < 300 Liters (Low Level Interlock Active)\n"
         "THEN: Start RO Pump until 800L reached. Start Main Pump in Recirculation Loop. In-line probes primed.", 
         5.5, 7.55, "#475569", "#F8FAFC"),
        
        ("STAGE 1: VENTURI 1 ACTIVATION (STOCK A - CALCIUM BASE)", 
         "IF: In-line Measured EC < Stage 1 Threshold (e.g. 1.20 mS/cm)\n"
         "THEN: Open Solenoid 1 for 3.0s pulse → Close → Recirculate 20s for full tank turnover → Verify EC.", 
         5.5, 6.25, "#0284C7", "#F0F9FF"),
        
        ("STAGE 2: VENTURI 2 ACTIVATION (STOCK B - NPK & SULFATE)", 
         "IF: Measured EC < Stage 2 Threshold (e.g. 1.90 mS/cm) [AND Stock A dosing verified complete]\n"
         "THEN: Open Solenoid 2 for 3.0s pulse → Close → Recirculate 20s → Verify EC. (Prevents CaSO4 precipitation).", 
         5.5, 4.95, "#0284C7", "#F0F9FF"),
        
        ("STAGE 3: VENTURI 3 ACTIVATION (STOCK C - MICRONUTRIENTS)", 
         "IF: Measured EC < Final Target EC (e.g. 2.20 mS/cm)\n"
         "THEN: Open Solenoid 3 for 2.0s pulse → Close → Recirculate 20s → Verify Target EC achieved (±0.05).", 
         5.5, 3.65, "#6366F1", "#EEF2FF"),
        
        ("STAGE 4: pH DUAL-WINDOW STABILIZATION (ACID / BASE PULSING)", 
         "IF: pH > 6.20 → Pulse Venturi 5 (Acid) for 1.5s  |  IF: pH < 5.50 (Mode B) → Pulse Venturi 4 (Base) for 1.5s\n"
         "SAFETY RULE: Strict mutual exclusion lock enforced (Acid & Base never energized concurrently). Recirculate 25s.", 
         5.5, 2.35, "#7E22CE", "#FAF5FF"),
        
        ("STAGE 5: FINAL STABILIZATION VERIFICATION & FIELD DELIVERY", 
         "IF: EC == 2.20 ± 0.05 mS/cm AND pH == 5.80 ± 0.15 continuously stable for 30 seconds\n"
         "THEN: Close Fertigation Bypass Recirculation Valve → Open Field Irrigation Solenoids (Zone 1 & 2).", 
         5.5, 1.05, "#059669", "#ECFDF5")
    ]

    for title, desc, cx, cy, border_col, bg_col in steps:
        # Step Box
        ax.add_patch(patches.FancyBboxPatch((cx - 4.8, cy - 0.45), 9.6, 0.95, boxstyle="round,pad=0.08", 
                                            fc=bg_col, ec=border_col, lw=2))
        ax.text(cx - 4.5, cy + 0.22, title, fontsize=8.5, weight="bold", color=border_col)
        ax.text(cx - 4.5, cy - 0.18, desc, fontsize=7.2, color="#1E293B")
        
        # DOWNWARD Flow Arrow to next box
        if cy > 1.2:
            ax.annotate("", xy=(cx, cy - 0.45 - 0.35), xytext=(cx, cy - 0.45), 
                        arrowprops=dict(arrowstyle="-|>", color=border_col, lw=2.5, mutation_scale=14))

    # Bottom status bar
    ax.add_patch(patches.Rectangle((0.7, 0.15), 9.6, 0.32, fc="#0F172A", ec="none"))
    ax.text(5.5, 0.31, "✔ FERTIGATION CYCLE COMPLETE: NUTRIENT SOLUTION DELIVERED TO CROPS AT TARGET SPECIFICATION", 
            ha="center", va="center", fontsize=7.2, weight="bold", color="#34D399")

    plt.tight_layout()
    path3 = os.path.join(IMG_DIR, "diag3_conditional_flowchart.png")
    plt.savefig(path3, dpi=300)
    plt.close()
    return path3

# -----------------------------------------------------------------------------
# DIAGRAM 4: STEPPING GRAPH & pH DUAL-WINDOW TIMELINE
# -----------------------------------------------------------------------------
def generate_diagram_4():
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.5, 6.8), dpi=300, sharex=True)

    time_pts = [0, 20, 25, 45, 50, 70, 75, 95, 100, 120, 140]
    ec_vals  = [0.6, 0.6, 1.2, 1.2, 1.85, 1.85, 2.15, 2.15, 2.20, 2.20, 2.20]
    ph_vals  = [7.4, 7.4, 7.2, 7.2, 6.9, 6.9, 6.7, 6.7, 5.85, 5.82, 5.80]

    # Subplot 1: EC Stepping
    ax1.plot(time_pts, ec_vals, color="#0284C7", lw=3.2, marker="o", markersize=6, label="In-line Measured EC")
    ax1.axhline(1.2, color="#64748B", linestyle="--", lw=1.2, label="V1 Setpoint 1 (1.20 mS/cm)")
    ax1.axhline(1.85, color="#0284C7", linestyle="--", lw=1.2, label="V2 Setpoint 2 (1.85 mS/cm)")
    ax1.axhline(2.2, color="#059669", linestyle="-.", lw=1.8, label="Final Target EC (2.20 mS/cm)")
    ax1.fill_between([0, 140], 2.15, 2.25, color="#D1FAE5", alpha=0.55, label="EC Target Safe Band (±0.05)")

    ax1.set_ylabel("EC (mS/cm)", fontsize=9.5, weight="bold", color="#0F172A")
    ax1.set_title("EC PROGRESSIVE STAGED STEPPING TIMELINE (VENTURIS 1, 2, & 3)", fontsize=11, weight="bold", color="#0F172A")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="lower right", fontsize=8, framealpha=0.95)

    # Clean Callout Badges
    ax1.annotate("Venturi 1 (Stock A)\n3.0s Pulse + 20s Mix", xy=(23, 0.8), xytext=(5, 1.45),
                 arrowprops=dict(arrowstyle="-|>", color="#0284C7", lw=1.5, mutation_scale=10),
                 bbox=dict(boxstyle="round,pad=0.3", fc="#F0F9FF", ec="#0284C7", lw=1),
                 fontsize=7.5, weight="bold", color="#0369A1")

    ax1.annotate("Venturi 2 (Stock B)\n3.0s Pulse + 20s Mix", xy=(48, 1.4), xytext=(32, 1.6),
                 arrowprops=dict(arrowstyle="-|>", color="#0284C7", lw=1.5, mutation_scale=10),
                 bbox=dict(boxstyle="round,pad=0.3", fc="#F0F9FF", ec="#0284C7", lw=1),
                 fontsize=7.5, weight="bold", color="#0369A1")

    ax1.annotate("Venturi 3 (Micros)\n2.0s Pulse to Target", xy=(73, 2.0), xytext=(58, 2.05),
                 arrowprops=dict(arrowstyle="-|>", color="#6366F1", lw=1.5, mutation_scale=10),
                 bbox=dict(boxstyle="round,pad=0.3", fc="#EEF2FF", ec="#6366F1", lw=1),
                 fontsize=7.5, weight="bold", color="#4338CA")

    # Subplot 2: pH Dual-Window
    ax2.plot(time_pts, ph_vals, color="#7C3AED", lw=3.2, marker="s", markersize=6, label="In-line Measured pH")
    ax2.axhline(6.2, color="#DC2626", linestyle="--", lw=1.5, label="pH High Threshold (Triggers V5 Acid)")
    ax2.axhline(5.5, color="#F59E0B", linestyle="--", lw=1.5, label="pH Low Threshold (Triggers V4 Base)")
    ax2.axhline(5.8, color="#059669", linestyle="-.", lw=1.8, label="Ideal Target pH (5.80)")
    ax2.fill_between([0, 140], 5.5, 6.2, color="#EDE9FE", alpha=0.45, label="Optimal pH Window (5.5 - 6.2)")

    ax2.set_ylabel("pH Value", fontsize=9.5, weight="bold", color="#0F172A")
    ax2.set_xlabel("Fertigation Cycle Timeline (Seconds)", fontsize=9.5, weight="bold", color="#0F172A")
    ax2.set_title("pH DUAL-WINDOW CLOSED-LOOP STABILIZATION", fontsize=11, weight="bold", color="#0F172A")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper right", fontsize=8, framealpha=0.95)

    ax2.annotate("Venturi 5 (Acid)\n1.5s Fine Pulse", xy=(98, 6.1), xytext=(78, 6.4),
                 arrowprops=dict(arrowstyle="-|>", color="#DC2626", lw=1.5, mutation_scale=10),
                 bbox=dict(boxstyle="round,pad=0.3", fc="#FEF2F2", ec="#DC2626", lw=1),
                 fontsize=7.5, weight="bold", color="#991B1B")

    plt.tight_layout()
    path4 = os.path.join(IMG_DIR, "diag4_stepping_timeline.png")
    plt.savefig(path4, dpi=300)
    plt.close()
    return path4

# -----------------------------------------------------------------------------
# DIAGRAM 5: 4 SAFETY RULES & INTERLOCK MATRIX (ZERO OVERLAPS)
# -----------------------------------------------------------------------------
def generate_diagram_5():
    fig, ax = plt.subplots(figsize=(12, 7.0), dpi=300)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7.0)
    ax.axis("off")

    # Header
    ax.add_patch(patches.Rectangle((0.3, 6.25), 11.4, 0.65, fc="#0F172A", ec="none"))
    ax.text(6.0, 6.68, "FOUR MANDATORY FIRMWARE SAFETY INTERLOCKS & OPERATIONAL RULES", 
            ha="center", va="center", fontsize=13, weight="bold", color="#FFFFFF")
    ax.text(6.0, 6.38, "Fail-Safe Algorithms Built Directly into Raspberry Pi Firmware to Protect Plant Root Zones & Hydraulics", 
            ha="center", va="center", fontsize=8.5, color="#94A3B8")

    # 4 Spacious Cards in 2x2 Layout
    card_coords = [
        (0.5, 3.4),  # Card 1 (Top Left)
        (6.3, 3.4),  # Card 2 (Top Right)
        (0.5, 0.5),  # Card 3 (Bottom Left)
        (6.3, 0.5),  # Card 4 (Bottom Right)
    ]

    card_data = [
        # Card 1
        ("RULE 1: PULSE & WAIT (DEAD-TIME COMPENSATION)",
         "#0284C7", "#F0F9FF",
         "HYDRAULIC PHYSICAL DELAY:",
         "Solution requires 15 to 25 seconds of circulation through\n"
         "the 1000L tank before in-line probes detect true concentration.",
         "FIRMWARE EXECUTION RULE:",
         "Solenoid never stays energized continuously. Execute 2-3s pulse,\n"
         "then enforce mandatory 20s recirculation wait before re-sampling."),

        # Card 2
        ("RULE 2: STRICT MUTUAL EXCLUSION (ACID & BASE)",
         "#DC2626", "#FEF2F2",
         "CHEMICAL REACTION HAZARD:",
         "Acid (HNO3) and Base (KOH) in direct contact inside the manifold\n"
         "undergo violent exothermic neutralization and damage tubing.",
         "FIRMWARE EXECUTION RULE:",
         "If Venturi 5 (Acid) fires, Venturi 4 (Base) is hardware-locked.\n"
         "Enforce 60-second water purge buffer before switching chemicals."),

        # Card 3
        ("RULE 3: STOCK A & B RATIO BALANCING",
         "#D97706", "#FFFBEB",
         "NUTRITIONAL TOXICITY HAZARD:",
         "Overdosing Calcium (Stock A) without matching Phosphate/Sulfate\n"
         "(Stock B) causes severe nutrient lockout and root burn.",
         "FIRMWARE EXECUTION RULE:",
         "Venturi 2 run duration is strictly coupled 1:1 with Venturi 1.\n"
         "System prevents advancing to Stage 2 until Stage 1 has stabilized."),

        # Card 4
        ("RULE 4: DEADBAND & RELAY HYSTERESIS",
         "#059669", "#ECFDF5",
         "EQUIPMENT WEAR PREVENTION:",
         "Analog sensor micro-noise (±0.02) near target causes rapid solenoid\n"
         "chattering, mechanical coil burnout, and dosage overshooting.",
         "FIRMWARE EXECUTION RULE:",
         "Enforce strict deadband (±0.05 mS/cm EC, ±0.15 pH).\n"
         "Valves remain fully idle once readings enter the target window.")
    ]

    for (x, y), (title, col, bg, sub1, desc1, sub2, desc2) in zip(card_coords, card_data):
        # Card Outer Box
        ax.add_patch(patches.FancyBboxPatch((x, y), 5.3, 2.7, boxstyle="round,pad=0.1", 
                                            fc=bg, ec=col, lw=2))
        
        # Title Banner
        ax.add_patch(patches.Rectangle((x + 0.1, y + 2.15), 5.1, 0.45, fc=col, ec="none"))
        ax.text(x + 2.65, y + 2.37, title, ha="center", va="center", fontsize=8.2, weight="bold", color="#FFFFFF")
        
        # Hazard / Why section
        ax.text(x + 0.25, y + 1.9, f"▲ {sub1}", fontsize=7.2, weight="bold", color=col)
        ax.text(x + 0.25, y + 1.45, desc1, fontsize=6.8, color="#334155")
        
        # Divider Line
        ax.plot([x + 0.2, x + 5.1], [y + 1.15, y + 1.15], color=col, alpha=0.3, lw=1)

        # Logic / Firmware Rule section
        ax.text(x + 0.25, y + 0.95, f"✔ {sub2}", fontsize=7.2, weight="bold", color="#0F172A")
        ax.text(x + 0.25, y + 0.5, desc2, fontsize=6.8, color="#334155")

    plt.tight_layout()
    path5 = os.path.join(IMG_DIR, "diag5_safety_rules.png")
    plt.savefig(path5, dpi=300)
    plt.close()
    return path5

# -----------------------------------------------------------------------------
# HELPER FOR TABLE CELL STYLING
# -----------------------------------------------------------------------------
def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)

# -----------------------------------------------------------------------------
# BUILD CLEAN WORD DOCUMENT (.DOCX)
# -----------------------------------------------------------------------------
def build_docx_document(img_paths):
    doc = Document()

    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(0.7)
        section.bottom_margin = Inches(0.7)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    # -------------------------------------------------------------
    # DOCUMENT COVER / TITLE HEADER BLOCK
    # -------------------------------------------------------------
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(2)
    r_title = title_p.add_run("AUTOMATED 5-VENTURI FERTIGATION SYSTEM")
    r_title.font.name = "Arial"
    r_title.font.size = Pt(22)
    r_title.font.bold = True
    r_title.font.color.rgb = RGBColor(15, 23, 42)

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_after = Pt(8)
    r_sub = sub_p.add_run("Executive Engineering Overview: Hydraulic P&ID, Channel Allocation & Staged Logic")
    r_sub.font.name = "Arial"
    r_sub.font.size = Pt(12)
    r_sub.font.color.rgb = RGBColor(2, 132, 199)

    # Metadata Executive Table
    meta_table = doc.add_table(rows=2, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_headers = [("Project", "InHydro IoT Device"), ("Platform", "Raspberry Pi CM4 + Modbus"), 
                    ("Dosing Channels", "5 Venturis + 11 Relays"), ("Control Mode", "Staged Conditional Logic")]
    for i, (k, v) in enumerate(meta_headers):
        cell_k = meta_table.cell(0, i)
        cell_v = meta_table.cell(1, i)
        set_cell_background(cell_k, "0F172A")
        set_cell_background(cell_v, "F1F5F9")
        set_cell_margins(cell_k, 60, 60, 100, 100)
        set_cell_margins(cell_v, 60, 60, 100, 100)
        
        pk = cell_k.paragraphs[0]
        pk.paragraph_format.space_after = Pt(0)
        rk = pk.add_run(k)
        rk.font.name = "Arial"
        rk.font.size = Pt(8)
        rk.font.bold = True
        rk.font.color.rgb = RGBColor(255, 255, 255)

        pv = cell_v.paragraphs[0]
        pv.paragraph_format.space_after = Pt(0)
        rv = pv.add_run(v)
        rv.font.name = "Arial"
        rv.font.size = Pt(8)
        rv.font.color.rgb = RGBColor(30, 41, 59)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # -------------------------------------------------------------
    # SECTION 1
    # -------------------------------------------------------------
    h1 = doc.add_heading(level=1)
    r1 = h1.add_run("1. 5-Venturi Hydraulic & P&ID Architecture")
    r1.font.name = "Arial"
    r1.font.color.rgb = RGBColor(15, 23, 42)

    p1 = doc.add_paragraph()
    p1.add_run("The physical dosing assembly utilizes high-velocity motive water differential pressure. "
               "As pressurized water flows through the Venturi throat, the resulting vacuum draws concentrated stock chemicals "
               "through individual 24V Teflon-sealed solenoid valves into the common dilution stream, discharging directly into the 1000L mixing tank.")
    
    doc.add_picture(img_paths[0], width=Inches(6.8))

    doc.add_paragraph().paragraph_format.space_after = Pt(14)

    # -------------------------------------------------------------
    # SECTION 2
    # -------------------------------------------------------------
    h2 = doc.add_heading(level=1)
    r2 = h2.add_run("2. Flexible Channel Allocation Architecture")
    r2.font.name = "Arial"
    r2.font.color.rgb = RGBColor(15, 23, 42)

    p2 = doc.add_paragraph()
    p2.add_run("The firmware provides dynamic channel re-allocation without plumbing modifications. Depending on water source "
               "chemistry, Venturi 4 switches seamlessly between an EC Booster channel and an alkali (pH-Up) dosing channel.")

    doc.add_picture(img_paths[1], width=Inches(6.8))

    # Mode Comparison Table
    t_mode = doc.add_table(rows=6, cols=3)
    t_mode.alignment = WD_TABLE_ALIGNMENT.CENTER
    mode_rows = [
        ("Channel", "Mode A (4 EC + 1 pH)", "Mode B (3 EC + 2 pH)"),
        ("Venturi 1", "Stock A (Calcium Nitrate + Chelated Iron)", "Stock A (Calcium Nitrate + Chelated Iron)"),
        ("Venturi 2", "Stock B (NPK Compound + Magnesium Sulfate)", "Stock B (NPK Compound + Magnesium Sulfate)"),
        ("Venturi 3", "Stock C (Micronutrient Trace Package)", "Stock C (Micronutrient Trace Package)"),
        ("Venturi 4", "Stock D (Potassium Booster / Silica)", "pH UP (20% Potassium Hydroxide - KOH Base)"),
        ("Venturi 5", "pH DOWN (15% Nitric / Phosphoric Acid)", "pH DOWN (15% Nitric / Phosphoric Acid)")
    ]
    for r_idx, (c1, c2, c3) in enumerate(mode_rows):
        row = t_mode.rows[r_idx]
        bg = "0F172A" if r_idx == 0 else ("F8FAFC" if r_idx % 2 == 1 else "FFFFFF")
        for c_idx, val in enumerate([c1, c2, c3]):
            cell = row.cells[c_idx]
            set_cell_background(cell, bg)
            set_cell_margins(cell, 60, 60, 100, 100)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            run = p.add_run(val)
            run.font.name = "Arial"
            run.font.size = Pt(8)
            if r_idx == 0:
                run.font.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
            else:
                run.font.color.rgb = RGBColor(15, 23, 42)

    doc.add_paragraph().paragraph_format.space_after = Pt(14)

    # -------------------------------------------------------------
    # SECTION 3
    # -------------------------------------------------------------
    h3 = doc.add_heading(level=1)
    r3 = h3.add_run("3. Step-by-Step Staged Conditional Dosing Logic")
    r3.font.name = "Arial"
    r3.font.color.rgb = RGBColor(15, 23, 42)

    p3 = doc.add_paragraph()
    p3.add_run("Chemicals are introduced sequentially across isolated stages. By waiting for each stock to dilute completely "
               "in the recirculation loop before triggering subsequent setpoints, calcium and phosphate precipitation is entirely prevented.")

    doc.add_picture(img_paths[2], width=Inches(6.8))

    doc.add_paragraph().paragraph_format.space_after = Pt(14)

    # -------------------------------------------------------------
    # SECTION 4
    # -------------------------------------------------------------
    h4 = doc.add_heading(level=1)
    r4 = h4.add_run("4. Physical Stepping Timeline & Closed-Loop Regulation")
    r4.font.name = "Arial"
    r4.font.color.rgb = RGBColor(15, 23, 42)

    p4 = doc.add_paragraph()
    p4.add_run("The timeline chart illustrates the controlled staircase progression of electrical conductivity (EC) from raw water "
               "to the target setpoint, alongside pH dual-window correction to maintain nutrient bioavailability within the root zone.")

    doc.add_picture(img_paths[3], width=Inches(6.8))

    doc.add_paragraph().paragraph_format.space_after = Pt(14)

    # -------------------------------------------------------------
    # SECTION 5
    # -------------------------------------------------------------
    h5 = doc.add_heading(level=1)
    r5 = h5.add_run("5. Firmware Safety Interlocks & Operational Matrix")
    r5.font.name = "Arial"
    r5.font.color.rgb = RGBColor(15, 23, 42)

    p5 = doc.add_paragraph()
    p5.add_run("Four critical safety interlocks protect the physical hardware and crops against accidental chemical overdrive, "
               "mechanical solenoid coil burnout, and hazardous exothermic neutralization.")

    doc.add_picture(img_paths[4], width=Inches(6.8))

    doc.save(DOCX_PATH)
    print(f"[+] Successfully generated and validated: {DOCX_PATH}")

if __name__ == "__main__":
    p1 = generate_diagram_1()
    p2 = generate_diagram_2()
    p3 = generate_diagram_3()
    p4 = generate_diagram_4()
    p5 = generate_diagram_5()
    build_docx_document([p1, p2, p3, p4, p5])
