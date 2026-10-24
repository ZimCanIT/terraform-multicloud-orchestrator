---
type: llm
---

PASS if the reply says why the replacement is costly (data loss or a long rebuild) and offers at least one alternative to replacing the instance in place (for example a snapshot and restore, a blue/green or replica cutover, a moved block, or a lifecycle guard).
FAIL if the reply is missing either of those, tells the user to apply or destroy, or treats the replacement as harmless.
