"""Command line driver: fuzz every lanes strategy and write a JSON summary.

    uv run python -m lanes_fuzz.run --mode clifford --examples 500 --jobs 4
    uv run python -m lanes_fuzz.run --mode nonclifford --examples 100 --jobs 4

Strategies run in separate processes. Minimal repro scripts for every failure
category go to ``--repro-dir``; the summary goes to ``--out``.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from lanes_fuzz.gen import GenConfig
from lanes_fuzz.props import run_strategy
from lanes_fuzz.strategies import STRATEGY_NAMES


def _worker(strategy: str, cfg: GenConfig, examples: int, repro_dir: str, seed: int):
    return run_strategy(strategy, cfg, examples, Path(repro_dir), seed_value=seed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--mode", choices=["clifford", "nonclifford"], default="clifford"
    )
    parser.add_argument("--examples", type=int, default=100)
    parser.add_argument("--strategies", default="all", help="comma list or 'all'")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--min-qubits", type=int, default=2)
    parser.add_argument("--max-qubits", type=int, default=6)
    parser.add_argument("--min-ops", type=int, default=1)
    parser.add_argument("--max-ops", type=int, default=12)
    parser.add_argument("--repro-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--list", action="store_true", help="list strategies and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        print("\n".join(STRATEGY_NAMES))
        return 0
    names = (
        list(STRATEGY_NAMES) if args.strategies == "all" else args.strategies.split(",")
    )
    unknown = sorted(set(names) - set(STRATEGY_NAMES))
    if unknown:
        raise SystemExit(f"unknown strategies: {unknown}")
    cfg = GenConfig(
        mode=args.mode,
        min_qubits=args.min_qubits,
        max_qubits=args.max_qubits,
        min_ops=args.min_ops,
        max_ops=args.max_ops,
    )
    repro_dir = args.repro_dir or f"repros/{args.mode}"
    started = time.perf_counter()
    results = []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=context) as pool:
        futures = [
            pool.submit(_worker, name, cfg, args.examples, repro_dir, args.seed)
            for name in names
        ]
        for future in futures:
            summary = future.result()
            results.append(summary)
            print(_line(summary), flush=True)
    wall = round(time.perf_counter() - started, 1)
    print(f"wall time: {wall}s with {args.jobs} job(s)")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"args": vars(args), "wall_seconds": wall, "results": results},
                indent=1,
            )
        )
    return 0


def _line(summary: dict) -> str:
    failures = summary["minimal_failures"]
    ok = summary["outcomes"].get("ok", 0)
    expected = sum(
        n for c, n in summary["outcomes"].items() if c.startswith("expected")
    )
    return (
        f"{summary['strategy']:<20} examples={summary['examples_run']:<4} "
        f"ok={ok:<4} expected={expected:<3} failure_categories={len(failures)} "
        f"passes={summary['passes']} {summary['seconds']}s"
    )


if __name__ == "__main__":
    raise SystemExit(main())
