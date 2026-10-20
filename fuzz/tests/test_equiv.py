"""The equivalence helpers accept equal circuits and reject different ones."""

import numpy as np
import pytest
import stim
from lanes_fuzz import equiv
from lanes_fuzz.gen import KernelSpec, build_kernel

H_THEN_CZ = KernelSpec(2, (("h", 0), ("cz", 0, 1)), measure=True)
H_ONLY = KernelSpec(2, (("h", 0),), measure=True)
# `cx(0, 1)` equals `h(1); cz(0, 1); h(1)`: different source, same unitary.
CX = KernelSpec(2, (("cx", 0, 1),), measure=False)
H_CZ_H = KernelSpec(2, (("h", 1), ("cz", 0, 1), ("h", 1)), measure=False)


def test_equal_kernels_have_equal_tableaus():
    assert equiv.tableaus_equal(build_kernel(CX), build_kernel(H_CZ_H))


def test_different_kernels_have_different_tableaus():
    assert not equiv.tableaus_equal(build_kernel(H_THEN_CZ), build_kernel(H_ONLY))


def test_tableau_ignores_the_terminal_measurement():
    with_measure = KernelSpec(2, (("h", 0), ("cz", 0, 1)), measure=True)
    without = KernelSpec(2, (("h", 0), ("cz", 0, 1)), measure=False)
    assert equiv.tableaus_equal(build_kernel(with_measure), build_kernel(without))


def test_tableau_distinguishes_a_pauli_sign():
    # X changes only signs of the tableau, never which Paulis map where.
    plain = KernelSpec(1, (("h", 0),), measure=False)
    flipped = KernelSpec(1, (("h", 0), ("x", 0)), measure=False)
    assert not equiv.tableaus_equal(build_kernel(plain), build_kernel(flipped))


def test_kernel_to_stim_matches_the_source_circuit():
    circuit = equiv.kernel_to_stim(build_kernel(H_THEN_CZ))
    assert circuit == stim.Circuit("H 0\nCZ 0 1\nM(0) 0 1")


def test_statevectors_equal_up_to_global_phase():
    a = np.array([1, 1j, 0, 0]) / np.sqrt(2)
    assert equiv.statevectors_equal_up_to_phase(a, a * np.exp(0.7j))


def test_statevectors_with_different_amplitudes_differ():
    a = np.array([1, 0, 0, 0], dtype=complex)
    b = np.array([0, 1, 0, 0], dtype=complex)
    assert not equiv.statevectors_equal_up_to_phase(a, b)
    assert not equiv.statevectors_equal_up_to_phase(a, np.array([1, 0], dtype=complex))


def test_statevectors_with_a_relative_phase_differ():
    plus = np.array([1, 1]) / np.sqrt(2)
    minus = np.array([1, -1]) / np.sqrt(2)
    assert not equiv.statevectors_equal_up_to_phase(plus, minus)


@pytest.mark.parametrize("k", [1, 3, -2])
def test_statevector_of_a_rotation_kernel_is_normalized(k):
    spec = KernelSpec(2, (("h", 0), ("rz", 0, k), ("cx", 0, 1)), measure=False)
    state = equiv.statevector(build_kernel(spec))
    assert state.shape == (4,)
    assert abs(np.linalg.norm(state) - 1) < 1e-6


H_CZ_H_ONLY_CZ = KernelSpec(2, (("cz", 0, 1),), measure=False)
T_ON_PLUS = KernelSpec(2, (("h", 0), ("h", 1), ("t", 1)), measure=False)


def test_unitary_check_accepts_the_same_unitary_written_differently():
    assert equiv.unitaries_equal(build_kernel(CX), build_kernel(H_CZ_H))


def test_unitary_check_rejects_a_different_unitary():
    assert not equiv.unitaries_equal(build_kernel(CX), build_kernel(H_CZ_H_ONLY_CZ))


def test_unitary_check_sees_a_relative_phase_between_columns():
    # S differs from identity only by a phase on |1>: invisible from |0>.
    s_gate = KernelSpec(1, (("s", 0),), measure=False)
    identity = KernelSpec(1, (("h", 0), ("h", 0)), measure=False)
    assert equiv.statevectors_equal_up_to_phase(
        equiv.statevector(build_kernel(s_gate)),
        equiv.statevector(build_kernel(identity)),
    )
    assert not equiv.unitaries_equal(build_kernel(s_gate), build_kernel(identity))


def _lowered(spec):
    from lanes_fuzz.check import compile_to_move
    from lanes_fuzz.strategies import build_strategy, physical_arch

    from bloqade.lanes.transform import MoveToSquinPhysical

    kernel = build_kernel(spec)
    move_mt = compile_to_move(kernel, build_strategy("astar"), False)
    return kernel, MoveToSquinPhysical(physical_arch()).emit(move_mt, no_raise=False)


def test_unitary_check_rejects_what_one_statevector_cannot_see():
    """A stray X on the |+> qubit leaves the state from |00> unchanged."""
    from lanes_fuzz.plant import plant_extra_x

    kernel, lifted = _lowered(T_ON_PLUS)
    planted = plant_extra_x(lifted)
    assert equiv.statevectors_equal_up_to_phase(
        equiv.statevector(kernel), equiv.statevector(planted)
    )
    assert not equiv.unitaries_equal(kernel, planted)


def test_unitary_works_on_a_lowered_kernel_with_qubit_new_statements():
    kernel, lifted = _lowered(T_ON_PLUS)
    assert equiv.unitaries_equal(kernel, lifted)
