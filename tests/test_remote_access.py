"""Reaching the dashboard from outside — the one named exception to the guard.

reported 2026-08-28: users should be able to reach their dashboard when they are
out, through a tunnel. Then, having been shown what stood in the way.

What stood in the way is not an accident. `guard_mutations` refuses any request
carrying a forwarding header, or addressed to a host that is not this machine,
FOR READS AS WELL AS WRITES — and the comment beside it records why: on the
reference system that exact arrangement left a control surface, house lights
included, reachable from outside with no password, found afterwards.

So the exception had to be shaped so that the hole cannot come back. These
tests are that shape, and the two that matter most are:

  * `test_a_lookalike_hostname_is_not_let_in` — the obvious implementation
    trusts the forwarding headers, which the caller sets. This one trusts a
    single name the user typed, compared exactly.
  * `test_rebinding_is_still_refused_while_remote_access_is_on` — the attack
    the guard was hardened against in the first place. A page that re-resolves
    its own domain to 127.0.0.1 arrives wearing its own name, which is not the
    declared one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import dashboard_auth, exposure, paths

CONFIG = (Path(__file__).resolve().parents[1] / "configs" / "examples"
          / "architecture.yaml")
TUNNEL = "a1b2.ngrok-free.app"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    # keyring is not isolated by a temporary home, so the PIN's "has one been
    # chosen?" answer would otherwise come from the real machine and change
    # the result of tests about refusing the shipped PIN.
    monkeypatch.setattr(dashboard_auth, "is_default", lambda: False)
    exposure.turn_off()
    yield
    exposure.turn_off()


# ---------------------------------------------------------------------------
# Off, and off when broken
# ---------------------------------------------------------------------------

def test_it_is_off_to_begin_with():
    assert exposure.state().on is False
    assert exposure.allows(TUNNEL) is False


def test_an_unreadable_state_file_means_off():
    """A security switch whose broken state is "open" fails the wrong way."""
    exposure.turn_on(TUNNEL)
    (paths.app_dir() / exposure.STATE_FILE).write_text("{ not json",
                                                       encoding="utf-8")
    assert exposure.state().on is False
    assert exposure.allows(TUNNEL) is False


# ---------------------------------------------------------------------------
# What it refuses to be given
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host", ["", "https://a.ngrok-free.app",
                                  "a.ngrok-free.app:443", "localhost",
                                  "127.0.0.1", "::1", "notahost"])
def test_bad_addresses_are_refused_with_a_reason(host):
    problem = exposure.why_not(host)
    assert problem, f"{host!r} should not be accepted"
    assert problem[0].isupper() or problem.startswith("Give")


def test_naming_this_machine_is_refused():
    """Otherwise the exception is a no-op that looks like protection."""
    assert "already works" in exposure.why_not("localhost")


def test_it_will_not_switch_on_while_the_pin_is_the_shipped_one(monkeypatch):
    """The throttle cannot help if the answer is printed in the instructions."""
    monkeypatch.setattr(dashboard_auth, "is_default", lambda: True)
    done, message = exposure.turn_on(TUNNEL)
    assert done is False
    assert "PIN" in message
    assert exposure.state().on is False


# ---------------------------------------------------------------------------
# Who is let in
# ---------------------------------------------------------------------------

def test_the_declared_address_is_let_in():
    assert exposure.turn_on(TUNNEL)[0] is True
    assert exposure.allows(TUNNEL) is True
    assert exposure.allows(TUNNEL.upper() + ":443") is True


@pytest.mark.parametrize("host", [
    "evil-a1b2.ngrok-free.app",          # prefix
    "a1b2.ngrok-free.app.evil.com",      # suffix
    "a1b2.ngrok-free.appx",              # one character
    "ngrok-free.app",                    # the parent
    "localhost",                         # what it used to be
])
def test_a_lookalike_hostname_is_not_let_in(host):
    """Exact, lower-cased, port stripped. No wildcards, no suffix matching."""
    exposure.turn_on(TUNNEL)
    assert exposure.allows(host) is False


def test_turning_it_off_shuts_the_declared_address_out_again():
    exposure.turn_on(TUNNEL)
    exposure.turn_off()
    assert exposure.allows(TUNNEL) is False


# ---------------------------------------------------------------------------
# Through the guard itself
# ---------------------------------------------------------------------------

def _served(path: str, host: str) -> bool:
    """Did this host actually get the page?

    Signed in FOR THAT HOST, because the session cookie is per-host and the
    door's own checks run before the guard: without a session, a foreign host
    is turned away by the door and the guard is never reached. That is fine in
    production and useless in a test about the guard.

    The question asked is "was it served", not "what status" -- the first
    version asserted 403 and passed on a redirect to /login, which is what a
    request that never reached the guard also produces.
    """
    from aki_agent.dashboard import create_app

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    browser = app.test_client()
    with browser.session_transaction(base_url=f"http://{host}") as signed_in:
        signed_in["in"] = True
    reply = browser.get(path, base_url=f"http://{host}")
    return reply.status_code == 200


def test_a_tunnel_is_not_served_while_remote_access_is_off():
    assert _served("/projects", TUNNEL) is False


def test_a_forwarding_header_is_refused_while_remote_access_is_off():
    from aki_agent.dashboard import create_app

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    reply = app.test_client().get(
        "/projects", headers={"X-Forwarded-For": "203.0.113.9"})
    assert reply.status_code == 403


def test_the_declared_tunnel_is_served_once_it_is_on():
    exposure.turn_on(TUNNEL)
    assert _served("/projects", TUNNEL) is True


def test_rebinding_is_still_refused_while_remote_access_is_on():
    """The attack the guard was hardened against, retried with the door ajar.

    A page the user is merely visiting re-resolves its own domain to 127.0.0.1
    and reads this dashboard same-origin. It arrives wearing ITS hostname,
    which is not the one the user declared.
    """
    exposure.turn_on(TUNNEL)
    assert _served("/projects", "attacker.example") is False


def test_localhost_keeps_working_when_it_is_on():
    """Opening a tunnel must not shut the owner out of their own machine."""
    exposure.turn_on(TUNNEL)
    assert _served("/projects", "localhost") is True


def test_every_page_says_so_while_it_is_open():
    """A door that is open and does not look open is what this avoids."""
    exposure.turn_on(TUNNEL)
    from aki_agent.dashboard import create_app

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    html = app.test_client().get("/projects").get_data(as_text=True)
    assert "Reachable from outside" in html
    assert TUNNEL in html


def test_no_banner_when_it_is_shut():
    from aki_agent.dashboard import create_app

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    html = app.test_client().get("/projects").get_data(as_text=True)
    assert "Reachable from outside" not in html


# ---------------------------------------------------------------------------
# The switch has to be usable from the page, not only from the CLI
# ---------------------------------------------------------------------------

def _form_depth_of_the_switch(page: str) -> int | None:
    """How many forms deep is the switch's own <form>?

    HTML has no nested forms: when a <form> start tag arrives while another is
    still open, the parser drops it and every field inside joins the OUTER
    form. Nothing warns -- the page renders, the button presses, and the post
    goes somewhere else entirely.

    That is exactly what shipped on 2026-08-28. The section lived inside the
    form that posts to /settings/save, so the switch posted there instead.
    Confirmed in a real browser at the time: one form on the page, and the
    button's .form.action was /settings/save.

    Returns the depth its start tag was written at (0 = top level, what we
    want), or None if the switch is not on this page at all.
    """
    import re

    depth = 0
    for tag in re.finditer(r"<form\b[^>]*>|</form\s*>", page, re.I):
        text = tag.group(0)
        if text.startswith("</"):
            depth = max(0, depth - 1)
            continue
        if 'action="/remote"' in text:
            return depth
        depth += 1
    return None


def _page(path: str) -> str:
    from aki_agent.dashboard import create_app

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    browser = app.test_client()
    with browser.session_transaction() as signed_in:
        signed_in["in"] = True
    reply = browser.get(path)
    assert reply.status_code == 200, f"{path} answered {reply.status_code}"
    return reply.get_data(as_text=True)


def test_the_switch_is_on_the_connections_page():
    """The switch is on the connections page."""
    assert _form_depth_of_the_switch(_page("/connections")) == 0


def test_the_switch_is_not_wrapped_in_another_form():
    """The regression that made the move worth doing.

    Depth 0 is not decoration: at any other depth the browser silently hands
    the button to somebody else's form.
    """
    for path in ("/connections", "/settings"):
        depth = _form_depth_of_the_switch(_page(path))
        assert depth in (0, None), (
            f"{path} draws the remote-access switch {depth} form(s) deep; "
            "the browser will post it to the enclosing form instead")
