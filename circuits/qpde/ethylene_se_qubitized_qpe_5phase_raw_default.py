"""Guppy entrypoint for the optimized circuit in the adjacent pytket JSON."""
from pathlib import Path
import json
from pytket import Circuit
from guppylang import guppy
from guppylang.std.builtins import output
from guppylang.std.quantum import qubit, discard

__demonstrator_pytket_json__ = Path(__file__).with_name('ethylene_se_qubitized_qpe_5phase_raw_default.json')
_circuit = Circuit.from_dict(json.loads(__demonstrator_pytket_json__.read_text()))
loaded = guppy.load_pytket("loaded", _circuit, use_arrays=False)

@guppy
def main() -> None:
    q0 = qubit()
    q1 = qubit()
    q2 = qubit()
    q3 = qubit()
    q4 = qubit()
    q5 = qubit()
    q6 = qubit()
    q7 = qubit()
    q8 = qubit()
    q9 = qubit()
    q10 = qubit()
    q11 = qubit()
    q12 = qubit()
    b0, b1, b2, b3, b4 = loaded(q0, q1, q2, q3, q4, q5, q6, q7, q8, q9, q10, q11, q12)
    output('c[0]', b0)
    output('c[1]', b1)
    output('c[2]', b2)
    output('c[3]', b3)
    output('c[4]', b4)
    discard(q0)
    discard(q1)
    discard(q2)
    discard(q3)
    discard(q4)
    discard(q5)
    discard(q6)
    discard(q7)
    discard(q8)
    discard(q9)
    discard(q10)
    discard(q11)
    discard(q12)

# Recompiling this saved wrapper does not repeat optional optimization.
main = main.with_minimal_opt()
