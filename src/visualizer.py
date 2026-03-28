"""
Interactive Gantt chart visualizer for Job Shop Scheduling solutions.

Plots all machines on the y-axis, even if no operations are assigned to them.
Hover over an operation bar to see its name, job name, and operation index.
"""

import json
import argparse
from pathlib import Path

import plotly.graph_objects as go


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def visualize(jobs_path: str, machines_path: str, schedule_path: str, output_html: str | None = None):
    """Create an interactive Gantt chart of the schedule."""
    jobs_data = load_jsonl(jobs_path)
    machines_data = load_jsonl(machines_path)
    schedule_data = load_jsonl(schedule_path)

    # Build job lookup for due_time info
    jobs_by_id = {j["job_id"]: j for j in jobs_data}

    # Build ordered list of all machines (grouped by machine group)
    all_machines = []  # list of (machine_id, group_name, machine_name)
    for group in machines_data:
        for m in group["machines"]:
            all_machines.append((m["machine_id"], group["name"], m["name"]))

    machine_ids = [m[0] for m in all_machines]
    machine_labels = [f"{m[0]} ({m[2]})" for m in all_machines]

    # Assign a color to each job
    job_ids = [j["job_id"] for j in jobs_data]
    colors = _generate_colors(len(job_ids))
    job_color = {jid: colors[i] for i, jid in enumerate(job_ids)}

    fig = go.Figure()

    # Collect operations from schedule
    for sched_job in schedule_data:
        jid = sched_job["job_id"]
        job_def = jobs_by_id.get(jid)
        job_name = sched_job.get("name", jid)
        color = job_color.get(jid, "rgb(128,128,128)")

        # Build op index lookup from job definition
        op_index_map = {}
        if job_def:
            for idx, op in enumerate(job_def["operations"], start=1):
                op_index_map[op["op_id"]] = idx

        for op in sched_job["operations"]:
            assigned = op.get("assigned_machine")
            if assigned is None or assigned not in machine_ids:
                continue

            op_idx = op_index_map.get(op["op_id"], "?")
            y_pos = machine_ids.index(assigned)

            hover_text = (
                f"<b>Operation:</b> {op['name']}<br>"
                f"<b>Job:</b> {job_name} ({jid})<br>"
                f"<b>Op index:</b> {op_idx} of {len(sched_job['operations'])}<br>"
                f"<b>Machine:</b> {assigned}<br>"
                f"<b>Time:</b> {op['start_time']} → {op['end_time']}"
            )

            fig.add_trace(go.Bar(
                x=[op["end_time"] - op["start_time"]],
                y=[assigned],
                base=[op["start_time"]],
                orientation="h",
                marker=dict(color=color, line=dict(color="black", width=1)),
                hovertemplate=hover_text + "<extra></extra>",
                name=f"{jid}: {op['name']}",
                showlegend=False,
                text=f"{job_name} ({jid}) - {op['name']} ({op['op_id']})",
                textposition="inside",
                textfont=dict(color="white", size=10),
            ))

    # Add a custom legend for jobs
    for jid in job_ids:
        job_name = jobs_by_id[jid]["name"]
        fig.add_trace(go.Bar(
            x=[0], y=[machine_ids[0]], base=[0],
            orientation="h",
            marker=dict(color=job_color[jid]),
            name=f"{jid} ({job_name})",
            showlegend=True,
            hoverinfo="skip",
            visible="legendonly" if False else True,
        ))

    fig.update_layout(
        title="Job Shop Schedule - Gantt Chart",
        xaxis_title="Time",
        yaxis=dict(
            title="Machine",
            categoryorder="array",
            categoryarray=list(reversed(machine_ids)),
            ticktext=list(reversed(machine_labels)),
            tickvals=list(reversed(machine_ids)),
        ),
        barmode="overlay",
        height=max(400, len(machine_ids) * 60 + 150),
        hovermode="closest",
        legend=dict(title="Jobs"),
    )

    if output_html:
        fig.write_html(output_html)
        print(f"Gantt chart saved to {output_html}")
    else:
        fig.show()


def _generate_colors(n: int) -> list[str]:
    """Generate n visually distinct colors."""
    base_colors = [
        "rgb(31, 119, 180)",
        "rgb(255, 127, 14)",
        "rgb(44, 160, 44)",
        "rgb(214, 39, 40)",
        "rgb(148, 103, 189)",
        "rgb(140, 86, 75)",
        "rgb(227, 119, 194)",
        "rgb(127, 127, 127)",
        "rgb(188, 189, 34)",
        "rgb(23, 190, 207)",
    ]
    if n <= len(base_colors):
        return base_colors[:n]
    # Cycle if more jobs than colors
    return [base_colors[i % len(base_colors)] for i in range(n)]


def main():
    parser = argparse.ArgumentParser(description="Visualize a job shop schedule as a Gantt chart")
    parser.add_argument("jobs", help="Path to jobs.jsonl")
    parser.add_argument("machines", help="Path to machines.jsonl")
    parser.add_argument("schedule", help="Path to proposed_schedule.jsonl")
    parser.add_argument("-o", "--output", help="Output HTML file (if omitted, opens in browser)")
    args = parser.parse_args()

    visualize(args.jobs, args.machines, args.schedule, args.output)


if __name__ == "__main__":
    main()
