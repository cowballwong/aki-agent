"""Noticing a habit — and, more importantly, refusing to call one thing a habit.

A proposal engine that fires too readily is worse than none: every wrong
suggestion spends trust, and the feature ends up switched off. So most of what
is held here is the NOT: not from one afternoon, not from a single ask, not
twice for the same thing, and never a skill written without being asked.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from aki_agent import paths, skill_ideas


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    paths.ensure_app_dirs()
    return tmp_path


def ask(said: str, day: int, hour: int = 9) -> dict:
    when = _dt.datetime(2026, 8, day, hour, tzinfo=_dt.timezone.utc)
    return {"stamp": when.isoformat(), "role": "user", "said": said}


def test_three_asks_across_three_days_is_a_habit(app_home):
    rows = [
        ask("can you chase the building control officer again", 1),
        ask("chase building control for the decision notice", 3),
        ask("please chase building control, still nothing", 6),
    ]

    ideas = skill_ideas._from_rows(rows, limit=5)

    assert len(ideas) == 1
    assert "building" in ideas[0].title
    assert len(ideas[0].asks) == 3


def test_the_same_thing_five_times_in_one_afternoon_is_not_a_habit(app_home):
    """It is one task going badly.

    Proposing a skill for it would be the assistant mistaking somebody's
    frustration for a routine -- and the suggestion would arrive on the worst
    possible day to receive it.
    """
    rows = [ask("the export keeps failing, try the export again", 4, hour)
            for hour in (9, 10, 11, 12, 13)]

    assert skill_ideas._from_rows(rows, limit=5) == []


def test_one_ask_is_never_a_pattern(app_home):
    rows = [ask("draft the party wall notice for number 14", 1)]

    assert skill_ideas._from_rows(rows, limit=5) == []


def test_two_asks_about_different_things_stay_apart(app_home):
    rows = [
        ask("chase building control about the decision notice", 1),
        ask("book the structural engineer for thursday", 3),
        ask("chase building control again please", 5),
    ]

    ideas = skill_ideas._from_rows(rows, limit=5)

    assert ideas == [], "two of one thing and one of another is still two"


def test_a_cantonese_habit_is_noticed_too(app_home):
    """No spaces, so word-splitting cannot work -- character pairs can.

    Without this the feature would silently only work for people who write in
    English, which for this package's owner is the wrong half.
    """
    rows = [
        ask("幫我睇下今個星期嘅排程表", 1),
        ask("排程表有冇衝突,睇下先", 4),
        ask("再睇一次排程表", 7),
    ]

    ideas = skill_ideas._from_rows(rows, limit=5)

    assert len(ideas) == 1
    assert len(ideas[0].asks) == 3


def test_saying_no_once_settles_it(app_home):
    """Otherwise the same suggestion arrives every night until it is muted."""
    rows = [
        ask("chase building control about the notice", 1),
        ask("chase building control again", 3),
        ask("any word from building control? chase them", 5),
    ]
    first = skill_ideas._from_rows(rows, limit=5)
    assert first

    skill_ideas.dismiss(first[0].key, why="I would rather do this myself")

    assert skill_ideas._from_rows(rows, limit=5) == []


def test_a_draft_asks_questions_rather_than_inventing_the_procedure(app_home):
    """A draft that guesses reads as authoritative and gets saved unread."""
    rows = [
        ask("chase building control about the decision notice", 1),
        ask("chase building control again", 3),
        ask("chase building control, still waiting", 5),
    ]
    idea = skill_ideas._from_rows(rows, limit=1)[0]

    draft = skill_ideas.to_skill_draft(idea)

    assert "?" in draft["body"], "it must ask, not assert"
    assert "not a skill" in draft["body"]
    assert "chase building control" in draft["body"], (
        "the person's own words are the evidence for the suggestion")


def test_nothing_is_written_anywhere_by_proposing(app_home):
    """Proposing is not doing. The only thing it may write is a refusal."""
    from aki_agent import skills_store

    rows = [
        ask("chase building control about the notice", 1),
        ask("chase building control again", 3),
        ask("chase building control, anything?", 5),
    ]
    before = len(skills_store.read_all())

    skill_ideas._from_rows(rows, limit=5)

    assert len(skills_store.read_all()) == before


def test_words_that_carry_no_subject_are_ignored(app_home):
    """Otherwise every polite request matches every other one."""
    shared = skill_ideas.words_in("please could you just have a look at this")

    assert shared == set(), "courtesy is not a topic"


def test_a_chinese_name_reads_as_a_word_not_a_stutter(app_home):
    """廣東話 is matched as 廣東 + 東話 and must not be PRINTED that way.

    The overlapping pairs are right for comparing two asks and wrong for
    reading: on the Surface the first real suggestion this feature ever made
    was titled "廣東 東話", which looks like a fault rather than a topic.
    """
    rows = [
        ask("用廣東話寫返個 caption", 1),
        ask("呢篇用廣東話,唔好書面語", 4),
        ask("廣東話版本再寫一次", 7),
    ]

    idea = skill_ideas._from_rows(rows, limit=1)[0]

    assert "廣東話" in idea.title
    assert "廣東 東話" not in idea.title


def test_joining_only_happens_between_chinese_pairs(app_home):
    """An English word ending in the letter another starts with is not a word."""
    joined = skill_ideas._readable(["fix", "xray", "廣東", "東話"])

    assert joined[:2] == ["fix", "xray"], "English is left alone"
    assert "廣東話" in joined
