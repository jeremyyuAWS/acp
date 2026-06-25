# Rule documentation

One file per rule in the ACP rule catalog (`config/rule-catalog.json`).

Each file covers: what the rule checks, the exact code path that implements it,
how to write a unit test, what a correct fix looks like, and failure modes.

| Format | Rules | Source |
|--------|-------|--------|
| DOCX   | 9     | `DigitalA11y.Analysers.DotNet/Rules/Docx/` |
| PPTX   | 8     | `DigitalA11y.Analysers.DotNet/Rules/Pptx/` |
| XLSX   | 7     | `DigitalA11y.Analysers.DotNet/Rules/Xlsx/` |
| PDF    | 7     | `worker-python/analysers/rules/pdf/` |

## Fix modes

| Mode | Meaning |
|------|---------|
| `auto` | The engine can apply a safe, deterministic fix with no human review. |
| `ai-assisted` | The engine drafts a fix; a human must approve before it is applied. These populate the HITL queue. |
| `human-only` | The issue requires a judgment call a person must make. The engine can detect but cannot fix it. |
