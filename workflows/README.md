# Circuit optimization

Run from the repository root, using the existing uv environment:

```sh
uv run python -m workflows.optimize circuits/qpde/h2_1qubit_qpe_1phase_raw.pkl --optimization default
uv run python -m workflows.optimize circuits/qpde/h2_1qubit_qpe_1phase_raw.pkl --optimization extended --extended-pass CliffordSimp
```

The Python function is `workflows.optimize.optimize_circuit(path, optimization="default")`.
It returns a dictionary of saved file paths. It also accepts a pytket circuit object;
use `output_dir=` to select its destination (otherwise `circuits/`). Nothing runs on import.

Inputs: trusted `.pkl`/`.pickle` containing pytket or Qiskit circuits (or a pytket
dictionary), pytket `.json`/`.pytket` JSON, Guppy `.py` with an argument-free `main`
(select another with `--entrypoint`), and compiled `.hugr`. Pickle loading and Python
imports execute code, so use files you trust. Bind symbolic circuit parameters first.

| Mode | Optional optimization |
| --- | --- |
| `none` | Bypass all optional passes. Necessary compilation still happens. |
| `minimal` | Guppy's minimal compilation; currently equivalent to `none`. |
| `classical` | Guppy classical normalization; quantum gate optimization is disabled. |
| `default` | Classical normalization and redundant quantum gate removal. |
| `extended` | Default plus `SquashRzPhasedX`, `CliffordSimp`, then `FullPeepholeOptimise`. |

With `extended`, repeat `--extended-pass NAME` to choose passes and their order;
omitting it selects all three. Implicit wire swaps are disabled. The installed
`PauliGraphResynthesis` is deliberately excluded: a one-qubit Rz circuit with a
nonzero global phase lost that phase in an exact matrix check. `PauliSimp` and
`GreedyPauliSimp` are also excluded. The enabled passes are checked using exact
unitaries including global phase, not equality only up to a phase.

For pytket/Qiskit inputs, quantum passes run directly on a copy of the pytket
circuit; its Guppy wrapper receives only the selected structural/classical work.
This avoids extra classical bits introduced by a HUGR-to-pytket round trip.
For Guppy/HUGR inputs, the corresponding passes run on HUGR through TKET.

Outputs go beside the input, for example in `circuits/qpde/`, with a suffix naming
the mode and any extended passes. Existing files are never overwritten. Use
`--output-dir EXISTING_DIRECTORY` for another location.

- `.hugr`: compiled circuit for Selene/ShotPlot.
- `.json`: optimized pytket circuit, retaining its registers and global phase.
- `.py`: runnable Guppy wrapper loading the adjacent JSON; this is not expanded
  gate-by-gate Guppy source. Keep the pair together. It does not reapply optional
  optimization when compiled.
- `.optimization.json`: settings, source hash, package versions and gate counts
  where available. Gate counts describe the pytket circuit before hardware lowering.

Arbitrary Guppy programs cannot always be represented as one pytket circuit.
If faithful JSON/wrapper export is unavailable, the optimizer saves HUGR and a
report explaining the limitation. It does not approximate the program to force export.

Simulation and ShotPlot accept the same inputs and optimization arguments:

```sh
uv run python -m workflows.simulate circuits/qpde/h2_1qubit_qpe_1phase_raw.pkl --qubits 3 --simulator quest --optimization none
uv run python -m workflows.plot_shot circuits/qpde/h2_1qubit_qpe_1phase_raw_default.hugr --qubits 3 --simulator quest --optimization none
```

The workflow default remains `default` for source/JSON/pickle circuits. Saved HUGR
and generated Guppy wrappers are preserved unless another mode is explicitly chosen.
To preserve a saved JSON too, select `--optimization none`. Backend-required gate
conversion and scheduling still occur; optimization may change noisy outcomes and
shot durations. General rotations require QuEST rather than Stim. ShotPlot still
requires the deferred private packages described in the repository README.
