"""Explicitly generate a scheduled-operation timeline using optional ShotPlot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import inspect
import math
import os
from pathlib import Path
import sys

from workflows._common import (
    WorkflowError, add_arguments, compile_circuit, make_noise_model, new_run_dir,
    noise_from_args, normalise_noise, optional_module, package_versions,
    validate_run, write_json,
)


def plot_shot(
    circuit: str | Path, *, n_qubits: int, shots: int = 1, simulator: str = "stim",
    seed: int | None = None, coinflip_bias: float = 0.0,
    noise: dict[str, float] | None = None, output_dir: str | Path | None = None,
    entrypoint: str = "main", show: bool = False,
) -> Path:
    """Save PNG/PDF figures and settings; requires private plotting packages."""
    validate_run(n_qubits, shots, seed)
    if simulator not in {"stim", "quest", "coinflip"}:
        raise WorkflowError("The plotting simulator must be stim, quest or coinflip.")
    if not math.isfinite(coinflip_bias) or not 0 <= coinflip_bias <= 1:
        raise WorkflowError("Coinflip bias must be between 0 and 1.")
    noise_values = normalise_noise(noise)
    if simulator == "coinflip" and any(noise_values.values()):
        raise WorkflowError("Coinflip performs no quantum simulation; omit noise or use stim/quest.")

    plot_shots = optional_module("shotplot", "ShotPlot").plot_shots
    optional_module("selene_anduril", "Anduril runtime")
    eldarion = optional_module("selene_eldarion", "Eldarion compilation")
    eldarion.register_eldarion()
    from selene_sim import Coinflip, Quest, Stim

    backend = {"stim": Stim, "quest": Quest, "coinflip": lambda: Coinflip(bias=coinflip_bias)}[simulator]()
    kwargs = {"n_qubits": n_qubits, "simulator": backend, "shots": shots,
              "circuit_name": Path(circuit).stem}
    parameters = inspect.signature(plot_shots).parameters
    if seed is not None:
        seed_parameter = next((name for name in ["random_seed", "seed"] if name in parameters), None)
        if seed_parameter is None:
            raise WorkflowError("This ShotPlot API exposes no seed argument; omit --seed.")
        kwargs[seed_parameter] = seed
    if any(noise_values.values()):
        if "error_model" not in parameters:
            raise WorkflowError("This ShotPlot API exposes no error_model argument; noisy plotting is unavailable.")
        kwargs["error_model"] = make_noise_model(noise_values)

    hugr, source = compile_circuit(circuit, entrypoint)
    directory = new_run_dir("shotplot", circuit, output_dir)
    (directory / "circuit.hugr").write_bytes(hugr)
    import matplotlib.pyplot as plt

    before = set(plt.get_fignums())
    label = (f"Coinflip: P(True)={coinflip_bias:g}; no quantum-state simulation"
             if simulator == "coinflip" else f"{simulator}; one execution per plotted shot")
    try:
        returned = plot_shots(hugr, **kwargs)
        figures = [plt.figure(number) for number in sorted(set(plt.get_fignums()) - before)]
        if not figures and hasattr(returned, "savefig"):
            figures = [returned]
        if not figures:
            raise WorkflowError("ShotPlot exposed no Matplotlib figure; its installed API needs checking.")
        saved = []
        for index, figure in enumerate(figures, 1):
            figure.suptitle(f"{Path(circuit).stem} — {label}")
            for suffix in ["png", "pdf"]:
                name = f"timeline_{index:03d}.{suffix}"
                figure.savefig(directory / name, bbox_inches="tight")
                saved.append(name)
        write_json(directory / "settings.json", {
            "created_utc": datetime.now(timezone.utc).isoformat(), "source": source,
            "packages": package_versions(), "files": saved,
            "settings": {"n_qubits": n_qubits, "shots": shots, "simulator": simulator,
                         "seed": seed, "runtime": "anduril",
                         "coinflip_bias": coinflip_bias if simulator == "coinflip" else None,
                         "noise_probabilities": noise_values},
            "quantum_state_simulation": simulator != "coinflip",
            "note": "A separate plotting execution, not a replay of earlier simulation results or an average runtime.",
        })
        if show:
            plt.show()
        else:
            for figure in figures:
                plt.close(figure)
    except Exception as error:
        for number in set(plt.get_fignums()) - before:
            plt.close(number)
        write_json(directory / "error.json", {"source": source, "error": str(error)})
        raise WorkflowError(f"ShotPlot failed: {error}. Details: {directory / 'error.json'}") from error
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser, plotting=True)
    parser.add_argument("--coinflip-bias", type=float, default=0.0,
                        help="P(True) in Coinflip mode; default 0 forces the all-zero path")
    parser.add_argument("--show", action="store_true", help="Also display figures interactively")
    args = parser.parse_args(argv)
    if not args.show:
        os.environ.setdefault("MPLBACKEND", "Agg")
    try:
        directory = plot_shot(args.circuit, n_qubits=args.qubits, shots=args.shots,
                              simulator=args.simulator, seed=args.seed,
                              coinflip_bias=args.coinflip_bias, noise=noise_from_args(args),
                              output_dir=args.output, entrypoint=args.entrypoint, show=args.show)
    except WorkflowError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    print(f"Saved timeline and settings: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
