---
type: regex
target: { source: file, path: outputs.tf }
pattern: '(?:^|\n)output\s+"[^"\n]+"\s*(?:\{[ \t]*\n(?:(?!\})(?![ \t]*description\s*=)[^\n]*\n)*\}|\{\s*\})'
match: not_contains
---
