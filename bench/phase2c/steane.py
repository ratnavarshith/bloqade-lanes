import os, sys, time
sys.path.insert(0, os.getcwd())
from dataclasses import replace
from benchmarks.cli import _apply_architecture_mode
from benchmarks.harness import BenchmarkRunner, default_strategy_configs
from benchmarks.harness.matrix import PalindromePlacementStrategy, PhysicalPlacementStrategy, RustPlacementTraversal
from benchmarks.harness.models import BenchmarkJob
from benchmarks.kernels import select_benchmark_cases
from bloqade.lanes.arch.gemini import physical
case = [c for c in select_benchmark_cases(None) if c.case_id == "steane_physical_35"][0]
base = next(c for c in default_strategy_configs() if c.strategy_id == "rust_cascade_ids")
def cfg(bound, budget, fb=False):
    return replace(base, strategy_id=f"bound={bound} budget={budget} fallback={fb}",
        build_placement_strategy=lambda: PalindromePlacementStrategy(inner=PhysicalPlacementStrategy(
            arch_spec=physical.get_arch_spec(),
            traversal=RustPlacementTraversal(strategy="cascade-ids", completion_bound=bound, max_expansions=budget, fallback_push_rotate=fb))))
runner = BenchmarkRunner(repeats=1, warmup=0)
for budget in (int(a) for a in sys.argv[1:]):
    for bound in (None, "bus_cut"):
        job = _apply_architecture_mode([BenchmarkJob(case, cfg(bound, budget))], architecture_mode="physical")[0]
        t = time.perf_counter(); row = runner._run_one(job)
        print(f"budget={budget} bound={bound}: success={row.success} events={row.move_count_events} nodes={row.nodes_explored} "
              f"cost={row.extra.get('cost_sum')} h_root={row.extra.get('h_root_sum')} {time.perf_counter()-t:.1f}s | {row.notes[-90:]}", flush=True)
