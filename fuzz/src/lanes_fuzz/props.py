"""Hypothesis properties and the per-strategy driver.

Hypothesis tells failures apart by exception type and origin, so each failure
*category* (see :mod:`lanes_fuzz.check`) gets its own exception class. It then
shrinks every category separately to a minimal kernel.

A run that stops at the first failure would stop counting examples, so the
driver works in passes: a category whose minimal repro is already saved becomes
*known* and is only counted afterwards. It repeats until a pass of ``examples``
kernels finishes with every failure known; that last pass supplies the counts.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, Phase, given, seed, settings
from hypothesis.errors import Flaky
from lanes_fuzz.check import Outcome, PlantHook, check_kernel
from lanes_fuzz.gen import GenConfig, KernelSpec, kernel_specs, render
from lanes_fuzz.repro import write_repro


class FuzzFailure(AssertionError):
    """A kernel that broke a check; carries what is needed to write a repro."""

    def __init__(self, spec: KernelSpec, strategy: str, outcome: Outcome):
        super().__init__(f"[{strategy}] {outcome.category}: {outcome.detail[:300]}")
        self.spec = spec
        self.strategy = strategy
        self.outcome = outcome


_FAILURE_TYPES: dict[str, type[FuzzFailure]] = {}


def failure_type(category: str) -> type[FuzzFailure]:
    """One exception class per category, so Hypothesis keeps them apart."""
    if category not in _FAILURE_TYPES:
        _FAILURE_TYPES[category] = type(f"FuzzFailure[{category}]", (FuzzFailure,), {})
    return _FAILURE_TYPES[category]


@dataclass
class Ledger:
    calls: int = 0
    seconds: float = 0.0
    categories: Counter[str] = field(default_factory=Counter)
    samples: dict[str, str] = field(default_factory=dict)

    def record(self, spec: KernelSpec, outcome: Outcome) -> None:
        self.calls += 1
        self.seconds += outcome.seconds
        self.categories[outcome.category] += 1
        if outcome.status != "ok" and outcome.category not in self.samples:
            self.samples[outcome.category] = outcome.detail[:300]


def make_property(
    strategy: str,
    cfg: GenConfig,
    examples: int,
    known: set[str],
    ledger: Ledger,
    *,
    seed_value: int,
    plant: PlantHook | None = None,
):
    @seed(seed_value)
    @settings(
        max_examples=examples,
        deadline=None,
        database=None,
        suppress_health_check=list(HealthCheck),
        phases=[Phase.generate, Phase.shrink],
        report_multiple_bugs=True,
        print_blob=False,
    )
    @given(kernel_specs(cfg))
    def prop(spec: KernelSpec) -> None:
        outcome = check_kernel(spec, strategy, plant)
        ledger.record(spec, outcome)
        if outcome.failed and outcome.category not in known:
            raise failure_type(outcome.category)(spec, strategy, outcome)

    return prop


def _flatten(exc: BaseException) -> list[BaseException]:
    if isinstance(
        exc, BaseExceptionGroup
    ):  # noqa: F821 (builtin from 3.11; this project needs 3.12)
        return [leaf for inner in exc.exceptions for leaf in _flatten(inner)]
    return [exc]


def run_strategy(
    strategy: str,
    cfg: GenConfig,
    examples: int,
    repro_dir: Path | None,
    *,
    seed_value: int = 0,
    max_passes: int = 8,
    plant: PlantHook | None = None,
    planted_repros: bool = False,
) -> dict[str, Any]:
    """Fuzz one strategy; return a JSON-able summary."""
    started = time.perf_counter()
    known: dict[str, FuzzFailure] = {}
    repros: dict[str, str] = {}
    notes: list[str] = []
    passes = 0
    ledger = Ledger()
    completed = False

    while passes < max_passes:
        ledger = Ledger()
        prop = make_property(
            strategy,
            cfg,
            examples,
            set(known),
            ledger,
            seed_value=seed_value + passes,
            plant=plant,
        )
        passes += 1
        try:
            prop()
            completed = True
            break
        except BaseException as exc:
            leaves = _flatten(exc)
            found = [leaf for leaf in leaves if isinstance(leaf, FuzzFailure)]
            for leaf in leaves:
                if isinstance(leaf, Flaky):
                    notes.append(f"flaky: {str(leaf)[:200]}")
                elif not isinstance(leaf, FuzzFailure):
                    raise
            for failure in found:
                category = failure.outcome.category
                known[category] = failure
                if repro_dir is not None:
                    path = write_repro(
                        repro_dir,
                        failure.spec,
                        strategy,
                        category,
                        failure.outcome.detail,
                        planted=planted_repros,
                    )
                    repros[category] = str(path)
            if not found:
                break

    return {
        "strategy": strategy,
        "mode": cfg.mode,
        "examples_requested": examples,
        "examples_run": ledger.calls,
        "completed_clean_pass": completed,
        "passes": passes,
        "seconds": round(time.perf_counter() - started, 1),
        "check_seconds": round(ledger.seconds, 1),
        "outcomes": dict(ledger.categories),
        "samples": ledger.samples,
        "minimal_failures": {
            category: {
                "n_qubits": f.spec.n_qubits,
                "n_ops": len(f.spec.ops),
                "ops": [list(op) for op in f.spec.ops],
                "measure": f.spec.measure,
                "detail": f.outcome.detail[:300],
                "kernel": render(f.spec),
                "repro": repros.get(category),
            }
            for category, f in known.items()
        },
        "notes": notes,
    }
