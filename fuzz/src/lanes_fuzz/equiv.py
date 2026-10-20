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

``unitaries_equal`` (non-Clifford kernels, <= 6 qubits)
    Both kernels are run from every computational basis state and from
    ``(|0> + |b>)/sqrt 2`` for every ``b > 0`` (prep gates are inserted right
    after the allocation), each probe compared up to its own phase because the
    simulator randomizes the global phase of every run. If ``U_a`` and ``U_b``
    agree on all probes they are equal up to one global phase (the basis probes
    fix each column, the superpositions tie each column's phase to column 0).
    Unlike the single statevector this sees every input, so a stray ``Z`` on a
    ``|0>`` qubit or ``X`` on a ``|+>`` qubit is caught. Costs ``2^(n+1)-1``
    simulations per kernel, hence the qubit limit.
"""

from __future__ import annotations

import io

import numpy as np
import stim
from bloqade.stim.emit.stim_str import EmitStimMain
from bloqade.stim.upstream.from_squin import squin_to_stim
from bloqade.squin import gate
from kirin import ir, rewrite
from kirin.dialects import ilist, py
from kirin.dialects.func import Invoke

from bloqade import qubit

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


MAX_UNITARY_QUBITS = 6

Prep = tuple[tuple, ...]  # ("x", q) | ("h", q) | ("cx", control, target)


def _with_prep(method: ir.Method, prep: Prep) -> ir.Method:
    """Copy of ``method`` with the gates ``prep`` applied right after allocation.

    Handles both allocation forms: ``qubit.new`` statements (lowered kernels) and
    one ``qalloc`` call whose register is indexed (kernels written in squin).
    """
    method = method.similar()
    stmts = list(method.callable_region.walk())
    news = [s for s in stmts if isinstance(s, qubit.stmts.New)]
    if news:
        anchor, qubits = news[-1], [n.result for n in news]
    else:
        anchor = next(s for s in stmts if isinstance(s, Invoke))  # `qalloc(n)`
        n_qubits = int(np.log2(len(statevector(method))))
        qubits, at = [], anchor
        for i in range(n_qubits):
            idx = py.Constant(i)
            get = py.indexing.GetItem(anchor.result, idx.result)
            idx.insert_after(at)
            get.insert_after(idx)
            at = get
            qubits.append(get.result)
        anchor = at
    for op in prep:
        groups = []
        for q in op[1:]:
            groups.append(ilist.New(values=(qubits[q],)))
        for g in groups:
            g.insert_after(anchor)
            anchor = g
        if op[0] == "cx":
            gate_stmt = gate.stmts.CX(
                controls=groups[0].result, targets=groups[1].result
            )
        else:
            gate_stmt = {"x": gate.stmts.X, "h": gate.stmts.H}[op[0]](
                qubits=groups[0].result
            )
        gate_stmt.insert_after(anchor)
        anchor = gate_stmt
    return method


def _probe_preps(n: int) -> list[Prep]:
    """Input states: every basis state, and ``(|0> + |b>)/sqrt 2`` for every ``b > 0``.

    The simulator gives each run a random global phase, so each probe is compared
    on its own up to phase. Basis probes alone would miss a relative phase between
    columns; the superposition probes pin every column to column 0.
    """
    preps: list[Prep] = []
    for b in range(2**n):
        bits = [i for i in range(n) if (b >> i) & 1]
        preps.append(tuple(("x", i) for i in bits))
        if b:
            fanout = tuple(("cx", bits[0], i) for i in bits[1:])
            preps.append((("h", bits[0]),) + fanout)
    return preps


def unitaries_equal(before: ir.Method, after: ir.Method) -> bool:
    """Equal as unitaries up to global phase, for measurement-free kernels."""
    n = int(np.log2(len(statevector(before))))
    return all(
        statevectors_equal_up_to_phase(
            statevector(_with_prep(before, prep)), statevector(_with_prep(after, prep))
        )
        for prep in _probe_preps(n)
    )


def nonclifford_equal(before: ir.Method, after: ir.Method) -> tuple[bool, str]:
    """Compare two measurement-free kernels; returns ``(equal, kind)``.

    The full unitary up to global phase for at most ``MAX_UNITARY_QUBITS`` qubits,
    otherwise the single statevector from ``|0...0>``.
    """
    n = int(np.log2(len(statevector(before))))
    if n <= MAX_UNITARY_QUBITS:
        return unitaries_equal(before, after), "unitary"
    return (
        statevectors_equal_up_to_phase(statevector(before), statevector(after)),
        "statevector",
    )
