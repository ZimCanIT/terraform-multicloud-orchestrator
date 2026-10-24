---
type: regex
target: { source: file, path: variables.tf }
pattern: '(?:^|\n)variable\s+"[^"\n]+"\s*(?:\{[ \t]*(?:(?:#|//)[^\n]*)?\r?\n(?:[ \t]*\r?\n)*(?=([ \t]+)[^ \t\r\n])(?:(?!\})(?!\1description\s*=)[^\n]*\n)*\}|\{\s*\}|\{(?![ \t]*description\b)[^\n{}]+\})'
match: not_contains
---
