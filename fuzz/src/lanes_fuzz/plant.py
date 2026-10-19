"""Deliberate bugs, used only to prove the equivalence check can fail."""

from __future__ import annotations

from bloqade.squin import gate
from kirin import ir
from kirin.dialects import func, ilist

from bloqade import qubit


def plant_extra_x(method: ir.Method) -> ir.Method:
    """Return a copy of ``method`` with a stray ``X`` on its first qubit.

    This is the "wrong gate injected after lowering" bug: the lowered circuit
    then differs from the original by a Pauli, which changes the Clifford
    tableau (and the state vector, unless the first qubit happens to sit in an
    ``X`` eigenstate).
    """
    method = method.similar()
    stmts = list(method.callable_region.walk())
    first_qubit = next(s for s in stmts if isinstance(s, qubit.stmts.New))
    ret = next(s for s in stmts if isinstance(s, func.Return))
    group = ilist.New(values=(first_qubit.result,))
    group.insert_before(ret)
    gate.stmts.X(qubits=group.result).insert_before(ret)
    return method
