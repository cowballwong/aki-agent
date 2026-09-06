"""Open every page, in both states an install is ever in.

Three nav pages returned 500 before setup once, and the reason they survived
so long is that a developer's machine is never in that state: there is always
a config, so the pages that assume one always work. The person who meets the
failure is somebody on their first five minutes, and what they see is a stack
trace where a welcome should be.

So both states are checked here, and the one without a configuration is the
one that matters.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aki_agent import config as config_module, paths
from aki_agent.dashboard import create_app

EXAMPLE = Path(__file__).resolve().parents[1] / "configs" / "examples" / "architecture.yaml"


def _pages(app):
    return sorted({rule.rule for rule in app.url_map.iter_rules()
                   if "GET" in rule.methods and "<" not in rule.rule})


def _open_them_all(app):
    """Every GET page, as somebody who has entered the PIN. Returns failures."""
    app.config["TESTING"] = True
    broken = []
    with app.test_client() as browser:
        with browser.session_transaction() as session:
            session["in"] = True
        for rule in _pages(app):
            try:
                answer = browser.get(rule, follow_redirects=False)
            except Exception as exc:                     # noqa: BLE001
                broken.append(f"{rule} raised {type(exc).__name__}: {exc}")
                continue
            if answer.status_code >= 500:
                broken.append(f"{rule} returned {answer.status_code}")
    return broken


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    return tmp_path


def test_every_page_opens_on_a_configured_install(home):
    target = home / "config.yaml"
    shutil.copy(EXAMPLE, target)
    loaded = config_module.load(target)
    loaded.layout.root = EXAMPLE.parent
    config_module.save(loaded, target)

    broken = _open_them_all(create_app(target))
    assert not broken, "pages failed on a normal install:\n  " + "\n  ".join(broken)


def test_every_page_opens_before_setup_has_ever_run(home):
    """No configuration file at all -- the first five minutes.

    A page here may reasonably say "you have not set up yet". What it may not
    do is fail: this is the state somebody is in when they are deciding
    whether this software works.
    """
    never_created = home / "config.yaml"
    assert not never_created.exists()

    broken = _open_them_all(create_app(never_created))
    assert not broken, ("pages failed before setup:\n  " + "\n  ".join(broken))


def test_the_check_is_actually_looking_at_pages(home):
    """A guard on the guard.

    Both tests above pass if `_pages` returns nothing, and it would return
    nothing after a refactor that renamed the url map. That would leave two
    green tests watching an empty list.
    """
    target = home / "config.yaml"
    shutil.copy(EXAMPLE, target)
    assert len(_pages(create_app(target))) > 20
