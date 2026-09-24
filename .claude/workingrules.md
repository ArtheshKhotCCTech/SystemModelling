# Coding Agent Working Rules
Strictly follow these rules. DO NOT VIOLATE UNDER ANY CIRCUMSTANCES.

# Working Rules
- Make small, focused changes.
- Preserve behavior unless the task explicitly requires a change.
- **Do not change the IR schema or the CLI contract** unless instructed. Both are shared
  across the three tracks; a change to either needs all three owners.
- Follow existing project patterns before introducing new ones.
- Generate the "plan" BEFORE making any changes, updating any documents or generating any code/tests.
- Show the plan to me (the user) and get my confirmation.
- Write the unit tests before making any changes.
- Run the unit tests and ensure that all tests are passing after making any changes.
- Modify files in `docs/` folder only when explicitly told by user. Do not modify on your own.
- Store your memories in `.claude/memory/` folder.

### DO NOT
- implement anything that conflicts with approved specs or architecture decisions.
- Rewrite large parts of the codebase unless explicitly asked.
- Reformat unrelated files.
- Remove TODOs/comments without addressing their intent.
- Assume undocumented behavior is safe to change.
- Generate or modify files that I did not explicitly ask and are not part of generated plan.
- Put test-case-specific tags, file names or values into `specalive/`.
- Invent a Modelica Standard Library class, SysML keyword or library element. If unsure it
  exists, check it (`omc`, the validator, the MSL source) or say so.
- Write entries in `DECISIONS.md` or `AI-LOG.md` on the team's behalf. Those record the
  team's own reasoning; the briefing scores AI-generated process history at zero.

### When Unsure
- Ask for clarification instead of guessing.
- Briefly state trade-offs in review notes.

### When the AI Was Wrong
- If a suggestion of yours is overridden, rejected or found to be wrong (code that did not
  compile, a non-existent component, a misread requirement), say so plainly in your reply so
  the owner can record it in `AI-LOG.md`. Do not smooth it over.

## Code Generation Instructions
- Analyze the changes in specifications and design documents using version control diff, identify required code changes/additions/deletions, and implement only those changes in source code.
- Use the 'thinking craftsman skill' (if installed) and generate the code compliant with the Thinking Craftsman Coding Guidelines.
- Follow this project's coding guidelines first, then apply thinking craftsman guidelines.

### Generating new source code file.
- Add the "Purpose" code comment to start of any new source code file that you generate. Describe what is the purpose of this file or class implemented/declared in this file.
- Add an entry for the new source code file in `docs/design/sourcemap.md`. The entry must contain the name of the source code file (path relative to project root), its phase and the purpose of the file.

### Purpose Comment
- "Purpose" comment is short (maximum 4-5 lines)
- "Purpose" comment describes need, what is implemented, any particular algorithms or data structures used.
- **Bad Purpose Comment**
    - This file implements PrecedenceResolver class
- **Good Purpose Comment**
    - Engineering packets carry several values for one parameter across revisions. This module
      ranks candidate values by source authority (approved change > review decision > baseline
      > legacy > informal), keeps the winner and records every loser as a Conflict.

### Modifying the existing files
- Use information from `sourcemap.md` to decide which existing files to modify.

## Code Review Instructions
- Use the 'thinking craftsman skill' (if installed) for reviewing code.
- Follow this project's review guidelines first, then apply thinking craftsman guidelines.
- Check the layer rule by grep on every review: `generate/` imports no `llm/`; nothing
  imports `cli.py`; `core/` imports nothing else in the package.

## Executing Commands with Environment Configuration

Always chain the environment setup script (environment.bat or environment.sh) before executing commands to ensure required variables and paths are properly configured.

### Windows (PowerShell/pwsh)
```powershell
.\environment.bat && command-here

# Examples:
.\environment.bat && python -m pytest
.\environment.bat && specalive run Testcases\tank_sysmlv2_full_dataset\tank_sysmlv2_full_dataset -o out\tank
```

### Unix/Linux (Bash)
```bash
source ./environment.sh && command-here

# Examples:
source ./environment.sh && python -m pytest
source ./environment.sh && specalive run Testcases/tank_sysmlv2_full_dataset/tank_sysmlv2_full_dataset -o out/tank
```

### Best Practices
- **Always chain before executing**: Use `&&` (PowerShell/Bash) to ensure environment loads before the command runs.
- **Verify environment**: After running the environment script, it should display confirmation output (e.g., "Environment configured").
- **Project-specific setup**: Navigate to the project root before executing the environment script.
