"""Differential test: the occupancy analysis against the Rust validator.

    uv run python -m lanes_fuzz.diff --examples 200 --jobs 4 --out results/diff.json

For every lanes strategy, the same ``--examples`` random Clifford kernels are
compiled to move IR and each output is judged by both sides. Then, per strategy,
``--mutants-per-kind`` mutants of each kind are made from those outputs:

* ``drop``: delete one ``move.Move``;
* ``duplicate``: run one ``move.Move`` twice in a row;
* ``retarget``: replace one lane of a move set by another lane (a lane seen in
  the compiled programs, or one with its site or word id shifted by one);
* ``swap``: exchange the lanes of two move sets.

The validator side is :func:`lanes_fuzz.check.rust_validate` (``check_lane_group``
on every move set plus the atom interpreter's ``validate_moves`` replay); the
analysis side is :func:`lanes_fuzz.occupancy.analyze`.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import random
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import seed as hypothesis_seed
from kirin import ir
from lanes_fuzz.check import compile_to_move, rust_validate, signature
from lanes_fuzz.gen import GenConfig, KernelSpec, build_kernel, kernel_specs
from lanes_fuzz.occupancy import analyze
from lanes_fuzz.strategies import STRATEGY_NAMES, build_strategy, physical_arch

from bloqade.lanes.bytecode.encoding import LaneAddress
from bloqade.lanes.dialects import move

MUTATIONS = ("drop", "duplicate", "retarget", "swap")


def draw_specs(count: int, seed: int) -> list[KernelSpec]:
    specs: list[KernelSpec] = []

    @settings(
        max_examples=count,
        database=None,
        deadline=None,
        phases=[Phase.generate],
        suppress_health_check=list(HealthCheck),
    )
    @hypothesis_seed(seed)
    @given(kernel_specs(GenConfig()))
    def collect(spec: KernelSpec) -> None:
        specs.append(spec)

    collect()
    return specs[:count]


# ── verdicts ─────────────────────────────────────────────────────────


def judge(move_mt: ir.Method) -> dict:
    arch = physical_arch()
    try:
        analysis = sorted({v.kind for v in analyze(move_mt, arch)})
    except Exception as exc:  # noqa: BLE001 - a crash is a bug in the analysis
        analysis = [f"CRASH {signature(exc)}"]
    try:
        rust_validate(move_mt)
        validator = ""
    except Exception as exc:  # noqa: BLE001
        validator = signature(exc)
    return {"analysis": analysis, "validator": validator}


def verdict(record: dict) -> str:
    key = (bool(record["analysis"]), bool(record["validator"]))
    return {
        (False, False): "both accept",
        (True, True): "both reject",
        (True, False): "only analysis rejects",
        (False, True): "only validator rejects",
    }[key]


# ── mutations ────────────────────────────────────────────────────────


def _moves(move_mt: ir.Method) -> list[move.Move]:
    return [s for s in move_mt.callable_region.walk() if isinstance(s, move.Move)]


def _with_lanes(stmt: move.Move, lanes) -> move.Move:
    return move.Move(stmt.current_state, lanes=tuple(lanes))


def mutate(
    kind: str, base: ir.Method, rng: random.Random, lane_pool: list
) -> tuple[ir.Method, str]:
    """A mutated copy of ``base`` and a one-line description."""
    mt = base.similar()
    moves = _moves(mt)
    if kind == "drop":
        i = rng.randrange(len(moves))
        stmt = moves[i]
        stmt.result.replace_by(stmt.current_state)
        stmt.delete()
        return mt, f"dropped move set {i} of {len(moves)}"
    if kind == "duplicate":
        i = rng.randrange(len(moves))
        stmt = moves[i]
        first = _with_lanes(stmt, stmt.lanes)
        second = move.Move(first.result, lanes=stmt.lanes)
        first.insert_before(stmt)
        stmt.replace_by(second)
        return mt, f"duplicated move set {i} of {len(moves)}"
    if kind == "retarget":
        i = rng.randrange(len(moves))
        stmt = moves[i]
        j = rng.randrange(len(stmt.lanes))
        old = stmt.lanes[j]
        if rng.random() < 0.5:
            new = rng.choice(lane_pool)
            how = "another lane from the programs"
        else:
            field = rng.choice(["site_id", "word_id"])
            args = dict(
                move_type=old.move_type,
                word_id=old.word_id,
                site_id=old.site_id,
                bus_id=old.bus_id,
                direction=old.direction,
                zone_id=old.zone_id,
            )
            args[field] += 1
            new = LaneAddress(**args)
            how = f"{field} + 1"
        lanes = list(stmt.lanes)
        lanes[j] = new
        stmt.replace_by(_with_lanes(stmt, lanes))
        return mt, f"lane {j} of move set {i}: {old!r} -> {new!r} ({how})"
    if kind == "swap":
        a, b = rng.sample(range(len(moves)), 2)
        la, lb = moves[a].lanes, moves[b].lanes
        moves[a].replace_by(_with_lanes(moves[a], lb))
        moves[b].replace_by(_with_lanes(moves[b], la))
        return mt, f"swapped the lanes of move sets {a} and {b} of {len(moves)}"
    raise ValueError(kind)


def _can_mutate(kind: str, moves: list[move.Move]) -> bool:
    if kind == "swap":
        return len({m.lanes for m in moves}) >= 2
    return bool(moves)


# ── one strategy ─────────────────────────────────────────────────────


def run_one(strategy: str, specs: list[KernelSpec], per_kind: int, seed: int) -> dict:
    start = time.perf_counter()
    records: list[dict] = []
    programs: list[tuple[int, ir.Method]] = []
    refused = 0
    for i, spec in enumerate(specs):
        try:
            move_mt = compile_to_move(
                build_kernel(spec), build_strategy(strategy), spec.measure
            )
        except Exception as exc:  # noqa: BLE001
            refused += 1
            records.append(
                {
                    "source": "compiled",
                    "strategy": strategy,
                    "example": i,
                    "no-output": signature(exc),
                }
            )
            continue
        programs.append((i, move_mt))
        records.append(
            {"source": "compiled", "strategy": strategy, "example": i, **judge(move_mt)}
        )

    rng = random.Random(f"{seed}-{strategy}")
    lane_pool = [lane for _, mt in programs for m in _moves(mt) for lane in m.lanes]
    for kind in MUTATIONS:
        pool = [(i, mt) for i, mt in programs if _can_mutate(kind, _moves(mt))]
        for _ in range(per_kind if pool else 0):
            i, base = rng.choice(pool)
            mutant, how = mutate(kind, base, rng, lane_pool)
            records.append(
                {
                    "source": kind,
                    "strategy": strategy,
                    "example": i,
                    "how": how,
                    **judge(mutant),
                }
            )
    return {
        "strategy": strategy,
        "compiled": len(programs),
        "no_output": refused,
        "records": records,
        "seconds": time.perf_counter() - start,
    }


# ── summary ──────────────────────────────────────────────────────────

VERDICTS = (
    "both accept",
    "both reject",
    "only analysis rejects",
    "only validator rejects",
)


def summarize(runs: list[dict]) -> dict:
    records = [r for run in runs for r in run["records"] if "no-output" not in r]
    table: dict[str, Counter] = {}
    for r in records:
        table.setdefault(r["source"], Counter())[verdict(r)] += 1
    buckets: dict[tuple, dict] = {}
    for r in records:
        v = verdict(r)
        if v in ("only analysis rejects", "only validator rejects"):
            key = (v, tuple(r["analysis"]), r["validator"], r["source"])
            b = buckets.setdefault(key, {"count": 0, "example": r})
            b["count"] += 1
    return {
        "table": {s: {v: c.get(v, 0) for v in VERDICTS} for s, c in table.items()},
        "total": {v: sum(c.get(v, 0) for c in table.values()) for v in VERDICTS},
        "no_output": {r["strategy"]: r["no_output"] for r in runs},
        "disagreements": [
            {
                "verdict": k[0],
                "analysis": list(k[1]),
                "validator": k[2],
                "source": k[3],
                "count": b["count"],
                "example": b["example"],
            }
            for k, b in sorted(buckets.items(), key=lambda kb: -kb[1]["count"])
        ],
    }


def _worker(args):
    return run_one(*args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--examples", type=int, default=200)
    parser.add_argument("--mutants-per-kind", type=int, default=6)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strategies", default="all")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    names = (
        list(STRATEGY_NAMES) if args.strategies == "all" else args.strategies.split(",")
    )
    specs = draw_specs(args.examples, args.seed)
    jobs = [(n, specs, args.mutants_per_kind, args.seed) for n in names]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=context) as pool:
        runs = list(pool.map(_worker, jobs))
    result = {"examples": len(specs), **summarize(runs)}
    shown = ("examples", "table", "total", "no_output")
    print(json.dumps({k: result[k] for k in shown}, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
