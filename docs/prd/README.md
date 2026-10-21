# PRD folder

`docs/PRD.md` (Draft 3.3) stays the authority. Claude Code reads that file only.

| File | What it is |
| --- | --- |
| `PRD-draft-3.3-original.md` | Frozen copy of `docs/PRD.md` as of 2026-10-20. Do not edit. |
| `modifications/PRD-draft-3.3-amended.md` | The same text with the permanent changes written in, each marked `[AMENDED ...]` or `[OPEN CONFLICT ...]`. |
| `modifications/amendments.diff` | The exact differences between the two files. |
| `modifications/DEVIATIONS.md` | Every place the build differs from, adds to, or conflicts with the PRD, with its status. |

To see the differences yourself in PowerShell:

    git diff --no-index docs/prd/PRD-draft-3.3-original.md docs/prd/modifications/PRD-draft-3.3-amended.md

In VS Code: select both files in the Explorer, right-click, "Compare Selected".

Adopting an amendment means copying it into `docs/PRD.md` yourself. Nothing here changes `docs/PRD.md` until you do.
