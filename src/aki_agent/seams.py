"""The one registry every swappable part of this package reports into.

WHAT A SEAM IS, AND WHAT THIS MODULE DELIBERATELY DOES NOT DO
------------------------------------------------------------
A seam is a place where one capability can be served by more than one thing:
a message can reach the user by file or by Telegram; a calendar can be an ICS
subscription or a Google account. Each seam has three parts -- a definition
saying what a provider must offer, the providers themselves, and the code that
consumes them.

This module owns none of those three. It owns only the *filing cabinet*: a
registry that knows how to hold things that have a `name`, hand one back, and
list what it has.

That is the whole point, and it was learned from the code rather than decided
in advance. `channels.Channel` declares `available() -> bool`. The calendar
seam needs `available()` plus a capability set, because an ICS feed can be
read and cannot be written to. If this module tried to impose one Provider
protocol on both, one of them would have to grow a method it does not mean.

So the definition belongs to each seam, next to the providers that implement
it. The registry only ever asks a provider for its `name`.

WHY ONE MODULE AND SEPARATE INSTANCES
-------------------------------------
One module, because four copies of the same forty lines drift apart within a
month.

Separate instances, because a shared namespace collides within a week: there
is a calendar provider called `google` and there will one day be a mail
provider called `google`, and they are not the same object.
"""

from __future__ import annotations

from typing import Iterator, Protocol, TypeVar


class Named(Protocol):
    """The only thing this registry requires of anything it holds."""

    name: str


P = TypeVar("P", bound=Named)


# Every registry files itself here as it is created, so that one function can
# apply the configuration to all of them and one command can report on all of
# them without importing each seam by name -- which is the import cycle this
# module exists to avoid (`channels` imports `seams`, so `seams` cannot
# import `channels`).
_SEAMS: dict[str, "Registry"] = {}


class Registry:
    """Holds the providers for one seam.

    `what` is the singular word for the thing being held -- "channel",
    "calendar". It exists so a failure reads as `there is no calendar called
    'work'` rather than a message about registries, which is a word the user
    of this package should never have to meet.
    """

    def __init__(self, what: str, listed: bool = True) -> None:
        self.what = what
        self._entries: dict[str, P] = {}
        # None means "everything registered". A tuple means the configuration
        # named these and only these.
        self._chosen: tuple[str, ...] | None = None
        # A registry claims the seam name globally, which is what lets
        # `apply` and `inspect` reach every seam without importing each one.
        # `listed=False` is for a registry that is not a seam of this
        # installation -- a test exercising the container itself. Without the
        # opt-out such a registry becomes a permanent seam that `inspect`
        # then reports on a real machine.
        self.listed = listed
        if listed:
            _SEAMS[what] = self

    # -- writing ---------------------------------------------------------

    def register(self, provider: P) -> None:
        """Add one, replacing any earlier provider of the same name.

        Replacing rather than refusing is deliberate and is the behaviour
        `channels` already had: a test that registers a fake Telegram channel
        over the real one is the normal way this package is tested, and making
        that an error would mean every such test needed an unregister first.
        """
        self._entries[provider.name] = provider

    def unregister(self, name: str) -> None:
        self._entries.pop(name, None)

    def clear(self) -> None:
        """Back to empty, and back to no configured list.

        Dropping `_chosen` too is the part worth stating: `clear()` means
        "this registry is as it was before anything happened to it", and a
        filter that survived it would quietly shorten the next test's view of
        a registry it had just filled itself.
        """
        self._entries.clear()
        self._chosen = None

    # -- reading ---------------------------------------------------------

    def get(self, name: str) -> P | None:
        if self._chosen is not None and name not in self._chosen:
            return None
        return self._entries.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(name for name in self._entries
                            if self._chosen is None
                            or name in self._chosen))

    # -- the configured list ---------------------------------------------

    def choose(self, wanted) -> tuple[str, ...]:
        """Limit this seam to the named providers. Returns unknown names.

        FILTERED, NOT UNREGISTERED
        --------------------------
        The obvious implementation removes what the list leaves out. It is
        also one-way: the dashboard is a long-running process that reloads
        the configuration, and a provider dropped by one read could never come
        back when the user put it back in the file.

        So the list is a view. `registered()` still sees everything, which is
        what lets `inspect` say "installed but switched off" rather than
        silently showing a shorter list than the machine actually has.
        """
        if wanted is None:
            self._chosen = None
            return ()
        wanted = tuple(str(one).strip() for one in wanted if str(one).strip())
        unknown = tuple(one for one in wanted if one not in self._entries)
        self._chosen = wanted
        return unknown

    def chosen(self) -> tuple[str, ...] | None:
        """What the configuration asked for, or None if it said nothing."""
        return self._chosen

    def registered(self) -> tuple[P, ...]:
        """Everything present, including what the list switched off."""
        return tuple(self._entries[name] for name in sorted(self._entries))

    def switched_off(self) -> tuple[str, ...]:
        if self._chosen is None:
            return ()
        return tuple(name for name in sorted(self._entries)
                     if name not in self._chosen)

    def all(self) -> tuple[P, ...]:
        """Every provider, in name order, whether or not it is usable now.

        Sorted rather than in registration order so that two machines with the
        same providers list them the same way -- an inspection command whose
        output shuffles between runs is one nobody trusts.
        """
        return tuple(self._entries[name] for name in self.names())

    def __contains__(self, name: object) -> bool:
        return name in self.names()

    def __iter__(self) -> Iterator[P]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self.names())


# ---------------------------------------------------------------------------
# The configured list
# ---------------------------------------------------------------------------

def load_every_seam() -> None:
    """Make sure every seam has registered before anything reads the list.

    A registry files itself when its module is first imported. Most commands
    import only what they need, so without this a configuration naming
    `channel:` could be told there is no such seam purely because nothing in
    that command had touched `channels` yet -- a message that would send a
    person to fix a correct file.

    Imported inside the function on purpose: `channels` imports this module,
    so the same line at the top of the file is a cycle.

    THIRD-PARTY PLUGINS LOAD AFTER THE BUILT-IN SEAMS, NEVER BEFORE
    --------------------------------------------------------------
    A plugin registers into a seam, so the seam has to exist first. Ordering
    it the other way would give a plugin a registry that had not been created
    yet and a puzzling error instead of its provider.

    A plugin that fails is contained by `plugins.load_all` and reported by
    `inspect`; nothing here can raise because of one.
    """
    import_seam_modules()

    from . import plugins

    plugins.load_all()


def import_seam_modules() -> None:
    """Just the built-in seams, with no plugins.

    Split out from `load_every_seam` to break a real cycle, found by running
    `plugin list` in the demo: that command loads plugins directly, a plugin's
    `register` asked for `seam("calendar")`, and the registry did not exist
    yet because nothing had imported `calendar_seam` in that path. The plugin
    got `None` and the error read as a bug in the plugin.

    `plugins.load_all` calls this, and `load_every_seam` calls this and then
    the plugins. Neither can re-enter the other.
    """
    from . import accounts, calendar_seam, channels, guides  # noqa: F401


def known() -> tuple[str, ...]:
    """Every seam that exists in this installation, in name order."""
    return tuple(sorted(_SEAMS))


def seam(what: str) -> Registry | None:
    return _SEAMS.get(what)


def apply(config) -> list[str]:
    """Apply a configuration's `providers:` block to every seam.

    Returns problems in plain language; an empty list means it applied
    cleanly. Two rules are enforced here rather than left to each seam:

    **The block replaces, it does not merge.** A seam the block names is
    limited to exactly the names it lists. This is the rule worth being
    strict about: a merging override is one whose effect cannot be read off
    the page, and the page is the whole point.

    **A name nothing answers to is an error, not a silent skip.** A typo in
    `telegam` would otherwise turn the assistant's messages off and report
    nothing -- the failure would surface hours later as "why did it not tell
    me", which is the worst possible time to learn about a typo.

    Seams the block says nothing about keep every provider they have, so a
    configuration written before this existed behaves exactly as it did.
    """
    load_every_seam()
    wanted = dict(getattr(config, "providers", None) or {})

    problems: list[str] = []
    for what, registry in _SEAMS.items():
        registry.choose(wanted.get(what))

    for what, names in wanted.items():
        registry = _SEAMS.get(what)
        if registry is None:
            problems.append(
                f"Your configuration lists providers for '{what}', which is "
                f"not something this assistant has. It knows about: "
                f"{', '.join(known())}.")
            continue
        unknown = registry.choose(names)
        if unknown:
            # NEVER OBEY A LIST THAT COULD NOT BE FULLY HONOURED
            # --------------------------------------------------
            # Obeying `channel: [telegam]` means filtering the seam down to a
            # name nothing answers to -- which leaves no channel at all and
            # switches the assistant's messages off. The command line refuses
            # to run at all on this, but the dashboard is a long-running
            # process that has to keep working while somebody fixes the file,
            # and a half-applied list there is silent breakage.
            #
            # So a list with an unknown name is reported and discarded, and
            # the seam keeps everything it has.
            registry.choose(None)
        for name in unknown:
            problems.append(
                f"Your configuration asks for a {registry.what} called "
                f"'{name}', and there is no such thing. Available: "
                f"{', '.join(sorted(one.name for one in registry.registered()))}.")
        if unknown:
            # The empty-seam message below would be true and would point at
            # the wrong fix: with a typo the answer is to correct the name,
            # not to delete the line. One root cause, one instruction.
            continue
        if not registry.names():
            problems.append(
                f"Your configuration switches off every {registry.what}. "
                f"Remove the '{what}:' line to get the usual ones back.")
    return problems


def clear_chosen() -> None:
    """Forget every configured list. For tests and for a fresh process."""
    for registry in _SEAMS.values():
        registry.choose(None)
