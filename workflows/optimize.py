"""Optimize a saved circuit and export HUGR, pytket JSON and a Guppy wrapper."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence

from workflows._common import ROOT, WorkflowError, package_versions

LEVELS = ("none", "minimal", "classical", "default", "extended")
EXTENDED_PASSES = ("SquashRzPhasedX", "CliffordSimp", "FullPeepholeOptimise")


@dataclass
class PreparedCircuit:
    hugr: bytes
    source: dict
    pytket: Any = None
    export_note: str | None = None


def add_optimization_arguments(parser: argparse.ArgumentParser, *, default: str | None = None) -> None:
    help_text = ("Default for source circuits; preserve saved HUGR/wrappers unless explicitly selected"
                 if default is None else "Optional circuit optimization after loading")
    parser.add_argument("--optimization", choices=LEVELS, default=default, help=help_text)
    parser.add_argument("--extended-pass", dest="extended_passes", action="append",
                        choices=EXTENDED_PASSES,
                        help="With extended: choose a pass; repeat to set order. Default: all three in listed order")


def _settings(optimization: str | None, extended_passes: Sequence[str] | None,
              *, saved: bool = False) -> tuple[str, tuple[str, ...]]:
    level = optimization if optimization is not None else ("none" if saved else "default")
    if level not in LEVELS:
        raise WorkflowError(f"Optimization must be one of {', '.join(LEVELS)}.")
    selected = tuple(extended_passes) if extended_passes is not None else EXTENDED_PASSES
    if extended_passes is not None and level != "extended":
        raise WorkflowError("Choose optimization='extended' when specifying extended passes.")
    if level == "extended" and (not selected or any(p not in EXTENDED_PASSES for p in selected)):
        raise WorkflowError(
            f"Extended passes must be chosen from {', '.join(EXTENDED_PASSES)}. "
            "PauliGraphResynthesis is excluded: the installed version loses global phase."
        )
    return level, selected if level == "extended" else ()


def _extended_pass(name: str):
    from pytket.passes import CliffordSimp, FullPeepholeOptimise, SquashRzPhasedX

    factories = {
        "SquashRzPhasedX": SquashRzPhasedX,
        "CliffordSimp": lambda: CliffordSimp(allow_swaps=False),
        "FullPeepholeOptimise": lambda: FullPeepholeOptimise(allow_swaps=False),
    }
    return factories[name]()


def _load_module(path: Path):
    name = "_demonstrator_circuit_" + hashlib.sha256(
        str(path).encode() + path.read_bytes()
    ).hexdigest()[:20]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise WorkflowError(f"Cannot load circuit: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _as_pytket(value):
    from pytket import Circuit

    if isinstance(value, Circuit):
        return value.copy()
    if isinstance(value, dict):
        return Circuit.from_dict(value)
    if type(value).__module__.startswith("qiskit"):
        from qiskit import QuantumCircuit
        from pytket.extensions.qiskit import qiskit_to_tk

        if isinstance(value, QuantumCircuit):
            return qiskit_to_tk(value)
    raise WorkflowError("Expected a pytket circuit, a pytket circuit dictionary or a Qiskit QuantumCircuit.")


def _compile_guppy(program, level: str, selected: Sequence[str]) -> bytes:
    from guppylang import OptimizationLevel
    from tket.passes import PytketHugrPass

    levels = {"none": OptimizationLevel.Minimal, "minimal": OptimizationLevel.Minimal,
              "classical": OptimizationLevel.Classical, "default": OptimizationLevel.Default,
              "extended": OptimizationLevel.Default}
    if not callable(getattr(program, "with_opt_level", None)):
        raise WorkflowError("The selected entrypoint must be a Guppy function.")
    configured = program.with_opt_level(levels[level])
    for name in selected:
        configured = configured.with_optimization(PytketHugrPass(_extended_pass(name)))
    return configured.compile().to_bytes()


def _wrapper(circuit, json_name: str) -> str:
    """Keep registers in pytket's sorted order and explicitly discard borrowed qubits."""
    lines = [
        '"""Guppy entrypoint for the optimized circuit in the adjacent pytket JSON."""',
        "from pathlib import Path", "import json", "from pytket import Circuit",
        "from guppylang import guppy", "from guppylang.std.builtins import output",
        "from guppylang.std.quantum import qubit, discard", "",
        f"__demonstrator_pytket_json__ = Path(__file__).with_name({json_name!r})",
        "_circuit = Circuit.from_dict(json.loads(__demonstrator_pytket_json__.read_text()))",
        'loaded = guppy.load_pytket("loaded", _circuit, use_arrays=False)', "",
        "@guppy", "def main() -> None:",
    ]
    qubits = [f"q{i}" for i in range(circuit.n_qubits)]
    bits = [f"b{i}" for i in range(circuit.n_bits)]
    lines.extend(f"    {q} = qubit()" for q in qubits)
    assignment = ", ".join(bits) + " = " if bits else ""
    lines.append(f"    {assignment}loaded({', '.join(qubits)})")
    lines.extend(f"    output({str(bit)!r}, {name})" for bit, name in zip(circuit.bits, bits))
    lines.extend(f"    discard({q})" for q in qubits)
    lines.extend(["", "# Recompiling this saved wrapper does not repeat optional optimization.",
                  "main = main.with_minimal_opt()", ""])
    return "\n".join(lines)


def _compile_pytket(circuit, level: str) -> bytes:
    if circuit.free_symbols():
        raise WorkflowError("Bind symbolic circuit parameters before exporting executable Guppy/HUGR.")
    with tempfile.TemporaryDirectory(prefix="demonstrator-guppy-") as temporary:
        path = Path(temporary) / "circuit.py"
        path.with_suffix(".json").write_text(json.dumps(circuit.to_dict()))
        path.write_text(_wrapper(circuit, "circuit.json"))
        # Quantum passes have already run on the exported pytket circuit. Only
        # classical normalization is applied to its executable Guppy wrapper.
        wrapper_level = "minimal" if level in {"none", "minimal"} else "classical"
        return _compile_guppy(_load_module(path).main, wrapper_level, ())


def _optimize_pytket(circuit, level: str, selected: Sequence[str]):
    from pytket.passes import RemoveRedundancies

    result = circuit.copy()
    if level in {"default", "extended"}:
        RemoveRedundancies().apply(result)
    for name in selected:
        _extended_pass(name).apply(result)
    return result


def _export_pytket(hugr: bytes):
    from tket._state import CompilationState

    try:
        return CompilationState.from_bytes(hugr).to_tket1(), None
    except Exception:
        return None, (
            "This Guppy/HUGR program cannot be exported faithfully as one pytket circuit "
            "(for example, it contains Guppy outputs, allocation or control flow). "
            "Only HUGR and the optimization report were saved."
        )


def prepare_circuit(circuit, entrypoint: str = "main", optimization: str | None = None,
                    extended_passes: Sequence[str] | None = None,
                    *, export_pytket: bool = False) -> PreparedCircuit:
    """Load and optimize without writing results or running any simulation."""
    try:
        return _prepare_circuit(circuit, entrypoint, optimization, extended_passes, export_pytket)
    except WorkflowError:
        raise
    except Exception as error:
        raise WorkflowError(f"Could not load or optimize the circuit: {error}") from error


def _prepare_circuit(circuit, entrypoint, optimization, extended_passes, export_pytket):
    source: dict = {}
    program = None
    hugr = None
    native = None
    saved = False
    if isinstance(circuit, (str, Path)):
        path = Path(circuit).expanduser().resolve()
        if not path.is_file():
            raise WorkflowError(f"Circuit file does not exist: {path}")
        raw = path.read_bytes()
        source = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
        suffix = path.suffix.lower()
        if suffix in {".pkl", ".pickle"}:
            import pickle

            native = _as_pytket(pickle.loads(raw))
            source["format"] = "pickle"
        elif suffix in {".json", ".pytket"}:
            native = _as_pytket(json.loads(raw))
            source["format"] = "pytket-json"
        elif suffix == ".py":
            module = _load_module(path)
            saved_json = getattr(module, "__demonstrator_pytket_json__", None)
            if saved_json is not None and entrypoint == "main":
                native = _as_pytket(json.loads(Path(saved_json).read_text()))
                saved = True
                source["format"] = "guppy-wrapper"
                source["pytket_sha256"] = hashlib.sha256(Path(saved_json).read_bytes()).hexdigest()
            else:
                program = getattr(module, entrypoint, None)
                source.update(format="guppy", entrypoint=entrypoint)
        elif suffix == ".hugr":
            from hugr.package import Package
            from tket_exts import tket_registry

            Package.from_bytes(raw, tket_registry())
            hugr, saved = raw, True
            source["format"] = "hugr"
        else:
            raise WorkflowError("Choose .pkl/.pickle, Guppy .py, .hugr, or pytket .json/.pytket JSON.")
    else:
        native = _as_pytket(circuit)
        source["format"] = "pytket-object"

    level, selected = _settings(optimization, extended_passes, saved=saved)
    source.update(optimisation=level, extended_passes=list(selected))
    if native is not None:
        before = native.n_gates
        optimized = _optimize_pytket(native, level, selected)
        source.update(pytket_gates_before=before, pytket_gates_after=optimized.n_gates,
                      n_qubits=optimized.n_qubits, n_bits=optimized.n_bits)
        return PreparedCircuit(_compile_pytket(optimized, level), source, optimized)
    if hugr is None:
        hugr = _compile_guppy(program, level, selected)
    elif level not in {"none", "minimal"}:
        from guppylang import OptimizationLevel
        from tket._state import CompilationState
        from tket.passes import PytketHugrPass

        package = CompilationState.from_bytes(hugr).to_python()
        chosen = OptimizationLevel.Classical if level == "classical" else OptimizationLevel.Default
        passes = chosen.passes() + [PytketHugrPass(_extended_pass(name)) for name in selected]
        for index, module in enumerate(package.modules):
            for pass_ in passes:
                module = pass_.run(module).hugr
            package.modules[index] = module
        hugr = package.to_bytes()
    native, note = _export_pytket(hugr) if export_pytket else (None, None)
    return PreparedCircuit(hugr, source, native, note)


def optimize_circuit(circuit, *, optimization: str | None = None,
                     extended_passes: Sequence[str] | None = None, entrypoint: str = "main",
                     output_dir: str | Path | None = None) -> dict[str, Path]:
    """Save new circuit files beside the input; return their paths. Never overwrites."""
    prepared = prepare_circuit(circuit, entrypoint, optimization, extended_passes, export_pytket=True)
    if isinstance(circuit, (str, Path)):
        original = Path(circuit).expanduser().resolve()
        directory = Path(output_dir).expanduser().resolve() if output_dir else original.parent
        stem = original.stem
    else:
        directory = Path(output_dir).expanduser().resolve() if output_dir else ROOT / "circuits"
        stem = "circuit"
    if not directory.is_dir():
        raise WorkflowError(f"Output directory does not exist: {directory}")
    label = prepared.source["optimisation"]
    if label == "extended":
        label += "_" + "_".join(prepared.source["extended_passes"])
    stem += "_" + label
    files = {"hugr": directory / f"{stem}.hugr", "report": directory / f"{stem}.optimization.json"}
    content = {"hugr": prepared.hugr}
    if prepared.pytket is not None:
        files.update(pytket=directory / f"{stem}.json", guppy=directory / f"{stem}.py")
        content.update(pytket=(json.dumps(prepared.pytket.to_dict(), indent=2) + "\n").encode(),
                       guppy=_wrapper(prepared.pytket, files["pytket"].name).encode())
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "source": prepared.source,
              "packages": package_versions(), "files": {key: path.name for key, path in files.items()},
              "export_note": prepared.export_note}
    content["report"] = (json.dumps(report, indent=2) + "\n").encode()
    existing = next((path for path in files.values() if path.exists()), None)
    if existing is not None:
        raise WorkflowError(f"Preserving existing file: {existing}. Choose another output directory.")
    created = []
    try:
        for key, path in files.items():
            with path.open("xb") as handle:
                created.append(path)
                handle.write(content[key])
    except OSError as error:
        for path in created:
            path.unlink(missing_ok=True)
        raise WorkflowError(f"Could not save optimized circuit: {error}") from error
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("circuit", type=Path, help="Trusted pickle, Guppy .py, HUGR or pytket JSON")
    parser.add_argument("--entrypoint", default="main")
    parser.add_argument("--output-dir", type=Path, help="Existing destination; defaults to the input directory")
    add_optimization_arguments(parser)
    args = parser.parse_args(argv)
    try:
        files = optimize_circuit(args.circuit, optimization=args.optimization,
                                 extended_passes=args.extended_passes, entrypoint=args.entrypoint,
                                 output_dir=args.output_dir)
    except WorkflowError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    report = json.loads(files["report"].read_text())
    source = report["source"]
    if "pytket_gates_before" in source:
        print(f"Gates: {source['pytket_gates_before']} -> {source['pytket_gates_after']}")
    for kind, path in files.items():
        print(f"{kind}: {path}")
    if report["export_note"]:
        print(report["export_note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
