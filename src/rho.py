"""
Rolling Horizon Optimization (RHO) for Job Shop Scheduling.

Breaks a large scheduling problem into overlapping windows, solves each with
the CP-SAT solver, and rolls forward by fixing completed jobs.

Pipeline:
  1. heuristic_order_jobs  — order all jobs by priority
  2. run_rho               — iteratively: form window → solve → fix → roll
     ├── prepare_window_jobs
     ├── solver.solve
     ├── select_jobs_to_fix
     ├── propagate_fixes
     └── build_complete_schedule
"""

import json
import os

from solver import solve, load_jsonl, save_schedule


# ---------------------------------------------------------------------------
# Heuristic
# ---------------------------------------------------------------------------

def heuristic_order_jobs(jobs_data: list[dict]) -> list[str]:
    """Order jobs by slack time ascending, then reward descending.

    Slack = due_time - total_processing_time.
    Tighter deadlines (smaller slack) get scheduled first.
    """
    def key(job):
        total_proc = sum(op["processing_time"] for op in job["operations"])
        slack = job["due_time"] - total_proc
        return (slack, -job["reward"])

    return [j["job_id"] for j in sorted(jobs_data, key=key)]


# ---------------------------------------------------------------------------
# Fix & Propagate
# ---------------------------------------------------------------------------

def select_jobs_to_fix(schedule: list[dict], k: int) -> list[str]:
    """Return the k jobs that complete earliest in the schedule."""
    completions = []
    for sj in schedule:
        last_end = max(op["end_time"] for op in sj["operations"])
        completions.append((sj["job_id"], last_end))
    completions.sort(key=lambda x: x[1])
    return [jid for jid, _ in completions[:k]]


def propagate_fixes(
    schedule: list[dict],
    jobs_data: list[dict],
    fix_job_ids: set[str],
    prev_fixed_ops: dict[tuple, dict],
) -> tuple[dict[tuple, dict], dict[str, list[str]]]:
    """Fix jobs and propagate: if an operation is fixed on a machine, all
    operations earlier on that machine are also fixed; within a job, all
    operations before a fixed one are also fixed.

    Returns:
        all_fixed_ops:  {(jid, oid): op_dict} — complete set of fixed ops.
        partial_fixes:  {jid: [oid, ...]} — for jobs only partially fixed.
    """
    sched_by_id = {s["job_id"]: s for s in schedule}
    jobs_by_id = {j["job_id"]: j for j in jobs_data}

    fixed_ops = dict(prev_fixed_ops)

    # Add all ops from newly fully-fixed jobs
    for jid in fix_job_ids:
        if jid not in sched_by_id:
            continue
        for op in sched_by_id[jid]["operations"]:
            fixed_ops[(jid, op["op_id"])] = {
                "job_id": jid,
                "op_id": op["op_id"],
                "assigned_machine": op["assigned_machine"],
                "start_time": op["start_time"],
                "end_time": op["end_time"],
            }

    # Iteratively propagate until stable
    unfixed_jids = [jid for jid in sched_by_id if jid not in fix_job_ids]
    changed = True
    while changed:
        changed = False

        # Per-machine: latest fixed end time
        machine_fix_end: dict[str, int] = {}
        for fop in fixed_ops.values():
            mid = fop["assigned_machine"]
            machine_fix_end[mid] = max(machine_fix_end.get(mid, 0), fop["end_time"])

        for jid in unfixed_jids:
            job_def = jobs_by_id[jid]
            op_order = [op["op_id"] for op in job_def["operations"]]
            sched_ops = {op["op_id"]: op for op in sched_by_id[jid]["operations"]}

            # Find ops on machines that are scheduled before a fixed op
            machine_fixed = set()
            for oid in op_order:
                if (jid, oid) in fixed_ops:
                    continue
                if oid not in sched_ops:
                    continue
                op = sched_ops[oid]
                mid = op["assigned_machine"]
                if mid in machine_fix_end and op["start_time"] < machine_fix_end[mid]:
                    machine_fixed.add(oid)

            # Propagate within job: if op i is fixed, all 1..i-1 are too
            last_fixed_idx = -1
            for idx, oid in enumerate(op_order):
                if oid in machine_fixed or (jid, oid) in fixed_ops:
                    last_fixed_idx = idx

            for idx in range(last_fixed_idx + 1):
                oid = op_order[idx]
                if (jid, oid) not in fixed_ops and oid in sched_ops:
                    op = sched_ops[oid]
                    fixed_ops[(jid, oid)] = {
                        "job_id": jid,
                        "op_id": oid,
                        "assigned_machine": op["assigned_machine"],
                        "start_time": op["start_time"],
                        "end_time": op["end_time"],
                    }
                    changed = True

    # Build partial_fixes summary
    partial_fixes: dict[str, list[str]] = {}
    for jid in unfixed_jids:
        job_def = jobs_by_id[jid]
        op_order = [op["op_id"] for op in job_def["operations"]]
        fixed_in_job = [oid for oid in op_order if (jid, oid) in fixed_ops]
        if fixed_in_job:
            partial_fixes[jid] = fixed_in_job

    return fixed_ops, partial_fixes


# ---------------------------------------------------------------------------
# Window Preparation
# ---------------------------------------------------------------------------

def compute_availability(
    base_availability: dict[str, dict],
    fixed_ops: dict[tuple, dict],
) -> dict[str, dict]:
    """Set each machine's start_time to after the latest fixed op on it."""
    avail = {mid: dict(v) for mid, v in base_availability.items()}
    for fop in fixed_ops.values():
        mid = fop["assigned_machine"]
        if mid in avail:
            avail[mid]["start_time"] = max(avail[mid]["start_time"], fop["end_time"])
        else:
            avail[mid] = {"start_time": fop["end_time"], "end_time": None}
    return avail


def prepare_window_jobs(
    jobs_data: list[dict],
    window_job_ids: list[str],
    partial_fixes: dict[str, list[str]],
    fixed_ops: dict[tuple, dict],
) -> list[dict]:
    """Build job list for the solver. Remove fixed ops, set earliest_start."""
    jobs_by_id = {j["job_id"]: j for j in jobs_data}
    result = []

    for jid in window_job_ids:
        job = jobs_by_id[jid]
        pfixed = partial_fixes.get(jid, [])
        fixed_set = set(pfixed)

        if not fixed_set:
            result.append(dict(job))
            continue

        remaining = [op for op in job["operations"] if op["op_id"] not in fixed_set]
        if not remaining:
            continue

        last_fixed_end = max(
            fixed_ops[(jid, oid)]["end_time"] for oid in pfixed
        )
        result.append({
            **job,
            "operations": remaining,
            "earliest_start": last_fixed_end,
        })

    return result


def build_complete_schedule(
    solver_schedule: list[dict],
    partial_fixes: dict[str, list[str]],
    fixed_ops: dict[tuple, dict],
    jobs_data: list[dict],
) -> list[dict]:
    """Combine fixed ops + solver output into full schedule entries."""
    jobs_by_id = {j["job_id"]: j for j in jobs_data}
    complete = []

    for sj in solver_schedule:
        jid = sj["job_id"]
        pfixed = partial_fixes.get(jid, [])

        if not pfixed:
            complete.append(sj)
            continue

        # Fixed ops first (in original order), then solver output
        job_def = jobs_by_id[jid]
        fixed_op_dicts = []
        for op_def in job_def["operations"]:
            oid = op_def["op_id"]
            if (jid, oid) in fixed_ops:
                fop = fixed_ops[(jid, oid)]
                fixed_op_dicts.append({
                    "op_id": oid,
                    "name": op_def["name"],
                    "assigned_machine": fop["assigned_machine"],
                    "start_time": fop["start_time"],
                    "end_time": fop["end_time"],
                })

        complete.append({
            "job_id": jid,
            "name": sj["name"],
            "operations": fixed_op_dicts + sj["operations"],
        })

    return complete


# ---------------------------------------------------------------------------
# Post-Processing
# ---------------------------------------------------------------------------

def post_process_schedule(
    schedule: list[dict],
    machines_data: list[dict],
    bottleneck_groups: list[str],
) -> list[dict]:
    """Resolve conflicts on non-bottleneck machines.

    For each non-bottleneck group, greedily assign operations to machines.
    If a machine is not free at the operation's start time, delay the operation
    and cascade the delay to all subsequent operations in the same job.

    Iterates until no more delays are needed (cascading across groups may
    create new conflicts on other non-bottleneck groups).
    """
    bottleneck_set = set(bottleneck_groups)

    group_to_machines: dict[str, list[str]] = {}
    machine_to_group: dict[str, str] = {}
    for group in machines_data:
        gname = group["name"]
        group_to_machines[gname] = [m["machine_id"] for m in group["machines"]]
        for m in group["machines"]:
            machine_to_group[m["machine_id"]] = gname

    # Identify non-bottleneck (job_idx, op_idx, group) entries
    non_bn_index: list[tuple[int, int, str]] = []
    for ji, sj in enumerate(schedule):
        for oi, op in enumerate(sj["operations"]):
            mid = op["assigned_machine"]
            if mid in machine_to_group and machine_to_group[mid] not in bottleneck_set:
                non_bn_index.append((ji, oi, machine_to_group[mid]))

    # Iterate until stable (cascading delays may create new conflicts)
    for _ in range(100):
        any_delay = False

        for gname in group_to_machines:
            if gname in bottleneck_set:
                continue

            machines = group_to_machines[gname]

            # Collect current times for ops on this group
            group_ops: list[tuple[int, int, int, int]] = []
            for ji, oi, g in non_bn_index:
                if g != gname:
                    continue
                op = schedule[ji]["operations"][oi]
                group_ops.append((op["start_time"], op["end_time"], ji, oi))

            group_ops.sort(key=lambda x: x[0])

            machine_free = {mid: 0 for mid in machines}

            for _, _, ji, oi in group_ops:
                op = schedule[ji]["operations"][oi]
                current_start = op["start_time"]
                current_end = op["end_time"]
                duration = current_end - current_start

                # Find a machine free at or before current_start
                best = None
                for mid in machines:
                    if machine_free[mid] <= current_start:
                        best = mid
                        break

                if best is None:
                    # All busy — pick earliest free, delay this op + cascade
                    best = min(machines, key=lambda m: machine_free[m])
                    delay = machine_free[best] - current_start

                    # Shift this op and ALL later ops in the same job
                    job_ops = schedule[ji]["operations"]
                    for k in range(oi, len(job_ops)):
                        job_ops[k]["start_time"] += delay
                        job_ops[k]["end_time"] += delay

                    any_delay = True
                    current_end = op["end_time"]  # updated after shift

                op["assigned_machine"] = best
                machine_free[best] = current_end

        if not any_delay:
            break

    return schedule


# ---------------------------------------------------------------------------
# RHO Orchestrator
# ---------------------------------------------------------------------------

def run_rho(
    jobs_data: list[dict],
    machines_data: list[dict],
    bottleneck_groups: list[str],
    base_availability: dict[str, dict],
    window_size: int,
    fix_count: int,
    output_dir: str,
    time_limit_seconds: float = 60.0,
) -> list[dict]:
    """Run Rolling Horizon Optimization.

    Returns the final merged schedule.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Order jobs by heuristic
    ordered_ids = heuristic_order_jobs(jobs_data)
    with open(os.path.join(output_dir, "job_ordering.json"), "w") as f:
        json.dump(ordered_ids, f, indent=2)
    print(f"Job ordering (by slack): {ordered_ids}")

    # Global state
    fixed_ops: dict[tuple, dict] = {}       # (jid, oid) -> op dict
    fully_fixed: set[str] = set()
    partial_fixes: dict[str, list[str]] = {}  # jid -> [fixed oid list]
    global_schedule: dict[str, dict] = {}     # jid -> complete schedule entry
    remaining = list(ordered_ids)

    step = 0
    while remaining:
        print(f"\n{'='*60}")
        print(f"Step {step}: {len(remaining)} jobs remaining")
        print(f"{'='*60}")

        # Form window
        window_ids = remaining[:window_size]
        print(f"Window: {window_ids}")

        # Prepare jobs for solver
        window_jobs = prepare_window_jobs(
            jobs_data, window_ids, partial_fixes, fixed_ops,
        )
        save_schedule(
            window_jobs,
            os.path.join(output_dir, f"step_{step}_window_jobs.jsonl"),
        )

        # Compute availability from all fixed ops
        avail = compute_availability(base_availability, fixed_ops)
        with open(os.path.join(output_dir, f"step_{step}_availability.json"), "w") as f:
            json.dump(avail, f, indent=2)

        # Solve
        result = solve(
            window_jobs, machines_data, bottleneck_groups,
            machine_availability=avail,
            time_limit_seconds=time_limit_seconds,
        )

        print(f"Solver: {result['status']}, reward={result['total_reward']}")
        if "error" in result:
            print(f"Error: {result['error']}")
            break

        for jr in result["job_results"]:
            s = "ON TIME" if jr["on_time"] else "LATE"
            print(f"  {jr['job_id']} ({jr['name']}): end={jr['end_time']}, "
                  f"due={jr['due_time']}, {s}")

        # Save raw solver output
        save_schedule(
            result["schedule"],
            os.path.join(output_dir, f"step_{step}_solver_output.jsonl"),
        )

        # Build complete schedule (re-attach fixed ops for partially fixed jobs)
        complete = build_complete_schedule(
            result["schedule"], partial_fixes, fixed_ops, jobs_data,
        )
        save_schedule(
            complete,
            os.path.join(output_dir, f"step_{step}_complete_schedule.jsonl"),
        )

        # Update global schedule
        for entry in complete:
            global_schedule[entry["job_id"]] = entry

        # --- Fix & Propagate ---
        fix_ids = select_jobs_to_fix(complete, fix_count)
        fix_set = set(fix_ids)
        print(f"Fixing: {fix_ids}")

        fixed_ops, new_partial = propagate_fixes(
            complete, jobs_data, fix_set, fixed_ops,
        )

        # Merge partial_fixes: keep old entries for jobs not in this window
        window_set = set(window_ids)
        updated_partial: dict[str, list[str]] = {}
        for jid, ops in partial_fixes.items():
            if jid not in window_set and jid not in fully_fixed:
                updated_partial[jid] = ops
        for jid, ops in new_partial.items():
            updated_partial[jid] = ops
        partial_fixes = updated_partial

        fully_fixed.update(fix_set)

        # Save fix info
        fix_info = {
            "fully_fixed_this_step": sorted(fix_ids),
            "partial_fixes": partial_fixes,
            "total_fixed_ops": len(fixed_ops),
        }
        with open(os.path.join(output_dir, f"step_{step}_fixes.json"), "w") as f:
            json.dump(fix_info, f, indent=2)

        if new_partial:
            for jid, ops in new_partial.items():
                print(f"  {jid}: {len(ops)}/{len([o for o in next(j for j in jobs_data if j['job_id']==jid)['operations']])} ops fixed")

        # Remove fully fixed jobs from remaining
        remaining = [jid for jid in remaining if jid not in fix_set]

        step += 1
        if step > 50:
            print("Safety limit reached")
            break

    # Post-process: resolve non-bottleneck machine conflicts
    final = list(global_schedule.values())
    final = post_process_schedule(final, machines_data, bottleneck_groups)

    final_path = os.path.join(output_dir, "final_schedule.jsonl")
    save_schedule(final, final_path)
    print(f"\n{'='*60}")
    print(f"RHO complete: {step} steps")
    print(f"Final schedule: {final_path}")

    return final


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    """Demo: run RHO on rho_demo data with M4 as bottleneck, W=4, K=2."""
    import sys

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "rho_demo")
    output_dir = os.path.join(data_dir, "trace")

    jobs_data = load_jsonl(os.path.join(data_dir, "jobs.jsonl"))
    machines_data = load_jsonl(os.path.join(data_dir, "machines.jsonl"))

    # All machines start at 0, unbounded
    base_availability = {}
    for group in machines_data:
        for m in group["machines"]:
            base_availability[m["machine_id"]] = {
                "start_time": 0, "end_time": None,
            }

    print("="*60)
    print("Rolling Horizon Optimization Demo")
    print(f"  Jobs:        {len(jobs_data)}")
    print(f"  Bottleneck:  M4")
    print(f"  Window size: 4")
    print(f"  Fix count:   2")
    print("="*60)

    final = run_rho(
        jobs_data=jobs_data,
        machines_data=machines_data,
        bottleneck_groups=["M4"],
        base_availability=base_availability,
        window_size=4,
        fix_count=2,
        output_dir=output_dir,
    )

    # Validate with evaluator
    print(f"\n{'='*60}")
    print("Validating final schedule...")
    print("="*60)
    sys.path.insert(0, os.path.dirname(__file__))
    from evaluator import evaluate
    result = evaluate(
        os.path.join(data_dir, "jobs.jsonl"),
        os.path.join(data_dir, "machines.jsonl"),
        os.path.join(output_dir, "final_schedule.jsonl"),
    )
    if result["valid"]:
        print(f"VALID! Total reward: {result['total_reward']}")
        print(f"  On time: {len(result['on_time_jobs'])}, Late: {len(result['late_jobs'])}")
    else:
        print("INVALID!")
        for err in result["errors"]:
            print(f"  - {err}")


if __name__ == "__main__":
    main()
