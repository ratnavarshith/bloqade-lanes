"""One timing process: runs rust_cascade_ids (h0) and the bus-cut variant over the
physical suite, in the order given, and dumps one JSON record per job.

usage (from python/): ../.venv/bin/python /tmp/phase2c/bench.py <out.json> <h0_first|bc_first>
"""
import json
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.getcwd())

from benchmarks.cli import _apply_architecture_mode
from benchmarks.harness import BenchmarkRunner, default_strategy_configs
from benchmarks.harness.matrix import (
    PalindromePlacementStrategy,
    PhysicalPlacementStrategy,
    RustPlacementTraversal,
)
from benchmarks.harness.models import BenchmarkJob
from benchmarks.kernels import select_benchmark_cases

from bloqade.lanes.arch.gemini import physical

out_path, order = sys.argv[1], sys.argv[2]

h0 = next(c for c in default_strategy_configs() if c.strategy_id == "rust_cascade_ids")
bc = replace(
    h0,
    strategy_id="rust_cascade_ids_bus_cut",
    build_placement_strategy=lambda: PalindromePlacementStrategy(
        inner=PhysicalPlacementStrategy(
            arch_spec=physical.get_arch_spec(),
            traversal=RustPlacementTraversal(
                strategy="cascade-ids", completion_bound="bus_cut"
            ),
        )
    ),
    notes="IDS, then an A* refinement gated by max(h0, |R|)",
)
strategies = (h0, bc) if order == "h0_first" else (bc, h0)

cases = select_benchmark_cases(None)
runner = BenchmarkRunner(repeats=1, warmup=0)

# Warm the process (imports, lazy caches) on the smallest case, untimed.
warm = [c for c in cases if c.case_id == "ghz_4"]
runner.run_jobs(_apply_architecture_mode([BenchmarkJob(warm[0], s) for s in strategies], architecture_mode="physical"))

records = []
for case in sorted(cases, key=lambda c: c.case_id):
    jobs = _apply_architecture_mode(
        [BenchmarkJob(case, s) for s in strategies], architecture_mode="physical"
    )
    for job in jobs:
        os.environ["BUSCUT_CASE"] = job.case.case_id
        os.environ["BUSCUT_STRATEGY"] = job.strategy.strategy_id
        row = runner._run_one(job)
        records.append(
            dict(
                case=row.case_id,
                strategy=row.strategy_id,
                success=row.success,
                wall_ms=row.wall_time_ms,
                move_events=row.move_count_events,
                nodes=row.nodes_explored,
                cuts_by_h=row.cuts_by_h,
                cuts_by_g=row.cuts_by_g,
                cuts_inf=row.cuts_infeasible,
                max_gap=row.max_optimality_gap,
                extra=row.extra,
                notes=row.notes[-120:],
            )
        )
        print(row.case_id, row.strategy_id, row.success, row.wall_time_ms, flush=True)
json.dump(records, open(out_path, "w"), indent=1, default=str)
