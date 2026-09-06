"""Which brain this assistant is actually talking to, and how to reach it again.

WHY THIS EXISTS
---------------
Claude Code can be pointed at something other than Anthropic. Ollama publishes
the recipe: three environment variables and a model chosen on the command
line.

    ANTHROPIC_AUTH_TOKEN=ollama
    ANTHROPIC_API_KEY=
    ANTHROPIC_BASE_URL=http://localhost:11434
    claude --model qwen3.5

Both halves of that live somewhere this package could not see. The variables
are set in the terminal the student typed them into, and the model is an
argument to one command. Neither survives into the launcher this package
writes for them, or into the scheduled tasks it installs -- so an assistant set
up by somebody running a local model would, on its own, start up talking to a
service they are not signed in to and fail in a way they could not diagnose.


WHAT IS RECORDED, AND WHAT IS REFUSED
-------------------------------------
The endpoint and the model, because reproducing them is the whole point.

The auth token is recorded ONLY when it is the literal word Ollama documents
(`ollama`), which is not a secret and cannot be used anywhere else. Any other
value is somebody's real credential: the fact that one is needed is recorded,
the value never is, and it is left to come from the environment as before.
Writing a token into a config file that sits in a synced folder is how a key
ends up somewhere it cannot be recalled from.

A CORRECTION THIS FILE EXISTS TO CARRY
--------------------------------------
`launcher.py` said, for a while, that Ollama could not be used at all --
"verified in `claude --help`". The observation was true and the conclusion was
not: `--help` lists the first-party providers, and says nothing about the
environment variable that points the client somewhere else. Checking the right
thing badly reads exactly like checking the right thing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# What Ollama's own documentation tells people to set. The token is a literal,
# not a credential -- it exists because the client requires the header, and
# Ollama ignores its value.
OLLAMA_TOKEN = "ollama"
OLLAMA_DEFAULT_PORT = "11434"


@dataclass
class Backend:
    """Where the model comes from, in a form that can be reproduced."""

    base_url: str = ""
    model: str = ""
    # True when the endpoint needs an Authorization header whose value is a
    # real credential -- recorded as a fact, never as a value.
    needs_token: bool = False
    # The literal token, only ever Ollama's own word.
    token: str = ""

    @property
    def is_local(self) -> bool:
        """Is the model served from this machine rather than over the wire?"""
        return bool(self.base_url) and (
            "localhost" in self.base_url or "127.0.0.1" in self.base_url)

    @property
    def is_ollama(self) -> bool:
        return (self.token == OLLAMA_TOKEN
                or OLLAMA_DEFAULT_PORT in (self.base_url or ""))

    @property
    def is_default(self) -> bool:
        """Nothing was overridden: ordinary Claude Code, signed in as them."""
        return not self.base_url

    def sentence(self) -> str:
        """One line somebody can act on."""
        if self.is_default:
            return "Claude Code, signed in as you"
        where = "on this machine" if self.is_local else self.base_url
        named = f" running {self.model}" if self.model else ""
        if self.is_ollama:
            return f"Ollama {where}{named}"
        return f"a custom endpoint at {self.base_url}{named}"

    def environment(self) -> dict:
        """The variables a fresh process needs to reach the same brain.

        Empty for an ordinary install, which is what makes this safe to apply
        unconditionally: nothing is changed for the people who changed nothing.
        """
        if self.is_default:
            return {}
        settings = {"ANTHROPIC_BASE_URL": self.base_url}
        if self.token:
            settings["ANTHROPIC_AUTH_TOKEN"] = self.token
            # Ollama's own instructions clear this. Left set, the client
            # prefers the key and never reaches the local endpoint.
            settings["ANTHROPIC_API_KEY"] = ""
        return settings

    def arguments(self) -> list[str]:
        """What has to be added to the `claude` command line."""
        return ["--model", self.model] if (self.model and not self.is_default) else []


def detect(environment: dict | None = None) -> Backend:
    """Read the running environment. Changes nothing.

    Called while the student's own session is the one running this, which is
    the only moment the answer is knowable without asking them.
    """
    source = os.environ if environment is None else environment
    base_url = (source.get("ANTHROPIC_BASE_URL") or "").strip()
    if not base_url:
        return Backend()

    token = (source.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    known = token == OLLAMA_TOKEN
    return Backend(
        base_url=base_url,
        model=(source.get("ANTHROPIC_MODEL") or "").strip(),
        needs_token=bool(token) and not known,
        token=token if known else "",
    )


def model_in_use(fallback: str = "") -> str:
    """The model this machine's most recent session actually used.

    Read from the transcript rather than from the environment, because the
    model is chosen with `--model` on the command line and never appears in
    the environment at all. The usage meter already reads this file for the
    same reason.
    """
    try:
        from . import today

        latest = today.read_usage()
        return (latest.model or fallback).strip()
    except Exception:                                     # noqa: BLE001
        return fallback


def describe(environment: dict | None = None) -> Backend:
    """`detect`, with the model filled in from the transcript if need be."""
    found = detect(environment)
    if found.is_default or found.model:
        return found
    found.model = model_in_use()
    return found


def models_available(base_url: str = "") -> tuple[bool, list[str]]:
    """(is it answering, what it is holding) for an Ollama-style endpoint.

    Asked when the launcher is being written, because that is the moment the
    model is chosen. Before this, the model was only ever whatever the
    environment happened to carry, so somebody running two models had no way
    to say which one their assistant should start with.

    One second, like the same call in `optimising`: an endpoint on this
    machine that has not answered in a second is not running, and this is
    asked while a person waits at a prompt.
    """
    import json as _json
    import urllib.error
    import urllib.request

    where = (base_url or stored().base_url or "").rstrip("/")
    if not where:
        return False, []

    try:
        with urllib.request.urlopen(f"{where}/api/tags", timeout=1) as answer:
            data = _json.loads(answer.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return False, []

    found = []
    for one in data.get("models") or []:
        name = (one or {}).get("name") or (one or {}).get("model") or ""
        if name:
            found.append(str(name))
    return True, sorted(found)


def is_cloud_model(name: str) -> bool:
    """Ollama serves its hosted models under the same endpoint, by name.

    So "local or cloud" is not a second setting to store -- it is which name
    was chosen, and the only honest thing to do is say which one it is at the
    moment of choosing. A cloud model needs an Ollama account and is metered;
    a local one is free and runs on the machine.
    """
    return name.strip().endswith("-cloud") or ":cloud" in name


def _record_file():
    from . import paths

    return paths.app_dir() / "state" / "backend.json"


def remember(found: Backend | None = None) -> Backend:
    """Write down which brain this install was set up against.

    Called from setup, while the student's own session is running and the
    answer is still visible. Afterwards it is the only record: a scheduled
    task cannot see the terminal they configured.
    """
    from . import atomic, paths

    found = found or describe()
    paths.ensure_app_dirs()
    atomic.write_json(_record_file(), {
        "base_url": found.base_url,
        "model": found.model,
        "needs_token": found.needs_token,
        # Only ever Ollama's documented literal -- see the module note.
        "token": found.token,
    })
    return found


def stored() -> Backend:
    """What was recorded, or an ordinary install if nothing was.

    Never falls back to reading the environment. A scheduled task inherits
    whatever Task Scheduler happens to hold, and guessing from that would make
    the assistant's brain depend on which process started it -- the failure
    this whole module exists to prevent.
    """
    from . import atomic

    saved = atomic.read_json(_record_file(), default=None)
    if not isinstance(saved, dict):
        return Backend()
    return Backend(
        base_url=str(saved.get("base_url") or ""),
        model=str(saved.get("model") or ""),
        needs_token=bool(saved.get("needs_token")),
        token=str(saved.get("token") or ""),
    )
