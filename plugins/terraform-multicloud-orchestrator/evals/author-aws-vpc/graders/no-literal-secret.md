---
type: regex
target: { source: file, path: main.tf }
pattern: '(?:password|passwd|secret|token|api_?key|access_?key|private_?key|credential)(?![a-z0-9_]*_(?:name|id|ids|arn|path|file|ttl|url|uri|version)\s*=)[a-z0-9_]*\s*=\s*"(?!arn:|https?://|/)[^"$\n]{8,}"|(?:^|[^a-z0-9])(?:pass|pwd)(?![a-z0-9_]*_(?:name|id|ids|arn|path|file|ttl|url|uri|version)\s*=)[a-z0-9_]*\s*=\s*"(?!arn:|https?://|/)[^"$\n]{8,}"|variable\s+"(?![^"\n]*_(?:name|id|ids|arn|path|file|ttl|url|uri|version)")(?:[^"\n]*(?:password|passwd|secret|token|api_?key|access_?key|private_?key|credential|pwd)|(?:[^"\n]*[_-])?pass)[^"\n]*"\s*\{[^}]*?\bdefault\s*=\s*"(?!arn:|https?://|/)[^"$\n]{8,}"|AKIA[0-9A-Z]{16}|-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}'
flags: i
match: not_contains
---
