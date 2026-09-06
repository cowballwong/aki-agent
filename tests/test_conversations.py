"""Searching what was SAID, not what was written down.

The distinction is the whole point of the feature: `memory` holds the notes
the assistant chose to keep, and this holds the conversation those notes were
distilled from. Most of what somebody wants back later -- why a decision went
that way, what was tried and dropped -- never became a note.

The rules held here are the ones that are invisible when broken: an index that
silently swallows the wrong person's work, one that answers about a world
sixteen days out of date, and a Chinese query that finds nothing because the
tokenizer never saw a space.
"""

from __future__ import annotations

import datetime as _dt
import json

import pytest

from aki_agent import conversations


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A home with transcripts in it, and a workspace those sessions ran in."""
    home = tmp_path / "home"
    (home / ".claude" / "projects" / "a-project").mkdir(parents=True)
    root = tmp_path / "Assistant"
    (root / "01_Config").mkdir(parents=True)
    monkeypatch.setattr(conversations.paths, "home", lambda: home)
    monkeypatch.setenv("AKI_AGENT_HOME", str(root / "01_Config"))
    return home, root


def write_session(home, turns, cwd, name="session.jsonl"):
    """Turns as Claude Code really records them."""
    lines = []
    when = _dt.datetime(2026, 8, 24, 9, 0, tzinfo=_dt.timezone.utc)
    for index, (role, text) in enumerate(turns):
        content = text if role == "user" else [{"type": "text", "text": text}]
        lines.append(json.dumps({
            "type": role,
            "cwd": str(cwd),
            "timestamp": (when + _dt.timedelta(minutes=index)).isoformat(),
            "message": {"role": role, "content": content},
        }, ensure_ascii=False))
    path = home / ".claude" / "projects" / "a-project" / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_what_was_said_can_be_found_again(workspace):
    home, root = workspace
    write_session(home, [
        ("user", "why did we drop the postcode lookup?"),
        ("assistant", "It needed a paid key, so we asked for the town instead."),
    ], cwd=root)

    conversations.refresh(root=root)
    hits = conversations.search("paid key")

    assert len(hits) == 1
    assert "paid key" in hits[0]["said"].replace("[", "").replace("]", "")
    assert hits[0]["role"] == "assistant"


def test_a_chinese_question_finds_a_chinese_answer(workspace):
    """The reason this index uses trigram at all.

    The default tokenizer splits on spaces. A Cantonese sentence has none, so
    the whole line becomes one token and every search inside it fails -- while
    reporting no matches, which reads as "we never discussed it".
    """
    home, root = workspace
    write_session(home, [
        ("user", "點解個報告要用書面語"),
        ("assistant", "因為交出去俾客戶睇,書面語先啱場合。"),
    ], cwd=root)

    conversations.refresh(root=root)

    assert conversations.search("書面語"), "a Chinese phrase must be findable"
    assert conversations.search("報告"), "and so must a shorter one"


def test_a_session_from_another_folder_is_never_indexed(workspace):
    """The rule that matters most, and the one nobody would notice was broken.

    Claude Code keeps every project's transcripts in one place. Someone who
    uses it for their employer's code as well would have that work quietly
    pulled into their assistant's index -- and would only find out when it
    surfaced in a search.
    """
    home, root = workspace
    write_session(home, [("user", "the client's rate is confidential")],
                  cwd=home / "somewhere-else", name="elsewhere.jsonl")
    write_session(home, [("user", "my own note about the extension")],
                  cwd=root, name="mine.jsonl")

    conversations.refresh(root=root)

    assert conversations.search("confidential") == []
    assert conversations.search("extension"), "and the person's own is kept"


def test_nothing_is_indexed_when_there_is_no_workspace_to_compare_against(
        workspace):
    """No root means no way to tell whose session it is, so nothing is taken.

    Failing towards an empty index is the safe direction: an empty search says
    'nothing found' and somebody looks again, while a wrongly-full one says
    nothing at all.
    """
    home, root = workspace
    write_session(home, [("user", "something private")], cwd=root)

    conversations.refresh(root=None)

    assert conversations.search("private") == []


def test_the_second_refresh_does_not_re_read_the_file(workspace):
    home, root = workspace
    write_session(home, [("user", "first thing")], cwd=root)

    first = conversations.refresh(root=root)
    again = conversations.refresh(root=root)

    assert first["added"] == 1
    assert again["added"] == 0, "an unchanged file has nothing to add"
    assert again["total"] == 1, "and nothing may be counted twice"


def test_new_turns_are_picked_up_without_re_reading_the_old_ones(workspace):
    """The offset is a resume point, not a stop sign."""
    home, root = workspace
    write_session(home, [("user", "first thing")], cwd=root)
    conversations.refresh(root=root)

    write_session(home, [("user", "first thing"), ("user", "second thing")],
                  cwd=root)
    second = conversations.refresh(root=root)

    assert second["added"] == 1
    assert second["total"] == 2
    assert conversations.search("second thing")


def test_a_rewritten_file_is_read_from_the_start(workspace):
    """A file that shrank is a different file wearing the same name."""
    home, root = workspace
    write_session(home, [("user", "a long first conversation about roofs")],
                  cwd=root)
    conversations.refresh(root=root)

    write_session(home, [("user", "short")], cwd=root)
    conversations.refresh(root=root)

    assert conversations.search("short"), "the replacement must be indexed"


def test_tool_output_and_thinking_are_not_conversation(workspace):
    home, root = workspace
    path = home / ".claude" / "projects" / "a-project" / "mixed.jsonl"
    path.write_text(json.dumps({
        "type": "assistant",
        "cwd": str(root),
        "timestamp": "2026-08-24T09:00:00Z",
        "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "gargoyle"},
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "echo gargoyle"}},
            {"type": "text", "text": "Done — the roof survey is filed."},
        ]},
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    conversations.refresh(root=root)

    assert conversations.search("gargoyle") == [], (
        "an index of commands and reasoning is a different feature")
    assert conversations.search("roof survey")


def test_a_search_that_is_not_a_query_language_still_works(workspace):
    """People type what they remember, not FTS5 expressions."""
    home, root = workspace
    write_session(home, [("assistant", "Run it with --fix and it applies them.")],
                  cwd=root)

    conversations.refresh(root=root)

    assert conversations.search("--fix"), "punctuation must not be syntax"
    assert conversations.search('he said "no"') == [], (
        "and an unmatched phrase is an empty result, not an exception")


def test_searching_before_anything_is_indexed_says_nothing_rather_than_raising(
        workspace):
    assert conversations.search("anything") == []
    assert conversations.search("") == []


def test_a_two_character_chinese_word_is_still_findable(workspace):
    """Trigram needs three characters. Chinese words are often two.

    報告, 問題, 時間 -- these are ordinary words, not abbreviations, and a
    trigram index matches none of them. Left alone the search would answer
    "nothing" and the person would conclude they had never discussed it.
    """
    home, root = workspace
    write_session(home, [("assistant", "個報告星期五交,問題喺個時間表。")],
                  cwd=root)

    conversations.refresh(root=root)

    for word in ("報告", "問題", "時間"):
        assert conversations.search(word), f"{word} must be findable"


def test_a_wildcard_typed_by_a_person_is_not_a_wildcard(workspace):
    """`%` and `_` mean something to LIKE and nothing to the person typing."""
    home, root = workspace
    write_session(home, [("user", "the fee is 10 per cent"),
                         ("user", "we agreed 5%")], cwd=root)

    conversations.refresh(root=root)
    hits = conversations.search("5%")

    assert len(hits) == 1, "a literal % must not match every line"
    assert "5%" in hits[0]["said"]


def test_a_system_prompt_is_not_somebody_talking(workspace):
    """Claude Code files several non-speech things as `user` records.

    A sub-agent's system prompt, a slash-command marker, a skill preamble.
    All read as fluent first-person text, so nothing downstream can tell them
    apart — and left in, a feature that counts what somebody keeps asking for
    concludes they ask to be David ninety-nine times. That is not a
    hypothetical: it is what the Surface printed on 2026-08-24.
    """
    home, root = workspace
    write_session(home, [
        ("user", "You are David, the maintainer Wong's assistant. Reply in yue."),
        ("user", "<command-name>/aki-agent:upgrade</command-name>"),
        ("user", "Base directory for this skill: C:/somewhere/skills/x"),
        ("user", "<system-reminder>remember the rules</system-reminder>"),
        ("user", "can you chase building control for me"),
    ], cwd=root)

    conversations.refresh(root=root)

    assert conversations.search("David") == []
    assert conversations.search("upgrade") == []
    assert conversations.search("skill") == []
    assert conversations.search("remember") == []
    assert conversations.search("building control"), (
        "and the one real sentence survives")


def test_a_telegram_message_keeps_its_words_and_loses_its_envelope(workspace):
    """The channel wrapper is how a person reaches the assistant from a phone.

    Dropping the record would lose every message the maintainer sends; keeping the XML
    would put `chat_id` and a message number into the search index.
    """
    home, root = workspace
    write_session(home, [
        ("user", '<channel source="telegram" chat_id="7563892302">\n'
                 'the drainage drawing needs a revision\n</channel>'),
    ], cwd=root)

    conversations.refresh(root=root)

    assert conversations.search("drainage drawing")
    assert conversations.search("7563892302") == [], "the envelope is not content"


def test_changing_the_rules_rebuilds_what_was_already_indexed(workspace,
                                                              monkeypatch):
    """A filter that only applies to unread lines is not a filter.

    Reading is incremental, so rows admitted under the old rules stay for ever
    unless something goes back for them. On the Surface the system-prompt
    filter was written, shipped and installed, and the machine went on
    reporting that the maintainer asks to be David 23 times — because those rows had
    been indexed the day before.
    """
    home, root = workspace
    write_session(home, [("user", "You are David, an assistant. Reply in yue.")],
                  cwd=root)

    # As it was before the filter existed: admit everything.
    #
    # Restored by hand rather than with `monkeypatch.undo()`, which undoes
    # EVERY patch including this fixture's -- and a test that loses its
    # isolation stops reading a temporary folder and starts reading the real
    # one. This test did exactly that once, and left an index of 893 real
    # transcripts in the author's own install.
    original = conversations.NOT_SPEECH
    conversations.NOT_SPEECH = ()
    try:
        conversations.refresh(root=root)
        assert conversations.search("David"), "the old index really did hold it"
    finally:
        conversations.NOT_SPEECH = original

    # The rules change, and the stamp changes with them.
    monkeypatch.setattr(conversations, "RULES", conversations.RULES + 1)
    conversations.refresh(root=root)

    assert conversations.search("David") == [], (
        "the fix has to reach rows that were already there")


def test_a_pasted_credential_never_enters_the_index(workspace):
    """People paste keys into chat, and this index gets read back out loud.

    A search result, a suggestion, a screen shared in a classroom. Before this
    existed the Surface printed a real Telegram bot token as a skill
    suggestion — a secret the person had typed once, months earlier, resurfaced
    by the feature meant to be helpful.
    """
    home, root = workspace
    # Invented, and assembled from pieces at run time. Written out whole it
    # would be a credential-shaped string committed to the repository, and the
    # package's own guard against exactly that would fail this file -- which
    # is the guard working, not a nuisance to be silenced.
    fake = ":".join(("1234567890",
                     "AAHfake0Token1For2" + "Tests3Only4Never5Real6x"))
    write_session(home, [
        ("user", f"here is the bot token {fake}"),
        ("user", "the drainage drawing needs a revision"),
    ], cwd=root)

    conversations.refresh(root=root)

    assert conversations.search("bot token") == []
    assert conversations.search("1234567890") == []
    assert conversations.search("drainage"), "ordinary sentences are unaffected"


def test_the_harness_talking_to_itself_is_not_a_person_asking(workspace):
    """These are the most repetitive text on the machine.

    Left in, they are the first thing a habit-finder concludes somebody keeps
    asking for — the Surface offered "interrupted request tool use, 3 times"
    as a candidate skill.
    """
    home, root = workspace
    write_session(home, [
        ("user", "[Request interrupted by user for tool use]"),
        ("user", "[Your previous response had no visible output. Please "
                 "continue and produce a user-visible response.]"),
        ("user", "check the party wall notice for number 14"),
    ], cwd=root)

    conversations.refresh(root=root)

    assert conversations.search("interrupted") == []
    assert conversations.search("visible output") == []
    assert conversations.search("party wall")
