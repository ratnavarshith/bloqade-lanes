# Results (numbers and repro commands)

Base: `main` = `4c1446a08d7f90e2119a089fe8300c5bec89b7e5`.
Environment: `uv sync --locked --dev --extra sim`. Run commands from `python/` unless they say otherwise.
Raw data lives in `bench/phase1/`, `bench/phase2/` and `bench/phase2c/`.

## Phase 1: reproduction on `main`

```
../.venv/bin/python -m benchmarks.cli --architecture logical \
  --compare benchmarks/harness/latest_logical.csv --output /tmp/phase1/logical.csv
../.venv/bin/python -m benchmarks.cli --architecture physical \
  --strategies rust_cascade_ids --output /tmp/phase1/physical.csv
```

- **Logical:** `no differences found`, exit 0.
- **Physical, `rust_cascade_ids` against `latest_physical.csv`:** 9/9 cases, 0 differing deterministic columns.

| case | success | move_count_events | nodes_explored | max_optimality_gap |
|---|---|---|---|---|
| adder_4 | True | 38 | 48 | 0.500000 |
| adder_64 | True | 1550 | 4810 | 0.833333 |
| bv_70 | True | 198 | 135 | 0.000000 |
| ghz_4 | True | 12 | 9 | 0.333333 |
| ghz_6 | True | 20 | 18 | 0.333333 |
| qpe_9 | True | 220 | 152 | 0.000000 |
| steane_logical_5 | True | 18 | 12 | 0.000000 |
| steane_physical_35 | False | | | |
| trotter_rand_35 | True | 1258 | 11165 | 0.840000 |

Gemini physical spec: 1 zone, 3 site buses, 19 word buses, 0 zone buses, 44 (bus, direction) groups, 1120 lanes.

## Phase 2b: root diagnostic (branch `bus-cut-diag`, strong-term bound)

```
git checkout bus-cut-diag && uv run --locked maturin develop --release
cd python && BUSCUT_DIAG_PATH=/tmp/phase2/diag.csv ../.venv/bin/python -m benchmarks.cli \
  --architecture physical --strategies rust_cascade_ids --output /tmp/phase2/physical_diag_run.csv
python3 bench/phase2/diag_summary.py        # from the repo root; reads bench/phase2/diag.csv
```

- **Roots:** 813 (812 `Solved`, 1 `BudgetExceeded`).
- **Checks:** h < h0 on 0 roots; h > cost on 0; infinite h on 0.
- **Strong term:** `strong > h0` on 0 roots, and `|R| > h0` on 97.

| case | solves | h>h0 | frac | mean(h−h0) | max(h−h0) | agg gap h0 → h | max gap h0 → h | cert (h=cost) h0 / h |
|---|---|---|---|---|---|---|---|---|
| adder_4 | 14 | 0 | 0.0% | 0.000 | 0 | 15.8% → 15.8% | 50.0% → 50.0% | 12 / 12 |
| adder_64 | 514 | 24 | 4.7% | 0.054 | 2 | 33.0% → 31.2% | 83.3% → 77.8% | 330 / 330 |
| bv_70 | 72 | 0 | 0.0% | 0.000 | 0 | 0.0% → 0.0% | 0.0% → 0.0% | 72 / 72 |
| ghz_4 | 4 | 0 | 0.0% | 0.000 | 0 | 16.7% → 16.7% | 33.3% → 33.3% | 2 / 2 |
| ghz_6 | 6 | 0 | 0.0% | 0.000 | 0 | 20.0% → 20.0% | 33.3% → 33.3% | 2 / 2 |
| qpe_9 | 84 | 0 | 0.0% | 0.000 | 0 | 0.0% → 0.0% | 0.0% → 0.0% | 84 / 84 |
| steane_logical_5 | 6 | 0 | 0.0% | 0.000 | 0 | 0.0% → 0.0% | 0.0% → 0.0% | 6 / 6 |
| steane_physical_35 | 1 | 1 | 100.0% | 4.000 | 4 | n/a | n/a | 0 / 0 |
| trotter_rand_35 | 112 | 72 | 64.3% | 1.661 | 4 | 69.5% → 54.7% | 84.0% → 68.2% | 20 / 20 |
| ALL | 813 | 97 | 11.9% | 0.268 | 4 | 42.2% → 35.7% | 84.0% → 77.8% | 528 / 528 |

- **Gap definitions:** agg gap = (Σcost − Σh)/Σcost over solved roots; max gap = max over roots of (cost − h)/cost.
- **Multi-zone specs:** the `--arch-spec` runs on `examples/arch/full.json`, `two_zone_bus.json`, `two_zone_aligned_site_bus.json` and `two_zone_grid.json` gave success=False on ghz_4, with 0 roots logged. The errors are in `bench/phase2/multizone_*.csv`.

## Phase 2c: `rust_cascade_ids`, h0 vs bus-cut `max(h0, |R|)` (branch `bus-cut-bound`)

```
git checkout bus-cut-bound && uv run --locked maturin develop --release
cd python
../.venv/bin/python ../bench/phase2c/bench.py /tmp/phase2c/run1.json h0_first
../.venv/bin/python ../bench/phase2c/bench.py /tmp/phase2c/run2.json bc_first
../.venv/bin/python ../bench/phase2c/bench.py /tmp/phase2c/run3.json h0_first
cd .. && python3 bench/phase2c/analyze.py   # from the repo root; reads bench/phase2c/run{1,2,3}.json
```

- **Fields not identical across the 3 runs:** none.
- **Wall time:** the median of the 3 processes.
- **certs:** certificates over measured solves.

| case | cost (shots) | move events | nodes | cuts_by_h | root gap | max per-solve gap | certs | wall ms |
|---|---|---|---|---|---|---|---|---|
| adder_4 | 19 / 19 | 38 / 38 | 48 / 36 | 26 / 20 | 15.8% / 15.8% | 50.0% / 50.0% | 6/7 / 6/7 | 461 / 487 |
| adder_64 | 775 / 775 | 1550 / 1550 | 4810 / 4530 | 698 / 917 | 33.0% / 31.2% | 83.3% / 77.8% | 165/257 / 165/257 | 21459 / 20988 |
| bv_70 | 99 / 99 | 198 / 198 | 135 / 135 | 32 / 32 | 0.0% / 0.0% | 0.0% / 0.0% | 36/36 / 36/36 | 715 / 626 |
| ghz_4 | 6 / 6 | 12 / 12 | 9 / 8 | 3 / 2 | 16.7% / 16.7% | 33.3% / 33.3% | 1/2 / 1/2 | 331 / 303 |
| ghz_6 | 10 / 10 | 20 / 20 | 18 / 13 | 7 / 3 | 20.0% / 20.0% | 33.3% / 33.3% | 1/3 / 1/3 | 494 / 528 |
| qpe_9 | 110 / 110 | 220 / 220 | 152 / 152 | 42 / 42 | 0.0% / 0.0% | 0.0% / 0.0% | 42/42 / 42/42 | 2072 / 2042 |
| steane_logical_5 | 9 / 9 | 18 / 18 | 12 / 12 | 3 / 3 | 0.0% / 0.0% | 0.0% / 0.0% | 3/3 / 3/3 | 63 / 64 |
| steane_physical_35 | fail / fail | | | | | | | |
| trotter_rand_35 | 629 / 629 | 1258 / 1258 | 11165 / 10879 | 156 / 560 | 69.5% / 54.7% | 84.0% / 68.2% | 10/56 / 10/56 | 3839 / 3746 |
| total | 1657 / 1657 | 3314 / 3314 | 16349 / 15765 | 967 / 1579 | | | | 29432 / 28783 |

Wall samples in ms:

| case, strategy | run 1 | run 2 | run 3 |
|---|---|---|---|
| adder_64, h0 | 20637 | 21767 | 21459 |
| adder_64, bus-cut | 21641 | 19186 | 20988 |
| trotter_rand_35, h0 | 4058 | 3839 | 3820 |
| trotter_rand_35, bus-cut | 3746 | 3546 | 3867 |

`BusCutBound::new` timing came from one run of a temporary instrumented build (`Instant` around each construction, reverted afterwards). The raw lines are in `bench/phase2c/run_timing.err`.

| case | calls | total ms | mean ms | max ms |
|---|---|---|---|---|
| adder_4 | 14 | 7.1 | 0.51 | 0.59 |
| adder_64 | 514 | 222.8 | 0.43 | 1.83 |
| bv_70 | 72 | 22.4 | 0.31 | 0.42 |
| ghz_4 | 4 | 2.4 | 0.60 | 0.71 |
| ghz_6 | 6 | 3.7 | 0.62 | 0.73 |
| qpe_9 | 84 | 41.7 | 0.50 | 0.77 |
| steane_logical_5 | 6 | 3.5 | 0.59 | 0.70 |
| trotter_rand_35 | 112 | 158.2 | 1.41 | 3.92 |
| all | 812 | 461.9 | | |

`steane_physical_35` under `cascade-ids` at different expansion budgets (`../.venv/bin/python ../bench/phase2c/steane.py 300 3000 30000`):

| budget | bound | success | events | nodes | cost Σ | h_root Σ | s |
|---|---|---|---|---|---|---|---|
| 300 | h0 | False | | | | | 0.1 |
| 300 | bus-cut | False | | | | | 0.1 |
| 3000 | h0 | False | | | | | 0.2 |
| 3000 | bus-cut | False | | | | | 0.2 |
| 30000 | h0 | True | 128 | 90180 | 64 | 11 | 11.5 |
| 30000 | bus-cut | True | 128 | 90177 | 64 | 18 | 10.1 |

At the failing root (Phase 2b diag): n_atoms 28, h0 4, |R| 8, h 8, status `BudgetExceeded`.

## Phase 2d

**B: completion bound in the IDS leg**
- `cuts_infeasible > 0` rows: 0 of 8 bounded rows in `latest_physical.csv`, 0 of 6 in `latest_logical.csv`, and 0 in the `bench/phase2c/run1.json` rows.
- The experiment was not run (see the session report).

**C: `fix-budget-error` (`c925bce1`)**
- **Benchmarks against the committed baselines:**
  - **Logical:** `--compare benchmarks/harness/latest_logical.csv` gave `no differences found`, exit 0.
  - **Physical:** `--compare benchmarks/harness/latest_physical.csv` gave `no differences found`, exit 0 (full physical matrix; `notes` column compared strictly).
- **Rust:** `cargo test --workspace` all `ok`; `bloqade-lanes-search` lib: 531 passed.
- **Python:** `pytest python/tests --deselect python/tests/gemini/decoding/test_msd_postselection_numerical_regression.py` gave 2512 passed, 69 skipped, 1 deselected, 2 xfailed. The deselected test needs the optional `clifft` package, which is not in `--extra sim`.
- **New tests:** `test_a_placement_out_of_budget_warns_with_the_solver_status` and `test_a_failed_placement_is_still_raised_when_asked`. In `ghz` (4 qubits, cascade-ids), budget 300 leaves 0 `place.CZ` and gives 0 warnings; budget 1 leaves 3 `place.CZ` and gives 1 warning containing `BUDGET_EXCEEDED`.

**D2: `fix-spec-comment` (`e8ce2fe3`)**
- `spec.py` comment changed from "10 buses" to "19 buses".

## Branches (HEADs on `origin`)

| branch | HEAD | base |
|---|---|---|
| main | 4c1446a0 | |
| bus-cut-bound | 8cc37d2f | 4c1446a0 |
| bus-cut-strong | c4e2ed74 | 4c1446a0 |
| bus-cut-diag | 17dd39ae (the commit adding this file is on top) | c4e2ed74 |
| fix-budget-error | c925bce1 | 4c1446a0 |
| fix-spec-comment | e8ce2fe3 | 4c1446a0 |

## Phase 4a: property fuzzer (branch `fuzz`, HEAD `16194db7`, base `4c1446a`)

Environment: `fuzz/` project, `uv sync --locked`; hypothesis 6.152.5, stim 1.16.0, kirin-toolchain 0.22.16, bloqade-circuit 0.15.2.
Fuzzer tests: `cd fuzz && uv run --locked pytest` gave 52 passed.

```
cd fuzz && uv sync --locked
uv run --locked python -m lanes_fuzz.run --mode clifford    --examples 500 --jobs 4 --repro-dir repros/clifford    --out results/clifford.json
uv run --locked python -m lanes_fuzz.run --mode nonclifford --examples 100 --jobs 4 --repro-dir repros/nonclifford --out results/nonclifford.json
uv run --locked python -m lanes_fuzz.run --mode clifford --examples 100 --max-qubits 14 --max-ops 40 --jobs 4 --seed 1 --repro-dir repros/clifford-large --out results/clifford-large.json
```

### Runs (14 strategies each, 4 processes)

| run | size | strategies | examples | ok | expected refusal | real failures | wall s |
|---|---|---|---|---|---|---|---|
| Clifford | 2-6 qubits, 1-12 ops | 14 | 7000 | 6954 | 46 | 0 | 705.6 |
| non-Clifford | 2-6 qubits, 1-12 ops | 14 | 1400 | 1400 | 0 | 0 | 135.0 |
| Clifford stress | 2-14 qubits, 1-40 ops | 14 | 1400 | 1388 | 12 | 0 | 168.1 |

Per-strategy wall seconds (Clifford run): astar 147.0, dfs 146.0, bfs 147.6, ids 146.5, greedy 141.2, push-rotate 141.3, entropy 159.9, cascade-ids 141.7, cascade-dfs 159.6, cascade-entropy 165.3, pipeline_default 207.5, pipeline_route_all 253.1, loose_goal 241.3, receding_horizon 243.9.

### Expected refusal: `PlacementError` "would spuriously entangle ... bystanders"

| run | strategy | refusals in final pass | examples in final pass | passes | minimal kernel (qubits / ops) |
|---|---|---|---|---|---|
| Clifford | loose_goal | 23 | 500 | 2 | 4 / 3 |
| Clifford | receding_horizon | 23 | 500 | 2 | 4 / 3 |
| non-Clifford | loose_goal | 0 | 100 | 2 | 5 / 3 |
| non-Clifford | receding_horizon | 0 | 100 | 2 | 4 / 2 |
| Clifford stress | loose_goal | 6 | 100 | 2 | 4 / 2 |
| Clifford stress | receding_horizon | 6 | 100 | 2 | 4 / 2 |

All other strategies: 0 expected refusals and 0 failures in every run.
Categories checked for: compile exception, `place.CZ` left, Rust validator rejection (`check_lanes` or `validate_moves`), move-to-squin exception, equivalence crash, tableau or statevector mismatch. Count of each outside the table above: 0.
Rate: Clifford run 23/500 = 4.6% per refusing strategy; stress run 6/100 = 6.0%; non-Clifford final pass 0/100 (category found in pass 1 and shrunk).

### Planted-bug results

| planted bug | check expected to catch it | result |
|---|---|---|
| stray X on first qubit after lowering, kernel `h; cx; cx` with terminal measure, all 14 strategies | Stim tableau | 14 of 14 `equivalence: tableau differs`; unplanted control `ok` on 14 of 14 |
| same bug, kernel `rx(pi/8); cx`, `astar` | statevector | `equivalence: statevector differs` |
| same bug on `h; h; t` (qubit 0 left in `|+>`) | statevector | not detected (X\|+> = \|+>): documented blind spot |
| lane group mixing a site-bus and a word-bus lane in the move IR, `astar` | Rust validator | `validator: ...`, detail contains `check_lanes` |
| planted X, driver with `astar`, 30 examples | Hypothesis shrinking | 1 category, minimal kernel 2 qubits / 1 op (the config minimum) |
| planted X, saved repro run as a script | standalone repro | exit 1, `REPRODUCED` |

### Coverage limits of the generator

- Gates: H, S, X, Z, CZ, CX, broadcast CZ; non-Clifford mode adds T, RZ, RX with angles k*pi/8, k in -7..8.
- One register from `squin.qalloc`; straight-line code; no loops, branches, helper functions or multiple registers.
- Measurement: a single terminal `measure` of all qubits in Clifford mode; none in non-Clifford mode; no mid-circuit measurement, reset or classical control.
- Not generated: `u3`, `cy`, `swap`, `sqrt_*`, `ccz`, noise statements.
- Size: Clifford at most 14 qubits (stress) and 40 ops; non-Clifford at most 6 qubits and 12 ops.
- Equivalence: tableau ignores measurement records; statevector compares the output on |0...0> only.
- Arch: built-in Gemini physical spec only (1 zone, 0 zone buses); the multi-zone specs are rejected by the physical strategies (Phase 2b).
- Strategies run with the knobs in `fuzz/src/lanes_fuzz/strategies.py`; default `max_expansions` where the matrix sets none.
