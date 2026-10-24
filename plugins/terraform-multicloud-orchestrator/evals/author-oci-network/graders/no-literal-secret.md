---
type: regex
target: { source: file, path: main.tf }
pattern: '(?:password|passwd|secret|token|api_?key|access_?key|private_?key|credential)[a-z0-9_]*\s*=\s*"[^"$\n]{8,}"|AKIA[0-9A-Z]{16}|-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}'
flags: i
match: not_contains
---
