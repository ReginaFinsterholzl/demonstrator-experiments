# Trace a circuit and estimate its resources

From the repository root:

```sh
uv run python run_selene-retrace circuits/bell.py --trace-qubits 2 --code surface --distance 5

uv run python run_selene-retrace circuits/qpde/h2_1qubit_qpe_1phase_raw_default.hugr --trace-qubits 3 --code surface --distance 5
```

`--help` lists all options. The importable function is
`workflows.run_selene_retrace.run_selene_retrace`; it returns the saved run folder.
Importing it starts no runs. Use the same keyword names as the defaults below
when overriding ReTrace options from Python.

The script checks the sibling `ReTrace` checkout **before importing ReTrace**.
If its branch is not `hybridpFT`, it offers abort or continue, defaulting to abort.
It never switches branches, stashes or discards work. Without interactive input,
it aborts unless `--allow-other-branch` was explicitly supplied. The branch,
commit and dirty state are saved in the run settings.

The tracing qubit limit counts live circuit qubits **before QEC encoding**.
It is independent of `--physical-qubits`, the estimator's hardware budget.
Hydrogen needs 3 tracing qubits; ethylene needs 13.

## Inputs and optimization

The shared loader accepts compiled `.hugr`, Guppy `.py`, trusted pytket/Qiskit
pickles, and pytket JSON. Python files and pickles execute code when loaded;
use trusted inputs. Guppy defaults to the argument-free entrypoint `main`.

This workflow defaults to **`--optimization none`**, including for source inputs.
The other choices are `minimal`, `classical`, `default` and `extended`:

```sh
uv run python run_selene-retrace circuits/bell.py --trace-qubits 2 --code surface --distance 5 --optimization extended --extended-pass SquashRzPhasedX
```

Repeat `--extended-pass` to select an ordered sequence; omitting it with
`extended` uses all three enabled passes. The same gate-basis effects and
global-phase restrictions as the [optimizer](README.md) apply. Compiler-required
lowering remains necessary even with `none`.

## QEC model and defaults

Choose a model explicitly with `--code`:

- `surface`, `color`, `surface-pft`: also supply `--distance`.
- `c422`: also supply `--level` (0 through 3).
- `csd`, `hybrid-helix-surface`: use the fixed specifications in ReTrace.

The defaults are:

| Option | Default | ReTrace name if different |
| --- | --- | --- |
| `--physical-qubits` | 1500 | `num_qubits` |
| `--synthesis-accuracy` | 0.01 | `synth_accuracy` |
| `--num-samples` | 1 | |
| `--seed` | 43 | |
| `--seed-increment` | true | |
| `--demand-factor` | 1 | |
| `--demand-ramping` | None: ReTrace chooses by code | |
| `--allow-jumping` | true | |
| `--perform-ec-on-resource-states` | false | |
| `--careful-alloc` | true | |
| `--debug` | false | |
| `--space-optimized` | true | |

Boolean options accept a `--no-` form, for example `--no-space-optimized` or
`--no-seed-increment`. All defaults can be overridden. Settings not exposed here
retain the checked ReTrace version's defaults, including its hardware timing
and error assumptions. Batch boundaries are always retained.

The separate `--trace-seed` defaults to 43. Tracing executes **one** application
path with Coinflip measurement answers; this does not simulate the quantum state.
ReTrace's `--num-samples` and `--seed-increment` apply to scheduler sampling of
that fixed path, not to new application paths.

Use `--measurements FILE.json` for a prescribed path. The file can contain a JSON
array such as `[true, false]`, or be a prior run's `measurements.json`. The replay
must supply exactly the measurement sequence requested by the program.

## Saved outputs

Each run creates `results/<circuit>/selene_retrace_<timestamp>/`; `--output PATH`
selects a different new folder. Existing folders are preserved.

- `circuit.hugr`: the exact input used for tracing after optional optimization.
- `trace.json`: versioned raw Selene event record.
- `measurements.json`: qubit identifiers, answers and boolean replay values.
- `shot_outputs.json`: tagged program outputs from the traced execution.
- `program.json`: the `selene-retrace` gate batches passed to ReTrace.
- `trace_summary.json`: operation counts and batch counts, including lifetime ops.
- `settings.json`: parameters, source hash, package versions and repository revisions.
- `summary.json`: modeled depth, runtime, peak physical qubits, logical error,
  postselection statistics and individual scheduler samples.
- `trace.log`, `retrace.log`: compilation/tracing and estimation messages.
- `build/`: native build and trace-stream artifacts, ignored by Git.

If a stage fails, `error.json` identifies it. A completed trace remains available
even if resource estimation fails. Debug files also stay in the run folder.

ReTrace currently ignores `Measure` entries and accounts for measurement at
`QFree`; the small adaptive validation checks both entries and the resulting
batch boundaries. This does not establish universal measurement-ordering support.
The summaries are resource-model predictions, not quantum measurement histograms
or explicit faulty-QEC simulation results. The integration checks use SurfaceCode
at distance 5; other model selections use the corresponding ReTrace implementations.

No Anduril, Eldarion, ShotPlot, JFrog access or sibling-environment changes are needed.
