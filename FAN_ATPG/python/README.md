# Native FAN Verilog Python bridge

Build with the interpreter used by the application:

```sh
python FAN_ATPG/setup.py build_ext --inplace
```

The frontend calls original `MdtLibBuilder` / `Techlib::check`, then
`VlogNlBuilder` / `Netlist::check`, and `Circuit::buildCircuit(netlist, 1)`.
It calls original FAN multiple-backtrace target ATPG and parallel fault
simulation. No alternate Verilog parser or BENCH reader is included.

```python
catalog = cpp_fan.catalog_stuck_at(netlist_path, library_path)
graph = cpp_fan.circuit_graph(netlist_path, library_path)
session = cpp_fan.StuckAtSession(netlist_path, library_path)
```

Catalog and graph preparation skip solver setup. A session allocates its
simulator and computes FAN search structures only before its first target.

The MDT library is mandatory. Protocol identity is `fan_verilog_fullscan_v3`.
`run_stuck_at_ordered(netlist_path, library_path, ordered_fault_ids, ...)`
provides a one-shot wrapper. Legacy BENCH input is rejected.

Supported input is combinational or fullscan structural Verilog with named
technology cell pins. Supported native Boolean primitives: BUF/INV, AND/NAND/OR/NOR
with 2-4 inputs, XOR/XNOR with 2-3 inputs. Cells may contain several primitives;
the mapper selects gate types from primitive arity, rather than the parent
cell's port count. The original builder's empty positional-instance methods
now report failure instead of silently dropping instances.

Fullscan single-capture netlists are supported through the original native
PPI/PPO cut. The bridge normalizes those boundaries to PI/PO without changing
gate IDs or fanins. Input vectors append FF Q states after physical PIs;
outputs append FF D next states after physical POs. Graph and result metadata
include the chain order and state boundary gate IDs. Only complete single
chains using CK/test_si/test_se/test_so pass validation. RN/SN must be tied
inactive with LOGIC1_X1; connected QN requires an explicit inverter on Q.
No multi-cycle, partial-scan or scan-chain protocol test generation is implied.

Binary TIE0/TIE1 now retain exact values in scalar and native ATPG evaluation.
Scan/constant catalogs use uncollapsed functional data sites, including dead
sites as unobservable, and omit automatically detected clock/shift faults
from both detection counts and total. TIE cells instantiated before FF cells
are ordered safely by native levelization.

Unsupported inputs fail before the solver: ordinary non-scan DFF/latches,
MUX, unknown/high-impedance primitives, black boxes, combinational cycles,
multiple drivers, missing required pins, nonbinary port types and reserved
scan/clock ports on combinational circuits. Optional scan FF QN may be open.
Original validation requires every signal to have a driver and consumer.

`circuit_graph` returns schema `fan_circuit_graph_v1`: gates have `gate_id`,
`name`, `kind`, `fanins` (native IDs). It also returns input/output gate IDs
and port names. IDs are contiguous original Circuit order. The fault catalog
uses `g<ID>:GO:sa0` / `g<ID>:GI0:sa1`, numeric `gate_id`, human `gate_name`,
and native equivalence counts (all one for scan/constant catalogs). GO has io=1, input_index=-1,
input_wire_name='-'; GI has io=0, zero-based primitive pin index, source
`g<ID>` and duplicate-pin occurrence. PO boundaries are original Circuit gates.

The source distribution includes original `.l`/`.y` grammars, generated
Flex/Bison C++ snapshots and vendored pybind11 headers. Normal builds require
setuptools and a C++14 compiler. To regenerate with flex and bison installed:

```sh
FAN_REGENERATE_PARSERS=1 python FAN_ATPG/setup.py build_ext --inplace
```

Windows scanners use io.h compatibility. Original parser readers use UTF-8
_wfopen so Unicode library and netlist paths work. Each read resets scanner
exclusive state, line count, and MDT parenthesis state, including after errors.

Primary selection is consumed exactly once. Generated full vectors are
checked by independent scalar simulation before acceptance, then simulated
by original FAN parallel simulation against all undetected faults. Native
no-test results count as redundant for structurally dead observation cones or after exhaustive independent proof
(up to 10 PIs); other no-test/limited searches count as aborted. No fallback
patterns are generated. Each target keeps its chronological backtrack limit
and deterministic work limit max(1000, 10*gate_count+100*backtrack_limit).
Historical podem_calls aliases count primary FAN calls.

Ranked DTC visits exactly one original unknown output-driver wire per PO,
without charging the PO boundary. It exposes that wire's GO and receiving GI
faults. Rankings must be exact permutations; accepted cubes only refine X
positions and must preserve primary and secondary detection. After attempts,
solver events clear and good values restore from the accepted cube.

STC uses reverse simulation then fixed-seed shuffled passes until five passes
without improvement. Every pass checks preservation of detected collapsed
faults. result() is idempotent and includes vectors plus port names.

Tests execute physical solver checks only, without training:

```sh
python -m pytest tests/test_fan_native.py tests/test_fan_acceptance.py -q
```
