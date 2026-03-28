"""
Window-based solver for Flexible Job Shop Scheduling using OR-Tools CP-SAT.

Schedules operations on bottleneck machine groups within a time window.
Non-bottleneck groups are treated as having infinite capacity (no variables
created for them), but their processing times are preserved in the time chain.
"""

import json
import argparse

from ortools.sat.python import cp_model


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def solve(
    jobs_data: list[dict],
    machines_data: list[dict],
    bottleneck_groups: list[str],
    machine_availability: dict[str, dict],
    time_limit_seconds: float = 60.0,
) -> dict:
    """Solve FJSP on a time window focusing on bottleneck machine groups.

    Args:
        jobs_data: Job definitions (from jobs.jsonl format).
        machines_data: Machine group definitions (from machines.jsonl format).
        bottleneck_groups: Machine group names to schedule (others = infinite capacity).
        machine_availability: Per-machine time windows. Maps machine_id to
            {"start_time": int, "end_time": int | None}. start_time is required,
            end_time is optional (None = unbounded).
        time_limit_seconds: Solver time limit.

    Returns:
        Dict with: status, schedule, total_reward, job_results, and optionally error.
    """
    # --- Build machine group index ---
    group_to_machines: dict[str, list[str]] = {}
    for group in machines_data:
        group_to_machines[group["name"]] = [m["machine_id"] for m in group["machines"]]

    bottleneck_set = set(bottleneck_groups)

    for bg in bottleneck_groups:
        if bg not in group_to_machines:
            return {
                "status": "ERROR",
                "schedule": [],
                "total_reward": 0,
                "job_results": [],
                "error": f"Bottleneck group '{bg}' not found in machines data.",
            }

    # --- Compute horizon (finite upper bound for variable domains) ---
    total_proc = sum(
        op["processing_time"] for job in jobs_data for op in job["operations"]
    )
    max_due = max((job["due_time"] for job in jobs_data), default=0)

    # Global bounds derived from per-machine availability
    global_start = min(
        (a["start_time"] for a in machine_availability.values()),
        default=0,
    )
    finite_ends = [
        a["end_time"] for a in machine_availability.values()
        if a.get("end_time") is not None
    ]
    if finite_ends:
        horizon = max(max(finite_ends), max_due, global_start + total_proc)
    else:
        horizon = max(max_due, global_start + total_proc) + total_proc

    # --- Build CP-SAT model ---
    model = cp_model.CpModel()

    # Storage
    op_vars: dict[tuple[str, str], dict] = {}
    machine_intervals: dict[str, list] = {}  # machine_id -> [optional interval vars]
    job_on_time: dict[str, tuple] = {}       # job_id -> (BoolVar, reward)
    all_end_vars: list[cp_model.IntVar] = []  # all operation end vars

    for job in jobs_data:
        jid = job["job_id"]
        prev_end = None

        for op in job["operations"]:
            oid = op["op_id"]
            duration = op["processing_time"]
            allowed_groups = op["machines"]

            # Each operation belongs to exactly one machine group
            op_group = allowed_groups[0]
            is_bottleneck = op_group in bottleneck_set

            # Time variables (all operations need these for the time chain)
            start_var = model.NewIntVar(global_start, horizon, f"s_{jid}_{oid}")
            end_var = model.NewIntVar(global_start, horizon, f"e_{jid}_{oid}")
            interval_var = model.NewIntervalVar(
                start_var, duration, end_var, f"iv_{jid}_{oid}"
            )

            machine_options: list[tuple[str, cp_model.IntVar]] = []

            if is_bottleneck:
                # Create optional intervals for each machine in the group
                presence_vars = []

                for mid in group_to_machines[op_group]:
                    avail = machine_availability.get(mid, {})
                    m_start = avail.get("start_time", global_start)
                    m_end = avail.get("end_time")  # None = unbounded

                    pres = model.NewBoolVar(f"p_{jid}_{oid}_{mid}")
                    opt_iv = model.NewOptionalIntervalVar(
                        start_var, duration, end_var, pres,
                        f"o_{jid}_{oid}_{mid}",
                    )
                    presence_vars.append(pres)
                    machine_options.append((mid, pres))

                    # Per-machine availability constraints
                    model.Add(start_var >= m_start).OnlyEnforceIf(pres)
                    if m_end is not None:
                        model.Add(end_var <= m_end).OnlyEnforceIf(pres)

                    if mid not in machine_intervals:
                        machine_intervals[mid] = []
                    machine_intervals[mid].append(opt_iv)

                model.AddExactlyOne(presence_vars)

            # Precedence within job
            if prev_end is not None:
                model.Add(start_var >= prev_end)
            elif "earliest_start" in job:
                # First operation of a partially-fixed job (used by RHO)
                model.Add(start_var >= job["earliest_start"])
            prev_end = end_var

            all_end_vars.append(end_var)

            op_vars[(jid, oid)] = {
                "start": start_var,
                "end": end_var,
                "interval": interval_var,
                "machine_options": machine_options,
                "is_bottleneck": is_bottleneck,
                "op_group": op_group,
            }

        # On-time indicator for objective
        if prev_end is not None:
            on_time = model.NewBoolVar(f"ot_{jid}")
            model.Add(prev_end <= job["due_time"]).OnlyEnforceIf(on_time)
            model.Add(prev_end > job["due_time"]).OnlyEnforceIf(on_time.Not())
            job_on_time[jid] = (on_time, job["reward"])

    # No-overlap per bottleneck machine
    for mid, intervals in machine_intervals.items():
        model.AddNoOverlap(intervals)

    # Objective: maximize(W * total_reward - sum_of_all_op_end_times)
    # W is large enough that reward always dominates. The secondary term
    # pushes every operation as early as possible, which is important for
    # rolling horizon — finishing early leaves room for the next window.
    num_ops = len(all_end_vars)
    W = horizon * num_ops + 1
    reward_term = sum(reward * var for var, reward in job_on_time.values())
    earliness_term = sum(all_end_vars)
    model.Maximize(W * reward_term - earliness_term)

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    status_code = solver.Solve(model)

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status_str = status_map.get(status_code, "UNKNOWN")

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": status_str,
            "schedule": [],
            "total_reward": 0,
            "job_results": [],
            "error": (
                f"Solver returned {status_str}. "
                f"The machine availability windows may be too tight."
            ),
        }

    # --- Extract solution ---
    schedule = []
    job_results = []

    for job in jobs_data:
        jid = job["job_id"]
        sched_ops = []
        last_end = 0

        for op in job["operations"]:
            oid = op["op_id"]
            info = op_vars[(jid, oid)]

            s = solver.Value(info["start"])
            e = solver.Value(info["end"])
            last_end = max(last_end, e)

            # Determine assigned machine
            assigned = None
            if info["is_bottleneck"] and info["machine_options"]:
                for mid, pres in info["machine_options"]:
                    if solver.Value(pres):
                        assigned = mid
                        break
            else:
                # Non-bottleneck: assign first machine from the group
                assigned = group_to_machines[info["op_group"]][0]

            sched_ops.append({
                "op_id": oid,
                "name": op["name"],
                "assigned_machine": assigned,
                "start_time": s,
                "end_time": e,
            })

        schedule.append({
            "job_id": jid,
            "name": job["name"],
            "operations": sched_ops,
        })

        on_time_var, reward = job_on_time.get(jid, (None, 0))
        is_on_time = bool(solver.Value(on_time_var)) if on_time_var is not None else False
        job_results.append({
            "job_id": jid,
            "name": job["name"],
            "due_time": job["due_time"],
            "end_time": last_end,
            "on_time": is_on_time,
            "reward": reward if is_on_time else 0,
        })

    return {
        "status": status_str,
        "schedule": schedule,
        "total_reward": sum(jr["reward"] for jr in job_results),
        "job_results": job_results,
    }


def save_schedule(schedule: list[dict], path: str):
    """Save schedule to JSONL file."""
    with open(path, "w") as f:
        for entry in schedule:
            f.write(json.dumps(entry) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Solve a job shop scheduling problem on a time window"
    )
    parser.add_argument("jobs", help="Path to jobs.jsonl")
    parser.add_argument("machines", help="Path to machines.jsonl")
    parser.add_argument(
        "availability",
        help='Path to availability JSON: {"machine_id": {"start_time": int, "end_time": int|null}, ...}',
    )
    parser.add_argument(
        "-b", "--bottleneck", nargs="+", required=True,
        help="Bottleneck machine group names (e.g. M1 M4)",
    )
    parser.add_argument(
        "-t", "--time-limit", type=float, default=60.0,
        help="Solver time limit in seconds (default: 60)",
    )
    parser.add_argument("-o", "--output", help="Output schedule JSONL path")
    args = parser.parse_args()

    jobs_data = load_jsonl(args.jobs)
    machines_data = load_jsonl(args.machines)

    with open(args.availability) as f:
        machine_availability = json.load(f)

    result = solve(
        jobs_data,
        machines_data,
        bottleneck_groups=args.bottleneck,
        machine_availability=machine_availability,
        time_limit_seconds=args.time_limit,
    )

    print(f"Status: {result['status']}")

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"Total reward: {result['total_reward']}")
    print("\nJob results:")
    for jr in result["job_results"]:
        status = "ON TIME" if jr["on_time"] else "LATE"
        print(
            f"  {jr['job_id']} ({jr['name']}): end={jr['end_time']}, "
            f"due={jr['due_time']}, {status}, reward={jr['reward']}"
        )

    if args.output:
        save_schedule(result["schedule"], args.output)
        print(f"\nSchedule saved to {args.output}")


if __name__ == "__main__":
    main()
