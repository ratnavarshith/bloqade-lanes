"""The differential harness: mutators keep the IR well formed and the two judges
agree on the cases where their rules coincide."""

import random

import pytest
from lanes_fuzz import diff
from lanes_fuzz.check import compile_to_move
from lanes_fuzz.gen import KernelSpec, build_kernel
from lanes_fuzz.strategies import build_strategy

GHZ = KernelSpec(3, (("h", 0), ("cx", 0, 1), ("cx", 1, 2)), measure=True)


@pytest.fixture(scope="module")
def base():
    return compile_to_move(build_kernel(GHZ), build_strategy("astar"), True)


def lane_pool(mt):
    return [lane for m in diff._moves(mt) for lane in m.lanes]


def test_a_compiled_program_is_accepted_by_both(base):
    record = diff.judge(base)
    assert diff.verdict(record) == "both accept", record


@pytest.mark.parametrize("kind", diff.MUTATIONS)
def test_mutants_are_well_formed_and_differ_from_the_base(base, kind):
    before = [m.lanes for m in diff._moves(base)]
    mutant, how = diff.mutate(kind, base, random.Random(1), lane_pool(base))
    assert [m.lanes for m in diff._moves(base)] == before  # base untouched
    assert [m.lanes for m in diff._moves(mutant)] != before, how
    mutant.verify()
    diff.judge(mutant)  # neither side crashes the harness


def test_dropping_a_move_set_removes_exactly_one(base):
    mutant, _ = diff.mutate("drop", base, random.Random(0), [])
    assert len(diff._moves(mutant)) == len(diff._moves(base)) - 1


def test_duplicating_a_move_set_adds_exactly_one(base):
    mutant, _ = diff.mutate("duplicate", base, random.Random(0), [])
    assert len(diff._moves(mutant)) == len(diff._moves(base)) + 1


def test_both_reject_an_atom_moved_twice(base):
    # Running a set twice moves the atoms again from sites that are now empty.
    mutant, _ = diff.mutate("duplicate", base, random.Random(0), [])
    assert diff.verdict(diff.judge(mutant)) == "both reject"
