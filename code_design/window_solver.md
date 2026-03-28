# Design of Our Window Solver

Use OR-Tools CP-SAT solver.

## Input

| Parameter | Type | Description |
|---|---|---|
| `jobs_data` | `list[dict]` | Job definitions (from `jobs.jsonl`) |
| `machines_data` | `list[dict]` | Machine group definitions (from `machines.jsonl`) |
| `bottleneck_groups` | `list[str]` | Machine group names to treat as bottleneck (e.g. `["M1", "M4"]`) |
| `machine_availability` | `dict[str, dict]` | Per-machine time windows: `{"M4-A": {"start_time": 0, "end_time": 80}, ...}`. `start_time` required, `end_time` optional (null = unbounded). |
| `time_limit_seconds` | `float` | Solver time limit (default 60s) |

## Output

Returns a dict with: `status`, `schedule` (JSONL format), `total_reward`, `job_results`.

## Mathematical Model

### Decision Variables

For each job $j$, operation $o$:
- $s_{j,o}, e_{j,o} \in \mathbb{Z}$ — start and end time
- For bottleneck operations, for each machine $m$ in the group: $p_{j,o,m} \in \{0,1\}$ — whether assigned to machine $m$

Non-bottleneck operations only have time variables (no machine selection), since they are treated as having infinite capacity.

### Constraints

1. **Duration**: $e_{j,o} = s_{j,o} + \text{processing\_time}_{j,o}$ (enforced by `IntervalVar`)

2. **Precedence**: $s_{j,o_{k+1}} \geq e_{j,o_k}$ for consecutive operations in a job.

3. **Machine selection** (bottleneck only): $\sum_{m \in \text{group}} p_{j,o,m} = 1$ — exactly one machine.

4. **No overlap** (bottleneck only): On each machine $m$, assigned operations cannot overlap. Implemented via `OptionalIntervalVar` + `AddNoOverlap`.

5. **Per-machine availability** (bottleneck only): $p_{j,o,m} = 1 \Rightarrow s_{j,o} \geq \text{start\_time}_m$ and $p_{j,o,m} = 1 \Rightarrow e_{j,o} \leq \text{end\_time}_m$. Implemented via `OnlyEnforceIf(presence)`.

### Objective

Two-level lexicographic objective combined into one expression:

$$\max \Big( W \cdot \sum_j \text{reward}_j \cdot \text{ontime}_j \;-\; \sum_{j,o} e_{j,o} \Big)$$

Where $W = \text{horizon} \times \text{num\_ops} + 1$, large enough that reward always dominates.

- **Primary**: maximize total reward from on-time jobs.
- **Secondary**: among solutions with equal reward, minimize the sum of ALL operation end times. This pushes every operation as early as possible, which is important for rolling horizon — finishing early leaves room for the next window.

The on-time indicator for each job:
- $\text{ontime}_j = 1 \Leftrightarrow e_{j,\text{last}} \leq \text{due\_time}_j$

## Key Design: Bottleneck vs Non-Bottleneck

- **Bottleneck groups**: Full optimization — machine selection variables, no-overlap constraints, per-machine availability windows.
- **Non-bottleneck groups**: Only time variables to maintain the precedence chain. No capacity constraints. Assigned the first machine from the group in the output.

This dramatically reduces the model size when only a few machine groups are actual bottlenecks.

## Rolling Horizon Optimization (`src/rho.py`)

### Pipeline

```
heuristic_order_jobs → [J5, J2, J6, J3, J4, J1]
                         ├── Window 0: [J5, J2, J6, J3] → solve → fix J2,J5
                         ├── Window 1: [J6, J3*, J4, J1] → solve → fix J3,J6
                         └── Window 2: [J4*, J1*]        → solve → fix J4,J1
                         (* = partially fixed from previous step)
```

### Key Functions

| Function | Purpose |
|---|---|
| `heuristic_order_jobs` | Sort jobs by slack (due_time - total_processing_time) ascending, reward descending |
| `select_jobs_to_fix` | Pick the K jobs that complete earliest in the current window |
| `propagate_fixes` | After fixing K jobs, fix operations of remaining jobs that are interleaved with fixed ops on the same machine. Propagate within each job: if op i is fixed, ops 1..i-1 are too |
| `prepare_window_jobs` | For partially fixed jobs: remove fixed ops, set `earliest_start` = last fixed op end time |
| `compute_availability` | For each machine, set start_time = max end_time of all fixed ops on that machine |
| `build_complete_schedule` | Re-attach fixed ops to solver output for complete per-job schedules |
| `post_process_schedule` | Resolve non-bottleneck machine conflicts by greedy assignment across machines in each group |
| `run_rho` | Orchestrator: loop until all jobs fixed, save trace at each step |

### Fix & Propagation Logic

1. Sort window jobs by completion time, fix the first K.
2. On each machine, compute latest fixed end time $T_m$.
3. For each unfixed job's operation: if it's on machine $m$ and starts before $T_m$, mark it fixed.
4. Within each job: if operation $i$ is fixed, all operations $1..i{-}1$ are also fixed (precedence).
5. Repeat steps 2-4 until no new fixes (handles cascading).

### Trace Output

Each step saves to `output_dir/`:
- `step_N_window_jobs.jsonl` — jobs sent to solver (fixed ops removed)
- `step_N_availability.json` — per-machine availability for this step
- `step_N_solver_output.jsonl` — raw solver output
- `step_N_complete_schedule.jsonl` — solver output + fixed ops re-attached
- `step_N_fixes.json` — which jobs fixed, which partially fixed
- `final_schedule.jsonl` — merged + post-processed final schedule
