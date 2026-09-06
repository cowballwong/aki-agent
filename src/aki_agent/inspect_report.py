"""What is actually loaded in this assistant, right now.

WHY THIS EXISTS (reported 2026-08-26)
-----------------------------------
Aki has skills, channels, calendars, scheduled tasks and connected accounts,
and until now there was no single place that answered "what have I actually
got?". A student finishes the install and cannot tell what they ended up
with; something misbehaves and the first question — is it even loaded? — has
no command behind it.

IT READS THE LIVE REGISTRIES, NOT THE CONFIGURATION FILE
--------------------------------------------------------
This is the whole discipline of the thing, borrowed from the DeepSeek
Harness's own inspect verb. A report built by reading `config.yaml` back can
only ever say what the file asked for. The one failure worth having a command
for is the file asking for something that did not happen — so the providers
come from the registries in this process, the configured list is reported
*beside* them, and anywhere the two disagree is called out rather than
averaged.

IT MUST SURVIVE A BROKEN CONFIGURATION
--------------------------------------
`cli._load_config` now refuses to run a command when the `providers:` block
names something nothing answers to. That is right for every other command and
would be exactly wrong here: the one tool for diagnosing that block cannot be
the one tool the block can switch off. So this loads the configuration itself
and reports the trouble as a finding instead of stopping on it.
"""

from __future__ import annotations

import inspect as _inspect
from typing import Any


def _wants_config(provider) -> bool:
    """Whether this provider's `available()` takes the configuration.

    Asked of the signature rather than discovered by calling and catching
    `TypeError`. Catching would also swallow a `TypeError` raised *inside* a
    provider and report it as "takes no configuration", which is a wrong
    answer dressed as a working one.
    """
    try:
        signature = _inspect.signature(provider.available)
    except (TypeError, ValueError):                       # pragma: no cover
        return False
    return bool(signature.parameters)


def _availability(provider, config=None) -> tuple[bool, str]:
    """Whether a provider is usable, whichever shape it answers in.

    `channels.Channel.available()` returns a bool and takes nothing; a
    calendar returns `(usable, reason)` and needs the configuration to know
    whether any feed is subscribed. That difference is deliberate -- a
    calendar has a sentence worth showing and a channel does not -- and this
    is the one place that has to hold both, which is a fair price for not
    forcing every seam into one protocol.

    THE CONFIGURATION HAS TO BE PASSED ON (found on the Surface, 2026-08-26)
    -----------------------------------------------------------------------
    The first version called `available()` with nothing. `IcsFeeds` takes
    `config=None` and so did not complain -- it simply answered as though
    nothing were subscribed. On the machine it was written on that was true
    and the report looked right. On a machine with two calendar
    subscriptions, the same report said "no calendar subscriptions yet" two
    lines under "calendars 2". A report that contradicts itself is worse than
    no report.
    """
    # NOT EVERY SEAM HAS AN AVAILABILITY (found on the Surface, 2026-08-29)
    # ---------------------------------------------------------------------
    # `guide` providers are documents. There is nothing for one to be
    # connected to, so they have no `available()` -- and the report printed
    # every guide as unusable with the words "'Guide' object has no attribute
    # 'available'" beside it. A report whose own failures look like the thing
    # it is reporting on teaches people to ignore it.
    if not callable(getattr(provider, "available", None)):
        return True, ""

    try:
        if _wants_config(provider):
            answer = provider.available(config)
        else:
            answer = provider.available()
    except Exception as exc:                              # noqa: BLE001
        return False, str(exc)

    if isinstance(answer, tuple):
        usable, reason = (list(answer) + [""])[:2]
        return bool(usable), str(reason or "")
    return bool(answer), ""


def _capabilities(provider) -> list[str]:
    getter = getattr(provider, "capabilities", None)
    if not callable(getter):
        return []
    try:
        return sorted(str(one) for one in getter())
    except Exception:                                     # noqa: BLE001
        return []


def gather(config=None) -> dict[str, Any]:
    """Everything worth reporting, as plain data.

    `config` may be None -- on a machine where the setup interview has not
    run, or where the file will not parse. The report still has to come out,
    because "there is no configuration" is itself the answer somebody needs.
    """
    from . import seams

    seams.load_every_seam()

    report: dict[str, Any] = {"seams": [], "problems": []}

    if config is not None:
        report["problems"] = seams.apply(config)

    for what in seams.known():
        registry = seams.seam(what)
        providers = []
        for provider in registry.registered():
            usable, reason = _availability(provider, config)
            providers.append({
                "name": provider.name,
                "usable": usable,
                "reason": reason,
                "capabilities": _capabilities(provider),
                "loaded": provider.name in registry.names(),
            })
        report["seams"].append({
            "seam": what,
            "providers": providers,
            "configured": (list(registry.chosen())
                           if registry.chosen() is not None else None),
            "switched_off": list(registry.switched_off()),
        })

    report["plugins"] = _plugins()
    report["workflows"] = _workflows()
    report["skills"] = _skills()
    report["scheduled"] = _scheduled()
    report["connections"] = _connections(config)
    report["google"] = _google()
    report["accounts"] = _accounts(config)
    report["config_path"] = (str(getattr(config, "source_path", "") or "")
                             if config is not None else "")
    return report


def _workflows() -> dict[str, Any]:
    """Installed workflows. Read from manifests only — nothing is imported,
    so a broken workflow cannot break `inspect`."""
    try:
        from . import workflows
    except Exception as exc:
        return {"folder": "", "installed": [], "problems": [str(exc)]}
    try:
        return workflows.report()
    except Exception as exc:
        return {"folder": "", "installed": [], "problems": [str(exc)]}


def _plugins() -> dict[str, Any]:
    """Installed third-party plugins, and which ones did not load.

    Reported beside the seams rather than inside them on purpose: a plugin
    that failed to load registers nothing, so it would be invisible in a
    per-seam listing -- and "installed but broken" is exactly the state a
    person needs this command for.
    """
    try:
        from . import plugins

        return plugins.report()
    except Exception as exc:                              # noqa: BLE001
        return {"error": str(exc)}


def _skills() -> dict[str, Any]:
    """Which skills are in the folder Claude Code actually reads.

    The folder matters more than the count. Skills written to
    `~/.aki-agent/skills/` were saved, listed and never loaded, which is a
    failure that looks like success from every angle except this one.
    """
    try:
        from . import library, skills_store

        folder = skills_store.skills_dir()
        installed = sorted(library.active_keys())
        return {
            "folder": str(folder),
            "folder_exists": folder.is_dir(),
            "installed": installed,
            "library_present": library.is_present(),
            "library_size": len(library.catalogue()),
        }
    except Exception as exc:                              # noqa: BLE001
        return {"error": str(exc)}


def _scheduled() -> dict[str, Any]:
    try:
        from . import schedule

        return {"installed": list(schedule.installed_names_or_empty())}
    except Exception as exc:                              # noqa: BLE001
        return {"error": str(exc)}


def _accounts(config) -> list[dict[str, Any]]:
    """Every connection, from the `account` seam, in one flat list.

    `_connections` below answers "what is in the configuration file". This
    answers "what is this assistant actually able to reach, and by what
    route" — which is the question a person asks, and the one that used to
    need four different places to answer.

    Kept beside `_connections` rather than replacing it: that key has callers,
    and a report is the wrong place to be clever.
    """
    try:
        from . import accounts
        return [
            {
                "service": c.service,
                "provider": c.provider,
                "kind": c.kind,
                "connected": c.connected,
                "detail": c.detail,
                "next_step": c.next_step,
            }
            for c in accounts.every(config)
        ]
    except Exception:                                     # noqa: BLE001
        return []


def _connections(config) -> dict[str, Any]:
    """Accounts by name only. Never a secret, and never a whole address.

    Anything printed here lands in a session transcript, which is written to
    disk and read back by a model later. `tools` already refuses to print a
    key for that reason; the same rule applies to anything else identifying.
    """
    if config is None:
        return {"mail": [], "calendars": [], "services": []}
    try:
        connections = config.connections
        return {
            "mail": [one.label or one.address.split("@")[-1]
                     for one in connections.mail],
            "calendars": [one.name for one in connections.calendars],
            "services": sorted({one.tool for one in
                                getattr(connections, "apis", ())}),
        }
    except Exception:                                     # noqa: BLE001
        return {"mail": [], "calendars": [], "services": []}


def _google() -> list[dict[str, Any]]:
    """Which Google permissions this machine currently holds.

    `inspect` answers "what else can it reach", and until 2026-08-29 there was
    one Google permission so it never appeared anywhere. There are three now,
    granted separately, and a person cannot be expected to remember which of
    them they said yes to months ago.

    The scope is printed in full on purpose: "connected to Google" is not an
    answer to what it can do, and the whole point of granting them separately
    is that the difference matters.

    No address, here as everywhere in this report -- it lands in a transcript.
    """
    try:
        from .connectors import google_account
    except Exception:                                     # noqa: BLE001
        return []

    found = []
    for one in google_account.SERVICES.values():
        try:
            live = google_account.connected(one)
        except Exception:                                 # noqa: BLE001
            # A credential store that will not answer is not a "no" -- see
            # `secrets.store_unavailable`. Reported as unknown, not as off.
            found.append({"service": one.key, "label": one.label,
                          "connected": None, "scope": one.scope})
            continue
        found.append({"service": one.key, "label": one.label,
                      "connected": live, "scope": one.scope})
    return found


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(report: dict[str, Any]) -> str:
    """The report as a person reads it."""
    lines: list[str] = ["What is loaded right now", ""]

    for entry in report.get("seams", []):
        configured = entry["configured"]
        heading = f"{entry['seam'].title()}s"
        if configured is not None:
            heading += f"  — configuration asks for: {', '.join(configured) or 'nothing'}"
        lines.append(heading)
        if not entry["providers"]:
            lines.append("  nothing registered")
        for provider in entry["providers"]:
            if not provider["loaded"]:
                # Installed and switched off is a state worth naming. Leaving
                # it out of the list would make the software look like it does
                # not have something it is carrying.
                state = "switched off by your configuration"
            elif provider["usable"]:
                state = "ready"
            else:
                state = provider["reason"] or "not usable"
            can = (f"  [{', '.join(provider['capabilities'])}]"
                   if provider["capabilities"] else "")
            lines.append(f"  {provider['name']:<11} {state}{can}")
        lines.append("")

    installed = report.get("plugins") or {}
    if installed.get("error"):
        lines.append(f"Plugins     could not be read — {installed['error']}")
    else:
        entries = installed.get("installed") or []
        lines.append(f"Plugins     {len(entries)} installed"
                     + (f" in {installed.get('folder', '')}" if entries
                        else ""))
        for one in entries:
            label = one["name"] + (f" {one['version']}" if one["version"]
                                   else "")
            if one["problem"]:
                lines.append(f"              ! {label} — {one['problem']}")
            elif one["registered"]:
                lines.append(f"              {label} → "
                             f"{', '.join(one['registered'])}")
            else:
                lines.append(f"              {label} — loaded, added nothing")
        for problem in (installed.get("problems") or []):
            if not any(problem.startswith(one["name"] + ":")
                       for one in entries):
                lines.append(f"              ! {problem}")

    skills = report.get("skills") or {}
    if skills.get("error"):
        lines.append(f"Skills      could not be read — {skills['error']}")
    else:
        count = len(skills.get("installed") or [])
        lines.append(f"Skills      {count} in {skills.get('folder', '')}")
        if not skills.get("library_present"):
            lines.append("            the shipped library is missing — "
                         "run doctor")
        elif skills.get("library_size"):
            lines.append(f"            {skills['library_size']} more "
                         "available in the library")
        for name in (skills.get("installed") or []):
            lines.append(f"              {name}")

    scheduled = report.get("scheduled") or {}
    if scheduled.get("error"):
        lines.append(f"Scheduled   could not be read — {scheduled['error']}")
    else:
        names = scheduled.get("installed") or []
        lines.append(f"Scheduled   {len(names)} installed"
                     + (f": {', '.join(names)}" if names else ""))

    connections = report.get("connections") or {}
    lines.append("Connected   "
                 f"mail {len(connections.get('mail') or [])}"
                 f" · calendars {len(connections.get('calendars') or [])}"
                 f" · services {len(connections.get('services') or [])}")

    google = report.get("google") or []
    if google:
        signed_in = [one for one in google if one.get("connected")]
        lines.append("")
        lines.append(f"Google      {len(signed_in)} of {len(google)} "
                     "permissions granted")
        for one in google:
            if one.get("connected") is None:
                mark, tail = "?", "could not be read"
            elif one.get("connected"):
                mark, tail = "✓", one.get("scope", "")
            else:
                mark, tail = "·", "not connected"
            lines.append(f"  {mark} {one['label']:<28} {tail}".rstrip())

    entries = report.get("accounts") or []
    if entries:
        live = sum(1 for e in entries if e.get("connected"))
        lines.append("")
        lines.append(f"Accounts    {live} of {len(entries)} connected")
        for entry in entries:
            mark = "✓" if entry.get("connected") else "·"
            tail = entry.get("detail") or ""
            if not entry.get("connected") and entry.get("next_step"):
                tail = entry["next_step"]
            lines.append(f"  {mark} {entry['service']:<28} "
                         f"{entry['kind']:<13} {tail}".rstrip())
        lines.append("")

    if report.get("config_path"):
        lines.append(f"Config      {report['config_path']}")

    problems = report.get("problems") or []
    if problems:
        lines.append("")
        lines.append("Problems with your configuration")
        for problem in problems:
            lines.append(f"  ! {problem}")

    return "\n".join(lines).rstrip() + "\n"
