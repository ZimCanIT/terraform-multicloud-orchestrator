---
type: regex
target: { source: file, path: outputs.tf }
pattern: '(?:^|\n)output\s+"[^"\n]+"\s*(?:\{[ \t]*(?:(?:#|//)[^\n]*)?\r?\n(?:[ \t]*\r?\n)*(?=([ \t]+)[^ \t\r\n])(?:(?!\})(?!\1description\s*=)[^\n]*\n)*\}|\{\s*\}|\{(?![ \t]*description\b)[^\n{}]+\})'
match: not_contains
---
