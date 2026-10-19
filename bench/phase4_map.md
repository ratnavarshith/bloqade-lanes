# Phase 4 map (read-only survey)

Base: `main` at `4c1446a`. Paths are relative to the repo root; `site/` means
`.venv/lib/python3.12/site-packages/`. The environment was synced with
`uv sync --locked --dev --extra sim`.

## 1. Squin kernels and lanes strategies from Python

### Building kernels
- **Decorator:** `bloqade.squin.kernel` is a kirin dialect group (`site/bloqade/squin/groups.py:11-31`); it runs folding and type inference (`groups.py:17`).
  - **Re-exports:** `site/bloqade/squin/__init__.py:21`.
  - **Allocation:** `qalloc` (`__init__.py:16`); `qubit.new()` / `qubit.qalloc()` also work.
  - **Gates:** `__init__.py:22-57`.
  - **Broadcast forms:** `squin.broadcast.*` (`__init__.py:65-67`).
- **Example kernels:**
  - `python/benchmarks/kernels/small/ghz_4.py:8-25`.
  - `python/tests/test_squin_to_move_stages.py:32-43`.
  - `python/tests/test_integration.py:49-54`.
- **Measurement:** the physical pipeline expects exactly one terminal measurement covering all qubits (`python/bloqade/lanes/transform/pipeline.py:57-59`). The benchmark kernels do not measure.

### Compilation entry points
`python/bloqade/lanes/transform/__init__.py:1-24` exports these stages: `PhysicalPipeline`, `LogicalPipeline`, `NativeToPlace`, `PhysicalNativeToPlace`, `LogicalNativeToPlace`, `PlaceToMove`, `MoveToSquinPhysical`, `MoveToSquinLogical` and `MoveToStackMove`.

- **`PhysicalPipeline(arch_spec, layout_heuristic, placement_strategy, place_opt_type).emit(mt, no_raise=True)`** (`pipeline.py:54-70`, `:114-129`).
  - With `placement_strategy=None` it uses `make_physical_placement_strategy(arch_spec=...)` (`pipeline.py:101-102`).
- **`LogicalPipeline`** (`pipeline.py:133-210`). Its default placement is `PalindromePlacementStrategy(inner=LogicalPlacementStrategyNoHome(...))` (`pipeline.py:179-182`).
- **Stage by stage, as the benchmark harness does it** (`python/benchmarks/harness/runner.py:46-62`):
  1. `NativeToPlace` (or `LogicalNativeToPlace`) `.emit(mt)`.
  2. `SequentialPlacePass(dialects)(place_mt)`.
  3. `PlaceToMove(layout_heuristic, placement_strategy, insert_initialize).emit(place_mt)`.
  - **Test helper with the same shape:** `python/tests/_squin_to_move_helper.py:22`.

### Strategies
- **Rust search strategies:**
  - Built as `PhysicalPlacementStrategy(arch_spec=..., traversal=RustPlacementTraversal(strategy=...))` (`python/bloqade/lanes/heuristics/physical/movement.py:65-133`, `:167-171`).
  - **Strategy names** (`SearchStrategyName`, `movement.py:41-53`): `astar`, `dfs`, `bfs`, `greedy`, `ids`, `cascade` (an alias of `cascade-ids`, `_solver_dispatch.py:24-25`), `cascade-ids`, `cascade-dfs`, `cascade-entropy`, `entropy`, `push-rotate`. The name-to-enum map is `heuristics/physical/_solver_dispatch.py:18-33`.
  - **`RustPlacementTraversal` defaults:**
    - `strategy="entropy"` (`:79`)
    - `max_expansions=300` (`:82`)
    - `completion_bound=None` (`:87`)
    - `block_spectators=True` (`:99`)
    - `fallback_push_rotate=False` (`:113`)
    - `cascade_bound=True` (`:125`)
- **Return-home wrapper:** `PalindromePlacementStrategy(inner=...)` (`python/bloqade/lanes/analysis/placement/strategy.py:401`).
  - **Benchmark wiring:** the benchmark rows wrap every Rust search strategy in it (`python/benchmarks/harness/matrix.py:106-281`).
- **Other placement families:**
  - **NoHome:** `heuristics/physical/nohome.py:39`.
  - **Loose goal:** `NoReturnPlacementStrategy`, `heuristics/physical/no_return.py:25`; row `rust_loose_goal`, `matrix.py:282-293`.
  - **Receding horizon:** `RecedingHorizonNoReturnPlacementStrategy`, `heuristics/physical/receding_horizon.py:29`; row at `matrix.py:294-303`.
  - **Shared base:** `heuristics/physical/_no_return_base.py:45`.
- **Pipeline default:**
  - `make_physical_placement_strategy` (`movement.py:553-625`). Its defaults are `move_solutions_per_layer=3`, `search_budget=300`, `strategy="entropy"` and `return_moves=True`. It builds NoHome, wrapped in Palindrome when `return_moves` is set (`:625`).
  - **Benchmark row:** `pipeline_default` (`matrix.py:68-88`).

## 2. The Rust validator from Python
- **Program validation:** `Program.validate(arch=None, stack=False)`.
  - Rust implementation: `crates/bloqade-lanes-bytecode-python/src/program_python.rs:69-94` (`fn validate` at `:78`).
  - It runs `validate_structure`, then `validate(arch)`, then `simulate_stack` when `stack=True`.
  - Stub: `python/bloqade/lanes/bytecode/_native.pyi:2750`.
- **Architecture checks:**
  - `ArchSpec.validate()`: `arch_python.rs:1046`, stub `_native.pyi:766`.
  - `ArchSpec.check_lanes(lanes) -> list[LaneGroupError]`: `arch_python.rs:1263`, stub `_native.pyi:1016`. This is the zone/bus/type/direction consistency check, plus membership and geometry.
  - Also `check_zone` and `check_locations`: `arch_python.rs:1245`, `:1249`.
- **Move validation:** `AtomStateData.validate_moves(lanes, arch_spec) -> ValidatedMoves`.
  - Rust: `crates/bloqade-lanes-bytecode-python/src/atom_state_python.rs:245-256`. Stub: `_native.pyi:2074`.
  - It raises `MoveValidationError`, which carries `.errors`.
- **Registration:**
  - Module registration: `crates/bloqade-lanes-bytecode-python/src/lib.rs:32-96`.
  - Python re-export: `python/bloqade/lanes/bytecode/__init__.py:43`.
- **Example callers:**
  - `python/tests/bytecode/test_bytecode.py:576`
  - `python/tests/bytecode/test_decoder.py:148`
  - `python/tests/analysis/atom/test_atom_state_data.py:121,149,183`
- **IR-level checks are separate:** the kirin `ValidationSuite` passes in `python/bloqade/lanes/validation/*` do not call the Rust validator.
  - Kirin's suite: `site/kirin/validation/validationpass.py:11,51,77,179`.

## 3. Kirin version and forward dataflow analysis
- **Version:**
  - `uv.lock:2559-2560`: `kirin-toolchain` `0.22.16`. Installed: `kirin_toolchain-0.22.16.dist-info`.
  - `pyproject.toml:17` pins `kirin-toolchain~=0.22.14`.
- **Forward analysis** (`site/kirin/analysis/forward.py`):
  - `ForwardFrame.set_values`, which joins into existing entries: `:13-22`.
  - `ForwardExtra(interp.AbstractInterpreter[...], ABC)`: `:29`.
  - `run(method, *args)`, where args default to `lattice.top()`: `:38-41`.
  - `run_no_raise(...)`: `:43-49`. It catches `Exception` and returns `(initialize_frame(method.code), lattice.bottom())`; the exception is discarded.
  - Abstract `method_self(method)`: `:52`.
  - `Forward(ForwardExtra[ForwardFrame[...]])`: `:58`.
  - `initialize_frame(node, *, has_parent_access=False)`: `:66`.
- **Lattice** (`site/kirin/lattice/abc.py`):
  - `Lattice` at `:29`, with abstract `join`, `meet` and `is_subseteq` at `:38`, `:43`, `:48`.
  - `BoundedLattice` at `:76`, with `bottom()` and `top()` at `:85`, `:89`.
  - Also `site/kirin/lattice/empty.py` (`EmptyLattice`) and `site/kirin/lattice/mixin.py`.
- **Interpreter core:**
  - `site/kirin/interp/abc.py`: `eval` at `:111`; `frame_eval` at `:275` (registry lookup, else `eval_fallback`); `eval_fallback` at `:308` (raises `NotImplementedError`). There is no `eval_stmt`.
  - `site/kirin/interp/abstract.py`: `AbstractInterpreter` at `:66`; `recursion_limit_reached` returns bottom at `:106`.
- **Method tables:**
  - `Dialect.register(node=None, key=None)`: `site/kirin/ir/dialect.py:73`.
  - `MethodTable`: `site/kirin/interp/table.py:204`.
  - `impl(head, *params)` and its overloads: `table.py:106`, `:133`, `:165`, `:192`.
- **Repo example to copy:** `python/bloqade/lanes/analysis/atom/`.
  - `AtomInterpreter(Forward[MoveExecution])`: `analysis.py:54`, with `lattice = MoveExecution` at `:55` and `keys = ("atom",)` at `:64`.
  - `method_self` returns bottom (`:75-76`); `eval_fallback` returns bottoms (`:78-79`).
  - The `MoveExecution` lattice: `atom/lattice.py:20-27`.
  - Method tables registered via `@annotate.dialect.register(key="atom")` (`impl.py:28`) and `@move.dialect.register(key="atom")` (`impl.py:49`), with `@interp.impl(...)` methods.
- **Second example:** `PlacementAnalysis(Forward[AtomState])`, `python/bloqade/lanes/analysis/placement/analysis.py:21-22`.
- **Stale override:** `python/bloqade/lanes/analysis/layout/analysis.py:88` defines `eval_stmt_fallback`, which kirin 0.22.16 never calls (kirin uses `eval_fallback`).

## 4. Stim tableau or statevector, before and after lowering
**Locked packages:**

| package | version | `uv.lock` line | installed |
|---|---|---|---|
| stim | 1.16.0 | 5883 | yes |
| pyqrack-cpu | 1.89.0 | 4709 | yes |
| bloqade-circuit | 0.15.2 | 284 | yes |
| bloqade-tsim | 0.1.5 | 512 | yes |
| cirq-core | 1.7.0 (py>=3.11) | 858 | yes |

The `sim` extra is defined at `pyproject.toml:33-36`.

**Before lowering:** a squin kernel without measurements.
- **Statevector:** `bloqade.pyqrack.device.StackMemorySimulator().state_vector(kernel)`.
  - Source: `site/bloqade/pyqrack/device.py:293` (class), `:203` (`state_vector`).
- **Stim:** `bloqade.stim.upstream.from_squin.squin_to_stim(mt, insert_ticks=False)` (`site/bloqade/stim/upstream/from_squin.py:7`) gives the Stim dialect IR.
  - Emit the circuit text with `EmitStimMain(dialects=mt.dialects, io=buf).initialize().run(node=mt)` (`site/bloqade/stim/emit/stim_str.py:24`). Then `stim.Circuit(text)` and `stim.Tableau.from_circuit(...)`.
  - Repo usage of exactly this sequence: `python/bloqade/gemini/compile/stim.py:39-55` (`compile_to_stim_program`), after `RemoveReturn` (`python/bloqade/lanes/rewrite/squin2stim.py:6`).

**After lowering:** move IR goes back to squin, then down the same two paths.
- **Back to squin:** `MoveToSquinPhysical(arch_spec=..., noise_model=..., aggressive_unroll=...).emit(move_mt)` (`python/bloqade/lanes/transform/move_to_squin.py:154`); `MoveToSquinLogical` at `:119`; base class at `:28`.
  - Harness usage: `python/benchmarks/harness/runner.py:276-281`, `:303-307`.
- **Statevector comparison:** `bloqade.lanes.utils.check_circuit(a, b, atol, rtol)` (`python/bloqade/lanes/utils.py:137-173`).
  - It compares phase-normalized `StackMemorySimulator` statevectors, so both methods must be measurement-free.
- **Existing round-trip tests:**
  - **Statevector:** `python/tests/test_integration.py:22-45` (logical pipeline, then `MoveToSquinPhysical`, then `check_circuit`) and `:49-135`. All are marked `@pytest.mark.slow`.
  - **Stim tableau:** `python/tests/gemini/test_logical_clifford_lowering.py:110-135` (`GeminiLogicalSimulator().task(kernel).noiseless_tsim_circuit.stim_circuit` against `stim.TableauSimulator` stabilizers).

## 5. Fuzz, property and Hypothesis tests
- **Hypothesis:** absent. It is not in `pyproject.toml`, `uv.lock` (0 matches for `name = "hypothesis"`) or `.venv`.
- **Rust:** no `proptest` or `quickcheck` in any `Cargo.toml` or `Cargo.lock`.
- **Hand-rolled seeded fuzz in Python:** `python/tests/rewrite/test_stackify.py:1273-1350`.
  - `_random_block(rng)` is at `:1276`; it is parametrized with `@pytest.mark.parametrize("seed", range(4))` at `:1343`, at 200 random blocks per seed.
- **Rust seeded random instances (not fuzzing):**
  - `crates/bloqade-lanes-search/src/bounds.rs`: `h0_never_exceeds_brute_force_optimum_on_randomized_instances`, seed `0xB01E_5EED`.
  - The same file on `bus-cut-bound`: the `BusCutBound` sandwich and consistency tests.
  - The `rand` crate is a regular dependency (`crates/bloqade-lanes-search/Cargo.toml:12`).
