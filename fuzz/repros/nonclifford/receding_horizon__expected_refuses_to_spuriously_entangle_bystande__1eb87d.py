"""Standalone repro found by lanes-fuzz.

strategy: receding_horizon
category: expected: refuses to spuriously entangle bystander atoms
detail:   a non-participating atom sits at a CZ partner site whose partner is also occupied; the global CZ pulse would spuriously entangle these bystanders alongside the intended pairs (controls=(0,), targets=(
kernel:   4 qubits, 2 ops, terminal measure: False

Run with bloqade-lanes and stim installed:  python receding_horizon__expected_refuses_to_spuriously_entangle_bystande__1eb87d.py
"""

from bloqade.lanes.analysis.placement import PalindromePlacementStrategy
from bloqade.lanes.bytecode import MoverSelection
from bloqade.lanes.heuristics.physical import (
    NoReturnPlacementStrategy,
    RecedingHorizonNoReturnPlacementStrategy,
    make_physical_placement_strategy,
)
from bloqade.lanes.heuristics.physical.placement import (
    PhysicalPlacementStrategy,
    RustPlacementTraversal,
)

from kirin.dialects import ilist

from bloqade import squin


@squin.kernel
def main():
    reg = squin.qalloc(4)
    squin.broadcast.cz(ilist.IList([reg[0], reg[1]]), ilist.IList([reg[2], reg[3]]))
    squin.cx(reg[0], reg[2])

# ── equivalence helpers (lanes_fuzz.equiv) ──────────────────────────


import io

import numpy as np
import stim
from bloqade.stim.emit.stim_str import EmitStimMain
from bloqade.stim.upstream.from_squin import squin_to_stim
from kirin import ir, rewrite

from bloqade.lanes.rewrite.squin2stim import RemoveReturn


def kernel_to_stim(method: ir.Method) -> stim.Circuit:
    """Lower a squin kernel to a ``stim.Circuit`` (the original is not mutated)."""
    method = method.similar()
    # `rewrite` on a single node would miss the nested `func.Return`; walk.
    rewrite.Walk(RemoveReturn()).rewrite(method.code)
    method = squin_to_stim(method)
    buf = io.StringIO()
    emit = EmitStimMain(dialects=method.dialects, io=buf)
    emit.initialize()
    emit.run(node=method)
    return stim.Circuit(buf.getvalue())


def tableau_of(method: ir.Method) -> stim.Tableau:
    return stim.Tableau.from_circuit(kernel_to_stim(method), ignore_measurement=True)


def tableaus_equal(before: ir.Method, after: ir.Method) -> bool:
    return tableau_of(before) == tableau_of(after)


def statevector(method: ir.Method) -> np.ndarray:
    from bloqade.pyqrack.device import StackMemorySimulator

    return np.asarray(StackMemorySimulator().state_vector(method), dtype=complex)


def statevectors_equal_up_to_phase(
    a: np.ndarray, b: np.ndarray, atol: float = 1e-6
) -> bool:
    if a.shape != b.shape:
        return False
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return False
    return bool(abs(np.vdot(a, b)) / norm >= 1.0 - atol)

# ── compile and validate (lanes_fuzz.check) ─────────────────────────
import re  # noqa: E402
import sys  # noqa: E402

from bloqade.lanes.analysis import atom  # noqa: E402
from bloqade.lanes.analysis.placement.exceptions import PlacementError  # noqa: E402
from bloqade.lanes.arch.gemini import physical  # noqa: E402
from bloqade.lanes.dialects import move, place  # noqa: E402
from bloqade.lanes.heuristics.physical.layout import (  # noqa: E402
    PhysicalLayoutHeuristicGraphPartitionCenterOut,
)
from bloqade.lanes.passes import SequentialPlacePass  # noqa: E402
from bloqade.lanes.transform import (  # noqa: E402
    MoveToSquinPhysical,
    NativeToPlace,
    PhysicalPipeline,
    PlaceToMove,
)

_ARCH = physical.get_arch_spec()


def physical_arch():
    return _ARCH


def expected_category(exc: BaseException) -> str | None:
    """The category of a documented, intentional refusal; ``None`` for anything else.

    Both are ``PlacementError``s the placement code raises on purpose:

    * the routing solver found no plan inside its budget or none exists;
    * the no-return strategies refuse a layout whose global CZ pulse would
      entangle bystander atoms (``tests/heuristics/test_no_return_base.py``
      asserts on this message).

    They are recorded and reported with their reason, never counted as failures.
    """
    if isinstance(exc, PlacementError):
        text = str(exc)
        if "CZ routing solver failed" in text:
            return "expected: routing solver failed"
        if "would spuriously entangle" in text:
            return "expected: refuses to spuriously entangle bystander atoms"
    return None


def signature(exc: BaseException) -> str:
    """A stable, coarse label for an exception: type plus its normalized message."""
    head = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    head = re.sub(r"0x[0-9a-fA-F]+", "<addr>", head)
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



HAS_MEASURE = False
CLIFFORD = True
EXPECTED_CATEGORY = 'expected: refuses to spuriously entangle bystander atoms'


def reproduce() -> str:
    """Run the steps of lanes_fuzz.check.check_kernel; return the category."""
    arch = physical_arch()
    strategy = RecedingHorizonNoReturnPlacementStrategy(arch_spec=arch)
    try:
        move_mt = compile_to_move(main, strategy, HAS_MEASURE)
    except Exception as exc:  # noqa: BLE001
        return expected_category(exc) or "compile: " + signature(exc)
    if any(isinstance(s, place.CZ) for s in move_mt.callable_region.walk()):
        return "not lowered: place.CZ left"
    try:
        rust_validate(move_mt)
    except Exception as exc:  # noqa: BLE001
        return "validator: " + signature(exc)
    try:
        lifted = MoveToSquinPhysical(arch).emit(move_mt, no_raise=False)
    except Exception as exc:  # noqa: BLE001
        return "to-squin: " + signature(exc)
    try:
        if CLIFFORD:
            equal, kind = tableaus_equal(main, lifted), "tableau"
        else:
            equal = statevectors_equal_up_to_phase(
                statevector(main), statevector(lifted)
            )
            kind = "statevector"
    except Exception as exc:  # noqa: BLE001
        return "equivalence-crash: " + signature(exc)
    return "ok" if equal else "equivalence: " + kind + " differs"


if __name__ == "__main__":
    got = reproduce()
    if got == EXPECTED_CATEGORY:
        print("REPRODUCED: " + got)
        sys.exit(1)
    print("NOT REPRODUCED (got " + repr(got) + ")")
    sys.exit(0)
