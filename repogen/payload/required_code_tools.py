#!/usr/bin/env python3
"""Views of what the instance's test really executed, for the required-code
agent. Staged next to evidence.json and trace.log inside the container.

  tools.py functions                 executed repository functions, by call distance
  tools.py executed FILE [START END] source with the executed lines marked
  tools.py trace                     summary of the traced target function
  tools.py check OUTPUT.json         validate the answer file before finishing
"""

import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as _handle:
        _CONFIG = json.load(_handle)
except (OSError, ValueError):
    _CONFIG = {}
ROOT = str(_CONFIG.get("root") or "/testbed").rstrip("/")
QA_DIR = str(_CONFIG.get("qa_dir") or "")
try:
    with open(str(_CONFIG.get("testcase") or ""), encoding="utf-8", errors="replace") as _handle:
        TESTCASE = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", _handle.read()))
except OSError:
    TESTCASE = set()
ROLES = ("target", "callee", "data", "configuration", "other")
NECESSITY = ("essential", "supporting")
VERIFIED = ("executed", "trace", "read")
EVENT_RE = re.compile(
    r"^(?:\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ )?(\S+?):(\d+) (\S+) "
    r"event=(call|line|return|exception)(.*)$"
)


def load_evidence():
    with open(os.path.join(HERE, "evidence.json"), encoding="utf-8") as handle:
        return json.load(handle)


def relative(path):
    path = path.replace("\\", "/")
    if path.startswith(ROOT + "/"):
        path = path[len(ROOT) + 1:]
    while path.startswith("./"):
        path = path[2:]
    return path


def where(depth):
    if depth < 0:
        return "outside the target"
    return "target" if depth == 0 else "depth %d" % depth


def cmd_functions(_args):
    evidence = load_evidence()
    rows = []
    for name, functions in evidence["files"].items():
        if QA_DIR and name.startswith(QA_DIR + "/"):
            continue
        for function in functions:
            depth = function["depth"]
            rows.append((depth if depth >= 0 else 10 ** 6, name, function))
    rows.sort(key=lambda row: (row[0], row[1], row[2]["first_line"]))
    print("%-20s %-38s %-7s %s" % ("where", "file", "lines", "function (executed line span)"))
    for _, name, function in rows:
        lines = function["lines"]
        print("%-20s %-38s %-7d %s (%d-%d)" % (
            where(function["depth"]), name, len(lines), function["function"],
            function["first_line"], max(lines),
        ))
    print("\n%d executed repository functions. 'outside the target' code ran during the "
          "test but not within a call to the traced target; it may still build the "
          "target's inputs." % len(rows))


def cmd_executed(args):
    if not args:
        sys.exit("usage: tools.py executed FILE [START END]")
    name = relative(args[0])
    evidence = load_evidence()
    ran = {}
    for function in evidence["files"].get(name, []):
        for line in function["lines"]:
            ran[line] = function
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        sys.exit("no such repository file: %s" % name)
    with open(path, encoding="utf-8", errors="replace") as handle:
        source = handle.read().splitlines()
    start = int(args[1]) if len(args) > 1 else 1
    end = min(int(args[2]) if len(args) > 2 else len(source), len(source))
    print("%s lines %d-%d   '>' marks a line that executed" % (name, start, end))
    for number in range(max(1, start), end + 1):
        print("%s %5d  %s" % (">" if number in ran else " ", number, source[number - 1]))
    hit = sum(1 for number in range(start, end + 1) if number in ran)
    print("\n%d of %d lines in this range executed" % (hit, end - start + 1))


def cmd_trace(_args):
    path = os.path.join(HERE, "trace.log")
    if not os.path.isfile(path):
        sys.exit("no trace.log for this instance")
    calls, returns, hits, raised = Counter(), Counter(), Counter(), Counter()
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            match = EVENT_RE.match(raw)
            if not match:
                continue
            file, line, func, event, tail = match.groups()
            if event == "call":
                calls[(func, int(line))] += 1
            elif event == "return":
                returns[func] += 1
            elif event == "line":
                hits[(relative(file), int(line))] += 1
            else:
                kind = tail.partition(" exc=")[2].partition(":")[0].strip()
                raised[(func, int(line), kind)] += 1
    print("Call events (function, line where the frame was entered):")
    for (func, line), count in sorted(calls.items()):
        print("  %6d  %s  at line %d" % (count, func, line))
    print("  A generator or coroutine is entered again at its yield/await line on "
          "every resumption.")
    print("\nException events seen inside traced frames:")
    for (func, line, kind), count in sorted(raised.items()):
        print("  %6d  %s  at %s:%d" % (count, kind, func, line))
    if not raised:
        print("  none")
    print("\nLine events (times each line was reported):")
    for (file, line), count in sorted(hits.items()):
        print("  %6d  %s:%d" % (count, file, line))


def cmd_check(args):
    if not args:
        sys.exit("usage: tools.py check OUTPUT.json")
    try:
        with open(args[0], encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.exit("ERROR: cannot read %s as JSON: %s" % (args[0], exc))
    errors, warnings = [], []
    entries = data.get("required") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        sys.exit("ERROR: the object needs a non-empty 'required' list")

    evidence = load_evidence()
    ran, depth_of = {}, {}
    for name, functions in evidence["files"].items():
        for function in functions:
            for line in function["lines"]:
                ran.setdefault(name, set()).add(line)
                depth_of[(name, line)] = function["depth"]

    covered = {}
    for index, item in enumerate(entries):
        tag = "required[%d]" % index
        if not isinstance(item, dict):
            errors.append("%s: not an object" % tag)
            continue
        name = relative(str(item.get("file") or ""))
        start, end = item.get("start_line"), item.get("end_line")
        if not name or not isinstance(start, int) or not isinstance(end, int):
            errors.append("%s: needs file, start_line and end_line (integers)" % tag)
            continue
        path = os.path.join(ROOT, name)
        if QA_DIR and name.startswith(QA_DIR + "/"):
            errors.append("%s: %s is an instance file, which the solver is given" % (tag, name))
            continue
        if not os.path.isfile(path):
            errors.append("%s: no such repository file %s" % (tag, name))
            continue
        with open(path, "rb") as handle:
            total = sum(1 for _ in handle)
        if start < 1 or end < start or end > total:
            errors.append("%s: range %s-%s is invalid for %s (%d lines)"
                          % (tag, start, end, name, total))
            continue
        for field, allowed in (("role", ROLES), ("necessity", NECESSITY), ("verified", VERIFIED)):
            if str(item.get(field) or "").strip().lower() not in allowed:
                errors.append("%s: %s must be one of %s" % (tag, field, ", ".join(allowed)))
        if not str(item.get("reason") or "").strip():
            errors.append("%s: reason is empty" % tag)

        span = set(range(start, end + 1))
        hit = span & ran.get(name, set())
        essential = str(item.get("necessity") or "").strip().lower() == "essential"
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read().splitlines()
        first = source[start - 1].strip()
        if first.startswith("@"):
            warnings.append("%s %s:%d: starts at a decorator; start at the def line unless "
                            "the decorator changes behaviour the answer depends on"
                            % (tag, name, start))
        if essential and end - start < 3 and TESTCASE:
            words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", " ".join(source[start - 1:end])))
            shared = sorted(word for word in words if word in TESTCASE)[:4]
            if shared:
                warnings.append("%s %s:%d-%d: a short essential entry whose names also appear "
                                "in the testcase (%s); if the testcase already gives the "
                                "value, it is not essential"
                                % (tag, name, start, end, ", ".join(shared)))
        previous = covered.setdefault(name, set())
        if span & previous:
            warnings.append("%s: overlaps an earlier entry in %s" % (tag, name))
        previous |= span
        label = "%s %s:%d-%d" % (tag, name, start, end)
        if not hit:
            if str(item.get("role") or "").lower() not in ("data", "configuration"):
                warnings.append("%s: no line in this range executed; if that is intended, "
                                "the role should be data or configuration" % label)
        else:
            # Longest stretch of consecutive lines that did not run.
            longest = run = 0
            for number in range(start, end + 1):
                run = 0 if number in hit else run + 1
                longest = max(longest, run)
            if longest >= 15:
                warnings.append("%s: contains %d consecutive lines that did not execute; "
                                "split the range unless the reader needs them"
                                % (label, longest))
        print("  %-60s %3d lines, %3d executed" % (label[:60], len(span), len(hit)))

    target = {key for key, depth in depth_of.items() if depth == 0}
    missed = sorted(line for name, line in target if line not in covered.get(name, set()))
    if missed:
        warnings.append("%d executed lines of the traced target are in no entry (first: %s)"
                        % (len(missed), missed[:5]))
    if str(data.get("confidence") or "").strip().lower() not in ("high", "medium", "low"):
        errors.append("confidence must be high, medium or low")

    for message in errors:
        print("ERROR   " + message)
    for message in warnings:
        print("WARNING " + message)
    if errors:
        sys.exit("\n%d error(s): fix them and run the check again" % len(errors))
    print("\nOK: %d entries, %d warning(s). Resolve each warning or explain it in 'notes'."
          % (len(entries), len(warnings)))


COMMANDS = {"functions": cmd_functions, "executed": cmd_executed,
            "trace": cmd_trace, "check": cmd_check}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](sys.argv[2:])
