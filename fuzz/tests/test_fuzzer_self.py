"""The fuzzer itself: a planted bug must be caught, shrunk and reproduced.

If these fail, a green fuzz run means nothing.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from kirin import ir
from lanes_fuzz.check import check_kernel
from lanes_fuzz.gen import GenConfig, KernelSpec
from lanes_fuzz.plant import plant_extra_x
from lanes_fuzz.props import run_strategy
from lanes_fuzz.repro import render_repro, write_repro

from bloqade.lanes.bytecode.encoding import SiteLaneAddress, WordLaneAddress
from bloqade.lanes.dialects import move

GHZ = KernelSpec(3, (("h", 0), ("cx", 0, 1), ("cx", 1, 2)), measure=True)
ROTATED = KernelSpec(2, (("rx", 0, 1), ("cx", 0, 1)), measure=False)
PLUS = KernelSpec(2, (("h", 0), ("cx", 0, 1)), measure=False)

STRATEGIES = ["astar", "greedy", "cascade-ids", "pipeline_default", "loose_goal"]


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_control_the_unplanted_kernel_passes(strategy):
    assert check_kernel(GHZ, strategy).status == "ok"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_wrong_gate_after_lowering_is_caught_by_the_tableau_check(strategy):
    outcome = check_kernel(GHZ, strategy, plant=plant_extra_x)
    assert outcome.failed
    assert outcome.category == "equivalence: tableau differs"


def test_a_wrong_gate_is_caught_by_the_statevector_check():
    assert check_kernel(ROTATED, "astar").status == "ok"
    outcome = check_kernel(ROTATED, "astar", plant=plant_extra_x)
    assert outcome.category == "equivalence: statevector differs"


def test_statevector_check_is_blind_to_x_on_a_plus_state():
    """Documented limitation: X|+> = |+>, so this planted bug is invisible to a
    statevector comparison on |0...0> (and visible to the tableau check)."""
    spec = KernelSpec(2, (("h", 0), ("h", 1), ("t", 1)), measure=False)
    assert check_kernel(spec, "astar", plant=plant_extra_x).status == "ok"


def _break_first_move(move_mt: ir.Method) -> ir.Method:
    """Replace the first move.Move by one whose lane group mixes two bus types."""
    move_mt = move_mt.similar()
    first = next(s for s in move_mt.callable_region.walk() if isinstance(s, move.Move))
    bad = (SiteLaneAddress(0, 0, 0), WordLaneAddress(0, 0, 0))
    first.replace_by(move.Move(first.current_state, lanes=bad))
    return move_mt


def test_an_invalid_lane_group_is_caught_by_the_rust_validator():
    assert check_kernel(GHZ, "astar").status == "ok"
    outcome = check_kernel(GHZ, "astar", plant_move=_break_first_move)
    assert outcome.failed
    assert outcome.category.startswith("validator:")
    assert "check_lanes" in outcome.detail


def test_the_driver_finds_shrinks_and_records_a_planted_bug(tmp_path):
    cfg = GenConfig(max_ops=8)
    summary = run_strategy(
        "astar",
        cfg,
        examples=30,
        repro_dir=tmp_path,
        plant=plant_extra_x,
        planted_repros=True,
    )
    assert summary["completed_clean_pass"]
    assert set(summary["minimal_failures"]) == {"equivalence: tableau differs"}
    minimal = summary["minimal_failures"]["equivalence: tableau differs"]
    # Hypothesis shrank it to the smallest kernel the config allows.
    assert minimal["n_qubits"] == cfg.min_qubits
    assert minimal["n_ops"] == cfg.min_ops
    # Every example was counted in the final pass, none dropped.
    assert summary["examples_run"] >= 30
    assert Path(minimal["repro"]).exists()


def test_a_repro_script_runs_standalone_and_reproduces_the_failure(tmp_path):
    path = write_repro(
        tmp_path, GHZ, "astar", "equivalence: tableau differs", planted=True
    )
    done = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert "REPRODUCED: equivalence: tableau differs" in done.stdout


def test_a_repro_script_reports_when_the_failure_is_gone(tmp_path):
    path = write_repro(tmp_path, GHZ, "astar", "equivalence: tableau differs")
    done = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "NOT REPRODUCED" in done.stdout


def test_repro_scripts_are_valid_python_for_every_strategy():
    from lanes_fuzz.strategies import STRATEGY_NAMES

    for name in STRATEGY_NAMES:
        compile(render_repro(GHZ, name, "x"), f"<repro {name}>", "exec")
