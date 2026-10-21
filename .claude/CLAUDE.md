CLAUDE.md
Project purpose
This repository contains a Python thesis project on Random Linear Network Coding (RLNC), finite-field packet operations, and packet authentication.
The project is used for both implementation work and simulation studies such as throughput, latency, orthogonality checks, acceptance rates, and recovery behavior.

What to ignore
Do not inspect or modify these folders unless the task explicitly requires it:

.git/
.venv/
pycache/
logs
binary_2pow4/
binary_2pow8/
notebooks/

Also avoid scanning very large generated text dumps unless the task is specifically about debugging logged generations.

Repository map
scripts/ : ad-hoc experiment scripts and comparison runners.

logs/ : failed generations, debug dumps, and experiment traces.

How to help on this project
Start by identifying whether the task is about field arithmetic, packet structure, coding, authentication, recovery, or simulation.
Prefer small targeted fixes over restructuring multiple modules.
When proposing a nontrivial change, explain the expected effect on decoding, verification, or simulation metrics.


Coding rules
Do not replace finite-field operations with normal integer math.
For debugging, prefer focused assertions and concise structured logs over large print dumps.

Logging and generated data
Use logs/ for failure cases and structured debug output.
Do not read all generated packet logs by default; inspect a small sample first.

## How

When reporting inormation to me, be extremely 
concise and sacrifice grammar for 
the sake of consicion.
