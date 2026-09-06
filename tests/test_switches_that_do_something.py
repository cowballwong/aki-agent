"""Controls the user can press, and what happens when they do.

The recurring defect in this package is not a broken control. It is a
control that is drawn, pressed, confirmed — and wired to nothing. These pin
the ones found on 2026-08-23.
"""
import datetime as _dt

from aki_agent import favourites, quiet


def test_unticking_every_day_does_not_mean_every_day():
    """The switch that confirmed and did the opposite.

    `from_dict` read a stored empty list as all seven days, so unticking
    everything produced a mode that applied *always*. On the shipped Weekend
    mode — window 00:00–00:00, which `holds()` treats as all day — that
    turned it into permanent silence.

    The form even said so and was overruled: the page printed "No day is
    ticked, so this mode never applies", then re-rendered the card with all
    seven ticked.
    """
    unticked = quiet.Mode.from_dict({
        "key": "weekend", "name": "Weekend",
        "start": "00:00", "end": "00:00", "days": [],
    })
    assert unticked.days == (), "an unticked mode came back with days on it"
    assert unticked.problems(), "an unticked mode reported itself as fine"
    assert "never" in unticked.when().lower()


def test_a_file_written_before_days_existed_still_means_every_day():
    """Absent and empty are different answers.

    The migration this replaced was right about one thing: a mode saved
    before the days field existed has no days key, and reading that as "no
    day" would silently switch off somebody's quiet hours.
    """
    legacy = quiet.Mode.from_dict({
        "key": "nightly", "name": "Nightly",
        "start": "22:00", "end": "07:00",
    })
    assert legacy.days == quiet.WEEKDAYS
    assert not legacy.problems()


def test_the_workspace_has_something_to_pin_with(tmp_path, monkeypatch):
    """Today promised a control that Workspace did not have.

    `/projects/pin` existed and `favourites.toggle` existed; the empty state
    on Today read "The ones you pin on Workspace appear here"; and nothing
    on Workspace posted to it. A promise on one page about a control that
    was never built on the other.
    """
    from pathlib import Path

    from aki_agent.dashboard import create_app

    monkeypatch.setattr(favourites.paths, "app_dir", lambda: tmp_path)

    app = create_app(Path("configs/examples/architecture.yaml"))
    with app.test_client() as browser:
        page = browser.get("/projects").get_data(as_text=True)

    assert 'action="/projects/pin"' in page, (
        "Workspace has no way to pin anything, and Today says it has")


def test_a_pinned_project_links_somewhere_that_exists(tmp_path, monkeypatch):
    """Every card on the landing page used to be a 404.

    `_favourites.html` wrote `/item?key=…`; the route is `/item/<path:key>`,
    and there is no bare `/item`. The correct form was one file away in
    `_items.html`.
    """
    import re
    from pathlib import Path

    from aki_agent.dashboard import create_app

    monkeypatch.setattr(favourites.paths, "app_dir", lambda: tmp_path)

    app = create_app(Path("configs/examples/architecture.yaml"))
    with app.test_client() as browser:
        page = browser.get("/projects").get_data(as_text=True)
        token = re.search(r'name="token" value="([^"]+)"', page).group(1)
        key = re.search(
            r'action="/projects/pin".*?name="key" value="([^"]+)"',
            page, re.S).group(1)
        browser.post("/projects/pin",
                     data={"token": token, "key": key, "back": "/projects"})

        today = browser.get("/").get_data(as_text=True)
        links = re.findall(r'class="favour[^"]*"\s+href="([^"]+)"', today)
        assert links, "nothing was pinned onto Today"
        for href in links:
            assert browser.get(href).status_code == 200, f"{href} is a dead link"


def test_held_messages_are_actually_delivered(tmp_path, monkeypatch):
    """The counter that could only go up.

    `notify.release()` was written, tested and called by nothing. The shipped
    08:05 task carried the prompt "Deliver any notifications held while I was
    unavailable" — plain English handed to a model with no command for it. So
    every page showed "Waiting to send: N", README promised in bold that held
    messages "are delivered afterwards as one summary rather than dropped",
    and N only ever rose.
    """
    import shutil
    from pathlib import Path

    from aki_agent import atomic, notify, paths, tasks

    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    shutil.copy("configs/examples/architecture.yaml", tmp_path / "config.yaml")

    atomic.write_json(notify.held_queue_path(), [
        {"created_at": "2026-08-23T23:10:00", "text": "A bill is due",
         "urgent": False},
        {"created_at": "2026-08-23T23:40:00", "text": "Client replied",
         "urgent": True},
    ])
    assert notify.held_count() == 2

    # A fixed time, not the wall clock.
    #
    # This passed for a day and then started failing at 22:00, because the
    # shipped config has quiet hours and the branch taken depends on what time
    # the suite happens to run. It found a real bug that way -- `decision.why`,
    # on a field called `reason` -- but by luck rather than by design, and a
    # test that only exercises the quiet branch after ten at night is a test
    # that mostly does not exercise it.
    morning = _dt.datetime(2026, 8, 24, 8, 5)
    outcome = tasks.run_one("release-held", channel="file", now=morning)

    assert outcome.ok, outcome.message
    assert notify.held_count() == 0, "the queue was not emptied"


def test_a_release_during_quiet_hours_leaves_the_queue_alone(tmp_path,
                                                             monkeypatch):
    """The other branch, which nothing reached on purpose until now.

    Being quiet stops the message, never the work — so a release that lands
    inside quiet hours must report why and leave every message where it is,
    rather than delivering into the silence or discarding.
    """
    import shutil

    from aki_agent import atomic, notify, paths, tasks

    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    shutil.copy("configs/examples/architecture.yaml", tmp_path / "config.yaml")

    atomic.write_json(notify.held_queue_path(), [
        {"created_at": "2026-08-23T23:10:00", "text": "A bill is due",
         "urgent": False},
    ])

    night = _dt.datetime(2026, 8, 24, 23, 30)
    outcome = tasks.run_one("release-held", channel="file", now=night)

    assert outcome.ok, outcome.message
    assert "still held" in outcome.message
    assert notify.held_count() == 1, "it delivered into the quiet anyway"


def test_the_release_task_calls_a_function_not_a_model():
    """A task whose work is a function call should call the function."""
    from aki_agent import schedule

    task = schedule.get_task("release-held")
    assert task is not None
    assert task.prompt.strip() == "__release__", (
        "the release task is describing its job to a language model again")


def test_there_is_a_way_to_bin_a_backlog():
    """`clear_held` has always said it exists for this. Nothing pressed it."""
    from pathlib import Path

    templates = Path("src/aki_agent/dashboard/templates")
    page = (templates / "_notifications.html").read_text(encoding="utf-8")
    assert 'action="/notifications/clear"' in page
    assert 'action="/notifications/release"' in page


def test_uninstall_says_what_it_will_do_with_credentials(monkeypatch):
    """The word "credential" appeared in neither list.

    `plan()` names what it removes and what it leaves. It said nothing about
    the credential store either way, so a student who removed the assistant
    kept their Gmail app password, their Google OAuth secret and refresh
    token, their Telegram API id and hash, and every paid API key — with
    nothing left on the machine to say what had put them there.

    `google_calendar.forget_everything()` had been written for exactly this
    and had no callers.
    """
    from aki_agent import secrets, uninstall

    held = {"api:openai": "sk-not-a-real-key"}
    monkeypatch.setattr(secrets, "get_secret", lambda key: held.get(key))

    the_plan = uninstall.plan()
    kinds = [item.kind for item in the_plan.removals] + \
            [item.kind for item in the_plan.kept]
    assert "secrets" in kinds, (
        "an uninstall plan that mentions credentials nowhere leaves them all "
        "behind, silently")


def test_the_sentinel_card_does_not_claim_an_automatic_check():
    """The switch governed the wording on its own card and nothing else.

    `is_on()` is read in four places and every one only prints something;
    `review()` deliberately ignores it, which is right. But nothing checks a
    draft without being asked, so "Drafts are looked at before they are
    shown, recorded or sent" described nothing.
    """
    from pathlib import Path

    card = (Path("src/aki_agent/dashboard/templates/_specialists.html")
            .read_text(encoding="utf-8"))
    assert "Drafts are looked at before they are shown" not in card
    assert "Nothing is being verified before it goes out" not in card


def test_a_today_row_can_be_acted_on_where_it_is(tmp_path, monkeypatch):
    """A Today row carries its own actions, raised from the bottom edge.

    The pills were only half of the pattern being copied. The other half
    swaps the list AND raises a list from the bottom edge when a button is
    pressed, showing nothing until then.

    A list that
    is always open costs the height whether anyone wants it or not, and that
    height is what stopped Today fitting on one screen.

    Before any of it, every row was a link somewhere else — so Today could
    say four things were waiting and let you do none of them. A list you can
    only read is a notification, not a queue.
    """
    import re
    import shutil
    from pathlib import Path

    from aki_agent import approvals, paths
    from aki_agent.dashboard import create_app

    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    shutil.copy("configs/examples/architecture.yaml", tmp_path / "config.yaml")

    approvals.ask("Send the fee proposal?",
                  body="It quotes the 2018 scope.",
                  options=[approvals.Option("send", "Send it"),
                           approvals.Option("hold", "Hold for now")])

    app = create_app(Path("configs/examples/architecture.yaml"))
    with app.test_client() as browser:
        page = browser.get("/").get_data(as_text=True)

        assert 'id="queue"' in page, "there is no panel to pull up"

        # Its own options, as real forms, inside the panel.
        assert "Send it" in page and "Hold for now" in page, (
            "the panel does not carry the item's own options, so it would "
            "have to invent them — and approvals.answer refuses anything "
            "that was not declared")

        found = re.search(r'action="/waiting/([^/]+)/send"', page)
        assert found, "no option button posts to the answer route"
        item_id = found.group(1)

        token = re.search(r'name="token" value="([^"]+)"', page).group(1)
        answered = browser.post(f"/waiting/{item_id}/send",
                                data={"token": token, "back": "/"})

        assert answered.headers["Location"].endswith("/"), (
            "answering from Today dumped the user on another page")
        assert not approvals.get(item_id).is_open


def test_the_back_field_cannot_be_aimed_somewhere_else():
    """A redirect target taken from a form is one somebody else can aim."""
    import re
    from pathlib import Path

    source = Path("src/aki_agent/dashboard/app.py").read_text(encoding="utf-8")
    guard = source[source.index("def _back_to("):]
    guard = guard[:guard.index("@app.route")]
    assert 'startswith("/")' in guard and 'startswith("//")' in guard, (
        "the back field is used without checking where it points")


def test_nothing_is_shown_until_a_button_is_pressed():
    """ — and that is what makes one screen possible.

    The attempt before this kept one list open under the buttons at all
    times. It cost the height whether anyone wanted it or not, and that
    height is what pushed Today past the fold.
    """
    from pathlib import Path

    from aki_agent.dashboard import create_app

    # Checked on the page a browser receives, not on the template text. The
    # first version of this test counted the literal `class="queuelist"` in
    # the source and broke the moment the three panes became a loop -- it was
    # asserting how the markup is written, not what it does. Rendering is the
    # only place the claim is actually true or false.
    app = create_app(Path("configs/examples/architecture.yaml"))
    app.config["TESTING"] = True
    html = app.test_client().get("/").get_data(as_text=True)

    # The panel itself starts hidden, and each list inside it starts hidden.
    assert 'class="queue" id="queue" hidden' in html
    assert html.count('class="queuelist"') == 3
    assert html.count('class="queuelist" data-pane="waiting" hidden') == 1


def test_main_does_not_capture_fixed_children():
    """A transform anywhere above a fixed element re-anchors it.

    `main` carried `animation: settle … both`, and `both` keeps the animation
    applying after it ends — so main was still applying `transform: none`,
    which is enough to make it the containing block for its `position: fixed`
    descendants. The raised panel and its button row were positioned against
    main and stopped 166px short of the bottom of the screen.

    Caught by measuring in a browser, which is the only place it shows.
    """
    from pathlib import Path

    css = (Path("src/aki_agent/dashboard/templates/base.html")
           .read_text(encoding="utf-8"))
    assert "animation: settle 0.18s ease-out both;" not in css, (
        "main is applying a transform after its entrance animation, which "
        "re-anchors every fixed child inside it")


def test_the_quick_actions_reach_every_page():
    """They moved to the rail, so their state has to travel with them.

     The Me time button
    renders its own on/off state, and that state used to be supplied by the
    Today route alone — so in the rail it would have been blank on every
    other page.
    """
    from pathlib import Path

    rail = (Path("src/aki_agent/dashboard/templates/base.html")
            .read_text(encoding="utf-8"))
    assert '{% include "_quick.html" %}' in rail, (
        "the quick actions are not in the rail")

    app_source = (Path("src/aki_agent/dashboard/app.py")
                  .read_text(encoding="utf-8"))
    shared = app_source[app_source.index("def inject_common("):]
    shared = shared[:shared.index("@app.route")]
    assert '"me_time"' in shared, (
        "Me time renders its own state and only Today supplies it, so the "
        "button is blank everywhere else")


def test_the_scrollbars_are_themed_for_both_engines():
    """The scrollbars are themed for both engines.

    Written twice on purpose. `scrollbar-color` is the standard property and
    is what Firefox honours; `::-webkit-scrollbar` is what Chromium and
    Safari read, and they ignore the standard one once a pseudo-element rule
    exists. Neither alone covers the browsers a student might have.
    """
    from pathlib import Path

    css = (Path("src/aki_agent/dashboard/templates/base.html")
           .read_text(encoding="utf-8"))
    assert "scrollbar-color:" in css, "Firefox gets the default grey bar"
    assert "::-webkit-scrollbar-thumb" in css, "Chromium gets the default bar"
