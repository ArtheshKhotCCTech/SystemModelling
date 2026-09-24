# Purpose: marks `specalive` as the one application package and exposes its version. Layers are
# subpackages (core, llm, ingest, extract, generate, toolchain, repair, verify, report) so the
# direction of every dependency is visible in its import path; see docs/design/ARCHITECTURE.md.
__version__ = "0.1.0"
