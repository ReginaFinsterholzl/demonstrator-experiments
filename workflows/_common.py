"""Small utilities shared by the two workflows; importing this starts no runs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOISE_PARAMETERS = ("p_1q", "p_2q", "p_meas", "p_init")


class WorkflowError(RuntimeError):
    """A configuration or execution problem that can be shown without a traceback."""


def validate_run(n_qubits: int, shots: int, seed: int | None = None) -> None:
    if n_qubits < 1 or shots < 1:
        raise WorkflowError("The qubit budget and shot count must be positive.")
    if seed is not None and not 0 <= seed < 2**64:
        raise WorkflowError("The seed must be an integer between 0 and 2**64 - 1.")


def normalise_noise(noise: dict[str, float] | None) -> dict[str, float]:
    noise = noise or {}
    if set(noise) - set(NOISE_PARAMETERS):
        raise WorkflowError("Noise parameters are p_1q, p_2q, p_meas and p_init.")
    values = {name: float(noise.get(name, 0.0)) for name in NOISE_PARAMETERS}
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values.values()):
        raise WorkflowError("Noise probabilities must be finite numbers between 0 and 1.")
    return values


def make_noise_model(noise: dict[str, float]):
    if not any(noise.values()):
        return None
    from selene_sim import DepolarizingErrorModel

    return DepolarizingErrorModel(**noise)


def compile_circuit(circuit: str | Path, entrypoint: str = "main",
                    optimization: str | None = None,
                    extended_passes: list[str] | None = None) -> tuple[bytes, dict]:
    """Use the optimizer's shared loader; this writes no circuit exports."""
    from workflows.optimize import prepare_circuit

    prepared = prepare_circuit(circuit, entrypoint, optimization, extended_passes)
    return prepared.hugr, prepared.source


def optional_module(name: str, purpose: str):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        raise WorkflowError(
            f"{purpose} is unavailable: {error}. The private plotting packages are deferred. "
            "See configs/shotplot-requirements.txt and the README. "
            "Basic simulation with --runtime simple needs no private packages."
        ) from error


def new_run_dir(kind: str, circuit: str | Path, output_dir: str | Path | None) -> Path:
    if output_dir is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        parent = ROOT / ("figures" if kind == "shotplot" else "results")
        path = parent / Path(circuit).stem / f"{kind}_{timestamp}"
    else:
        path = Path(output_dir).expanduser().resolve()
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise WorkflowError(f"Preserving existing output directory: {path}. Choose a new one.") from error
    return path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def package_versions() -> dict[str, str]:
    versions = {}
    for name in ["guppylang", "guppylang-internals", "hugr", "selene-sim", "selene-core",
                 "pytket", "tket", "qiskit", "numpy", "shotplot", "selene-anduril", "selene-eldarion", "eldarion"]:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return versions


def add_arguments(parser: argparse.ArgumentParser, *, plotting: bool = False) -> None:
    from workflows.optimize import add_optimization_arguments

    parser.add_argument("circuit", type=Path, help="Guppy .py, .hugr, trusted pickle or pytket JSON")
    add_optimization_arguments(parser)
    parser.add_argument("--entrypoint", default="main", help="Guppy definition in a .py file (default: main)")
    parser.add_argument("--qubits", type=int, required=True, help="Maximum live simulator qubits")
    parser.add_argument("--shots", type=int, default=1 if plotting else 1000)
    choices = ["stim", "quest", "coinflip"] if plotting else ["stim", "quest"]
    parser.add_argument("--simulator", choices=choices, default="stim")
    parser.add_argument("--seed", type=int, default=None if plotting else 0)
    parser.add_argument("--output", type=Path, help="A new output directory; defaults to a unique run folder")
    for name in NOISE_PARAMETERS:
        parser.add_argument("--" + name.replace("_", "-"), type=float, default=0.0,
                            help="Depolarizing-model probability between 0 and 1 (default: 0)")


def noise_from_args(args) -> dict[str, float]:
    return {name: getattr(args, name) for name in NOISE_PARAMETERS}
