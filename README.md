# Demonstrator experiments

One place for circuits, experiment workflows, configurations, outputs, and figures,
using a single Python 3.13 uv environment and the neighbouring source repositories.

## Setup status

The six folders and single Python 3.13 `.venv` are set up. Import checks passed for
Guppy, Selene, the local Helix compiler, ReTrace, selene-retrace (including its
native compiler), and the QEC circuit helpers. The Stim, QuEST, and
ReTrace-runtime libraries are present. No circuits were compiled or executed as
part of these checks.

ShotPlot and its private Anduril/Eldarion dependencies are deferred until JFrog
access is available. Their candidate versions are saved in
`configs/shotplot-requirements.txt`. They do not participate in the current
installation or dependency lockfile, so normal uv commands need no JFrog login.

## Layout

| Folder | Purpose |
| --- | --- |
| `circuits/` | Circuit source and saved circuit representations |
| `workflows/` | Future scripts connecting compilation, tracing, simulation, and estimation |
| `configs/` | Experiment parameters, seeds, code choices, and hardware assumptions |
| `notebooks/` | Future interactive experiments and analysis |
| `results/` | Outputs grouped by experiment and run |
| `figures/` | Selected plots for inspection, reports, or presentations |

The folders contain placeholders and the deferred ShotPlot package manifest. No
experiment entrypoint, example circuit, or notebook is included in this setup.

## One environment

Run commands from this repository. Recreate or synchronise the environment with:

```sh
uv sync --locked
```

Use `uv run python` for Python and `uv run jupyter lab` for notebooks. In an editor,
select this repository's `.venv/bin/python` interpreter. There is no need to
activate any neighbouring repository's environment.

The installed dependencies cover Guppy, local Selene simulation (Stim and QuEST),
Helix compilation, and ReTrace's imported functionality. The Qiskit 2.5.2 and
pygridsynth 2.0.0 pins follow the existing Helix setup. The Guppy 1.x and Selene
0.3.x versions start from the modern `c2h4qec` lockfile. This setup does not
install the neighbouring ReTrace distribution, whose declared dependency pins
are older; it imports that checkout's source using the versions declared here.

## Neighbouring repositories

Keep these checkouts alongside `demonstrator-experiments`:

| Checkout | Imports made available |
| --- | --- |
| `helix-logical-compiler` | `offline_helix_compiler` |
| `ReTrace` | `resource_estimator` and its `circuits` package |
| `selene-retrace` | `selene_retrace` and its compiler/runtime/interface plugins |
| `qecc-20_2_6` | `qecc2026`, `qecc2026Guppy`, and related circuit helpers |

The `dev-mode-dirs` setting in `pyproject.toml` makes these source folders
importable whenever uv installs this project in editable mode, its default.
No experiment script has to modify Python's search path. The checkouts' own
virtual environments are not used or changed.

Python source changes in those checkouts are visible to new Python processes;
restart a notebook kernel after changing imported code. Existing compiled Helix
and selene-retrace components are reused. Changes to their Rust/C components
still require rebuilding them in their owning repository. A fresh machine needs
those components built before the associated imports can succeed. Keep their
branches under your own control; this setup does not switch them.

The dependency lockfile fixes installed package versions, not neighbouring source
revisions. When experiments are added, record each run's configuration, seeds,
repository commits, and any uncommitted source changes beside its outputs.

## ShotPlot later

Basic local Selene simulation is available now. Hardware-timed ShotPlots need the
additional `shotplot`, `selene-anduril`, `selene-eldarion`, and `eldarion` packages
from Quantinuum's JFrog index. Installation returned HTTP 401, and account setup
is postponed at the user's request.

The candidate versions and index URL are recorded in
`configs/shotplot-requirements.txt`. When an account becomes available, configure
uv authentication locally, add those packages and their explicit index sources
to `pyproject.toml`, and regenerate `uv.lock` with `uv sync`. Check their imports
before using the plotting workflow. Credentials must stay outside this repository.
The current setup does not contact that private index.

For circuit behaviour, use Stim for supported Clifford circuits or QuEST for
general rotations within the available memory. A Coinflip timeline does not
simulate quantum outcome probabilities. ShotPlot uses its own Eldarion/Anduril
path; selene-retrace separately records gates for resource estimation.

Nexus submission (`qnexus`), the older `pecos_selene` noise model, and QEC decoder
packages are not required by this initial setup. Reusing older QEC examples may
need compatibility checks with Guppy 1.x; no circuit migration is included here.

## Outputs and Git

The environment, caches, logs, `results/raw/`, `results/cache/`, and common bulk
binary result formats are ignored. Small summaries, configurations, circuit
sources, and selected figures can be committed. Empty `.gitkeep` files preserve
the initial folder structure.
