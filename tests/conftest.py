"""Settings that apply to the whole suite.

WHY THIS EXISTS: THE SUITE WAS SPENDING MONEY
---------------------------------------------
On 2026-08-23 the draft checker was wired up so that raising a draft gets it
verified before it is shown. That is the right behaviour and it is what the
switch had been claiming for weeks.

It also meant every test that raised a draft made a full model call.
Measured: 25.9 seconds for one draft, and the suite went from 87 seconds to
past 400. Nothing failed. It got slow, and it spent real money on somebody's
subscription, quietly, on every run — including on a machine belonging to a
student who ran the tests to see whether their install was healthy.

A test suite must not reach the network or spend anything.

AND IT MUST NOT TOUCH THE ASSISTANT SOMEBODY IS USING
-----------------------------------------------------

They were not demo data and no upgrade put them there. They were THIS SUITE'S
fixtures -- "Party wall award not back", "Which staircase option?", "Reply to
Thomas" are written in `test_the_three_queues.py` -- landing in his real
`01_Config/state/approvals.json`. Proved by emptying that file and running the
suite: three rows, stamped with the second the run reached them.

Most tests already isolate themselves. One combination did not, and which one
is beside the point: `INTEGRATE.md` tells a student's own agent to run these
tests, so a suite that CAN reach a real install will reach somebody's, and the
symptom is items appearing in their queues that they did not put there and
cannot get rid of.

So the whole run is pointed at a temporary folder before a single test starts,
and the real path is remembered only to assert that nothing under it moved.
Being unable to reach it is a property of the suite now, not a habit each test
file has to remember.
"""

from __future__ import annotations

import pytest


# Captured before anything is redirected, so the guard below knows which
# folder is the one that must not be touched.
def _real_app_dir():
    from aki_agent import paths

    return paths.app_dir()


REAL_APP_DIR = None
_REAL_STATE = None


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_runner: this test exercises runner.run itself, so the "
        "suite-wide stub must not be applied to it")

    global REAL_APP_DIR, _REAL_STATE
    REAL_APP_DIR = _real_app_dir()
    _REAL_STATE = _fingerprint(REAL_APP_DIR)

    # THE NET UNDER THE PER-TEST ISOLATION.
    #
    # Patching `paths.home` per test is undone at teardown, and a thread the
    # dashboard started during a test outlives that -- so a write that lands a
    # moment late resolves the REAL home, follows the pointer, and reaches the
    # assistant somebody is using. That is what put three fixture rows in
    # The maintainer's queue: intermittent, one burst, always the same three.
    #
    # `AKI_AGENT_HOME` outranks the pointer and is never undone, so a late
    # write lands here instead. The per-test fixture sets it to that test's
    # own folder, so this value is only ever reached by something running
    # outside a test.
    import os
    import tempfile

    os.environ["AKI_AGENT_HOME"] = tempfile.mkdtemp(prefix="aki-tests-net-")


@pytest.fixture(autouse=True)
def _never_the_real_install(tmp_path, monkeypatch):
    """Give every test a home of its own, before it asks for anything.

    `AKI_AGENT_HOME` is deliberately NOT used here even though it would be the
    shorter way: it outranks `paths.home()`, so setting it for the whole run
    overrode the isolation the test files already do for themselves and broke
    sixty-five of them at once. Replacing home is the same isolation those
    files use, so a test that also does it simply wins, and one that never
    thought about it lands in a temporary folder instead of following the
    pointer into the assistant somebody is actually using.

    A test that MEANS to use the real one can monkeypatch it back; nothing
    does, which is the point.
    """
    from aki_agent import paths

    # Both, and to the same folder. `home` alone leaves the env var from the
    # session net in charge, which every test would then share; the env var
    # alone outranks the `home` patch the test files already do for
    # themselves, which broke sixty-five of them at once. Pointing both at
    # this test's own folder means whichever a caller consults, it agrees.
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / ".aki-agent"))
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    yield


def _fingerprint(folder):
    """What the real install's state looks like: name -> (size, mtime)."""
    state = folder / "state"
    if not state.is_dir():
        return {}
    found = {}
    for item in sorted(state.iterdir()):
        try:
            info = item.stat()
        except OSError:
            continue
        found[item.name] = (info.st_size, info.st_mtime_ns)
    return found


def pytest_sessionfinish(session, exitstatus):
    """Say so loudly if the run touched the assistant somebody is using.

    A quiet suite that writes into a real install is how three fixture rows
    ended up in the maintainer's queue and stayed there through two upgrades while he
    tried to work out where they came from.
    """
    if REAL_APP_DIR is None:
        return
    changed = sorted(
        name for name, was in _fingerprint(REAL_APP_DIR).items()
        if _REAL_STATE.get(name) != was)
    new = sorted(set(_fingerprint(REAL_APP_DIR)) - set(_REAL_STATE or {}))
    if changed or new:
        raise AssertionError(
            "the test run wrote into the real install at "
            f"{REAL_APP_DIR}: changed={changed} new={new}")


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch, request):
    """The single choke point every model consultation goes through.

    Stubbed here rather than at `sentinel.is_on`, which was the first
    attempt: switching the sentinel off globally broke every test that
    asserts on the state of that switch — including the one checking that a
    forged request cannot turn it off, which is a test that must never be
    quietly satisfied by the switch already being off.

    So the switch keeps its real value and nothing behind it reaches a model.
    A test that wants a particular answer patches `runner.run` itself, and
    theirs is applied after this one and wins.

    `autouse`, because the cost of forgetting is invisible: a test that
    accidentally triggers a call still passes. It is just slower, and it
    bills somebody.
    """
    # `runner.run` is itself under test in a few places -- that it puts the
    # prompt on stdin, that it forces UTF-8 in the child, that a missing
    # `claude` is a clear message. Stubbing it there would replace the subject
    # of the test with a stand-in and pass regardless.
    if request.node.get_closest_marker("real_runner"):
        return

    from aki_agent import runner

    def refuse(prompt: str, **_kwargs) -> runner.RunResult:
        return runner.RunResult(
            ok=False, output="",
            error=("no model is available in the test suite. If this test "
                   "needs one, patch runner.run with the answer it should "
                   "get -- a fixed reply is a better assertion than whatever "
                   "a model happened to say."),
            seconds=0.0,
        )

    monkeypatch.setattr(runner, "run", refuse)


@pytest.fixture
def checker(monkeypatch):
    """Turn the draft checker on, with a fixed verdict.

    Returns the list it records into, so a test can assert that the draft
    actually reached the checker and with what.
    """
    from aki_agent import sentinel

    asked: list[tuple[str, str]] = []

    def stand_in(draft: str, sources: str = "", workspace=None):
        """A flag on one of the four checks, and a pass on the rest.

        Every check is filled in, because `Verdict.line()` treats a verdict
        with no checks as unreadable — deliberately, so that "nothing parsed"
        can never be reported as "nothing wrong". A stub that skipped them
        would exercise that failure path instead of the one being tested.
        """
        asked.append((draft, sources))
        verdict = sentinel.Verdict(outcome=sentinel.FLAG, ran=True)
        verdict.checks = {name: "pass" for name in sentinel.CHECKS}
        verdict.checks["sources"] = "flag"
        verdict.reasons = {"sources": "the second paragraph has no source"}
        return verdict

    monkeypatch.setattr(sentinel, "is_on", lambda: True)
    monkeypatch.setattr(sentinel, "review", stand_in)
    return asked


# ---------------------------------------------------------------------------
# The dashboard now asks for a PIN
# ---------------------------------------------------------------------------
#
# Every test that opens a page was written before there was a door, so on the
# day the door was added 155 of them started reading a redirect to /login.
#
# The tempting fix was a flag in the application that switches the PIN off
# "for tests". That is how a real hole ships: the flag outlives the reason,
# somebody sets it somewhere else, and the check the suite was proving is the
# one nobody is running.
#
# So the product code is untouched and the SUITE lets itself in: every test
# client comes back already through the door, exactly as if a person had typed
# the PIN, and the suite looks like an install where a PIN has been chosen.
#
# Done here at import rather than in an autouse fixture, which was the first
# attempt and left fifteen tests still redirected: a module-scoped `browser`
# fixture is built BEFORE any function-scoped fixture of the test using it, so
# the patch had not been applied yet when its client was made. Patching at
# import happens before pytest builds anything at all.
#
# `tests/test_the_dashboard_pin.py` puts both of these back for its own tests,
# so the door is still proved by something.
# ---------------------------------------------------------------------------

from flask import Flask as _Flask

from aki_agent import dashboard_auth as _dashboard_auth

# Both patches are kept ON THE MODULE THEY PATCH rather than in a name here,
# and applied only once. pytest can import a conftest twice under different
# module names, and the second copy then read `is_default` AFTER the first had
# replaced it -- so what it saved as "the real one" was the stand-in, and the
# file that restores it restored nothing. It failed loudly. The version of
# that mistake which does not is the one to design against.

if not hasattr(_dashboard_auth, "the_real_is_default"):
    # A suite that never sets a PIN looks to the dashboard like a brand new
    # install, and a brand new install is sent to choose one before it may go
    # anywhere else. Right for a person; wrong for a test that asked for a
    # page.
    _dashboard_auth.the_real_is_default = _dashboard_auth.is_default
    _dashboard_auth.is_default = lambda: False

if not hasattr(_Flask, "unsigned_test_client"):
    _Flask.unsigned_test_client = _Flask.test_client

    def _signed_in_test_client(self, *args, **kwargs):
        client = _Flask.unsigned_test_client(self, *args, **kwargs)
        try:
            with client.session_transaction() as browser_session:
                browser_session["in"] = True
        except Exception:                                        # noqa: BLE001
            pass                # an app with no secret key: nothing to sign in
        return client

    _Flask.test_client = _signed_in_test_client

@pytest.fixture(autouse=True)
def no_installed_plugins(monkeypatch):
    """No test may see the plugins the person running it happens to have.

    WHY THIS IS HERE AND NOT IN ONE TEST (2026-08-26)
    -------------------------------------------------
    `test_an_unconnected_calendar_still_draws_the_month` failed on the
    author's machine the moment a calendar plugin was installed: the page
    correctly stopped saying "No calendar connected yet", because one was.

    The test was right and the suite was wrong. `INTEGRATE.md` tells a
    student's assistant to run these tests to prove nothing was hardcoded --
    a suite whose result depends on what that student has installed proves
    nothing. It is the same rule as `no_model_calls` above, one step further:
    a test must not reach the network, must not spend anything, and must not
    read the machine it is running on.

    Tests that are ABOUT plugins write into this folder and read back from
    it, so they keep working -- they simply do it somewhere that starts
    empty.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from aki_agent import plugins

    # Its own temporary directory, NOT a corner of `tmp_path`: several tests
    # list what is in `tmp_path` and count it, and a folder this fixture put
    # there made three of them fail. A fixture that isolates one thing must
    # not disturb another.
    folder = Path(tempfile.mkdtemp(prefix="aki-test-plugins-"))
    monkeypatch.setattr(plugins, "plugins_dir", lambda: folder)
    plugins.forget_loaded()
    try:
        yield
    finally:
        plugins.forget_loaded()
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------------
# A signed-in dashboard, for any test that wants to ask it for a page.
#
# It lived in `test_the_schedule_page.py` until 2026-09-05, when a second
# file needed it. Copying a twenty-line fixture is how two copies of "set up
# a dashboard" come to disagree about what a fresh install looks like -- so
# it moved here rather than being duplicated.
# ---------------------------------------------------------------------------
import pytest as _pytest


@_pytest.fixture
def dashboard_client(tmp_path, monkeypatch):
    """A dashboard whose state is this test's own folder.

    Without the paths.home patch these tests wrote into the developer's real
    ~/.aki-agent -- so they polluted each other in file order and, worse, left
    tasks behind on a real install. Caught when an edit test found two tasks
    where it had made one; the extra was the previous test's.
    """
    import shutil
    from pathlib import Path as _Path

    from aki_agent import config as config_module, paths
    from aki_agent.dashboard import create_app

    example = (_Path(__file__).resolve().parents[1]
               / "configs" / "examples" / "architecture.yaml")

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    target = tmp_path / "config.yaml"
    shutil.copy(example, target)
    loaded = config_module.load(target)
    loaded.layout.root = example.parent
    config_module.save(loaded, target)

    app = create_app(target)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        yield browser
