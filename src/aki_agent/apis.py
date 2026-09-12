"""External tools the assistant can be given keys for.

WHY THIS EXISTS WHEN THE PACKAGE PROMISES "NO API KEYS"
-------------------------------------------------------
The promise stands and is not weakened here: the assistant works with no key
at all. Email is an app password over IMAP, calendars are subscription
addresses, files are folders. Nothing on this page is needed to make the thing
run, and a user who never opens it loses nothing they were promised.

What the promise was protecting against was *being made to* register a
developer account before the software would do anything. It was never an
argument that outside services are bad. Someone who already pays for one and
wants pictures, or a voice, or a web search, was previously stuck: there was no
place to put the key, so a finished capability sat unreachable behind a missing
text box.

So: optional, off by default, and everything here reports plainly whether it is
set up rather than implying it.

TWO SEPARATE THINGS, DELIBERATELY
---------------------------------
1. THE KEY, which is a secret and goes to the operating system's credential
   store under `api:{tool}`. It is never written into the config file, never
   pre-filled into a form, and never sent back to the browser.

2. WHAT IT IS FOR, which is not a secret and goes in the config. A key with no
   declared job is inert on purpose — pasting a key must not silently enlist a
   paid service into work the user did not ask for.

That split is why the page can be honest. "Key saved" and "used for pictures"
are different claims, and a user is told both separately.

WHY A JOB RESOLVES TO EXACTLY ONE TOOL
--------------------------------------
Two tools can both make pictures. If both are simply "enabled", every caller
has to guess, and two callers will guess differently — which shows up much
later as one skill using the expensive service and another using the free one,
with nobody having chosen either.

So `for_job` answers with one tool or with nothing, and the answer is decided
by list order, which the user changes with one button. One mechanism, visible
on the page, no hidden precedence table.

THE CATALOGUE IS A CONVENIENCE, NOT A GATE
------------------------------------------
The listed services are there so nobody has to remember which environment
variable a library reads. A tool that is not listed can still be added by name,
and it works the same way. A catalogue that refuses the service you actually
pay for is worse than no catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from . import secrets as secrets_module

# ---------------------------------------------------------------------------
# The jobs a key can be given
# ---------------------------------------------------------------------------
#
# Named for what the user wants done, not for the industry term. "Text to
# speech" is a category name; "read something aloud" is a thing a person wants.
# The short key is what the config stores and what code asks for.


@dataclass(frozen=True)
class Job:
    key: str
    label: str
    help: str


JOBS: tuple[Job, ...] = (
    Job("image", "Make pictures",
        "Draw or generate an image from a description."),
    Job("edit_image", "Change a picture",
        "Alter an image that already exists, rather than starting from "
        "nothing."),
    Job("speech", "Read things aloud",
        "Turn written words into an audio file with a voice."),
    Job("transcribe", "Write down recordings",
        "Turn a voice note, meeting recording or video into text."),
    Job("video", "Make short video",
        "Generate a short clip. Slow and expensive everywhere — worth "
        "knowing before it is switched on."),
    Job("music", "Make music",
        "Generate a backing track or a piece of music."),
    Job("search", "Search the web",
        "Look things up live, rather than relying on what was known at "
        "training time."),
)

JOB_KEYS: tuple[str, ...] = tuple(job.key for job in JOBS)


def job(key: str) -> Job | None:
    for entry in JOBS:
        if entry.key == key:
            return entry
    return None


def job_label(key: str) -> str:
    """A job's name in words, falling back to the raw key.

    Falling back rather than raising matters: a config carried over from a
    later version naming a job this build has never heard of should render as
    itself on the page, not take the page down.
    """
    found = job(key)
    return found.label if found else key


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    """One external service, and the honest facts about it.

    `env_name` is the environment variable the service's own libraries and
    command-line tools read. Storing it means a skill can hand the key to
    something else without every skill hardcoding the spelling — and the
    spellings are genuinely inconsistent between vendors, which is exactly the
    kind of detail a user should never have to carry.
    """

    key: str
    name: str
    jobs: tuple[str, ...]
    env_name: str
    key_url: str
    # Anything true and useful that is not a price. Prices and free-tier limits
    # change monthly; a number written here would be wrong within a quarter and
    # would be believed anyway.
    note: str = ""


CATALOGUE: tuple[Tool, ...] = (
    Tool("gemini", "Google Gemini", ("image", "edit_image", "video", "speech"),
         "GEMINI_API_KEY", "https://aistudio.google.com/apikey",
         "Has a free tier, so it is usually the cheapest place to start for "
         "pictures."),
    Tool("openai", "OpenAI", ("image", "edit_image", "speech", "transcribe"),
         "OPENAI_API_KEY", "https://platform.openai.com/api-keys",
         "Pay as you go. The same key covers pictures, voice and "
         "transcription."),
    Tool("elevenlabs", "ElevenLabs", ("speech", "transcribe", "music"),
         "ELEVENLABS_API_KEY",
         "https://elevenlabs.io/app/settings/api-keys",
         "The strongest voices, including cloning your own. Free tier is "
         "small but enough to hear whether you like it."),
    Tool("minimax", "MiniMax", ("speech", "video", "music"),
         "MINIMAX_API_KEY", "https://platform.minimaxi.com",
         "Good Cantonese and Mandarin voices, which most Western services "
         "handle badly."),
    Tool("replicate", "Replicate",
         ("image", "edit_image", "video", "speech", "transcribe", "music"),
         "REPLICATE_API_TOKEN", "https://replicate.com/account/api-tokens",
         "One key, many models. Useful when you want to try something "
         "unusual without opening another account."),
    Tool("fal", "fal.ai", ("image", "edit_image", "video", "speech",
                           "transcribe"),
         "FAL_KEY", "https://fal.ai/dashboard/keys",
         "Same idea as Replicate, generally faster."),
    Tool("stability", "Stability AI", ("image", "edit_image", "video"),
         "STABILITY_API_KEY", "https://platform.stability.ai/account/keys"),
    Tool("bfl", "Black Forest Labs (FLUX)", ("image", "edit_image"),
         "BFL_API_KEY", "https://api.bfl.ai",
         "FLUX models. Strong at text inside an image, which most others "
         "get wrong."),
    Tool("deepgram", "Deepgram", ("transcribe", "speech"),
         "DEEPGRAM_API_KEY", "https://console.deepgram.com",
         "Built for long recordings and speaker labelling."),
    Tool("assemblyai", "AssemblyAI", ("transcribe",),
         "ASSEMBLYAI_API_KEY", "https://www.assemblyai.com/dashboard",
         "Transcription with summaries and chapters built in."),
    Tool("runway", "Runway", ("video",),
         "RUNWAYML_API_SECRET", "https://dev.runwayml.com"),
    Tool("luma", "Luma", ("video",),
         "LUMAAI_API_KEY", "https://lumalabs.ai/api/keys"),
    Tool("tavily", "Tavily", ("search",),
         "TAVILY_API_KEY", "https://app.tavily.com",
         "Search built for assistants: returns readable text rather than a "
         "page of links. Free tier is generous."),
    Tool("brave", "Brave Search", ("search",),
         "BRAVE_API_KEY", "https://api-dashboard.search.brave.com",
         "An independent index with a free tier."),
    Tool("serpapi", "SerpAPI", ("search",),
         "SERPAPI_API_KEY", "https://serpapi.com/manage-api-key",
         "Reads the real Google results page, including maps and hotels."),
)


def catalogue() -> tuple[Tool, ...]:
    return CATALOGUE


def tool(key: str) -> Tool | None:
    for entry in CATALOGUE:
        if entry.key == key:
            return entry
    return None


def tools_for_job(job_key: str) -> tuple[Tool, ...]:
    """Every listed service that can do this job.

    What the "which service" dropdown is built from.
    """
    return tuple(entry for entry in CATALOGUE if job_key in entry.jobs)


def normalise(raw: str) -> str:
    """A user-typed service name turned into a stable key.

    Custom entries are keyed the same way as catalogue ones so that everything
    downstream — the secret name, the config, the lookup — has one shape.
    """
    cleaned = "".join(
        character if character.isalnum() else "_"
        for character in (raw or "").strip().lower()
    )
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


# ---------------------------------------------------------------------------
# The key itself
# ---------------------------------------------------------------------------


def secret_name(tool_key: str) -> str:
    """Where this tool's key lives in the credential store.

    One namespace, `api:`, so a key can be found and removed by hand by
    someone who wants to check — which is a fair thing to want.
    """
    return f"api:{tool_key}"


def has_key(tool_key: str) -> bool:
    """Is a key stored? Reports existence only, never the value."""
    return bool(secrets_module.get_secret(secret_name(tool_key)))


def save_key(tool_key: str, value: str) -> str:
    """Store a key. Returns where it went, in words, for telling the user."""
    if not tool_key:
        raise ValueError("which service the key is for is missing")
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("no key was given")
    return secrets_module.set_secret(secret_name(tool_key), cleaned)


def forget_key(tool_key: str) -> bool:
    return secrets_module.delete_secret(secret_name(tool_key))


# ---------------------------------------------------------------------------
# What is set up, and what will actually be used
# ---------------------------------------------------------------------------


@dataclass
class Resolution:
    """The answer to "who does this job, and what do I call it with?"."""

    tool_key: str
    name: str
    env_name: str
    key: str


def entries(config) -> tuple:
    """The saved tool entries from a config, tolerating an older one.

    An older config has no `apis` at all. Reading through `getattr` rather
    than assuming the attribute means this module can be called from anywhere
    without every caller first checking which version of the config it has.
    """
    connections = getattr(config, "connections", None)
    return tuple(getattr(connections, "apis", ()) or ())


def display_name(entry) -> str:
    """What to call this entry on screen."""
    known = tool(entry.tool)
    if known:
        return known.name
    return entry.label or entry.tool


def available_jobs(entry) -> tuple[str, ...]:
    """Which jobs this entry may be given.

    A catalogue tool is limited to what it can actually do — offering
    "transcribe" for a service that only draws pictures produces a setting
    that looks configured and fails at the moment of use. A custom tool is not
    second-guessed: the user knows what they bought.
    """
    known = tool(entry.tool)
    return known.jobs if known else JOB_KEYS


def env_name_for(entry) -> str:
    known = tool(entry.tool)
    if known:
        return known.env_name
    return (entry.env_name
            or (normalise(entry.tool).upper() + "_API_KEY"))


def listing(config) -> list[dict]:
    """Every saved tool, as plain data for the page.

    Deliberately carries `has_key` and never the key. A template that is
    handed a secret is a secret in the browser's memory, its autofill store
    and possibly its crash report.
    """
    rows = []
    for entry in entries(config):
        rows.append({
            "tool": entry.tool,
            "name": display_name(entry),
            "has_key": has_key(entry.tool),
            # Which store actually holds it. Carried alongside `has_key`
            # because "no key" and "a key this process cannot see" send the
            # user to two different places, and only one of them is "go and
            # get a key". Still never the value.
            "key_where": secrets_module.where_is(secret_name(entry.tool)),
            "jobs": tuple(entry.jobs),
            "job_labels": tuple(job_label(one) for one in entry.jobs),
            "available_jobs": available_jobs(entry),
            "env_name": env_name_for(entry),
            "enabled": entry.enabled,
            "known": tool(entry.tool) is not None,
            "key_url": (tool(entry.tool).key_url if tool(entry.tool)
                        else ""),
        })
    return rows


def for_job(config, job_key: str) -> Resolution | None:
    """Which tool does this job, or None.

    None is a perfectly good answer and callers must handle it: no key set up
    is the normal state of this package, not an error condition.

    Requires all three things to be true at once — switched on, given this
    job, and holding a key. Any one missing and the honest answer is that the
    job cannot be done, rather than a failure at the moment of use.
    """
    for entry in entries(config):
        if not entry.enabled or job_key not in entry.jobs:
            continue
        key = secrets_module.get_secret(secret_name(entry.tool))
        if not key:
            continue
        return Resolution(tool_key=entry.tool, name=display_name(entry),
                          env_name=env_name_for(entry), key=key)
    return None


def can(config, job_key: str) -> bool:
    """Whether the job is possible at all, without fetching the key."""
    return for_job(config, job_key) is not None


def jobs_overview(config) -> list[dict]:
    """Job by job: who does it, who else could, who is only half set up.

    This is the panel that stops the page from lying. A key with no job, and a
    job with a chosen tool whose key was never saved, both look like progress
    on a plain list of services and are both non-functional.
    """
    overview = []
    for entry in JOBS:
        claiming = [one for one in entries(config)
                    if entry.key in one.jobs and one.enabled]
        with_key = [one for one in claiming if has_key(one.tool)]
        chosen = with_key[0] if with_key else None
        overview.append({
            "job": entry.key,
            "label": entry.label,
            "help": entry.help,
            "chosen": display_name(chosen) if chosen else "",
            "chosen_tool": chosen.tool if chosen else "",
            "others": [{"tool": one.tool, "name": display_name(one)}
                       for one in with_key[1:]],
            # Named as the problem rather than as a state: "chosen but no key"
            # is the thing the user has to fix.
            "waiting_for_key": [display_name(one) for one in claiming
                                if not has_key(one.tool)],
        })
    return overview


def brief(config) -> str:
    """What the assistant should know about its own outside abilities.

    Written for the agent to read at the start of a piece of work. Says what it
    can do AND what it cannot, because an assistant that does not know a job is
    impossible will promise it and then fail — which is worse than saying no at
    the outset.
    """
    lines: list[str] = []
    possible: list[str] = []
    impossible: list[str] = []

    for entry in jobs_overview(config):
        if entry["chosen"]:
            possible.append(f"{entry['label'].lower()} ({entry['chosen']})")
        else:
            impossible.append(entry["label"].lower())

    if possible:
        lines.append("Outside services set up: " + "; ".join(possible) + ".")
        lines.append(
            "Each one costs the user money per use. Say what you are about to "
            "spend it on before a large or repeated job.")
    else:
        lines.append("No outside services are set up.")

    if impossible:
        lines.append(
            "Not available, so do not offer these: "
            + ", ".join(impossible) + ". "
            "If asked, say plainly that no key is set up for it and that the "
            "API keys page in the dashboard is where one goes.")

    return "\n".join(lines)


def environment(config, *job_keys: str) -> dict[str, str]:
    """Environment variables for the tools serving the named jobs.

    For a skill that shells out to a vendor's own command-line tool. Returned
    rather than set: a process-wide `os.environ` write leaks a paid key into
    every later subprocess of the session, including ones the user never
    connected to that service.
    """
    wanted = job_keys or JOB_KEYS
    found: dict[str, str] = {}
    for job_key in wanted:
        resolved = for_job(config, job_key)
        if resolved:
            found[resolved.env_name] = resolved.key
    return found


# ---------------------------------------------------------------------------
# Changing what is set up
# ---------------------------------------------------------------------------
#
# These take a config, return a changed config, and never save. Saving is the
# caller's job, which keeps one route to disk and one place where the atomic
# write happens.


def _replaced(config, apis: tuple):
    """Put a new tool list on the config without touching anything else.

    `dataclasses.replace` rather than rebuilding `Connections` by hand: a
    hand-built one drops every field the writer forgot, which is how a mailbox
    disappears because somebody saved an API key.
    """
    import dataclasses

    config.connections = dataclasses.replace(config.connections, apis=apis)
    return config


def put(config, tool_key: str, jobs: tuple[str, ...],
        label: str = "", enabled: bool = True) -> tuple:
    """Add or update one tool entry. Returns (config, problems).

    Problems are returned rather than raised, and a problem means nothing
    changed. Every other form in this package behaves that way, and a page
    that half-applies a change is a page nobody can reason about.
    """
    from .config import ApiTool

    key = normalise(tool_key)
    if not key:
        return config, ["Pick a service, or type the name of one."]

    known = tool(key)
    allowed = known.jobs if known else JOB_KEYS
    chosen = tuple(one for one in jobs if one in allowed)
    rejected = [one for one in jobs if one not in allowed]

    problems = []
    if rejected and known:
        problems.append(
            f"{known.name} cannot do: "
            + ", ".join(job_label(one) for one in rejected)
            + ". The rest was saved."
        )

    existing = entries(config)
    previous = next((one for one in existing if one.tool == key), None)
    others = tuple(one for one in existing if one.tool != key)

    entry = ApiTool(
        tool=key,
        label=(label.strip() or (previous.label if previous else "")),
        jobs=chosen,
        enabled=enabled,
        env_name=(previous.env_name if previous else ""),
    )
    # Appended, not prepended. A new tool must not silently take over a job
    # from one that was already doing it — taking over is a button the user
    # presses, not a side effect of adding a key.
    return _replaced(config, others + (entry,)), problems


def remove(config, tool_key: str, forget_the_key: bool = True) -> tuple:
    """Remove a tool entry, and by default its stored key too.

    Removing the entry while leaving the key would leave a paid credential on
    the machine that nothing lists any more — findable later by anyone with the
    machine, and by then nobody remembers it is there.
    """
    key = normalise(tool_key)
    remaining = tuple(one for one in entries(config) if one.tool != key)
    if forget_the_key:
        forget_key(key)
    return _replaced(config, remaining), []


def prefer(config, tool_key: str) -> tuple:
    """Move a tool to the front, making it the one used for its jobs.

    The whole precedence mechanism, in one function: order decides, and this
    is how order changes.
    """
    key = normalise(tool_key)
    existing = entries(config)
    chosen = [one for one in existing if one.tool == key]
    if not chosen:
        return config, [f"There is no {key} set up."]
    others = tuple(one for one in existing if one.tool != key)
    return _replaced(config, tuple(chosen) + others), []
