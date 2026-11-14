"""Compile a Guppy circuit and explicitly run local Selene shots."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter

from workflows._common import (
    WorkflowError, add_arguments, compile_circuit, make_noise_model, new_run_dir,
    noise_from_args, normalise_noise, optional_module, package_versions,
    validate_run, write_json,
)


def simulate(
    circuit: str | Path, *, n_qubits: int, shots: int = 1000,
    simulator: str = "stim", seed: int = 0, runtime: str = "simple",
    noise: dict[str, float] | None = None, output_dir: str | Path | None = None,
    entrypoint: str = "main",
) -> Path:
    """Run shots and return the directory containing the compiled circuit and results."""
    validate_run(n_qubits, shots, seed)
    if simulator not in {"stim", "quest"}:
        raise WorkflowError("Choose stim for Clifford circuits or quest for general rotations.")
    if runtime not in {"simple", "anduril"}:
        raise WorkflowError("The runtime must be simple or anduril.")
    noise_values = normalise_noise(noise)

    from guppylang.emulator import EmulatorBuilder
    from selene_sim import Quest, Stim

    builder = EmulatorBuilder()
    runtime_plugin = None
    if runtime == "anduril":
        anduril = optional_module("selene_anduril", "Anduril runtime")
        eldarion = optional_module("selene_eldarion", "Eldarion compilation")
        eldarion.register_eldarion()
        builder = builder.with_build_arg("eldarion", True).link_utility(eldarion.QtmPlatformPlugin())
        runtime_plugin = anduril.AndurilRuntimePlugin()

    started = perf_counter()
    hugr, source = compile_circuit(circuit, entrypoint)
    directory = new_run_dir("simulation", circuit, output_dir)
    (directory / "circuit.hugr").write_bytes(hugr)
    try:
        emulator = (
            builder.with_build_dir(directory / "build").build(hugr, n_qubits=n_qubits)
            .with_simulator(Stim() if simulator == "stim" else Quest())
            .with_shots(shots).with_seed(seed)
        )
        if runtime_plugin is not None:
            emulator = emulator.with_runtime(runtime_plugin)
        error_model = make_noise_model(noise_values)
        if error_model is not None:
            emulator = emulator.with_error_model(error_model)
        build_seconds = perf_counter() - started
        started = perf_counter()
        result = emulator.run()
        execution_seconds = perf_counter() - started
    except Exception as error:
        write_json(directory / "error.json", {"source": source, "error": str(error)})
        hint = " Stim supports Clifford circuits; use --simulator quest for general rotations." if simulator == "stim" else ""
        raise WorkflowError(f"Selene failed: {error}.{hint} Details: {directory / 'error.json'}") from error

    raw_shots = [list(shot) for shot in result]
    counts: Counter[str] = Counter()
    rejection_counts: Counter[str] = Counter()
    accepted = 0
    for shot in result:
        exit_tags = {tag for tag, _ in shot if tag.lower().startswith("exit:")}
        if exit_tags:
            rejection_counts.update(exit_tags)
            continue
        accepted += 1
        counts[json.dumps(shot.collate_tags(), sort_keys=True)] += 1

    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "settings": {"n_qubits": n_qubits, "shots": shots, "simulator": simulator,
                     "seed": seed, "runtime": runtime,
                     "noise_model": "depolarizing" if any(noise_values.values()) else "ideal",
                     "noise_probabilities": noise_values},
        "packages": package_versions(),
        "attempted_shots": len(raw_shots), "accepted_shots": accepted,
        "rejected_shots": len(raw_shots) - accepted,
        "rejection_tags": dict(rejection_counts),
        "counts_conditioned_on_acceptance": True,
        "counts": [{"outputs": json.loads(key), "count": count}
                   for key, count in counts.most_common()],
        "wall_time_seconds": {"compile_and_build": build_seconds, "execution": execution_seconds},
    }
    write_json(directory / "shots.json", raw_shots)
    write_json(directory / "summary.json", summary)
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--runtime", choices=["simple", "anduril"], default="simple")
    args = parser.parse_args(argv)
    try:
        directory = simulate(args.circuit, n_qubits=args.qubits, shots=args.shots,
                             simulator=args.simulator, seed=args.seed, runtime=args.runtime,
                             noise=noise_from_args(args), output_dir=args.output,
                             entrypoint=args.entrypoint)
    except WorkflowError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    summary = json.loads((directory / "summary.json").read_text())
    print(f"Attempted: {summary['attempted_shots']}; accepted: {summary['accepted_shots']}; rejected: {summary['rejected_shots']}")
    for row in summary["counts"][:20]:
        print(f"  {json.dumps(row['outputs'], sort_keys=True)}: {row['count']}")
    print(f"Saved results: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
