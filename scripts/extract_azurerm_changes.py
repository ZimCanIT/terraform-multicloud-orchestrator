"""Extract the names that an azurerm upgrade guide removes or renames into JSON. Names only, no prose.

Usage: extract_azurerm_changes.py GUIDE.md OUT.json [RELEASE_TAG]

GUIDE.md is website/docs/guides/5.0-upgrade-guide.html.markdown from hashicorp/terraform-provider-azurerm.
The output feeds the skill's audit script (scripts/tf_audit.py in the skill directory).
"""

import collections
import datetime
import json
import re
import sys

if len(sys.argv) < 3:
    raise SystemExit(__doc__)
guide_path, out_path = sys.argv[1], sys.argv[2]
release_tag = sys.argv[3] if len(sys.argv) > 3 else "unknown"
lines = open(guide_path, encoding="utf-8").read().split("\n")
h2 = [(i, m.group(1)) for i, line in enumerate(lines) if (m := re.match(r"^## (.+)$", line))]
bounds = {name: (start, h2[k + 1][0] if k + 1 < len(h2) else len(lines)) for k, (start, name) in enumerate(h2)}
TICK = re.compile(r"`([^`]+)`")


def sections(name):
    start, end = bounds[name]
    current, out = None, collections.OrderedDict()
    for line in lines[start:end]:
        m = re.match(r"^### `([^`]+)`", line)
        if m:
            current = m.group(1)
            out[current] = []
        elif current and line.strip().startswith("*"):
            out[current].append(line.strip()[1:].strip())
    return out


def removed(name):
    result = {}
    for resource, bullets in sections(name).items():
        text = " ".join(bullets)
        after = text.split("superseded by", 1)[1] if "superseded by" in text else ""
        result[resource] = [t for t in TICK.findall(after) if t.startswith("azurerm_")]
    return result


PATTERNS = [
    ("renamed", re.compile(r"(?:has|have) been (?:removed|deprecated) in favou?r of|(?:has|have) been renamed to|(?:has|have) been (?:removed and )?superseded by|(?:has|have) been replaced (?:by|with)")),
    ("removed", re.compile(r"(?:has|have) been removed|(?:is|are) no longer supported")),
    ("values", re.compile(r"no longer accepts?")),
    ("required", re.compile(r"(?:is|are) now [Rr]equired")),
]
# A subject is an argument path such as `site_config.ftps_state`. Values such as `Paid` are not.
ARGUMENT_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
stats = collections.Counter()


def changes(name):
    result = collections.OrderedDict()
    for resource, bullets in sections(name).items():
        entries = []
        for bullet in bullets:
            kind, match = "other", None
            for candidate, pattern in PATTERNS:
                match = pattern.search(bullet)
                if match:
                    kind = candidate
                    break
            stats[kind] += 1
            if not match:
                continue
            subjects = [subject for subject in TICK.findall(bullet[: match.start()]) if ARGUMENT_PATH.match(subject)]
            objects = TICK.findall(bullet[match.end():])
            for subject in subjects:
                entry = {"kind": kind, "path": subject}
                if kind == "renamed" and objects:
                    entry["use"] = objects[0]
                elif kind == "values":
                    entry["values"] = objects
                entries.append(entry)
            # "X is now Required" often follows a rename in the same bullet list; nothing else to keep.
        if entries:
            result[resource] = entries
    return result


data = {
    "source": f"hashicorp/terraform-provider-azurerm, website/docs/guides/5.0-upgrade-guide.html.markdown, tag {release_tag}",
    "extracted": datetime.date.today().isoformat(),
    "note": "Names only. Read the guide for the wording and for changes this file does not classify.",
    "removed_resources": removed("Removed Resources"),
    "removed_data_sources": removed("Removed Data Sources"),
    "resources": changes("Breaking Changes in Resources"),
    "data_sources": changes("Breaking Changes in Data Sources"),
}
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=1, sort_keys=False)
    handle.write("\n")
print("bullets by kind:", dict(stats))
print("removed resources:", len(data["removed_resources"]), "data sources:", len(data["removed_data_sources"]))
print("resources with entries:", len(data["resources"]), "data sources with entries:", len(data["data_sources"]))
