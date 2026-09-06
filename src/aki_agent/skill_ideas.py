"""Noticing what you keep asking for, and offering to make it a skill.

WHAT THIS IS FOR
----------------
The package ships a library of skills somebody can switch on. What it could
not do is notice that THIS person keeps asking for something the library does
not have -- which is the only way an assistant ever becomes theirs rather than
a copy of everybody else's.

WHY IT PROPOSES AND NEVER WRITES
--------------------------------
A skill changes what the assistant does unasked, so one that appeared on its
own would be the package taking a decision it has no standing to take. This
produces candidates with the person's own words attached as evidence, and
stops. Saying yes is a separate act, and `skills_store.save` is what performs
it.

WHY IT COSTS NOTHING TO RUN
---------------------------
No model call. A proposal that costs money every night is one somebody
switches off in the first week, and then the feature is a switch nobody has
turned on rather than a thing that works. The signal is repetition, and
repetition is countable.

HOW IT DECIDES SOMETHING IS A HABIT
-----------------------------------
Three asks, on at least two different days, sharing the same handful of
content words. The two-day rule is what separates a habit from an afternoon:
asking for the same thing five times in one sitting is one task going badly,
not a pattern worth automating -- and proposing a skill for it would be the
assistant mistaking somebody's frustration for a routine.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import atomic, conversations, paths

# Words that carry no subject. Deliberately short: a long stop list starts
# deleting the very nouns that make two asks recognisably the same.
NOISE = {
    "the", "a", "an", "and", "or", "but", "if", "so", "then", "than", "that",
    "this", "these", "those", "it", "its", "is", "are", "was", "were", "be",
    "been", "being", "do", "does", "did", "done", "have", "has", "had", "can",
    "could", "will", "would", "shall", "should", "may", "might", "must",
    "for", "of", "to", "in", "on", "at", "by", "with", "from", "as", "into",
    "about", "please", "thanks", "thank", "you", "your", "yours", "me", "my",
    "mine", "we", "our", "us", "i", "he", "she", "they", "them", "his", "her",
    "their", "what", "when", "where", "which", "who", "whom", "why", "how",
    "not", "no", "yes", "ok", "okay", "just", "now", "again", "also", "all",
    "any", "some", "one", "two", "up", "out", "back", "let", "make", "made",
    "get", "got", "put", "see", "look", "need", "want", "like", "know",
}

MIN_ASKS = 3
MIN_DAYS = 2
MIN_SHARED = 2
LOOKBACK_DAYS = 30

# How many words of a bucket get shown in its name. NOT a limit on what it
# matches on -- that was tried, and truncating an alphabetically sorted list
# throws away Chinese words at random.
SIGNATURE = 8

# An ask is a sentence, not a document. Anything past this is a pasted error,
# a spec or a file, and its vocabulary is wide enough to overlap with
# everything it is compared against. This is what stops the runaway bucket:
# on the Surface, before this existed, one enormous system prompt produced a
# single "idea" with a forty-word name, claiming to have been asked 99 times.
LONGEST_ASK = 400


def _state_file():
    return paths.app_dir() / "state" / "skill-ideas.json"


def words_in(text: str) -> set[str]:
    """The content words of one ask, in a form two asks can be compared on.

    CJK is handled by taking overlapping PAIRS of characters rather than
    splitting on spaces, because there are none. A pair is the length of most
    ordinary Chinese words -- 報告, 圖則, 排程 -- so two asks about the same
    thing share them even when the sentences around them differ.
    """
    lowered = text.lower()
    found = {word for word in re.findall(r"[a-z][a-z0-9_-]{2,}", lowered)
             if word not in NOISE}
    for run in re.findall(r"[一-鿿]{2,}", text):
        found.update(run[index:index + 2] for index in range(len(run) - 1))
    return found


def _readable(words: list[str]) -> list[str]:
    """Put overlapping Chinese pairs back together for display.

    The matcher works on overlapping two-character pairs, which is right for
    comparing but wrong for reading: 廣東話 arrives as 廣東 and 東話 and gets
    printed as "廣東 東話", which looks like a stutter rather than a word.
    Joining pairs that share a character restores it.

    Display only. The pairs are what the bucket is matched on and they are
    left exactly as they were.
    """
    joined: list[str] = []
    for word in words:
        if (joined and len(word) == 2 and len(joined[-1]) >= 2
                and _is_cjk(word) and _is_cjk(joined[-1])
                and joined[-1][-1] == word[0]):
            joined[-1] = joined[-1] + word[1]
            continue
        joined.append(word)
    return joined


def _is_cjk(word: str) -> bool:
    return all("一" <= character <= "鿿" for character in word)


@dataclass
class Idea:
    """One thing somebody keeps asking for."""

    shared: tuple = ()
    asks: list = field(default_factory=list)   # [{"when", "said"}]

    @property
    def key(self) -> str:
        """A short, stable handle -- it gets typed to say "not this one"."""
        return "-".join(sorted(self.shared)[:4])

    @property
    def days(self) -> int:
        return len({(ask["when"] or "")[:10] for ask in self.asks})

    @property
    def title(self) -> str:
        """Short enough to read. The bucket may know more words than it says.

        A name is for recognising the thing, not for listing every word that
        put it in this bucket -- and an unbounded one produced a forty-word
        heading on the Surface that nobody could take in.
        """
        return " ".join(_readable(sorted(self.shared))[:SIGNATURE])

    def sentence(self) -> str:
        return (f"You have asked about {self.title} {len(self.asks)} times, "
                f"across {self.days} days.")


def _grouped(asks: list[dict]) -> list[Idea]:
    """Bucket asks that share enough content words to be the same request.

    Compared pairwise against the FIRST member rather than against the running
    intersection: taking the intersection each time lets a bucket drift, one
    word at a time, until the last ask in it has nothing to do with the first.
    """
    ideas: list[Idea] = []
    for ask in asks:
        said = ask["said"]
        if len(said) > LONGEST_ASK:
            continue
        vocabulary = words_in(said)
        if len(vocabulary) < MIN_SHARED:
            continue
        for idea in ideas:
            if len(vocabulary & set(idea.shared)) >= MIN_SHARED:
                idea.asks.append(ask)
                break
        else:
            # The whole vocabulary, not a truncated slice of it. Cutting the
            # signature to a fixed size looked like the fix for the runaway
            # bucket and was not: sorted order is alphabetical, so for Chinese
            # it discards whichever words happen to sort late -- 排程表 lost
            # its way into its own bucket that way. What actually caused the
            # runaway was one enormous message, and `LONGEST_ASK` is what
            # keeps those out.
            ideas.append(Idea(shared=tuple(sorted(vocabulary)), asks=[ask]))
    return ideas


def _seen() -> dict:
    return atomic.read_json(_state_file(), default={}) or {}


def propose(limit: int = 5, root=None) -> list[Idea]:
    """What this person keeps asking for that no skill covers yet.

    Returns nothing at all rather than something weak: a proposal that turns
    out to be noise costs more trust than it saves work.
    """
    conversations.refresh(root=root)
    rows = conversations.recent(days=LOOKBACK_DAYS, role="user")
    return _from_rows(rows, limit)


def _from_rows(rows: list[dict], limit: int) -> list[Idea]:
    asks = [{"when": row.get("stamp") or "", "said": row.get("said") or ""}
            for row in rows if row.get("role") == "user"]
    dismissed = _seen()
    ideas = [idea for idea in _grouped(asks)
             if len(idea.asks) >= MIN_ASKS
             and idea.days >= MIN_DAYS
             and idea.key not in dismissed]
    ideas.sort(key=lambda idea: (len(idea.asks), idea.days), reverse=True)
    return ideas[:limit]


def dismiss(key: str, why: str = "") -> None:
    """Never offer this one again.

    Kept rather than forgotten so that saying no once is not answering the
    same question every night for a month -- which is how a helpful feature
    becomes the one everybody mutes.
    """
    state = _seen()
    state[key] = {"why": why or "not wanted"}
    paths.ensure_app_dirs()
    atomic.write_json(_state_file(), state)


def to_skill_draft(idea: Idea) -> dict:
    """A starting point for `skills_store.save`, not a finished skill.

    The body is deliberately a set of questions rather than invented steps.
    A draft that guesses the procedure reads as authoritative and gets saved
    unread; one that asks gets edited, which is the point.
    """
    quotes = "\n".join(f"- \"{ask['said'][:160]}\" ({(ask['when'] or '')[:10]})"
                       for ask in idea.asks[:5])
    return {
        "name": idea.title.title(),
        "description": (f"Drafted from {len(idea.asks)} times you asked for "
                        f"something like this. Edit before switching it on."),
        "body": (
            f"## Why this was suggested\n\n{idea.sentence()}\n\n"
            f"In your own words:\n\n{quotes}\n\n"
            "## What to fill in\n\n"
            "- What should happen when you ask for this?\n"
            "- What does it need to read, and what may it change?\n"
            "- What should it never do without asking?\n\n"
            "Until those are answered this is a note, not a skill.\n"),
    }
