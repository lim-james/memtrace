# memtrace

LLVM instrumentation pass + runtime for tracing memory operations, with an
HTML visualizer for replaying traces.

## Requirements

- Clang/LLVM 20 (`clang++-20`, `llvm-config-20`)
- GCC 16 toolchain headers (`gcc-16` install, used for `--gcc-toolchain`)
- Python 3 (for `tools/render.py`)

## Build

```bash
make            # builds build/mem_trace_pass.so and build/runtime.o
```

## Release

_Work in progress, no deployments yet_
