"""One answer to "what have you actually got?".

WHY THIS EXISTS
---------------
A user asked their assistant, from a messaging app, "what specialists do you
have?" and was told there were none — that only the main assistant existed. Both halves were
wrong. The built-in checker has been there since installation, the package
ships ten specialists in the library, and `cli specialists` prints all of it
correctly.

The command was never the problem. Nothing the assistant reads had ever
mentioned it. `agents/assistant.md` taught it how to *create* a specialist and
how to *run* the checker, and stopped. So a question about what exists was
answered from the model's own imagination, and it invented four plausible
names.

That failure is not specific to specialists. Skills, knowledge and the library
had the same shape: a store, a dashboard page, and no route from a question in
a conversation to the thing that knows the answer. Two of them did not even
have a command.

WHY ONE COMMAND AND NOT FIVE
----------------------------
Because the assistant has to remember it under pressure, mid-conversation,
while doing something else. Five commands means five chances to recall the
wrong one or none. "What do you have" is a single question from the user's
side, so it gets a single answer here, and `agents/assistant.md` can carry one
rule instead of five.

It is also why this prints prose rather than JSON. The output is going to be
relayed to a person, often translated, and a model reading a table of plain
sentences reproduces them more faithfully than it reformats a data structure.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
Nothing is counted that has not been looked at. If a store cannot be read, the
section says so rather than reporting zero — "you have no specialists" and "I
could not open the specialists file" send a person to completely different
places, and only one of them is ever true at a time.
"""

from __future__ import annotations


def _safe(call, fallback):
    """Run a store read, and turn a failure into a sentence rather than a zero.

    Every store here lives in a file that can be missing, half-written or owned
    by a different user. A raised exception would lose the whole report; a
    swallowed one would report an empty inventory, which reads as fact.
    """
    try:
        return call(), ""
    except Exception as problem:                          # noqa: BLE001
        return fallback, f"(could not be read: {problem})"


def _specialists() -> list[str]:
    from . import sentinel, specialists

    out: list[str] = []
    state = "on"
    try:
        state = "on" if sentinel.is_on() else "off"
        built = sentinel.agent().describe()
    except Exception as problem:                          # noqa: BLE001
        out.append(f"  the built-in checker could not be read: {problem}")
        built = ""
    if built:
        out.append(f"  {sentinel.KEY} — {built} [{state}, built in]")

    own, trouble = _safe(specialists.read_all, [])
    if trouble:
        out.append(f"  your own specialists {trouble}")
    elif not own:
        out.append("  none of your own yet")
    else:
        for one in own:
            out.append(f"  {one.key} — {one.describe()}")
    return out


def _library_specialists() -> list[str]:
    """What is shipped but not switched on — the answer to "can I have one?".

    Listed separately and never mixed in with the ones that exist, because a
    specialist that is available and one that is ready to be given work are
    different answers to the question being asked.
    """
    from . import library

    if not library.is_present():
        return ["  the shipped library is not installed on this machine"]
    items, trouble = _safe(library.catalogue, [])
    if trouble:
        return [f"  the library {trouble}"]
    active, _ = _safe(library.active_keys, set())
    spare = [one for one in items
             if one.kind == "specialist" and one.key not in active]
    if not spare:
        return ["  everything the library ships is already switched on"]
    return [f"  {one.key} — {one.name}: {one.description}" for one in spare]


def _skills() -> list[str]:
    from . import skills_store

    found, trouble = _safe(skills_store.read_all, [])
    if trouble:
        return [f"  your skills {trouble}"]
    if not found:
        return ["  none yet"]
    return [f"  {one.key} — {one.description or one.name}" for one in found]


def _knowledge() -> list[str]:
    from . import knowledge

    found, trouble = _safe(knowledge.read_all, [])
    if trouble:
        return [f"  your knowledge {trouble}"]
    if not found:
        return ["  none yet"]
    out = []
    for one in found:
        tags = ", ".join(getattr(one, "tags", ()) or ())
        line = f"  {one.key} — {one.title}"
        if getattr(one, "target", ""):
            line += f"  <{one.target}>"
        if tags:
            line += f"  [{tags}]"
        out.append(line)
    return out


def report() -> str:
    """Everything the assistant has, in the order a person asks about it."""
    blocks: list[tuple[str, list[str]]] = [
        ("SPECIALISTS you can send work to right now", _specialists()),
        ("SPECIALISTS the library ships, not switched on "
         "(turn one on with: cli library --on <key>)", _library_specialists()),
        ("SKILLS installed", _skills()),
        ("KNOWLEDGE you have been given", _knowledge()),
    ]
    lines: list[str] = []
    for title, body in blocks:
        lines.append(title)
        lines.extend(body or ["  none"])
        lines.append("")
    lines.append("Outside services are listed separately: cli tools")
    return "\n".join(lines)
