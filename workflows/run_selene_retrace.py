"""Record one Selene-ReTrace execution and estimate its resources with ReTrace."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import copy
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from workflows._common import (
    ROOT, WorkflowError, compile_circuit, new_run_dir, package_versions,
    validate_run, write_json,
)
from workflows.optimize import add_optimization_arguments

RETRACE_REPO = ROOT.parent / "ReTrace"
EXPECTED_BRANCH = "hybridpFT"
CODE_NAMES = ("surface", "color", "surface-pft", "csd", "hybrid-helix-surface", "c422")
DEFAULT_RETRACE_OPTIONS = {
    "physical_qubits": 1500,
    "synthesis_accuracy": 1e-2,
    "num_samples": 1,
    "seed": 43,
    "seed_increment": True,
    "demand_factor": 1,
    "demand_ramping": None,
    "allow_jumping": True,
    "perform_ec_on_resource_states": False,
    "careful_alloc": True,
    "debug": False,
    "space_optimized": True,
}


def repository_info(path: Path) -> dict:
    def git(*args):
        try:
            result = subprocess.run(["git", "-C", str(path), *args], check=True,
                                    capture_output=True, text=True)
            return result.stdout.strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise WorkflowError(f"Cannot inspect Git checkout {path}: {error}") from error

    return {"path": str(path.resolve()), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def check_retrace_branch(repository: Path = RETRACE_REPO, *, allow_other_branch: bool = False,
                         input_fn=None) -> dict:
    """Only inspect Git; never switch, stash or discard anything."""
    info = repository_info(repository)
    info["expected_branch"] = EXPECTED_BRANCH
    info["continued_on_other_branch"] = False
    if info["branch"] == EXPECTED_BRANCH:
        return info
    if allow_other_branch:
        info["continued_on_other_branch"] = True
        return info
    if input_fn is None and not sys.stdin.isatty():
        raise WorkflowError(
            f"ReTrace is on {info['branch']!r}, expected {EXPECTED_BRANCH!r}. "
            "Aborted. Switch manually or explicitly use --allow-other-branch."
        )
    try:
        answer = (input_fn or input)(
            f"ReTrace is on {info['branch']!r}, expected {EXPECTED_BRANCH!r}. "
            "[a]bort / [c]ontinue (default: abort): "
        )
    except (EOFError, KeyboardInterrupt):
        answer = "abort"
    if answer.strip().lower() not in {"c", "continue"}:
        raise WorkflowError("Aborted; the ReTrace branch was not changed.")
    info["continued_on_other_branch"] = True
    return info


def _options(overrides: dict) -> tuple[dict, dict]:
    unknown = set(overrides) - DEFAULT_RETRACE_OPTIONS.keys()
    if unknown:
        raise WorkflowError(f"Unknown ReTrace options: {', '.join(sorted(unknown))}")
    options = DEFAULT_RETRACE_OPTIONS | overrides
    for name in ["physical_qubits", "num_samples", "demand_factor"]:
        if type(options[name]) is not int or options[name] < 1:
            raise WorkflowError(f"{name} must be a positive integer.")
    if type(options["seed"]) is not int or options["seed"] < 0:
        raise WorkflowError("seed must be a nonnegative integer.")
    for name, default in DEFAULT_RETRACE_OPTIONS.items():
        if type(default) is bool and type(options[name]) is not bool:
            raise WorkflowError(f"{name} must be boolean.")
    if options["demand_ramping"] is not None and type(options["demand_ramping"]) is not bool:
        raise WorkflowError("demand_ramping must be None, True or False.")
    accuracy = options["synthesis_accuracy"]
    if isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)) or not math.isfinite(accuracy) or not 1e-17 <= accuracy < 1:
        raise WorkflowError("synthesis_accuracy must be finite and between 1e-17 and 1 (exclusive at 1).")
    kwargs = options.copy()
    kwargs["num_qubits"] = kwargs.pop("physical_qubits")
    kwargs["synth_accuracy"] = kwargs.pop("synthesis_accuracy")
    return options, kwargs


def _validate_code(code: str, distance: int | None, level: int | None) -> None:
    if code not in CODE_NAMES:
        raise WorkflowError(f"Choose a QEC code from {', '.join(CODE_NAMES)}.")
    if code in {"surface", "color", "surface-pft"}:
        if type(distance) is not int or distance < 2:
            raise WorkflowError(f"{code} requires --distance >= 2.")
        if level is not None:
            raise WorkflowError("--level applies only to c422.")
    elif code == "c422":
        if type(level) is not int or not 0 <= level <= 3:
            raise WorkflowError("c422 requires --level between 0 and 3.")
        if distance is not None:
            raise WorkflowError("Use --level, rather than --distance, for c422.")
    elif distance is not None or level is not None:
        raise WorkflowError(f"{code} has a fixed code specification; omit --distance and --level.")


def _measurement_values(values) -> list[bool]:
    if not isinstance(values, list) or any(type(v) not in (bool, int) or v not in (0, 1) for v in values):
        raise WorkflowError("Replay measurements must be a list of booleans or 0/1 values.")
    return [bool(v) for v in values]


def load_measurements(path: Path) -> list[bool]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise WorkflowError(f"Cannot read measurement JSON: {error}") from error
    return _measurement_values(data.get("replay_values") if isinstance(data, dict) else data)


def _record_trace(hugr: bytes, directory: Path, trace_qubits: int, trace_seed: int,
                  measurements: list[bool] | None):
    from selene_core import DEFAULT_BUILD_PLANNER
    from selene_sim import build, ClassicalReplay, Coinflip
    from selene_sim.event_hooks import MeasurementExtractor, MultiEventHook, TraceStore
    from selene_retrace_qis_plugin import RetraceInterface, register_retrace_qis_interface
    from retrace_qis_compiler import register_retrace_qis_compiler
    from selene_retrace_runtime import RetraceRuntimePlugin

    # Keep the tracing build steps separate from normal simulation in this process.
    planner = copy.deepcopy(DEFAULT_BUILD_PLANNER)
    register_retrace_qis_interface(planner)
    register_retrace_qis_compiler(planner)
    trace_store = TraceStore()
    measurement_log = MeasurementExtractor()
    runner = build(hugr, build_dir=directory / "build", interface=RetraceInterface(),
                   planner=planner, platform="retrace")
    simulator = Coinflip() if measurements is None else ClassicalReplay(measurements=[measurements])
    shots = [list(shot) for shot in runner.run_shots(
        n_qubits=trace_qubits, n_shots=1, random_seed=trace_seed,
        simulator=simulator, runtime=RetraceRuntimePlugin(),
        event_hook=MultiEventHook([trace_store, measurement_log]),
    )]
    if len(trace_store.shots) != 1 or len(measurement_log.log_entries) != 1:
        raise WorkflowError("Expected exactly one recorded execution.")
    entries = [{"qubit": int(e.qbid), "value": int(e.result_value),
                "is_leakage_measurement": bool(e.is_meas_leaked)}
               for e in measurement_log.log_entries[0]]
    return trace_store.shots[0].get_trace(), entries, shots


@contextmanager
def _run_directory(directory: Path):
    """Keep ReTrace's optional debug files inside the run folder."""
    previous = Path.cwd()
    try:
        os.chdir(directory)
        yield
    finally:
        os.chdir(previous)


def _estimate(program: dict, code: str, distance: int | None, level: int | None,
              kwargs: dict, directory: Path):
    import resource_estimator
    from resource_estimator import codes

    actual = Path(resource_estimator.__file__).resolve().parent
    if actual != (RETRACE_REPO / "resource_estimator").resolve():
        raise WorkflowError(f"Imported ReTrace from {actual}, not the checked checkout {RETRACE_REPO}.")
    factories = {"surface": codes.SurfaceCode, "color": codes.ColorCode,
                 "surface-pft": codes.SurfaceCodePartialFaultTolerant,
                 "csd": codes.CSDCode, "hybrid-helix-surface": codes.HybridHelixSurfaceCode,
                 "c422": codes.Concatenated422Code}
    constructor_options = {"distance": distance} if distance is not None else {}
    if level is not None:
        constructor_options["level"] = level
    qec = factories[code](**constructor_options)
    with _run_directory(directory):
        scheduler = resource_estimator.run_selene_program_for_code(
            qec, program, flatten_batches=False, **kwargs,
        )
    return scheduler


def _resource_summary(scheduler) -> dict:
    result = scheduler.extrusion
    return {
        "qec_model": str(scheduler.logical_arch.code),
        "num_samples": result.num_samples,
        "depth_unit_seconds": result.depth_1_time,
        "sample_depths": list(result.sample_time_steps),
        "sample_runtime_seconds": [d * result.depth_1_time for d in result.sample_time_steps],
        "mean_depth": result.mean_time_step,
        "std_depth": result.std_time_step,
        "mean_runtime_seconds": result.mean_real_time,
        "std_runtime_seconds": result.std_real_time,
        "peak_allocated_physical_qubits": result.max_allocated_exact,
        "sample_modeled_logical_error_probabilities": list(result.sample_error_rates),
        "mean_modeled_logical_error_probability": result.mean_error_rate,
        "std_modeled_logical_error_probability": result.std_error_rate,
        "sample_postselection_discard_probabilities": list(result.sample_post_selection_rates),
        "mean_postselection_discard_probability": result.mean_post_selection_rate(),
        "max_idling_time_exceeded": list(scheduler.max_idling_time_exceeded),
    }


def run_selene_retrace(
    circuit: str | Path, *, trace_qubits: int, code: str,
    distance: int | None = None, level: int | None = None,
    optimization: str = "none", extended_passes: list[str] | None = None,
    entrypoint: str = "main", trace_seed: int = 43,
    measurements: list[bool] | None = None, output_dir: str | Path | None = None,
    allow_other_branch: bool = False, **retrace_options,
) -> Path:
    """Save one traced path, estimate its QEC resources, and return the run folder.

    ReTrace options use the names and defaults in DEFAULT_RETRACE_OPTIONS.
    No ReTrace code is imported before the branch check. Importing this module
    starts no runs. ReTrace's optional debug mode temporarily changes cwd.
    """
    validate_run(trace_qubits, 1, trace_seed)
    _validate_code(code, distance, level)
    options, kwargs = _options(retrace_options)
    if measurements is not None:
        measurements = _measurement_values(measurements)
    retrace_revision = check_retrace_branch(allow_other_branch=allow_other_branch)
    spec = importlib.util.find_spec("resource_estimator")
    if spec is None or spec.origin is None or Path(spec.origin).resolve().parent != (RETRACE_REPO / "resource_estimator").resolve():
        raise WorkflowError("This environment does not expose the checked sibling ReTrace checkout.")

    started = perf_counter()
    hugr, source = compile_circuit(circuit, entrypoint, optimization, extended_passes)
    directory = new_run_dir("selene_retrace", circuit, output_dir)
    (directory / "circuit.hugr").write_bytes(hugr)
    settings = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "source": source,
        "trace": {"qubit_limit": trace_qubits, "seed": trace_seed, "shots": 1,
                  "mode": "coinflip" if measurements is None else "replay",
                  "quantum_state_simulation": False, "supplied_measurements": measurements},
        "qec": {"code": code, "distance": distance, "level": level},
        "retrace_options": options, "retrace_kwargs": kwargs, "flatten_batches": False,
        "repositories": {"ReTrace": retrace_revision,
                         "selene-retrace": repository_info(ROOT.parent / "selene-retrace"),
                         "demonstrator-experiments": repository_info(ROOT)},
        "packages": package_versions(),
        "notes": ["One application path; scheduler samples do not sample new application paths.",
                  "Coinflip/replay answers are not quantum-state probabilities.",
                  "ReTrace hardware and unlisted scheduler settings retain the checked version's defaults."],
    }
    write_json(directory / "settings.json", settings)
    stage = "tracing"
    try:
        with (directory / "trace.log").open("w") as log, redirect_stdout(log), redirect_stderr(log):
            raw, entries, shots = _record_trace(hugr, directory, trace_qubits, trace_seed, measurements)
        from selene_formats.trace import Trace

        versioned = Trace(schema_version=raw.schema_version, events=raw.events)
        (directory / "trace.json").write_text(versioned.model_dump_json(indent=2) + "\n")
        replay = [bool(e["value"]) for e in entries] if all(e["value"] in (0, 1) for e in entries) else None
        write_json(directory / "measurements.json", {"records": entries, "replay_values": replay})
        write_json(directory / "shot_outputs.json", shots)
        stage = "gate-batch conversion"
        from selene_retrace.trace_to_gates import trace_to_gates

        program = trace_to_gates(raw)
        write_json(directory / "program.json", program.model_dump())
        counts = Counter(g.operation for b in program.gate_batches for g in b.gates)
        trace_summary = {"raw_events": len(raw.events), "batches": len(program.gate_batches),
                         "operation_counts": dict(counts), "measurement_answers": len(entries),
                         "batch_operation_counts": [dict(Counter(g.operation for g in b.gates))
                                                    for b in program.gate_batches],
                         "note": "Counts include allocation/freeing, reset and measurement entries."}
        write_json(directory / "trace_summary.json", trace_summary)
        trace_seconds = perf_counter() - started
        stage = "ReTrace estimation"
        started = perf_counter()
        with (directory / "retrace.log").open("w") as log, redirect_stdout(log), redirect_stderr(log):
            scheduler = _estimate(program.model_dump(), code, distance, level, kwargs, directory)
        summary = _resource_summary(scheduler)
        summary.update(trace_summary=trace_summary,
                       wall_time_seconds={"load_compile_and_trace": trace_seconds,
                                          "resource_estimation": perf_counter() - started})
        write_json(directory / "summary.json", summary)
    except Exception as error:
        write_json(directory / "error.json", {"stage": stage, "error_type": type(error).__name__,
                                              "error": str(error)})
        raise WorkflowError(f"{stage} failed: {error}. Saved data and logs: {directory}") from error
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("circuit", type=Path, help="HUGR, Guppy .py, trusted pickle or pytket JSON")
    parser.add_argument("--trace-qubits", "--qubits", type=int, required=True, dest="trace_qubits",
                        help="Maximum simultaneously live circuit qubits before QEC encoding")
    parser.add_argument("--code", choices=CODE_NAMES, required=True)
    parser.add_argument("--distance", type=int, help="Required for surface, color and surface-pft")
    parser.add_argument("--level", type=int, help="Required for c422; 0 through 3")
    parser.add_argument("--trace-seed", type=int, default=43)
    parser.add_argument("--measurements", type=Path, help="JSON replay values, or a previous measurements.json")
    parser.add_argument("--entrypoint", default="main")
    parser.add_argument("--output", type=Path, help="New output folder; defaults to results/<circuit>/selene_retrace_<timestamp>")
    parser.add_argument("--allow-other-branch", action="store_true",
                        help="Explicitly continue on a ReTrace branch other than hybridpFT; never switches branches")
    add_optimization_arguments(parser, default="none")
    for name in ["physical_qubits", "num_samples", "seed", "demand_factor"]:
        help_text = {"physical_qubits": "Physical hardware qubit budget for ReTrace",
                     "num_samples": "Scheduler samples for this one traced path",
                     "seed": "ReTrace scheduler seed, separate from --trace-seed",
                     "demand_factor": "ReTrace resource-state demand factor"}[name]
        parser.add_argument("--" + name.replace("_", "-"), type=int,
                            default=DEFAULT_RETRACE_OPTIONS[name], help=help_text)
    parser.add_argument("--synthesis-accuracy", type=float, default=DEFAULT_RETRACE_OPTIONS["synthesis_accuracy"],
                        help="Rotation-synthesis accuracy passed to ReTrace")
    for name in ["seed_increment", "demand_ramping", "allow_jumping", "perform_ec_on_resource_states",
                 "careful_alloc", "debug", "space_optimized"]:
        parser.add_argument("--" + name.replace("_", "-"), action=argparse.BooleanOptionalAction,
                            default=DEFAULT_RETRACE_OPTIONS[name],
                            help="ReTrace setting " + name + ("; None selects its code-dependent default" if name == "demand_ramping" else ""))
    args = parser.parse_args(argv)
    try:
        measurements = load_measurements(args.measurements) if args.measurements else None
        directory = run_selene_retrace(
            args.circuit, trace_qubits=args.trace_qubits, code=args.code, distance=args.distance,
            level=args.level, optimization=args.optimization, extended_passes=args.extended_passes,
            entrypoint=args.entrypoint, trace_seed=args.trace_seed, measurements=measurements,
            output_dir=args.output, allow_other_branch=args.allow_other_branch,
            **{name: getattr(args, name) for name in DEFAULT_RETRACE_OPTIONS},
        )
    except WorkflowError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    summary = json.loads((directory / "summary.json").read_text())
    print(f"Traced one path in {summary['trace_summary']['batches']} batches.")
    print(f"Mean modeled runtime: {summary['mean_runtime_seconds']:.6g} s")
    print(f"Peak allocated physical qubits: {summary['peak_allocated_physical_qubits']}")
    print(f"Mean modeled logical error probability: {summary['mean_modeled_logical_error_probability']:.6g}")
    print(f"Saved trace and resource results: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
