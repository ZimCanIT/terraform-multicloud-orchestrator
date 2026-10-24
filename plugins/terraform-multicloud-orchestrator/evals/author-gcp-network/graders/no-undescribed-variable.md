---
type: regex
target: { source: file, path: variables.tf }
pattern: '(?:^|\n)variable\s+"[^"\n]+"\s*(?:\{[ \t]*\n(?:(?!\})(?![ \t]*description\s*=)[^\n]*\n)*\}|\{\s*\})'
match: not_contains
---
