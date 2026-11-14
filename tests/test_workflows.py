"""Small numerical checks; outputs and compiler builds stay in temporary folders."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflows._common import ROOT, WorkflowError
from workflows.plot_shot import plot_shot
from workflows.simulate import simulate


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="demonstrator-workflows-")
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def run_circuit(self, circuit, **options):
        directory = simulate(circuit, output_dir=self.directory / options.pop("name", "run"), **options)
        return directory, json.loads((directory / "summary.json").read_text())

    def test_bell_stim_and_compiled_hugr(self):
        directory, summary = self.run_circuit(ROOT / "circuits/bell.py", n_qubits=2, shots=128, seed=17)
        self.assertEqual(summary["attempted_shots"], 128)
        self.assertEqual(summary["accepted_shots"], 128)
        self.assertEqual(summary["rejected_shots"], 0)
        self.assertEqual(sum(row["count"] for row in summary["counts"]), 128)
        for row in summary["counts"]:
            self.assertEqual(row["outputs"]["q0"], row["outputs"]["q1"])
        self.assertEqual({row["outputs"]["q0"][0] for row in summary["counts"]}, {False, True})
        _, repeated = self.run_circuit(directory / "circuit.hugr", n_qubits=2, shots=128,
                                       seed=17, name="compiled")
        self.assertEqual(repeated["counts"], summary["counts"])
        self.assertEqual(repeated["source"]["format"], "hugr")

    def test_non_clifford_rotation_and_measurement_noise(self):
        circuit = ROOT / "circuits/rotation.py"
        _, ideal = self.run_circuit(circuit, n_qubits=1, shots=1000, simulator="quest", seed=9)
        _, noisy = self.run_circuit(circuit, n_qubits=1, shots=1000, simulator="quest", seed=9,
                                    noise={"p_meas": 1.0}, name="noise")
        for summary, expected in [(ideal, 0.25), (noisy, 0.75)]:
            ones = sum(row["count"] for row in summary["counts"] if row["outputs"]["bit"][0])
            self.assertAlmostEqual(ones / summary["accepted_shots"], expected, delta=0.06)
        self.assertEqual(noisy["settings"]["noise_model"], "depolarizing")

    def test_rejected_shots_are_counted(self):
        circuit = self.directory / "postselection.py"
        circuit.write_text("""from guppylang import guppy
from guppylang.std.builtins import exit, output
from guppylang.std.quantum import h, measure, qubit

@guppy
def main() -> None:
    q = qubit()
    h(q)
    if measure(q).read():
        exit('rejected example')
    output('accepted', True)
""")
        directory, summary = self.run_circuit(circuit, n_qubits=1, shots=128, seed=11)
        self.assertGreater(summary["accepted_shots"], 0)
        self.assertGreater(summary["rejected_shots"], 0)
        self.assertEqual(summary["attempted_shots"], 128)
        self.assertEqual(summary["accepted_shots"] + summary["rejected_shots"], 128)
        self.assertEqual(sum(row["count"] for row in summary["counts"]), summary["accepted_shots"])
        self.assertTrue(summary["rejection_tags"])
        self.assertEqual(len(json.loads((directory / "shots.json").read_text())), 128)

    def test_stim_rejects_general_rotation(self):
        with self.assertRaisesRegex(WorkflowError, "use --simulator quest"):
            self.run_circuit(ROOT / "circuits/rotation.py", n_qubits=1, shots=1)

    def test_private_modes_fail_before_creating_outputs(self):
        output = self.directory / "private"
        with patch("workflows.simulate.optional_module", side_effect=WorkflowError("private packages unavailable")):
            with self.assertRaisesRegex(WorkflowError, "private packages"):
                simulate(ROOT / "circuits/bell.py", n_qubits=2, runtime="anduril", output_dir=output)
        with patch("workflows.plot_shot.optional_module", side_effect=WorkflowError("private packages unavailable")):
            with self.assertRaisesRegex(WorkflowError, "private packages"):
                plot_shot(ROOT / "circuits/bell.py", n_qubits=2, output_dir=output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
