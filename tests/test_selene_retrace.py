"""Branch guard, replayed paths and the real tracing-to-estimation connection."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from workflows._common import ROOT, WorkflowError
from workflows.run_selene_retrace import (
    DEFAULT_RETRACE_OPTIONS, _options, check_retrace_branch, load_measurements,
    run_selene_retrace,
)


class RetraceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="demonstrator-retrace-")
        self.directory = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)

    def test_branch_check_never_switches(self):
        repo = self.directory / "checkout"
        repo.mkdir()

        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()

        git("init", "-b", "hybridpFT")
        git("-c", "user.name=Workflow Test", "-c", "user.email=workflow@example.invalid",
            "commit", "--allow-empty", "-m", "test")
        self.assertEqual(check_retrace_branch(repo)["branch"], "hybridpFT")
        git("switch", "-c", "another-branch")
        with self.assertRaisesRegex(WorkflowError, "Aborted"):
            check_retrace_branch(repo, input_fn=lambda _: "")
        self.assertEqual(git("branch", "--show-current"), "another-branch")
        accepted = check_retrace_branch(repo, input_fn=lambda _: "continue")
        self.assertTrue(accepted["continued_on_other_branch"])
        self.assertEqual(git("branch", "--show-current"), "another-branch")
        with patch("workflows.run_selene_retrace.sys.stdin.isatty", return_value=False):
            with self.assertRaisesRegex(WorkflowError, "--allow-other-branch"):
                check_retrace_branch(repo)
        self.assertTrue(check_retrace_branch(repo, allow_other_branch=True)["continued_on_other_branch"])

    def test_defaults_mapping_and_validation(self):
        options, kwargs = _options({})
        self.assertEqual(options, DEFAULT_RETRACE_OPTIONS)
        self.assertEqual(kwargs["num_qubits"], 1500)
        self.assertEqual(kwargs["synth_accuracy"], 1e-2)
        for name in set(options) - {"physical_qubits", "synthesis_accuracy"}:
            self.assertEqual(kwargs[name], options[name])
        self.assertEqual(_options({"demand_factor": 3, "demand_ramping": False})[1]["demand_factor"], 3)
        with patch("workflows.run_selene_retrace.check_retrace_branch") as guard:
            with self.assertRaises(WorkflowError):
                run_selene_retrace(ROOT / "circuits/bell.py", trace_qubits=2,
                                   code="surface", distance=5, physical_qubits=0)
            guard.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_real_replay_records_branch_and_estimates_resources(self):
        source = self.directory / "adaptive.py"
        source.write_text('''from guppylang import guppy
from guppylang.std.builtins import output
from guppylang.std.quantum import qubit, h, x, z, measure

@guppy
def main() -> None:
    q0, q1 = qubit(), qubit()
    h(q0)
    first = measure(q0).read()
    if first:
        x(q1)
    else:
        z(q1)
    output("answer", measure(q1).read())
''')
        from selene_formats.trace import parse_trace_json
        from selene_retrace.trace_to_gates import trace_to_gates

        for answer, present, absent in [(True, "x", "z"), (False, "z", "x")]:
            with self.subTest(answer=answer):
                output = self.directory / str(answer)
                before = Path.cwd()
                run_selene_retrace(source, trace_qubits=2, code="surface", distance=5,
                                   measurements=[answer, answer], output_dir=output)
                self.assertEqual(Path.cwd(), before)
                settings = json.loads((output / "settings.json").read_text())
                self.assertEqual(settings["retrace_options"], DEFAULT_RETRACE_OPTIONS)
                self.assertEqual(settings["source"]["optimisation"], "none")
                self.assertFalse(settings["flatten_batches"])
                self.assertFalse(settings["trace"]["quantum_state_simulation"])
                self.assertEqual(load_measurements(output / "measurements.json"), [answer, answer])
                raw = parse_trace_json((output / "trace.json").read_text())
                program = json.loads((output / "program.json").read_text())
                self.assertEqual(trace_to_gates(raw).model_dump(), program)
                names = [g["operation"] for b in program["gate_batches"] for g in b["gates"]]
                self.assertIn(present, names)
                self.assertNotIn(absent, names)
                self.assertEqual(names.count("Measure"), 2)
                self.assertEqual(names.count("QFree"), 2)
                self.assertGreaterEqual(len(program["gate_batches"]), 2)
                summary = json.loads((output / "summary.json").read_text())
                self.assertEqual(summary["num_samples"], 1)
                self.assertGreater(summary["mean_runtime_seconds"], 0)
                self.assertGreater(summary["peak_allocated_physical_qubits"], 0)
                self.assertLessEqual(summary["peak_allocated_physical_qubits"], 1500)
                self.assertTrue((output / "retrace.log").read_text())
                self.assertFalse((output / "error.json").exists())

    def test_estimator_failure_keeps_trace(self):
        from selene_core.trace import SCHEMA_VERSION, Trace

        output = self.directory / "failure"
        raw = Trace(schema_version=SCHEMA_VERSION, events=[])
        with patch("workflows.run_selene_retrace._record_trace", return_value=(raw, [], [[]])):
            with patch("workflows.run_selene_retrace._estimate", side_effect=RuntimeError("estimator unavailable")):
                with self.assertRaisesRegex(WorkflowError, "estimator unavailable"):
                    run_selene_retrace(ROOT / "circuits/bell.py", trace_qubits=2,
                                       code="surface", distance=5, output_dir=output)
        for name in ["circuit.hugr", "trace.json", "measurements.json", "program.json", "settings.json"]:
            self.assertTrue((output / name).exists(), name)
        self.assertEqual(json.loads((output / "error.json").read_text())["stage"], "ReTrace estimation")


if __name__ == "__main__":
    unittest.main()
