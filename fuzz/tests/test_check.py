"""Classification of outcomes in lanes_fuzz.check."""

import subprocess
import sys

import pytest

from bloqade.lanes.analysis.placement.exceptions import PlacementError

from lanes_fuzz.check import check_kernel, expected_category, signature
from lanes_fuzz.gen import KernelSpec
from lanes_fuzz.repro import write_repro

SPURIOUS = "expected: refuses to spuriously entangle bystander atoms"

# Found and minimized by the fuzzer (4 qubits, 2 ops); the no-return strategies
# refuse it on purpose. A characterization of current behaviour: if lanes ever
# accepts this kernel, update the expectation rather than the check.
BYSTANDER = KernelSpec(4, (("bcz", ((0, 1), (2, 3))), ("cx", 0, 1)), measure=True)


@pytest.mark.parametrize(
    ("message", "category"),
    [
        (
            "CZ routing solver failed for pairs [(0, 1)]; no plan",
            "expected: routing solver failed",
        ),
        ("the global CZ pulse would spuriously entangle these bystanders", SPURIOUS),
    ],
)
def test_documented_refusals_are_expected(message, category):
    assert expected_category(PlacementError(message)) == category


def test_other_placement_errors_are_not_expected():
    assert (
        expected_category(PlacementError("qubits 0 and 3 are both assigned a site"))
        is None
    )


def test_other_exception_types_are_not_expected_even_with_the_same_text():
    assert expected_category(ValueError("CZ routing solver failed")) is None


def test_signature_normalizes_numbers_and_addresses():
    a = signature(ValueError("qubit 3 at 0x10004000000 failed"))
    b = signature(ValueError("qubit 11 at 0x2000 failed"))
    assert a == b == "ValueError: qubit # at <addr> failed"


@pytest.mark.parametrize("strategy", ["loose_goal", "receding_horizon"])
def test_a_bystander_refusal_is_recorded_as_expected_not_failure(strategy):
    outcome = check_kernel(BYSTANDER, strategy)
    assert outcome.status == "expected"
    assert outcome.category == SPURIOUS
    assert not outcome.failed


def test_the_other_strategies_handle_the_same_kernel():
    assert check_kernel(BYSTANDER, "astar").status == "ok"


def test_an_expected_refusal_has_a_standalone_repro(tmp_path):
    path = write_repro(tmp_path, BYSTANDER, "loose_goal", SPURIOUS)
    done = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert f"REPRODUCED: {SPURIOUS}" in done.stdout
