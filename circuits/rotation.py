"""A non-Clifford Rz example; ideally P(bit=1)=1/4. Use QuEST."""

from guppylang import guppy
from guppylang.std.angles import pi
from guppylang.std.builtins import output
from guppylang.std.quantum import h, measure, qubit, rz


@guppy
def main() -> None:
    q = qubit()
    h(q)
    rz(q, pi / 3)
    h(q)
    output("bit", measure(q).read())
