"""
Evaluator for Job Shop Scheduling solutions.

Validates a proposed schedule against job definitions and machine definitions,
and computes the total reward for on-time jobs.
"""

import json
import argparse
import sys
from pathlib import Path


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_machine_index(machines_data: list[dict]) -> dict:
    """Return two mappings:
    - machine_id -> group_name  (e.g. "M2-A" -> "M2")
    - group_name -> set of machine_ids
    """
    machine_to_group: dict[str, str] = {}
    group_to_machines: dict[str, set[str]] = {}
    for group in machines_data:
        group_name = group["name"]
        group_to_machines[group_name] = set()
        for m in group["machines"]:
            machine_to_group[m["machine_id"]] = group_name
            group_to_machines[group_name].add(m["machine_id"])
    return machine_to_group, group_to_machines


def evaluate(jobs_path: str, machines_path: str, schedule_path: str) -> dict:
    """Evaluate a proposed schedule.

    Returns a dict with:
      - valid: bool
      - errors: list of error strings (empty if valid)
      - total_reward: sum of reward for on-time jobs (0 if invalid)
      - job_results: per-job completion info
    """
    jobs_data = load_jsonl(jobs_path)
    machines_data = load_jsonl(machines_path)
    schedule_data = load_jsonl(schedule_path)

    machine_to_group, group_to_machines = build_machine_index(machines_data)
    all_machine_ids = set(machine_to_group.keys())

    errors: list[dict] = []  # each error: {"type": str, "detail": str, ...}

    # Index jobs by job_id
    jobs_by_id = {j["job_id"]: j for j in jobs_data}

    # Index schedule by job_id
    schedule_by_id: dict[str, dict] = {}
    for entry in schedule_data:
        jid = entry["job_id"]
        if jid in schedule_by_id:
            errors.append({"type": "DUPLICATE_JOB", "detail": f"Duplicate job in schedule: {jid}"})
        schedule_by_id[jid] = entry

    # Check all jobs are present in schedule
    for jid in jobs_by_id:
        if jid not in schedule_by_id:
            errors.append({"type": "MISSING_JOB", "detail": f"Job {jid} missing from schedule"})

    # Check no extra jobs in schedule
    for jid in schedule_by_id:
        if jid not in jobs_by_id:
            errors.append({"type": "UNKNOWN_JOB", "detail": f"Unknown job in schedule: {jid}"})

    # Per-machine timeline for conflict detection: machine_id -> list of (start, end, job_id, op_id)
    machine_timeline: dict[str, list[tuple]] = {}

    job_results: list[dict] = []

    for jid, job in jobs_by_id.items():
        if jid not in schedule_by_id:
            continue
        sched = schedule_by_id[jid]
        job_ops = job["operations"]
        sched_ops = sched["operations"]

        # Check all operations present
        job_op_ids = [op["op_id"] for op in job_ops]
        sched_op_ids = [op["op_id"] for op in sched_ops]

        if set(job_op_ids) != set(sched_op_ids):
            missing = set(job_op_ids) - set(sched_op_ids)
            extra = set(sched_op_ids) - set(job_op_ids)
            if missing:
                errors.append({"type": "MISSING_OPS", "detail": f"Job {jid}: missing operations {missing}"})
            if extra:
                errors.append({"type": "UNKNOWN_OPS", "detail": f"Job {jid}: unknown operations {extra}"})
            continue

        # Index scheduled ops by op_id
        sched_ops_by_id = {op["op_id"]: op for op in sched_ops}

        prev_end_time = None
        last_end_time = 0

        for idx, job_op in enumerate(job_ops):
            op_id = job_op["op_id"]
            sched_op = sched_ops_by_id[op_id]

            start = sched_op["start_time"]
            end = sched_op["end_time"]
            assigned = sched_op.get("assigned_machine")
            expected_duration = job_op["processing_time"]

            # Check start < end
            if start >= end:
                errors.append({
                    "type": "INVALID_TIME",
                    "detail": (
                        f"Job {jid}, op {op_id} ({sched_op.get('name', '')}): "
                        f"start_time ({start}) >= end_time ({end})"
                    ),
                })

            # Check processing time
            if end - start != expected_duration:
                errors.append({
                    "type": "DURATION_MISMATCH",
                    "detail": (
                        f"Job {jid}, op {op_id} ({sched_op.get('name', '')}): "
                        f"duration {end - start} != expected {expected_duration}, "
                        f"start_time={start}, end_time={end}"
                    ),
                })

            # Check operation sequence (previous op must finish before this one starts)
            if prev_end_time is not None and start < prev_end_time:
                prev_op_id = job_ops[idx - 1]["op_id"]
                errors.append({
                    "type": "PRECEDENCE",
                    "detail": (
                        f"Job {jid}: op {prev_op_id} ends at {prev_end_time}, "
                        f"but next op {op_id} ({sched_op.get('name', '')}) "
                        f"starts at {start}"
                    ),
                })

            prev_end_time = end
            last_end_time = max(last_end_time, end)

            # Check machine validity (if assigned)
            if assigned is not None:
                if assigned not in all_machine_ids:
                    errors.append({
                        "type": "UNKNOWN_MACHINE",
                        "detail": f"Job {jid}, op {op_id}: unknown machine {assigned}",
                    })
                else:
                    group = machine_to_group[assigned]
                    if group not in job_op["machines"]:
                        errors.append({
                            "type": "WRONG_MACHINE",
                            "detail": (
                                f"Job {jid}, op {op_id}: machine {assigned} (group {group}) "
                                f"not in allowed groups {job_op['machines']}"
                            ),
                        })

                # Track for conflict detection
                if assigned not in machine_timeline:
                    machine_timeline[assigned] = []
                machine_timeline[assigned].append((start, end, jid, op_id))

        # Record job result
        on_time = last_end_time <= job["due_time"]
        job_results.append({
            "job_id": jid,
            "name": job["name"],
            "due_time": job["due_time"],
            "end_time": last_end_time,
            "on_time": on_time,
            "reward": job["reward"] if on_time else 0,
        })

    # Check machine conflicts (no overlapping operations on same machine)
    for machine_id, intervals in machine_timeline.items():
        intervals.sort(key=lambda x: x[0])
        for i in range(len(intervals) - 1):
            start_a, end_a, jid_a, op_a = intervals[i]
            start_b, end_b, jid_b, op_b = intervals[i + 1]
            if start_b < end_a:
                errors.append({
                    "type": "OVERLAP",
                    "detail": (
                        f"Machine {machine_id}: "
                        f"{jid_a}/{op_a} [{start_a},{end_a}] overlaps with "
                        f"{jid_b}/{op_b} [{start_b},{end_b}]"
                    ),
                })

    valid = len(errors) == 0
    total_reward = sum(jr["reward"] for jr in job_results)
    on_time_jobs = [jr for jr in job_results if jr["on_time"]]
    late_jobs = [jr for jr in job_results if not jr["on_time"]]

    return {
        "valid": valid,
        "errors": errors,
        "total_reward": total_reward,
        "job_results": job_results,
        "on_time_jobs": on_time_jobs,
        "late_jobs": late_jobs,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate a job shop schedule")
    parser.add_argument("jobs", help="Path to jobs.jsonl")
    parser.add_argument("machines", help="Path to machines.jsonl")
    parser.add_argument("schedule", help="Path to proposed_schedule.jsonl")
    args = parser.parse_args()

    result = evaluate(args.jobs, args.machines, args.schedule)

    if result["valid"]:
        print("Schedule is VALID")
        print(f"\nTotal reward: {result['total_reward']}")
        print(f"On time: {len(result['on_time_jobs'])} jobs, "
              f"Late: {len(result['late_jobs'])} jobs")
        print("\nPer-job results:")
        for jr in result["job_results"]:
            status = "ON TIME" if jr["on_time"] else "LATE"
            print(
                f"  {jr['job_id']} ({jr['name']}): end={jr['end_time']}, "
                f"due={jr['due_time']}, {status}, reward={jr['reward']}"
            )
    else:
        print("Schedule is INVALID")
        # Group errors by type
        by_type: dict[str, list[str]] = {}
        for err in result["errors"]:
            by_type.setdefault(err["type"], []).append(err["detail"])
        for err_type, details in by_type.items():
            print(f"\n[{err_type}] ({len(details)} error(s)):")
            for d in details:
                print(f"  - {d}")
        sys.exit(1)


if __name__ == "__main__":
    main()
