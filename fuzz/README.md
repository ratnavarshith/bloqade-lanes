# lanes-fuzz

A property-based fuzzer for the bloqade-lanes compilation pipeline. It is a
separate project: nothing here changes `bloqade-lanes` itself, its
`pyproject.toml` or its `uv.lock`.

For random squin kernels it compiles with every lanes placement strategy, then
checks that

1. compilation succeeds and the move IR is fully lowered (no `place.CZ` left),
   or fails with a documented, recorded refusal;
2. the Rust validator accepts the move IR;
3. the lowered program is equivalent to the original kernel.

Failures are shrunk by Hypothesis to a minimal kernel and saved as standalone
repro scripts.

## Install

`bloqade-lanes` is a path dependency on `..` and is **built from the checkout**
(Rust included, so you need a Rust toolchain and `maturin` is fetched by uv):

```bash
cd fuzz
uv sync --locked
```

The install is not editable: the fuzzer tests exactly the commit it was built
from. After changing `bloqade-lanes`, rerun `uv sync --reinstall-package
bloqade-lanes` (or `uv sync --locked --reinstall`).

Versions are pinned. `pyproject.toml` pins `hypothesis`, `pytest`, `stim`, and
constrains every package the repo's own test environment
(`uv sync --locked --dev --extra sim`) installs to the version it installs.
`uv.lock` records the result.

## Run

```bash
# the fuzzer's own tests (generator, equivalence checks, planted bugs)
uv run --locked pytest

# fuzz: 14 strategies in parallel processes, summary as JSON
uv run --locked python -m lanes_fuzz.run --mode clifford    --examples 500 --jobs 4 \
    --repro-dir repros/clifford    --out results/clifford.json
uv run --locked python -m lanes_fuzz.run --mode nonclifford --examples 100 --jobs 4 \
    --repro-dir repros/nonclifford --out results/nonclifford.json

uv run --locked python -m lanes_fuzz.run --list          # strategy names
```

Useful options: `--strategies astar,greedy`, `--seed N`, `--min-qubits`,
`--max-qubits` (non-Clifford is limited to 6), `--min-ops`, `--max-ops`.

Reproduce a saved failure with only `bloqade-lanes` and `stim` installed:

```bash
uv run --locked python repros/clifford/<file>.py     # exit 1 + "REPRODUCED" if it still fails
```

## What is generated

`lanes_fuzz.gen.kernel_specs(GenConfig(...))` draws a small immutable
`KernelSpec`, rendered to a `@squin.kernel`. Valid by construction: qubit
indices in range, two-qubit gates on distinct qubits, broadcast CZ layers on
disjoint qubits, straight-line code, one terminal `measure` of all qubits.

| mode | gates | measure | check |
|---|---|---|---|
| `clifford` | H, S, X, Z, CZ, CX, broadcast CZ | terminal measure of all qubits | Stim tableau |
| `nonclifford` (at most 6 qubits) | the above plus T, RZ, RX (multiples of pi/8) | none | statevector |

Size (`min/max_qubits`, `min/max_ops`) and the gate mix (`weights`) are
parameters of `GenConfig`.

## What is compared

* **Clifford:** the kernel before and after lowering is turned into a
  `stim.Circuit` (`squin_to_stim` + `EmitStimMain`), and
  `stim.Tableau.from_circuit(..., ignore_measurement=True)` of each is compared
  for equality. A tableau fixes the Clifford unitary **up to global phase**,
  including every Pauli sign. Measurements are dropped: this compares the
  unitary part, not measurement records.
* **Non-Clifford:** `StackMemorySimulator.state_vector` of each kernel from
  `|0...0>`; equal when the normalized overlap `|<a|b>|` is within 1e-6 of 1
  (equal up to global phase). This only sees the output on the all-zeros input,
  so a difference invisible on that state (a stray `Z` on a `|0>` qubit, or `X`
  on `|+>`) is missed. `tests/test_fuzzer_self.py` documents one such case.

"After lowering" means the move IR from the strategy, lifted back to squin by
`MoveToSquinPhysical` on the physical arch spec.

## Outcome categories

* `ok`
* `expected: ...` - a documented refusal (a `PlacementError` from the routing
  solver, or the no-return strategies refusing to spuriously entangle bystander
  atoms). Recorded with its reason, shrunk, and given a repro, but reported
  apart from failures. The allow-list is `lanes_fuzz.check.expected_category`.
* failures: `compile: ...` (any other exception), `not lowered: place.CZ left`,
  `validator: ...`, `to-squin: ...`, `equivalence-crash: ...`,
  `equivalence: tableau|statevector differs`.

## How the run works

Hypothesis tells failures apart by exception type, so every category is its own
exception class and is shrunk separately. A run that stopped at the first
failure would stop counting examples, so the driver works in passes: once a
category has a saved minimal repro it is only counted, and the driver repeats
until a pass of the requested number of kernels ends with no new category. The
reported counts are from that last pass.

## Layout

```
src/lanes_fuzz/gen.py         kernel generator (Hypothesis strategy, rendering)
src/lanes_fuzz/strategies.py  the 14 lanes strategies as expressions
src/lanes_fuzz/equiv.py       Stim tableau and statevector comparison
src/lanes_fuzz/check.py       compile + lowering + validator + equivalence
src/lanes_fuzz/props.py       Hypothesis property, passes, summaries
src/lanes_fuzz/repro.py       standalone repro scripts
src/lanes_fuzz/run.py         command line runner
src/lanes_fuzz/plant.py       deliberate bugs, for the self-tests
tests/                        generator, equivalence, classification, planted bugs
repros/                       minimal repro scripts
results/                      JSON summaries of the recorded runs
```
