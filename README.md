# Demonstrator experiments

Circuit definitions, local Selene simulation, and optional scheduled-operation
plots in one Python 3.13 uv environment.

## Quick start

Run these commands from this repository:

```sh
uv sync --locked

# Clifford example: Bell-state outcomes should be 00 or 11.
uv run python -m workflows.simulate circuits/bell.py --qubits 2 --shots 1000 --seed 17

# General Rz rotation: ideal probability of bit=1 is 1/4; use QuEST.
uv run python -m workflows.simulate circuits/rotation.py --qubits 1 --simulator quest --shots 1000

# Add a simple depolarizing noise model.
uv run python -m workflows.simulate circuits/rotation.py --qubits 1 --simulator quest --p-1q 0.001 --p-meas 0.01
```

The normal `simple` runtime uses public packages and needs no account. Stim handles
supported Clifford circuits; QuEST handles general rotations within available
memory. Noise is off by default. The four optional probabilities are `--p-1q`,
`--p-2q`, `--p-meas`, and `--p-init`, each between 0 and 1. This is a configurable
local model, not a calibrated Helios hardware model.

Use `--help` on either workflow for its arguments. For notebooks, run
`uv run jupyter lab` and select this environment's Python interpreter.

## Circuit optimization

```sh
uv run python -m workflows.optimize circuits/qpde/h2_1qubit_qpe_1phase_raw.pkl --optimization default
```

The optimizer accepts trusted pickle files, Guppy, compiled HUGR and pytket JSON.
It saves HUGR, pytket JSON and a runnable Guppy wrapper beside the original where
faithful export is supported, plus an optimization report. Existing files are
preserved. Choose `none`, `minimal`, `classical`, `default` or `extended`.
Both simulation and ShotPlot accept `--optimization none` to bypass optional
optimization. See [the short optimization guide](workflows/README.md) for modes,
extended passes, export limitations and Python usage.

## Circuit files and outputs

To trace one execution path and pass its gate batches to the sibling ReTrace
resource estimator, use:

```sh
uv run python run_selene-retrace circuits/bell.py --trace-qubits 2 --code surface --distance 5
```

This includes the circuit optimization choices, an abort-or-continue check for
ReTrace's `hybridpFT` branch, configurable estimator settings and saved execution
records. See [the tracing and resource-estimation guide](workflows/SELENE_RETRACE.md).
Tracing uses Coinflip or replay, separately from quantum-state simulation.

A `.py` circuit file defines an argument-free Guppy entrypoint called `main`.
Use `--entrypoint NAME` to select another definition. Keep circuit files safe to
import: define circuits and helpers there, and start execution through the
workflow. The provided examples do not run simulations when imported.

Both workflows also accept an existing `.hugr` file, so simulation and plotting
can reuse the same compiled circuit, plus trusted pytket/Qiskit pickles and pytket
JSON. Saved HUGR and generated Guppy wrappers are preserved unless optimization
is explicitly requested; ordinary source circuits use `default`. Python files are loaded by file path; this
avoids the neighbouring ReTrace library's separate package also named `circuits`.

Each simulation creates a new directory under `results/<circuit>/` containing:

- `circuit.hugr`: the compiled circuit, including the optimizations Guppy applied.
- `summary.json`: output counts, settings, package versions, source hash, timing,
  and attempted/accepted/rejected shot counts.
- `shots.json`: all tagged outputs, including rejected shots and repeated tags.
- `build/`: intermediate Selene build files, ignored by Git.

Summary counts include accepted shots only; rejection counts and exit tags are
reported separately. Output values are lists to preserve repeated tags.
`wall_time_seconds` measures compilation/build and local computer execution time;
it is not a modeled hardware shot duration.

The default output folder is unique. `--output PATH` selects a new directory;
existing directories are preserved. The Python helper `workflows.simulate.simulate`
returns the output directory and starts a run only when called explicitly.

## Anduril and ShotPlot when package access is available

These entrypoints are implemented, but real Anduril/ShotPlot execution has not yet
been validated: the private packages are not installed. Their absence does not
affect ordinary simulation, `--help`, or normal uv synchronization.

The candidate packages are listed in `configs/shotplot-requirements.txt`. They
come from Quantinuum's JFrog index. When account access becomes available, add the
packages and their explicit index sources to `pyproject.toml`, authenticate with
uv locally, regenerate `uv.lock`, and check the installed APIs. Credentials stay
outside this repository. No private-index access is required by the current lock.

The following commands become available after that setup:

```sh
# Compile using Eldarion and run with the Anduril runtime.
uv run python -m workflows.simulate circuits/bell.py --qubits 2 --runtime anduril

# Plot a separately executed shot of the saved or source circuit.
uv run python -m workflows.plot_shot circuits/bell.py --qubits 2
uv run python -m workflows.plot_shot circuits/rotation.py --qubits 1 --simulator quest

# A deliberately forced all-zero measurement path, without quantum simulation.
uv run python -m workflows.plot_shot circuits/bell.py --qubits 2 --simulator coinflip --coinflip-bias 0
```

ShotPlot outputs PNG and PDF figures, the compiled HUGR, and settings under
`figures/<circuit>/`. Add `--show` to display figures interactively. Plots are
labelled with their simulator; Coinflip is explicitly labelled as performing no
quantum-state simulation. A plot is a separate execution, not an average runtime
or a replay of a prior simulation's measurement outcomes.

Plotting defaults to one shot, no noise, and no explicit seed. A requested
`--seed` or noise model is passed only if the installed ShotPlot function exposes
the corresponding argument; otherwise the workflow reports that it is unsupported.
The wrapper follows the calls in the existing `c2h4qec` examples. Private package
compatibility still needs a real test when access is available.

## Layout

| Folder | Purpose |
| --- | --- |
| `circuits/` | Import-safe circuit definitions and saved circuit representations |
| `workflows/` | Circuit optimization, simulation, optional ShotPlot and shared utilities |
| `configs/` | Experiment settings and deferred private-package requirements |
| `notebooks/` | Interactive experiments and analysis |
| `results/` | Simulation output grouped by circuit and run |
| `figures/` | Saved operation timelines and selected report figures |
| `tests/` | Small numerical workflow checks using temporary output folders |

The workflow code is self-contained. It uses `c2h4qec` only as an implementation
reference, imports nothing from it or triangulene, and includes no QEC components.

## Existing neighbouring source imports

The environment still makes the previously configured neighbouring checkouts
available: `helix-logical-compiler`, `ReTrace`, `selene-retrace`, and `qecc-20_2_6`.
The new simulation/plotting workflows do not depend on those imports. The
`dev-mode-dirs` setting in `pyproject.toml` registers their source folders when uv
installs this project in editable mode. Their environments are not used or changed.

Python source edits are visible to new processes; restart notebook kernels after
editing imported code. Their existing native libraries are reused, so Rust/C
changes still require rebuilding those components in their owning repository.
On a fresh machine those libraries must be built before their associated imports
will work. This setup does not switch branches or rebuild neighbouring projects.

The Qiskit 2.5.2 and pygridsynth 2.0.0 pins follow the existing Helix environment.
ReTrace is imported as source rather than installed with its older dependency
pins. Nexus submission, PECOS hardware-noise models and QEC decoders remain
outside the current workflows.

## Validation

```sh
uv run python -m unittest discover -s tests -v
```

The checks include exact matrix comparisons including global phase, circuit
format round trips, optimization bypass and protection of existing files. They
also use small unencoded circuits: Bell correlations with Stim, reuse of a
compiled HUGR, the analytic Rz probability with QuEST, measurement noise,
postselection accounting, unsupported Stim rotations, and unavailable private
packages. Numerical runs and build files use temporary directories. Private-mode
failure handling is checked without pretending to validate the unavailable
Anduril runtime or ShotPlot renderer.

## Outputs and Git

The environment, caches, logs, build directories, `results/raw/`, `results/cache/`,
and common bulk binary result formats are ignored. Small summaries, circuit
sources, configurations and selected figures can be committed. The dependency
lockfile fixes package versions, not neighbouring repository revisions; record
those revisions if future circuits import their functionality.
