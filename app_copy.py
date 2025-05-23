# app.py

import streamlit as st
import pandas as pd
import time
import sqlite3
import json
from datetime import datetime
from final_forward_copy import combined, accel_phase, race_energy
import matplotlib
matplotlib.use("Agg")
import requests


st.set_page_config(layout="wide")
main_title = st.title("Team Pursuit Race Simulator")
print("🔁 Version 2025-05-08-A")
# --- Setup database ---
conn = sqlite3.connect("simulations.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS optimizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    total_races INTEGER,
    runtime_seconds REAL,
    result_json TEXT
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS simulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    chosen_athletes TEXT,
    start_order TEXT,
    switch_schedule TEXT,
    peel_location INTEGER,
    final_order TEXT,
    final_time REAL,
    final_distance REAL,
    final_half_lap_count INTEGER,
    W_rem TEXT
)
""")
conn.commit()

drafting_percents = [1.0, 0.58, 0.52, 0.53]

# --- Helper functions ---
def switch_schedule_description(switch_schedule):
    return [i + 1 for i, v in enumerate(switch_schedule) if v == 1]

def save_simulation_to_db(record):
    cursor.execute("""
        INSERT INTO simulations (
            timestamp, chosen_athletes, start_order, switch_schedule,
            peel_location, final_order, final_time, final_distance,
            final_half_lap_count, W_rem
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.fromtimestamp(record["timestamp"]).isoformat(),
        json.dumps(record["chosen_athletes"]),
        json.dumps(record["start_order"]),
        json.dumps(record["switch_schedule"]),
        record["peel_location"],
        json.dumps(record["final_order"]),
        record["final_time"],
        record["final_distance"],
        record["final_half_lap_count"],
        json.dumps(record["W_rem"]),
    ))
    conn.commit()

def save_optimization_to_db(runtime, total_races, top_results):
    cursor.execute("""
        INSERT INTO optimizations (
            timestamp, total_races, runtime_seconds, result_json
        ) VALUES (?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        total_races,
        runtime,
        json.dumps(top_results),
    ))
    conn.commit()

def plot_switch_strategy(start_order, switch_schedule):
    import matplotlib.pyplot as plt
    colors = {rider: color for rider, color in zip(start_order, ['#2ca02c', '#1f77b4', '#ff7f0e', '#d62728'])}
    lead_segments = []
    leader_index = 0
    start = 0

    for i, switch in enumerate(switch_schedule):
        if switch == 1:
            duration = i + 1 - start
            lead_segments.append({"rider": start_order[leader_index % len(start_order)], "start": start, "duration": duration})
            start = i + 1
            leader_index += 1

    if start < len(switch_schedule):
        lead_segments.append({"rider": start_order[leader_index % len(start_order)], "start": start, "duration": len(switch_schedule) - start + 1})

    fig, ax = plt.subplots(figsize=(10, 4))
    y_levels = {rider: i for i, rider in enumerate(reversed(start_order))}

    for segment in lead_segments:
        rider = segment["rider"]
        y = y_levels[rider]
        ax.broken_barh([(segment["start"], segment["duration"])], (y - 0.4, 0.8), facecolors=colors[rider])
        ax.text(segment["start"] + segment["duration"] / 2, y, f'{segment["duration"]}', ha="center", va="center", fontsize=9, color="white")

    ax.set_yticks(list(y_levels.values()))
    ax.set_yticklabels(list(y_levels.keys()))
    ax.set_xlabel("Half-laps")
    ax.set_ylabel("Rider")
    ax.set_title("Turn Strategy")
    ax.grid(True, axis="x")
    st.pyplot(fig)
    plt.close(fig)

model_type = st.radio("Select Model Type",
    ["Pro", "Lite"],
    index=None,
)

if model_type == "Lite":
    st.markdown('***User Input Model***')
    # --- Main Tabs ---
    tab1, tab2, tab3, tab4 = st.tabs(["Data Input", "Advanced Settings", "Simulate Race", "Previous Simulations"])

    # --- Tab 1: Upload Data ---
    with tab1:
        uploaded_file = st.file_uploader("Upload Performance Data Excel File", type=["xlsx"])

    # --- Tab 2: Advanced Settings ---
    with tab2:
        rho_input = st.number_input("**Air Density (kg/m³)**", value=1.225, step=0.001, format="%.3f")
        Crr_input = st.number_input("**Rolling Resistance (Crr)**", value=0.0018, step=0.0001, format="%.4f")
        v0_input = st.number_input("**Initial Velocity (m/s)**", value=0.5, step=0.01, format="%.2f")

    # --- Tab 3: Simulate Race ---
    with tab3:
        if uploaded_file:
            left_col, right_col = st.columns([1, 3])

            with left_col:
                df_athletes = pd.read_excel(uploaded_file)

                available_athletes = (
                    df_athletes["Name"]
                    .str.extract(r"M(\d+)")[0]
                    .dropna()
                    .astype(int)
                    .tolist()
                )

                chosen_athletes = st.multiselect("Select 4 Athletes", available_athletes)
                st.markdown(f"Selected Riders: {sorted(chosen_athletes)}.")

                if len(chosen_athletes) == 4:
                    start_order = st.multiselect("Initial Rider Order", sorted(chosen_athletes))
                    st.markdown(f"Initial Starting Order: {start_order}")

                    st.subheader("Turn Schedule (32 half-laps)")
                    switch_schedule = []
                    peel_schedule = []

                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Turn (1 = Turn after this half-lap)**")
                        for i in range(31):
                            val = st.checkbox(f"{i+1}", key=f"switch_{i}")
                            switch_schedule.append(1 if val else 0)

                    with col2:
                        st.markdown("**Peel (1 = 3rd rider peel here)**")
                        for i in range(31):
                            val = st.checkbox(f"{i+1}", key=f"peel_{i}")
                            peel_schedule.append(1 if val else 0)

                    try:
                        peel_location = peel_schedule.index(1)
                    except ValueError:
                        peel_location = None

                    simulate = st.button("Simulate Race")
                    if simulate:
                        st.success("Simulation Complete!")
                else:
                    simulate = False
                    st.warning("Please select exactly 4 riders.")

            with right_col:
                if simulate and start_order and peel_location is not None:
                    with st.spinner("Running simulation..."):
                        v_SS, t_final, W_rem, slope, P_const, t_half_lap, final_order = combined(
                            accel_phase,
                            race_energy,
                            peel_location,
                            switch_schedule,
                            drag_adv=[1, 0.58, 0.52, 0.53],
                            df=df_athletes,
                            chosen_athletes=chosen_athletes,
                            order=start_order,
                            rho=rho_input,
                            Crr=Crr_input,
                            v0=v0_input
                        )

                    with st.container():
                        row1 = st.columns(3)
                        with row1[0]:
                            st.markdown("**Total Time**")
                            st.markdown(f"{t_final:.2f} s")
                        with row1[1]:
                            st.markdown("**Final Order**")
                            st.markdown(", ".join(str(rider) for rider in final_order))
                        with row1[2]:
                            st.markdown("**Turns:**")
                            switches = switch_schedule_description(switch_schedule)
                            st.markdown(", ".join(str(s) for s in switches))

                        st.subheader("Turn Strategy Timeline")
                        plot_switch_strategy(start_order, switch_schedule)

                        st.subheader("W′ Remaining per Rider:")
                        for idx, energy_left in enumerate(W_rem):
                            st.write(f"**Rider {idx+1}**: {energy_left:.1f} J")

                        simulation_record = {
                            "timestamp": time.time(),
                            "chosen_athletes": chosen_athletes,
                            "start_order": start_order,
                            "switch_schedule": switch_schedule,
                            "peel_location": peel_location,
                            "final_order": final_order,
                            "final_time": t_final,
                            "final_distance": None,
                            "final_half_lap_count": None,
                            "W_rem": W_rem,
                        }
                        save_simulation_to_db(simulation_record)

        else:
            st.info("Please upload a dataset first.")

    # --- Tab 4: Previous Simulations ---
    with tab4:
        st.subheader("Download Past Simulations")
        cursor.execute("SELECT * FROM simulations ORDER BY id DESC")
        all_rows = cursor.fetchall()

        if all_rows:
            df_download = pd.DataFrame([
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "chosen_athletes": json.loads(row[2]),
                    "start_order": json.loads(row[3]),
                    "switch_schedule": json.loads(row[4]),
                    "peel_location": row[5],
                    "final_order": json.loads(row[6]),
                    "final_time": row[7],
                    "final_distance": row[8],
                    "final_half_lap_count": row[9],
                    "W_rem": json.loads(row[10]),
                }
                for row in all_rows
            ])

            st.download_button(
                label="Download Simulations as CSV",
                data=df_download.to_csv(index=False).encode("utf-8"),
                file_name="simulations.csv",
                mime="text/csv",
            )

            for i, row in df_download.iterrows():
                with st.expander(f"Simulation #{row['id']} — {row['timestamp']}"):
                    st.write(f"**Chosen Athletes:** {row['chosen_athletes']}")
                    st.write(f"**Start Order:** {row['start_order']}")
                    st.write(f"**Final Order:** {row['final_order']}")
                    st.write(f"**Peel Location:** {row['peel_location']}")
                    st.write(f"**Total Time:** {row['final_time']:.2f} seconds")
                    st.write(f"**Turn Schedule:** {switch_schedule_description(row['switch_schedule'])}")
                    st.subheader("W′ Remaining per Rider:")
                    for idx, energy_left in enumerate(row["W_rem"]):
                        st.write(f"**Rider {idx+1}**: {float(energy_left):.1f} J")
                    st.subheader("Turn Strategy Timeline")
                    try:
                        plot_switch_strategy(row["start_order"], row["switch_schedule"])
                    except Exception as e:
                        st.warning("Couldn't render strategy timeline for this entry.")
                    delete = st.button(f"Delete Simulation #{row['id']}", key=f"delete_{row['id']}")
                    if delete:
                        cursor.execute("DELETE FROM simulations WHERE id = ?", (row["id"],))
                        conn.commit()
                        st.success(f"Simulation #{row['id']} deleted successfully.")
                        st.rerun()
        else:
            st.info("No simulations available yet.")
elif model_type == "Pro":
    st.markdown('***Optimization Model***')
    tab5, tab6, tab7, tab8 = st.tabs(["Data Input", "Advanced Settings", "Simulate Race", "Previous Simulations"])
    with tab5: 
        uploaded_file_opt = st.file_uploader("Upload Performance Data Excel File", type=["xlsx"])
    with tab6:
        rho_input_opt = st.number_input("**Air Density (kg/m³)**", value=1.225, step=0.001, format="%.3f")
        Crr_input_opt = st.number_input("**Rolling Resistance (Crr)**", value=0.0018, step=0.0001, format="%.4f")
        v0_input_opt = st.number_input("**Initial Velocity (m/s)**", value=0.5, step=0.01, format="%.2f")
    with tab7:
        if uploaded_file_opt:
            if st.button("Run Optimization Model"):
                with st.spinner("Initializing VM and running optimization..."):
                    try:
                        st.markdown("🌐 Sending startup request to VM...")
                        cloud_function_url = "https://us-central1-team-pursuit-optimizer.cloudfunctions.net/start-vm-lite"

                        vm_start_response = requests.post(cloud_function_url, timeout=10)
                        if vm_start_response.status_code == 200:
                            st.success("✅ VM start requested.")
                        st.markdown("📤 Sending optimization request...")
                        response = requests.post(
                            "http://35.209.48.32:8000/run_optimization",
                            timeout=3600,
                            headers={"Content-Type": "application/json"},
                            json={}
                        )

                        if response.status_code == 200:
                            result = response.json()
                            save_optimization_to_db(
                                result["runtime_seconds"],
                                result["total_races_simulated"],
                                result["top_results"]
                            )
                            st.success("✅ Optimization Complete!")
                            st.markdown(f"**Total Races Simulated:** {result['total_races_simulated']}")
                            st.markdown(f"**Runtime:** {result['runtime_seconds']} seconds")

                            st.subheader("Top 5 Results:")
                            for i, res in enumerate(result["top_results"], 1):
                                best_schedule = min(res["schedule"].items(), key=lambda x: x[1])
                                st.markdown(f"**#{i}** – Time: `{round(best_schedule[1], 2)}s`, Schedule: `{best_schedule[0]}`")

                        else:
                            st.error(f"❌ Backend error. Status code: {response.status_code}")

                    except Exception as e:
                        st.error(f"❌ Request failed: {e}")

        else:
            st.info("Please upload a dataset first.")
        with tab8:
            st.subheader("Previous Optimization Runs")
            cursor.execute("SELECT * FROM optimizations ORDER BY id DESC")
            rows = cursor.fetchall()

            if rows:
                df_opt = pd.DataFrame([
                    {
                        "id": row[0],
                        "timestamp": row[1],
                        "total_races": row[2],
                        "runtime_seconds": row[3],
                        "top_results": json.loads(row[4])
                    }
                    for row in rows
                ])

                st.download_button(
                    "Download as CSV",
                    data=df_opt.to_csv(index=False).encode("utf-8"),
                    file_name="optimizations.csv",
                    mime="text/csv",
                )

                for i, row in df_opt.iterrows():
                    with st.expander(f"Optimization #{row['id']} — {row['timestamp']}"):
                        for j, res in enumerate(row["top_results"], 1):
                            if isinstance(res["schedule"], dict):
                                best_key, best_time = min(res["schedule"].items(), key=lambda x: x[1])
                                st.markdown(f"**#{j}** – Time: `{round(best_time, 2)}s`, Schedule: `{best_key}`")
                                st.markdown(f"**Runtime:** `{row['runtime_seconds']:.2f} seconds`")
                            else:
                                st.markdown(f"**#{j}** – Time: `{res['time']}s`, Schedule: `{res['schedule']}`")

                        delete = st.button(f"Delete Simulation #{row['id']}", key=f"delete_{row['id']}")
                        if delete:
                            cursor.execute("DELETE FROM optimizations WHERE id = ?", (row["id"],))
                            conn.commit()
                            st.success(f"Simulation #{row['id']} deleted successfully.")
                            st.rerun()

            else:
                st.info("No optimizations stored yet.")







