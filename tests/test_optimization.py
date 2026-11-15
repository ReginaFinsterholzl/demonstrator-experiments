"""Optimization checks compare exact matrices, including their global phase."""

import json
from pathlib import Path
import pickle
import tempfile
import unittest

import numpy as np
from pytket import Circuit

from workflows._common import ROOT, WorkflowError, compile_circuit
from workflows.optimize import EXTENDED_PASSES, _optimize_pytket, optimize_circuit, prepare_circuit
from workflows.simulate import simulate


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="demonstrator-optimization-")
        self.directory = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)

    def test_exact_unitaries_including_global_phase(self):
        rng = np.random.default_rng(24)
        for _ in range(4):
            circuit = Circuit(3)
            circuit.add_phase(float(rng.uniform(-1, 1)))
            for step in range(12):
                q = step % 3
                circuit.H(q).S(q).Rz(float(rng.uniform(-1, 1)), q)
                circuit.CX(q, (q + 1) % 3)
            before = circuit.to_dict()
            expected = circuit.get_unitary()
            configurations = [(level, ()) for level in ["none", "minimal", "classical", "default"]]
            configurations += [("extended", (name,)) for name in EXTENDED_PASSES]
            configurations += [("extended", EXTENDED_PASSES)]
            for level, selected in configurations:
                with self.subTest(level=level, passes=selected):
                    optimized = _optimize_pytket(circuit, level, selected)
                    # No phase alignment: equality up to global phase is insufficient.
                    np.testing.assert_allclose(optimized.get_unitary(), expected, atol=1e-9, rtol=0)
                    self.assertEqual(circuit.to_dict(), before)

    def test_pickle_json_object_wrapper_and_hugr_roundtrips(self):
        circuit = Circuit(2, 2).H(0).H(0).H(0).CX(0, 1).measure_all()
        circuit.add_phase(.17)
        original = self.directory / "bell.pkl"
        original.write_bytes(pickle.dumps(circuit))
        untouched = original.read_bytes()
        files = optimize_circuit(original, optimization="default")
        self.assertEqual(set(files), {"hugr", "pytket", "guppy", "report"})
        self.assertTrue(all(p.parent == original.parent for p in files.values()))
        native = Circuit.from_dict(json.loads(files["pytket"].read_text()))
        self.assertEqual(native.n_bits, circuit.n_bits)
        self.assertLess(native.n_gates, circuit.n_gates)
        self.assertAlmostEqual(float(native.phase), float(circuit.phase))
        self.assertEqual(original.read_bytes(), untouched)
        for path in [files["pytket"], files["guppy"]]:
            prepared = prepare_circuit(path, optimization="none")
            self.assertEqual(prepared.pytket.to_dict(), native.to_dict())
        self.assertEqual(prepare_circuit(files["guppy"]).source["optimisation"], "none")
        hugr, source = compile_circuit(files["hugr"], optimization="none")
        self.assertEqual(hugr, files["hugr"].read_bytes())
        self.assertEqual(source["optimisation"], "none")
        prepared = prepare_circuit(circuit, optimization="none")
        self.assertEqual(prepared.pytket.to_dict(), circuit.to_dict())
        directory = simulate(files["guppy"], n_qubits=2, shots=32, seed=7,
                             optimization="none", output_dir=self.directory / "run")
        summary = json.loads((directory / "summary.json").read_text())
        self.assertEqual(summary["source"]["optimisation"], "none")
        self.assertEqual(summary["accepted_shots"], 32)
        for row in summary["counts"]:
            self.assertEqual(row["outputs"]["c[0]"], row["outputs"]["c[1]"])
        with self.assertRaisesRegex(WorkflowError, "Preserving existing file"):
            optimize_circuit(original, optimization="default")
        self.assertEqual(original.read_bytes(), untouched)

    def test_qiskit_pickle_and_pytket_json_extension(self):
        from qiskit import QuantumCircuit

        circuit = QuantumCircuit(1, 1)
        circuit.h(0)
        circuit.measure(0, 0)
        path = self.directory / "qiskit.pickle"
        path.write_bytes(pickle.dumps(circuit))
        self.assertEqual(prepare_circuit(path, optimization="none").pytket.n_qubits, 1)
        path = self.directory / "native.pytket"
        path.write_text(json.dumps(Circuit(1).X(0).to_dict()))
        self.assertEqual(prepare_circuit(path, optimization="minimal").pytket.n_gates, 1)

    def test_guppy_modes_skip_quantum_optimization_and_report_export_limits(self):
        source = self.directory / "redundant.py"
        source.write_text('''from guppylang import guppy
from guppylang.std.quantum import qubit, h, measure
from guppylang.std.builtins import output

@guppy
def main() -> None:
    q = qubit()
    h(q)
    h(q)
    output("bit", measure(q).read())
''')
        from hugr.package import Package
        from hugr.ops import ExtOp
        from tket_exts import tket_registry

        def hadamards(data):
            package = Package.from_bytes(data, tket_registry())
            return sum(isinstance(module[node].op, ExtOp) and module[node].op.op_def().name == "H"
                       for module in package.modules for node in module)

        none = prepare_circuit(source, optimization="none")
        classical = prepare_circuit(source, optimization="classical")
        default = prepare_circuit(source, optimization="default")
        self.assertEqual(hadamards(none.hugr), 2)
        self.assertEqual(hadamards(classical.hugr), 2)
        self.assertEqual(hadamards(default.hugr), 0)
        files = optimize_circuit(ROOT / "circuits/bell.py", output_dir=self.directory)
        self.assertEqual(set(files), {"hugr", "report"})
        self.assertIn("cannot be exported faithfully", json.loads(files["report"].read_text())["export_note"])

    def test_validation_does_not_create_outputs(self):
        circuit = Circuit(1).H(0)
        with self.assertRaisesRegex(WorkflowError, "PauliGraphResynthesis is excluded"):
            optimize_circuit(circuit, optimization="extended", extended_passes=["PauliGraphResynthesis"],
                             output_dir=self.directory)
        with self.assertRaisesRegex(WorkflowError, "specifying extended passes"):
            optimize_circuit(circuit, optimization="none", extended_passes=["CliffordSimp"],
                             output_dir=self.directory)
        self.assertEqual(list(self.directory.iterdir()), [])
        malformed = self.directory / "broken.hugr"
        malformed.write_bytes(b"not a HUGR envelope")
        with self.assertRaises(WorkflowError):
            optimize_circuit(malformed, optimization="none")
        self.assertEqual(list(self.directory.iterdir()), [malformed])


if __name__ == "__main__":
    unittest.main()
