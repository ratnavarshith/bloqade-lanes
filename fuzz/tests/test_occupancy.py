"""The occupancy analysis on hand-built move IR (Gemini physical arch).

Facts used (checked against ``ArchSpec.try_get_endpoints``): word lane
``WordLaneAddress(0, s, 0)`` carries (word 0, site s) to (word 1, site s); its
backward twin the reverse; ``SiteLaneAddress(1, 0, 0)`` carries (1, 0) to (1, 1).
"""

import pytest
from lanes_fuzz.occupancy import (
    Anything,
    Cell,
    Layout,
    OccupancyAnalysis,
    Unreached,
    analyze,
)
from lanes_fuzz.strategies import physical_arch

from bloqade.lanes.bytecode.encoding import (
    Direction,
    SiteLaneAddress,
    WordLaneAddress,
)
from bloqade.lanes.dialects import move
from bloqade.lanes.prelude import kernel

ARCH = physical_arch()


def loc(word, site):
    return move.LocationAddress(word, site)


def kinds(method):
    return [v.kind for v in analyze(method, ARCH)]


def run(method):
    analysis = OccupancyAnalysis(method.dialects, arch_spec=ARCH)
    analysis.run(method)
    return analysis


def test_a_valid_move_is_accepted_and_moves_the_atom():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0), loc(0, 1)))
        s2 = move.move(s1, lanes=(WordLaneAddress(0, 0, 0),))
        move.store(s2)

    analysis = run(main)
    assert analysis.violations == []
    assert analysis.current_state.sites == {loc(1, 0): 0, loc(0, 1): 1}


def test_a_move_set_of_several_lanes_moves_every_atom():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0), loc(0, 1)))
        s2 = move.move(
            s1, lanes=(WordLaneAddress(0, 0, 0), WordLaneAddress(0, 1, 0))
        )
        move.store(s2)

    analysis = run(main)
    assert analysis.violations == []
    assert analysis.current_state.sites == {loc(1, 0): 0, loc(1, 1): 1}


def test_a_move_from_an_empty_site_is_reported():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 1),))
        move.move(s1, lanes=(WordLaneAddress(0, 0, 0),))

    assert kinds(main) == ["empty-source"]


def test_a_move_into_a_stationary_atom_is_a_collision():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0), loc(1, 0)))
        move.move(s1, lanes=(WordLaneAddress(0, 0, 0),))

    assert kinds(main) == ["collision"]


def test_two_lanes_into_one_site_collide():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0),))
        move.move(s1, lanes=(WordLaneAddress(0, 0, 0), WordLaneAddress(0, 0, 0)))

    assert "collision" in kinds(main)


def test_fill_onto_an_occupied_site_is_a_collision():
    @kernel
    def main():
        s0 = move.load()
        move.fill(s0, location_addresses=(loc(0, 0), loc(0, 0)))

    assert kinds(main) == ["collision"]


def test_lanes_of_different_move_types_are_inconsistent():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0), loc(1, 0)))
        move.move(s1, lanes=(WordLaneAddress(0, 0, 0), SiteLaneAddress(1, 0, 0)))

    found = analyze(main, ARCH)
    assert [v.kind for v in found] == ["inconsistent-lanes"]
    assert "move type" in found[0].detail


def test_lanes_of_different_directions_are_inconsistent():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0), loc(1, 1)))
        move.move(
            s1,
            lanes=(
                WordLaneAddress(0, 0, 0),
                WordLaneAddress(0, 1, 0, Direction.BACKWARD),
            ),
        )

    found = analyze(main, ARCH)
    assert [v.kind for v in found] == ["inconsistent-lanes"]
    assert "direction" in found[0].detail


def test_lanes_of_different_buses_are_inconsistent():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0), loc(0, 1)))
        move.move(s1, lanes=(WordLaneAddress(0, 0, 0), WordLaneAddress(0, 1, 1)))

    assert "inconsistent-lanes" in kinds(main)


def test_a_lane_that_is_not_in_the_arch_is_reported():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0),))
        move.move(s1, lanes=(SiteLaneAddress(0, 0, 0),))

    assert kinds(main) == ["invalid-lane"]


def test_a_reported_collision_is_not_reported_again_downstream():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0), loc(1, 0)))
        s2 = move.move(s1, lanes=(WordLaneAddress(0, 0, 0),))  # collides at (1, 0)
        move.move(s2, lanes=(WordLaneAddress(0, 0, 0, Direction.BACKWARD),))

    assert kinds(main) == ["collision"]


def test_a_move_twice_from_the_same_site_is_caught_by_the_second():
    @kernel
    def main():
        s0 = move.load()
        s1 = move.fill(s0, location_addresses=(loc(0, 0),))
        s2 = move.move(s1, lanes=(WordLaneAddress(0, 0, 0),))
        move.move(s2, lanes=(WordLaneAddress(0, 0, 0),))

    assert kinds(main) == ["empty-source"]


# ── the lattice ──────────────────────────────────────────────────────


def test_join_of_layouts_is_unknown_where_they_differ():
    a = Layout({loc(0, 0): 0, loc(0, 1): 1})
    b = Layout({loc(0, 0): 0, loc(0, 1): 2, loc(1, 0): 3})
    joined = a.join(b)
    assert isinstance(joined, Layout)
    assert joined.sites == {
        loc(0, 0): 0,
        loc(0, 1): Cell.UNKNOWN,
        loc(1, 0): Cell.UNKNOWN,
    }


def test_unreached_is_the_identity_of_join_and_anything_absorbs():
    a = Layout({loc(0, 0): 0})
    assert a.join(Unreached()).is_structurally_equal(a)
    assert Unreached().join(a).is_structurally_equal(a)
    assert isinstance(a.join(Anything()), Anything)


def test_meet_keeps_the_known_cell_and_fails_on_a_conflict():
    known = Layout({loc(0, 0): 0})
    vague = Layout({loc(0, 0): Cell.UNKNOWN})
    assert known.meet(vague).is_structurally_equal(known)
    assert isinstance(known.meet(Layout({loc(0, 0): 1})), Unreached)
    assert known.meet(Anything()).is_structurally_equal(known)


@pytest.mark.parametrize(
    "a, b",
    [
        (Layout({loc(0, 0): 0}), Layout({loc(0, 0): Cell.UNKNOWN})),
        (Unreached(), Layout()),
        (Layout(), Anything()),
    ],
)
def test_subseteq_follows_the_order(a, b):
    assert a.is_subseteq(b)
    assert not b.is_subseteq(a)
