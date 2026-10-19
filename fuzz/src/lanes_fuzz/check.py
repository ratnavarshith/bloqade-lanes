"""Compile one generated kernel with one strategy and check the result.

Order of checks (the first that fails decides the outcome):

1. **compile** - ``PhysicalPipeline`` (kernels with a terminal measurement, the
   documented public entry) or the stage-by-stage path the benchmark harness and
   the lanes tests use (kernels without one), always with ``no_raise=False`` so a
   failure is an exception instead of a silently unlowered kernel. A
   ``PlacementError`` from the routing solver is an *expected, recorded*
   outcome; every other exception is a failure.
2. **lowered** - no ``place.CZ`` left in the move IR.
3. **validator** - the Rust validator on the move IR: the atom interpreter
   replays every ``move.Move`` through ``AtomStateData.validate_moves`` (Rust),
   and each lane group also goes through ``ArchSpec.check_lanes`` (Rust: group
   consistency, bus membership, AOD geometry).
4. **to-squin** - ``MoveToSquinPhysical`` turns the move IR back into squin.
5. **equivalence** - Stim tableau (Clifford) or statevector (non-Clifford) of the
   original kernel against the lowered-and-lifted one, see :mod:`lanes_fuzz.equiv`.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from kirin import ir
from lanes_fuzz import equiv
from lanes_fuzz.gen import KernelSpec, build_kernel
from lanes_fuzz.strategies import build_strategy, physical_arch

from bloqade.lanes.analysis import atom
from bloqade.lanes.analysis.placement.exceptions import PlacementError
from bloqade.lanes.dialects import move, place
from bloqade.lanes.heuristics.physical.layout import (
    PhysicalLayoutHeuristicGraphPartitionCenterOut,
)
from bloqade.lanes.passes import SequentialPlacePass
from bloqade.lanes.transform import (
    MoveToSquinPhysical,
    NativeToPlace,
    PhysicalPipeline,
    PlaceToMove,
)

NON_CLIFFORD_OPS = frozenset({"t", "rz", "rx"})

PlantHook = Callable[[ir.Method], ir.Method]


@dataclass(frozen=True)
class Outcome:
    status: Literal["ok", "expected", "failure"]
    category: str
    detail: str = ""
    seconds: float = 0.0

    @property
    def failed(self) -> bool:
        return self.status == "failure"


def is_clifford(spec: KernelSpec) -> bool:
    return not any(op[0] in NON_CLIFFORD_OPS for op in spec.ops)


def signature(exc: BaseException) -> str:
    """A stable, coarse label for an exception: type plus its normalized message."""
    head = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    head = re.sub(r"0x[0-9a-fA-F]+", "0x#", head)
    head = re.sub(r"\d+", "#", head)
    head = re.sub(r"\s+", " ", head)
    return f"{type(exc).__name__}: {head[:80]}"


def compile_to_move(kernel: ir.Method, strategy, has_measure: bool) -> ir.Method:
    arch = physical_arch()
    if has_measure:
        return PhysicalPipeline(arch_spec=arch, placement_strategy=strategy).emit(
            kernel, no_raise=False
        )
    # Same stages as `benchmarks/harness/runner.py::_squin_to_move` (physical).
    place_mt = NativeToPlace(arch_spec=arch).emit(kernel, no_raise=False)
    SequentialPlacePass(place_mt.dialects, no_raise=False)(place_mt)
    return PlaceToMove(
        layout_heuristic=PhysicalLayoutHeuristicGraphPartitionCenterOut(arch_spec=arch),
        placement_strategy=strategy,
        insert_initialize=False,
    ).emit(place_mt, no_raise=False)


def rust_validate(move_mt: ir.Method) -> None:
    """Raise if the Rust validator rejects any lane group of ``move_mt``."""
    arch = physical_arch()
    for stmt in move_mt.callable_region.walk():
        if isinstance(stmt, move.Move):
            errors = list(arch.check_lane_group(stmt.lanes))
            if errors:
                raise AssertionError(f"check_lanes rejected {stmt.lanes}: {errors}")
    # Replays every Move through AtomStateData.validate_moves (Rust).
    atom.AtomInterpreter(move_mt.dialects, arch_spec=arch).run(move_mt)


def check_kernel(
    spec: KernelSpec, strategy_name: str, plant: PlantHook | None = None
) -> Outcome:
    """Run all checks for ``spec`` under ``strategy_name``.

    ``plant`` (tests only) may rewrite the lifted kernel before the equivalence
    check, to prove that the check notices a wrong gate.
    """
    start = time.perf_counter()

    def done(status, category, detail="") -> Outcome:
        return Outcome(status, category, detail, time.perf_counter() - start)

    kernel = build_kernel(spec)
    strategy = build_strategy(strategy_name)

    try:
        move_mt = compile_to_move(kernel, strategy, spec.measure)
    except PlacementError as exc:
        if "CZ routing solver failed" in str(exc):
            return done("expected", "expected: routing solver failed", str(exc))
        return done("failure", f"compile: {signature(exc)}", str(exc))
    except Exception as exc:  # noqa: BLE001 - every other exception is a finding
        return done("failure", f"compile: {signature(exc)}", repr(exc))

    left = sum(isinstance(s, place.CZ) for s in move_mt.callable_region.walk())
    if left:
        return done("failure", "not lowered: place.CZ left", f"{left} place.CZ remain")

    try:
        rust_validate(move_mt)
    except Exception as exc:  # noqa: BLE001
        return done("failure", f"validator: {signature(exc)}", repr(exc))

    try:
        lifted = MoveToSquinPhysical(physical_arch()).emit(move_mt, no_raise=False)
        if plant is not None:
            lifted = plant(lifted)
    except Exception as exc:  # noqa: BLE001
        return done("failure", f"to-squin: {signature(exc)}", repr(exc))

    try:
        if is_clifford(spec):
            equal = equiv.tableaus_equal(kernel, lifted)
            kind = "tableau"
        else:
            equal = equiv.statevectors_equal_up_to_phase(
                equiv.statevector(kernel), equiv.statevector(lifted)
            )
            kind = "statevector"
    except Exception as exc:  # noqa: BLE001
        return done("failure", f"equivalence-crash: {signature(exc)}", repr(exc))
    if not equal:
        return done("failure", f"equivalence: {kind} differs", f"{kind} mismatch")
    return done("ok", "ok")
