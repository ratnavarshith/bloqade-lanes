"""The Rust validator accepts a move set in which no lane has an atom.

Candidate validator gap, found by the differential test (``lanes_fuzz.diff``):
the validator treats a lane with an empty source and a free destination as a
legal no-op ("AOD rectangle filler", ``atom_state.rs`` ``validate_moves``), so a
whole move set of such lanes passes. Compiler output does contain fillers next
to real movers (``loose_goal``, 5 qubits), so the rule itself is needed; what
is missing is any check that a set moves at least one atom. A dropped or
swapped move set then validates silently and only the equivalence check
notices.

Needs only bloqade-lanes:  uv run python repros/validator/empty_source_move_set_accepted.py
Exit 1 and "REPRODUCED" while the validator accepts it.
"""

import sys

from bloqade.lanes.analysis import atom
from bloqade.lanes.arch.gemini import physical
from bloqade.lanes.bytecode.encoding import WordLaneAddress
from bloqade.lanes.dialects import move
from bloqade.lanes.prelude import kernel


@kernel
def main():
    s0 = move.load()
    s1 = move.fill(s0, location_addresses=(move.LocationAddress(0, 1),))
    # Word lane (0, 0) -> (1, 0): its source site (0, 0) is empty, the only
    # atom sits at (0, 1). No atom moves.
    move.move(s1, lanes=(WordLaneAddress(0, 0, 0),))


arch = physical.get_arch_spec()
try:
    atom.AtomInterpreter(main.dialects, arch_spec=arch).run(main)
except Exception as exc:  # noqa: BLE001
    print(f"NOT REPRODUCED: the validator rejects it now: {exc}")
    sys.exit(0)
print("REPRODUCED: the validator accepts a move set that moves no atom")
sys.exit(1)
