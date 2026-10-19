"""Equivalence checks between a squin kernel before and after lowering.

Self-contained on purpose: this module's source is pasted into every standalone
repro script, so it imports only bloqade-lanes' dependencies and stim.

What is compared
================

``tableau_of`` / ``tableaus_equal`` (Clifford kernels)
    The kernel is lowered to the Stim dialect (``squin_to_stim``) and emitted as
    a ``stim.Circuit``. ``stim.Tableau.from_circuit(circuit,
    ignore_measurement=True)`` is the Clifford unitary the circuit applies. Two
    tableaus are equal exactly when the unitaries are equal **up to global
    phase** (a tableau does not record a global phase), including every
    Pauli sign. Measurements are dropped, so this compares the unitary part, not
    measurement records.

``statevector`` / ``statevectors_equal_up_to_phase`` (non-Clifford kernels)
    ``StackMemorySimulator.state_vector`` of the kernel run from ``|0...0>``
    (the kernel must contain no measurement). Equal means the normalized
    overlap ``|<a|b>|`` is within ``atol`` of 1, i.e. equal up to global phase.
    This compares the output state on the all-zeros input only; it can miss a
    difference that is invisible on that state (for example a stray ``Z`` on a
    qubit still in ``|0>``).
"""

from __future__ import annotations

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
