"""Guppy entrypoint for the optimized circuit in the adjacent pytket JSON."""
from pathlib import Path
import json
from pytket import Circuit
from guppylang import guppy
from guppylang.std.builtins import output
from guppylang.std.quantum import qubit, discard

__demonstrator_pytket_json__ = Path(__file__).with_name('h2_1qubit_qpe_1phase_raw_default.json')
_circuit = Circuit.from_dict(json.loads(__demonstrator_pytket_json__.read_text()))
loaded = guppy.load_pytket("loaded", _circuit, use_arrays=False)

@guppy
def main() -> None:
    q0 = qubit()
    q1 = qubit()
    q2 = qubit()
    b0 = loaded(q0, q1, q2)
    output('c[0]', b0)
    discard(q0)
    discard(q1)
    discard(q2)

# Recompiling this saved wrapper does not repeat optional optimization.
main = main.with_minimal_opt()
