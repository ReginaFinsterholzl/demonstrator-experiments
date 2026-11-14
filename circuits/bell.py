"""Two-qubit Clifford example. Importing this file does not run a simulation."""

from guppylang import guppy
from guppylang.std.builtins import output
from guppylang.std.quantum import cx, h, measure, qubit


@guppy
def main() -> None:
    q0, q1 = qubit(), qubit()
    h(q0)
    cx(q0, q1)
    output("q0", measure(q0).read())
    output("q1", measure(q1).read())
