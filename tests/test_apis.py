"""The API keys page, and the two claims it makes.

WHAT THESE TESTS ARE ACTUALLY DEFENDING
---------------------------------------
Two failures, both of which would look like a working feature:

1. A KEY SHOWN BACK. The page reports that a key exists. If it ever renders the
   value, the secret is in the browser, in its autofill store and possibly in a
   crash report — and nothing on screen would look different.

2. A SETTING SILENTLY LOST. Saving a mailbox used to rebuild the whole
   connections block by hand, which drops any field the writer forgot. Adding
   `apis` to that block means a mailbox save could delete every API key. So
   there is a test that saves a mailbox and then looks for the keys.

Neither is visible by using the dashboard once and seeing it work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import apis, config as config_module
from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "configs" / "examples" / "architecture.yaml"

FAKE_KEY = "sk-" + ("z" * 32)


@pytest.fixture
def store(monkeypatch):
    """An in-memory credential store, so no test touches the real keychain.

    A test that wrote to the developer's own password manager would leave real
    entries behind on a real machine — and on a CI runner it would either fail
    or, worse, fall back to writing a file.
    """
    kept: dict[str, str] = {}
    from aki_agent import secrets as secrets_module

    monkeypatch.setattr(secrets_module, "get_secret", kept.get)
    monkeypatch.setattr(secrets_module, "set_secret",
                        lambda key, value: kept.__setitem__(key, value)
                        or "a test store")
    monkeypatch.setattr(secrets_module, "delete_secret",
                        lambda key: kept.pop(key, None) is not None)
    return kept


@pytest.fixture
def config(tmp_path):
    """A real config, copied so a test can save over it."""
    import shutil

    target = tmp_path / "config.yaml"
    shutil.copy(EXAMPLE, target)
    loaded = config_module.load(target)
    # The example configs use a relative workspace path; the copy moved it, so
    # point it at something that exists or the dashboard renders "not set up".
    loaded.layout.root = EXAMPLE.parent
    config_module.save(loaded, target)
    return target


# ---------------------------------------------------------------------------
# The split: a key is not permission
# ---------------------------------------------------------------------------

def test_a_key_with_no_job_is_used_for_nothing(store):
    """Pasting a key must not enlist a paid service into anything."""
    blank = config_module.Config()
    blank, problems = apis.put(blank, "gemini", ())
    apis.save_key("gemini", FAKE_KEY)

    assert problems == []
    assert apis.has_key("gemini") is True
    assert apis.for_job(blank, "image") is None, (
        "a key with no declared job was used anyway")


def test_a_job_with_no_key_is_not_offered(store):
    """The reverse: chosen for a job, but nothing was ever pasted."""
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image",))

    assert apis.for_job(blank, "image") is None
    overview = {row["job"]: row for row in apis.jobs_overview(blank)}
    assert overview["image"]["chosen"] == ""
    assert "Google Gemini" in overview["image"]["waiting_for_key"], (
        "a service chosen for a job with no key must be named as the problem")


def test_both_halves_present_resolves(store):
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image", "video"))
    apis.save_key("gemini", FAKE_KEY)

    resolved = apis.for_job(blank, "image")
    assert resolved is not None
    assert resolved.name == "Google Gemini"
    assert resolved.env_name == "GEMINI_API_KEY"
    assert resolved.key == FAKE_KEY


def test_switched_off_is_not_used(store):
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image",), enabled=False)
    apis.save_key("gemini", FAKE_KEY)

    assert apis.for_job(blank, "image") is None


# ---------------------------------------------------------------------------
# One job, one tool
# ---------------------------------------------------------------------------

def test_a_new_service_does_not_take_over_an_existing_job(store):
    """Adding a second capable service must not silently redirect the work."""
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image",))
    apis.save_key("gemini", FAKE_KEY)
    blank, _ = apis.put(blank, "openai", ("image",))
    apis.save_key("openai", FAKE_KEY)

    assert apis.for_job(blank, "image").tool_key == "gemini"


def test_prefer_is_how_that_changes(store):
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image",))
    blank, _ = apis.put(blank, "openai", ("image",))
    apis.save_key("gemini", FAKE_KEY)
    apis.save_key("openai", FAKE_KEY)

    blank, problems = apis.prefer(blank, "openai")
    assert problems == []
    assert apis.for_job(blank, "image").tool_key == "openai"


def test_a_service_cannot_be_given_a_job_it_cannot_do(store):
    """Better to refuse now than to fail at the moment of use."""
    blank = config_module.Config()
    blank, problems = apis.put(blank, "assemblyai", ("transcribe", "video"))

    assert problems, "silently accepted a job the service cannot do"
    assert "video" in problems[0].lower() or "Make short video" in problems[0]
    saved = apis.entries(blank)[0]
    assert saved.jobs == ("transcribe",), "the rest should still be saved"


def test_an_unlisted_service_still_works(store):
    """A catalogue that refuses what you pay for is worse than no catalogue."""
    blank = config_module.Config()
    blank, problems = apis.put(blank, "My Image Thing", ("image",))
    apis.save_key("my_image_thing", FAKE_KEY)

    assert problems == []
    resolved = apis.for_job(blank, "image")
    assert resolved is not None
    assert resolved.env_name == "MY_IMAGE_THING_API_KEY"


# ---------------------------------------------------------------------------
# Removing
# ---------------------------------------------------------------------------

def test_removing_deletes_the_key_too(store):
    """A credential nothing lists any more is a credential nobody removes."""
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image",))
    apis.save_key("gemini", FAKE_KEY)

    blank, _ = apis.remove(blank, "gemini")
    assert apis.entries(blank) == ()
    assert apis.has_key("gemini") is False


# ---------------------------------------------------------------------------
# Round-tripping through the config file
# ---------------------------------------------------------------------------

def test_the_order_survives_a_save(config, store):
    """Order is the precedence mechanism, so a save must not reorder it."""
    loaded = config_module.load(config)
    loaded, _ = apis.put(loaded, "gemini", ("image",))
    loaded, _ = apis.put(loaded, "openai", ("image",))
    loaded, _ = apis.prefer(loaded, "openai")
    config_module.save(loaded, config)

    again = config_module.load(config)
    assert [one.tool for one in again.connections.apis] == ["openai", "gemini"]


def test_the_key_is_never_written_into_the_config(config, store):
    loaded = config_module.load(config)
    loaded, _ = apis.put(loaded, "gemini", ("image",))
    apis.save_key("gemini", FAKE_KEY)
    config_module.save(loaded, config)

    assert FAKE_KEY not in config.read_text(encoding="utf-8")


def test_an_unknown_service_is_not_dropped_on_reload(config, store):
    """Silent deletion of a user's own entry is the failure to avoid here."""
    loaded = config_module.load(config)
    loaded, _ = apis.put(loaded, "something-of-mine", ("image",))
    config_module.save(loaded, config)

    again = config_module.load(config)
    assert [one.tool for one in again.connections.apis] == ["something_of_mine"]


# ---------------------------------------------------------------------------
# The bug that adding this field could have caused
# ---------------------------------------------------------------------------

def test_saving_a_mailbox_does_not_wipe_the_api_keys(config, store):
    """The reason every Connections rebuild became `dataclasses.replace`."""
    loaded = config_module.load(config)
    loaded, _ = apis.put(loaded, "gemini", ("image",))
    config_module.save(loaded, config)

    app = create_app(config)
    app.config["TESTING"] = True
    from aki_agent.dashboard import app as app_module

    with app.test_client() as browser:
        response = browser.post("/connections/mail", data={
            "token": app_module.SESSION_TOKEN,
            "address": "someone@example.com",
            "imap_host": "imap.example.com",
        })
        assert response.status_code in (200, 302)

    again = config_module.load(config)
    assert [one.tool for one in again.connections.apis] == ["gemini"], (
        "saving a mailbox deleted the API keys")
    assert any(one.address == "someone@example.com"
               for one in again.connections.mail)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def _page(config_path: Path, url: str = "/tools") -> str:
    app = create_app(config_path)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        response = browser.get(url)
        assert response.status_code == 200
        return response.get_data(as_text=True)


def test_the_page_renders_with_nothing_set_up(config, store):
    """Renders, and says what it is, and says that empty is fine.

    This used to check the heading said "API keys". On 2026-09-04 the top bar
    stopped naming the tab and started naming the group -- so the heading here now says "System", and the
    tab strip underneath says "Keys & servers".

    Rewritten against the page's own words rather than restored, because an
    assertion on the heading was measuring the chrome. What this test is
    actually for is that the page renders on a machine with nothing set up
    and does not look broken while it is empty.
    """
    html = _page(config)
    assert "for outside services you already pay for" in html
    assert "normal state" in html, (
        "an empty page must say that empty is fine, not look broken")


def test_the_page_never_shows_a_key(config, store):
    loaded = config_module.load(config)
    loaded, _ = apis.put(loaded, "gemini", ("image",))
    config_module.save(loaded, config)
    apis.save_key("gemini", FAKE_KEY)

    html = _page(config)
    assert "Google Gemini" in html
    assert FAKE_KEY not in html, "the page rendered the key"
    assert "saved" in html


def test_the_page_offers_every_job_and_service(config, store):
    html = _page(config)
    for job in apis.JOBS:
        assert job.label in html
    for tool in apis.catalogue():
        assert tool.name in html


def test_a_change_needs_the_token(config, store):
    """The CSRF guard covers the new routes too, not just the old ones."""
    app = create_app(config)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        response = browser.post("/tools/save", data={"tool": "gemini"})
        assert response.status_code == 403


def test_saving_through_the_page_stores_the_key_and_the_jobs(config, store):
    app = create_app(config)
    app.config["TESTING"] = True
    from aki_agent.dashboard import app as app_module

    with app.test_client() as browser:
        browser.post("/tools/save", data={
            "token": app_module.SESSION_TOKEN,
            "tool": "elevenlabs",
            "api_key": FAKE_KEY,
            "jobs": ["speech"],
        })

    again = config_module.load(config)
    assert apis.for_job(again, "speech").name == "ElevenLabs"
    assert store["api:elevenlabs"] == FAKE_KEY
    assert FAKE_KEY not in config.read_text(encoding="utf-8")


def test_switching_one_off_through_the_page_works(config, store):
    """An unticked checkbox is not posted, which is how this silently fails."""
    app = create_app(config)
    app.config["TESTING"] = True
    from aki_agent.dashboard import app as app_module

    with app.test_client() as browser:
        browser.post("/tools/save", data={
            "token": app_module.SESSION_TOKEN,
            "tool": "gemini", "api_key": FAKE_KEY, "jobs": ["image"],
        })
        # The edit form posts the marker; `enabled` itself is absent because
        # the box was unticked.
        browser.post("/tools/save", data={
            "token": app_module.SESSION_TOKEN,
            "tool": "gemini", "jobs": ["image"], "enabled_present": "1",
        })

    again = config_module.load(config)
    assert again.connections.apis[0].enabled is False
    assert apis.for_job(again, "image") is None


# ---------------------------------------------------------------------------
# What the assistant is told
# ---------------------------------------------------------------------------

def test_the_brief_says_what_is_impossible_too(store):
    """An assistant that does not know a job is impossible will promise it."""
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image",))
    apis.save_key("gemini", FAKE_KEY)

    text = apis.brief(blank)
    assert "Google Gemini" in text
    assert "make pictures" in text.lower()
    assert "not available" in text.lower()
    assert "search the web" in text.lower(), (
        "the brief must name what cannot be done, not only what can")


def test_the_brief_mentions_the_cost(store):
    blank = config_module.Config()
    blank, _ = apis.put(blank, "openai", ("image",))
    apis.save_key("openai", FAKE_KEY)

    assert "money" in apis.brief(blank).lower()


def test_environment_returns_only_what_was_asked_for(store):
    blank = config_module.Config()
    blank, _ = apis.put(blank, "gemini", ("image",))
    blank, _ = apis.put(blank, "elevenlabs", ("speech",))
    apis.save_key("gemini", FAKE_KEY)
    apis.save_key("elevenlabs", FAKE_KEY)

    assert apis.environment(blank, "image") == {"GEMINI_API_KEY": FAKE_KEY}
    assert set(apis.environment(blank)) == {"GEMINI_API_KEY",
                                           "ELEVENLABS_API_KEY"}


def test_the_cli_never_prints_a_key(config, store, capsys):
    """Anything printed here lands in a transcript on disk, for good."""
    from aki_agent import cli

    loaded = config_module.load(config)
    loaded, _ = apis.put(loaded, "gemini", ("image",))
    config_module.save(loaded, config)
    apis.save_key("gemini", FAKE_KEY)

    import aki_agent.cli as cli_module
    original = cli_module._load_config
    cli_module._load_config = lambda: (config_module.load(config), "")
    try:
        assert cli.main(["tools"]) == 0
    finally:
        cli_module._load_config = original

    printed = capsys.readouterr().out
    assert "Google Gemini" in printed
    assert FAKE_KEY not in printed
