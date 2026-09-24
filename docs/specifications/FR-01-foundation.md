# Specification - Foundation

Delivered by **phase 1**. Tasks T0.1–T0.4. Shared by all three tracks, and first because it
settles the two highest-risk unknowns before any modelling code exists.

## Purpose
Give every track a package to code into, a CLI to hang its stage on, an LLM client that is
repeatable, and proof that the two external tools the project depends on actually run on the
team's machines.

## Modules
1. `pyproject.toml` — package metadata, dependencies, `[dev]` extras, the `specalive` console
   script.
2. `specalive/__init__.py`, `specalive/config.py`.
3. `specalive/cli.py` — subcommands `ingest`, `extract`, `generate`, `compile`, `verify`,
   `report`, `run`, `cache clear`, `doctor`. All but `doctor` and `cache clear` are stubs that
   print "not implemented in this phase" and exit non-zero.
4. `specalive/llm/client.py`, `specalive/llm/cache.py`.
5. `specalive/toolchain/omc.py` — probe only in this phase.
6. `specalive/toolchain/sysml_validate.py` — probe only in this phase.
7. `DECISIONS.md`, `AI-LOG.md` — headers and format line only. **The entries are the team's.**
8. `.gitignore`, `README.md` (setup and the compile command, filled in properly by phase 9).

## Requirements
1. `config.py` holds every tunable in one place: model name, cache directory, tool paths,
   per-tool timeouts, repair attempt limit. Values come from environment variables with
   defaults; nothing else in the package reads the environment.
2. **LLM client.**
   - Takes a Pydantic model as the response schema and returns a validated instance, using
     structured outputs in strict mode.
   - Temperature 0.
   - Every call is cached on disk, keyed by model name, the full prompt, the schema and a hash
     of the input. A cache hit makes no network call.
   - Logs tokens in and out and an estimated cost per call.
   - A network or API error raises a typed `LLMError` carrying the request id; it never
     returns a partial object.
3. **`specalive doctor`** reports, each as OK / FAIL with the detail:
   - Python version;
   - `omc` found, its version, and whether a script that loads MSL and **simulates
     `Modelica.Fluid.Examples.ControlledTankSystem.ControlledTanks`** succeeds (not the
     StateGraph example of the same name, which fails at runtime on OpenModelica 1.27.1; see
     `ADR.md`);
   - the SysML v2 validator found, and whether it parses the fixture
     `tests/fixtures/probe.sysml` (a part, a port, a connection, an attribute with a unit, a
     state machine);
   - `OPENAI_API_KEY` present (never printed) and one cached-able test call succeeds.
4. **The validator spike (T0.3)** tries the OMG SysML v2 Pilot Implementation first and at
   least one alternative. The choice and why the other lost go into `ADR.md` and a
   `DECISIONS.md` entry. Its install steps go into `docs/devenv.md`.
5. Every entry point reconfigures stdout and stderr to UTF-8 with `errors="replace"`.
6. `.gitignore` covers `out/`, the cache directory, `.venv/`, `environment.bat`,
   `environment.sh`, `.env`, `.claude/memory/`, `.claude/settings.local.json`.

## Acceptance
1. `pip install -e .[dev]` in a fresh 3.12 virtual environment succeeds, and
   `specalive --help` lists every subcommand.
2. `specalive doctor` reports OK on all four checks on **every team member's machine**. Paste
   the output of each into the pull request.
3. Calling the LLM client twice with the same input makes one network call; the second
   returns an identical object from cache. Shown by a unit test with the network mocked.
4. `python -c "import specalive.config, specalive.llm.client"` works with no API key set.
5. `DECISIONS.md` exists and holds the team's first entry (written by the team).

## Rules
| Id | Requirement |
|---|---|
| R-FND-1 | Toolchain proof precedes modelling code. No phase that generates or runs a model starts until `doctor` passes. |
| R-FND-2 | Only `config.py` reads environment variables. |
| R-FND-3 | The API key is never printed, logged, cached or committed. |
| R-FND-4 | Every external-tool call has a timeout and returns a structured result `{ok, command, stdout, stderr, duration}`; tool-reported errors do not raise. |
| R-FND-5 | The cache key includes the model name, so changing model never returns a stale answer. |
