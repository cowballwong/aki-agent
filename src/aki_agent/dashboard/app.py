"""The dashboard web application.

LOCALHOST ONLY, AND THAT IS A DECISION NOT A DEFAULT
----------------------------------------------------
It binds to 127.0.0.1. There is no remote access, no tunnel, no public mode.

Remote access is a support burden and a security surface, and no student needs
it on the first day. The system this package derives from had an
account-bound tunnel integration and an assumption of elevated privileges;
neither comes across.

If someone genuinely needs remote access later, the right answer is a proper
tunnel they choose and control — not a flag in here that quietly exposes a
personal dashboard to a coffee-shop network.

EVERY VIEW DECLARES ITS OWN FRESHNESS
-------------------------------------
Each page says when it read the disk. Where data may be stale, it says so in
words rather than showing a confident number.

That comes from a specific inherited failure: panels that displayed frozen
values — a countdown that had gone negative, a file scan pinned to a folder
name from months earlier — and looked entirely healthy while being wrong.
A panel that shows nothing is fine. A panel that lies is not.
"""

from __future__ import annotations

import dataclasses as _dataclasses
import datetime as _dt
import secrets as _stdlib_secrets
from pathlib import Path

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, url_for)
from flask import session as flask_session

from .. import config as config_module
from .. import dashboard_auth
from .. import dreaming as dreaming_module
from .. import optimising as optimising_module
from .. import semantic as semantic_module
from .. import vectors as vectors_module
from .. import folders as folders_module
from .. import favourites as favourites_module
from .. import me_time as me_time_module
from .. import quiet as quiet_module
from .. import secrets as secrets_module
from .. import telegram_chat as telegram_chat_module
from .. import (apis, approvals, conversation, doctor, events, knowledge,
                memory, notify, panels, paths, recycle, schedule, session,
                retire, scaffold, skills_store, specialists, steps,
                telegram_setup, themes as theme_list, traces,
                workspace)
from ..connectors import files as files_connector
from ..connectors import calendars as calendar_module
from ..connectors import mail
from . import settings

# The only address this ever binds to.
LOCALHOST = "127.0.0.1"
DEFAULT_PORT = 4321

# A token generated fresh each time the dashboard starts.
#
# WHY A DASHBOARD ON 127.0.0.1 STILL NEEDS ONE
# --------------------------------------------
# "It only listens on localhost" protects against the network. It does NOT
# protect against the browser. Any web page the user visits can quietly send a
# request to http://127.0.0.1:4321/ -- the browser will happily deliver it,
# because the page does not need to read the response to do damage. That is
# cross-site request forgery, and a dashboard that can create scheduled tasks
# and write skills is a very attractive target for it.
#
# So every request that CHANGES something must carry this token, which a
# random web page has no way to know. Reading is unprotected; nothing is
# revealed to a page that cannot see the response anyway.
SESSION_TOKEN = _stdlib_secrets.token_urlsafe(24)


def _sandbox_for(loaded, workspace_name: str):
    """The folder the assistant drafts in, as this workspace's page should
    name it.

    From 2026-08-19 there is one sandbox, at the root. A folder built by an
    earlier version has one inside each workspace instead, and those are still
    on disk and still being written to, so that one wins for its own page --
    pointing a person at a sandbox that is not the one their assistant uses is
    worse than showing nothing.
    """
    sandboxes = loaded.layout.sandbox_dirs()
    if not sandboxes:
        return None
    for path in sandboxes:
        if path.parent.name == workspace_name:
            return path
    at_root = (loaded.layout.root / loaded.layout.sandbox_dir
               if loaded.layout.root else None)
    return at_root if at_root in sandboxes else None


def _session_key() -> bytes:
    """The key that signs the login cookie, kept between restarts.

    Regenerated on every start, it would sign everybody out each time the
    dashboard restarts -- which an upgrade does, and an upgrade is exactly the
    moment somebody is already unsure whether anything survived.

    Not a user credential: it signs a cookie that says "this browser answered
    the PIN". It lives with the other state.
    """
    import secrets as _stdlib

    from .. import atomic

    where = paths.app_dir() / "state" / "dashboard-key"
    try:
        kept = where.read_text(encoding="utf-8").strip()
        if len(kept) >= 32:
            return kept.encode("utf-8")
    except OSError:
        pass

    fresh = _stdlib.token_urlsafe(48)
    try:
        paths.ensure_app_dirs()
        atomic.write_text(where, fresh + "\n")
    except OSError:                                       # pragma: no cover
        pass                    # a key held only in memory still works today
    return fresh.encode("utf-8")


# Which tab of /connections each form belongs to.
#
# Every form on that page answers by redirecting back to it with a sentence in
# ?note=. Once the page had tabs, a redirect that named no tab put that
# sentence on Gateway -- so somebody who had just typed a mail password was
# returned to a different tab, with the answer to their own action on a page
# they were not looking at. The page already had that failure once, in a
# different shape: five routes sent a sentence back and none of them was
# displayed at all (see the comment in connections.html).
#
# Keyed by endpoint rather than passed in a hidden field, because the endpoint
# is the one thing a form cannot get wrong.
CONNECTIONS_TAB = {
    "chat_pair_credentials": "gateway",
    "chat_pair_phone": "gateway",
    "chat_pair_code": "gateway",
    "chat_pair_out": "gateway",
    "chat_upload": "gateway",
    "connections_telegram": "gateway",
    "remote_access": "gateway",
    "connections_mail": "mail",
    "connections_mail_forget": "mail",
    "connections_calendar": "calendar",
    "connections_calendar_forget": "calendar",
    "connections_google_credentials": "calendar",
    "connections_google_connect": "calendar",
    "connections_google_callback": "calendar",
    "connections_google_disconnect": "calendar",
}


def back_to_connections(note: str = "", tab: str = ""):
    """Back to the tab this form was submitted from, carrying its answer."""
    where = tab or CONNECTIONS_TAB.get(request.endpoint or "", "gateway")
    extra = {"note": note} if note else {}
    return redirect(url_for("connections", tab=where, **extra))


def _plugin_rows() -> list:
    """Installed plugins, reloaded so the page reflects what is on disk now.

    Forced rather than memoised: this is the one page where somebody has just
    changed what is installed, and a cached answer would show them the state
    before their own click.
    """
    from .. import plugins as plugins_module

    found, _problems = plugins_module.load_all(force=True)
    rows = []
    for one in found:
        rows.append({
            "name": one.name,
            "version": one.version,
            "description": one.description,
            "registered": list(one.registered),
            "contents": one.contents,
            "problem": one.problem,
            "path": str(one.path),
        })
    return rows


def _workflow_rows() -> tuple[list, list]:
    """Installed workflows, read fresh.

    Forced rather than memoised for the same reason the plugin panel is: this
    is the page where somebody has just changed what is installed, and a cached
    answer would show them the state before their own click.

    Nothing is imported to build this. A workflow is described from its
    manifest, so one with a syntax error in it still lists cleanly and says so
    when you try to run it.
    """
    from .. import workflows as workflows_module

    found, problems = workflows_module.installed()
    rows = []
    for one in found:
        rows.append({
            "name": one.name,
            "title": one.title,
            "version": one.version,
            "description": one.description,
            "entry": one.entry,
            "deliverable": one.deliverable,
            "gates": list(one.gates),
            "requires": list(one.requires),
            "counts": one.counts,
            "problem": one.problem,
            "path": str(one.path),
            # BOTH OF THESE MUST BE HERE, and the reason is worth the note.
            #
            # The page is handed dicts, not `Workflow` objects. Jinja asking
            # a dict for `one.on` finds neither an attribute nor a key and
            # answers Undefined, which is falsy -- so adding the switch to
            # the model and forgetting this line made every row draw as
            # "off" and the button do nothing visible. It does not raise; it
            # renders a page that quietly says the opposite of the truth.
            "on": one.on,
            "from_plugin": one.from_plugin,
        })
    return rows, problems


def _pending_workflow(source: str):
    """What a folder or zip WOULD install, for the confirmation step.

    Copies nothing, and cleans up the temporary folder a zip needed before
    returning -- the answer is text, so there is nothing to keep.
    """
    from .. import workflows as workflows_module

    source = (source or "").strip()
    if not source:
        return None

    candidate = workflows_module.examine(source)
    try:
        if candidate.workflow is None:
            return {"source": source, "problem": candidate.problem}
        one = candidate.workflow
        return {
            "source": source,
            "name": one.name,
            "title": one.title,
            "version": one.version,
            "description": one.description,
            "deliverable": one.deliverable,
            "gates": list(one.gates),
            "counts": one.counts,
            "warnings": list(candidate.warnings),
            "problem": "",
        }
    finally:
        workflows_module.cleanup(candidate)


def _pending_plugin(source: str):
    """What a folder or zip WOULD install, for the confirmation step.

    Returns a small dict the template can render, or None. Nothing is copied
    and the temporary folder a zip needed is cleaned up before returning --
    the answer is text, so there is nothing to keep.
    """
    from .. import plugins as plugins_module

    source = (source or "").strip()
    if not source:
        return None

    candidate = plugins_module.examine(source)
    try:
        if candidate.plugin is None:
            return {"source": source, "problem": candidate.problem}
        return {
            "source": source,
            "name": candidate.plugin.name,
            "version": candidate.plugin.version,
            "description": candidate.plugin.description,
            "provides": list(candidate.plugin.provides),
            "contents": candidate.plugin.contents,
            "warnings": list(candidate.warnings),
            "problem": "",
        }
    finally:
        plugins_module.cleanup(candidate)


def create_app(config_path: Path | None = None) -> Flask:
    """Build the application.

    `config_path` exists so the two-config demonstration can run the real
    dashboard against either example configuration -- which is what proves the
    claim rather than merely asserting it.
    """
    app = Flask(__name__)
    app.config["PERSONAL_AGENT_CONFIG_PATH"] = config_path

    # Signs the login cookie. Kept in the state folder so a restart -- which
    # every upgrade causes -- does not sign everybody out mid-afternoon.
    app.secret_key = _session_key()

    def load_config():
        loaded = config_module.load(app.config["PERSONAL_AGENT_CONFIG_PATH"])
        # The `providers:` block decides which channel, calendar and so on
        # this installation loads, and the dashboard has to agree with the
        # command line about that or the two disagree about whether Telegram
        # is on. Problems are not raised here: this is the process somebody
        # uses to *fix* the file, so it keeps running. `seams.apply` discards
        # a list it could not fully honour, and `aki inspect` says what is
        # wrong with it.
        from .. import seams

        seams.apply(loaded)
        return loaded

    # -- the door ----------------------------------------------------------

    # `/sw.js` and the manifest are open on purpose, and the reason is a bug
    # that was found on the Surface on 2026-09-01 rather than reasoned about:
    # behind the PIN they answered 200 with the login PAGE, so the browser was
    # handed HTML where it expected JavaScript and the service worker simply
    # never registered -- no error, no notifications, nothing to see. Neither
    # file carries anything of his: the manifest is a name and two icons, and
    # the worker is static code that does nothing until a push arrives, and a
    # push has to be signed by the key that never leaves this machine.
    OPEN_TO_EVERYONE = ("/login", "/login/forgot", "/first-pin", "/static/",
                        "/sw.js", "/manifest.webmanifest")

    @app.before_request
    def require_the_pin():
        """Nothing is shown to somebody who has not entered the PIN.

        Reads included, and that is the point: the pages carry held email, the
        calendar, the chat panel, the day's memory. A login that guarded only
        the buttons would be decoration.

        The dashboard was already loopback-only, so this is not about the
        network. It is about everybody else who can reach this machine -- a
        family member, a shared desk, five unlocked minutes, another program
        on the box.
        """
        path = request.path
        if any(path == one or path.startswith(one)
               for one in OPEN_TO_EVERYONE):
            return None
        if not flask_session.get("in"):
            return redirect(url_for("login", next=path))
        # A PIN nobody has changed is the one printed in the instructions.
        if dashboard_auth.is_default() and path != "/first-pin":
            return redirect(url_for("first_pin"))
        return None

    # -- the guard on everything that changes something --------------------

    def _came_from_away() -> bool:
        """Did this request arrive through the declared remote name?

        The same reading `guard_mutations` does, in one place, so the login
        route cannot drift from the guard: anything that is not plain
        loopback got here because remote access is on and named this host.
        """
        host = (request.host or "").split(":")[0].lower()
        if host in ("127.0.0.1", "localhost", "::1", ""):
            return False
        from .. import exposure as exposure_module
        return exposure_module.allows(request.host or "")

    @app.before_request
    def guard_mutations():
        """Refuse anything that does not prove it came from this machine.

        Three checks, because each catches what the others miss:

          * the Host, which says the request was addressed to this computer
          * the token, which a foreign page cannot know
          * the Origin header, which a foreign page cannot forge

        A request failing any of them is rejected outright rather than
        partially handled. There is no useful "maybe" here.
        """
        # Fail closed if this did not arrive locally -- FOR READS TOO.
        #
        # Binding to loopback stops the network, but not a tunnel: put a
        # reverse proxy or an ngrok-style tunnel in front and every request
        # still arrives from 127.0.0.1, wearing forwarding headers. On the
        # reference system that exact arrangement made a control surface --
        # including the house lights -- reachable from outside with no
        # password at all. It was found afterwards, which is the wrong time.
        #
        # THIS CHECK USED TO SIT BELOW THE GET EARLY-RETURN (fixed
        # 2026-08-23). The comment beside it read "Reading is left alone; the
        # danger is writes", and that reasoning is what was wrong. Under DNS
        # rebinding a page the user is merely visiting resolves its own
        # domain to 127.0.0.1 and then reads this dashboard same-origin: the
        # held email, the calendar, the chat panel that every page carries,
        # the daily memory log, the house rules, the Telegram allowlist, the
        # MCP command lines. Writes were safe and everything else was not.
        #
        # A request addressed to a host that is not this machine has no
        # business reading either.
        forwarded = any(request.headers.get(header) for header in
                        ("X-Forwarded-For", "X-Real-IP", "X-Forwarded-Host",
                         "Forwarded"))
        host = (request.host or "").split(":")[0].lower()
        local_host = host in ("127.0.0.1", "localhost", "::1", "")

        # THE ONE NAMED EXCEPTION (reported 2026-08-28)
        # -------------------------------------------
        # He wants users to reach this from away from the desk. The exception
        # is deliberately not "trust the forwarding headers": those are set by
        # the client, and trusting them is the hole that was found. Instead the
        # user declares the single hostname their tunnel hands out, and only
        # that exact name is answered. See `exposure.py`.
        #
        # This keeps the rebinding path shut as well: a page that re-resolves
        # its own domain to 127.0.0.1 arrives wearing ITS name in Host, which
        # is not the declared one.
        from .. import exposure as exposure_module
        declared = exposure_module.allows(request.host or "")

        if not declared and (forwarded or not local_host):
            abort(403, "This dashboard only answers requests made on this "
                       "computer, not through a proxy, a tunnel, or another "
                       "name for this machine.")

        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None

        supplied = (request.form.get("token")
                    or request.headers.get("X-Dashboard-Token", ""))
        if not _stdlib_secrets.compare_digest(supplied, SESSION_TOKEN):
            abort(403, "This change did not come from the dashboard.")

        origin = request.headers.get("Origin")
        if origin:
            allowed = origin.startswith((f"http://{LOCALHOST}:",
                                         "http://localhost:"))
            if not allowed:
                # Same rule as the Host check: the declared tunnel name, and
                # nothing that merely resembles it.
                from urllib.parse import urlsplit
                allowed = exposure_module.allows(urlsplit(origin).hostname or "")
            if not allowed:
                abort(403, "This change came from somewhere else.")

        return None

    def _remote_state():
        """The whole state, for the page that switches it."""
        try:
            from .. import exposure as exposure_module
            return exposure_module.state()
        except Exception:                                 # noqa: BLE001
            return None

    def _remote_banner() -> str:
        """One line for the banner, or "" when nothing is exposed."""
        try:
            from .. import exposure as exposure_module
            current = exposure_module.state()
            if current.on and current.host:
                return current.host
        except Exception:                                 # noqa: BLE001
            pass
        return ""

    # -- shared context ----------------------------------------------------

    @app.context_processor
    def inject_common():
        from .. import __version__

        from . import navigation

        # Read once. `open_items` is a folder walk, and the counts, the pills
        # and the sheet's three lists are all views of the same answer.
        open_items = approvals.open_items()

        counts = {
            "held_count": notify.held_count(),
            "pending_count": conversation.pending_count(),
            "waiting_count": len(open_items),
        }

        common = {
            **counts,
            "nav_groups": navigation.GROUPS,
            "nav_here": navigation.current(request.path),
            "nav_counts": counts,
            "read_at": _dt.datetime.now(),
            "token": SESSION_TOKEN,
            # A door that is open and does not look open is the state
            # exposure.py exists to avoid, so this rides on every page.
            "remote_access": _remote_banner(),
            "remote_state": _remote_state(),
            "version": __version__,
            # Which projects are on Today, so the item table can draw a pin
            # that knows its own state. Shared rather than threaded through
            # the two routes that render that table, because a control that
            # only one of them passes the state for is a control that works
            # on one page and not the other.
            "pinned": {key: True for key in favourites_module.read_pins()},
            # The three quick actions moved into the rail, so their state has
            # to reach every page rather than only Today.
            "me_time": me_time_module.read(),
            # The sentence, not the object. It needs the config to say
            # whether there is a mailbox to watch, and the template has no
            # config -- so composing it there would mean the copy quietly
            # falling back to the version that cannot tell.
            "me_time_says": "",
            # For the queue rows: a due date only means something against a
            # today, and the row is the wrong place to work out what today is.
            "today_iso": _dt.date.today().isoformat(),
            # THE QUEUE BAR AND ITS SHEET RIDE ON EVERY PAGE.
            #
            # They were rendered by Today alone, so
            # walking to Settings left the three counts behind -- and the bar
            # is the thing that says something needs you, which is least
            # useful on the one page you were already looking at.
            #
            # Named `queue_*` rather than `waiting` / `held` / `drafted`,
            # because `held` already means something else on two other pages
            # -- `notify.read_held()` on Notifications and Inbox, a different
            # shape entirely. A shared name would have been overridden there
            # by each page's own kwargs and fed the wrong objects to the
            # sheet, on exactly the two pages nobody would think to check.
            "queue_waiting": [_for_the_sheet(one) for one in open_items
                              if one.kind == "waiting"],
            "queue_action": [_for_the_sheet(one) for one in open_items
                             if one.kind == "question"],
            "queue_drafted": [_for_the_sheet(one) for one in open_items
                              if one.kind == "draft"],
            "queue_new": approvals.unseen_counts(),
            "workspace_ok": False,
        }
        try:
            loaded = load_config()
            common.update({
                "me_time_says": common["me_time"].sentence(loaded),
                "assistant_name": loaded.assistant.name,
                "assistant_mark": loaded.assistant.initials(),
                # Validated before it reaches the stylesheet. A settings field
                # written straight into CSS is a settings field that can close
                # the rule early and inject.
                "accent": loaded.assistant.safe_colour(),
                "ground": theme_list.ground_for(loaded.assistant.safe_colour()),
                # The whole theme, not just its ground: the stylesheet reads
                # its fonts, corners and shadow too.
                "theme": (theme_list.matching(loaded.assistant.safe_colour())
                          or theme_list.DEFAULT),
                "user_name": loaded.user.name,
                "item_label": loaded.layout.schema.item_label,
                "item_label_plural": loaded.layout.schema.item_label_plural,
                # What the front page is a list *of*. With more than one
                # workspace it lists workspaces and the projects are one click
                # in; with one it lists the projects themselves, and calling
                # the link "Workspaces" would be a promise of a page that adds
                # nothing.
                "nav_label": ("Workspaces"
                              if len(loaded.layout.workspaces) > 1
                              else loaded.layout.schema.item_label_plural),
                "workspace_ok": bool(loaded.layout.root
                                     and loaded.layout.root.exists()),
            })
            # The rail carries the user's own word for their work.
            common["nav_groups"] = navigation.for_label(
                common["nav_label"])
            common["nav_here"] = navigation.current(
                request.path, common["nav_groups"])
        except config_module.ConfigError:
            common.update({
                "assistant_name": "Not set up yet",
                "assistant_mark": "?",
                "accent": "#67e8f9",
                "ground": "dark",
                "theme": theme_list.DEFAULT,
                "user_name": "",
                "item_label": "Item",
                "item_label_plural": "Items",
                "nav_label": "Items",
            })
        return common

    @app.template_filter("js")
    def _js_string(value) -> str:
        """A name safe to drop inside a single-quoted JavaScript string.

        Every `onsubmit="return confirm('Delete {{ name }}?')"` in this
        package interpolated the name raw. Jinja escapes `'` to `&#39;` for
        HTML, and the browser turns it back into `'` before the JS engine
        ever sees it -- so a task called "Check O'Brien's folder" produced
        `confirm('Delete Check O'Brien's folder?')`, a syntax error, a handler
        that never ran, and a Delete button that deleted without asking
        anything. Only for people whose names contain an apostrophe, which is
        most of Ireland and a good deal of everywhere else.

        `| tojson` is the usual advice and is wrong HERE: it wraps the value
        in DOUBLE quotes, which close the `onsubmit="..."` attribute itself.
        Checked, rather than assumed -- it renders
        `onsubmit="return confirm('Delete ' + "O\\u0027Brien\\u0027s folder" + '?')"`.

        So: escape for the JS string, and let Jinja's autoescaping handle the
        attribute as it already does.
        """
        text = str(value)
        # Backslash first, or it doubles the ones added after it.
        for old, new in (("\\", "\\\\"), ("'", "\\'"), ("\n", "\\n"),
                         ("\r", ""), (" ", "\\u2028"),
                         (" ", "\\u2029")):
            text = text.replace(old, new)
        return text

    # -- pages -------------------------------------------------------------

    @app.template_filter("weather_kind")
    def _weather_kind(description) -> str:
        """Which shape to draw for a described sky.

        The judgement lives in `today.weather_kind`, because the advice line
        under the icon asks the same question and two copies of it is how a
        sun ends up over the words "take an umbrella".
        """
        from .. import today as today_module

        return today_module.weather_kind(description)

    @app.template_filter("lines_starting")
    def _lines_starting(section, prefix) -> int:
        """Count the lines of a section that begin with a prefix.

        Jinja has no `match` test -- the first version of the project card
        used `select('match', ...)` and compiled cleanly, then raised
        `No test named 'match'` on the first real render. A filter that calls
        the same function the favourite cards call cannot drift from them and
        cannot fail at render time for a reason a template cannot express.
        """
        return favourites_module.count_lines(section or "", prefix)

    @app.template_filter("tokens")
    def _tokens(value) -> str:
        """1,234,567 -> 1.2M. A landing page is read at a glance."""
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            return str(value)
        for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"),
                             (1_000, "K")):
            if number >= size:
                trimmed = number / size
                return f"{trimmed:.1f}".rstrip("0").rstrip(".") + suffix
        return str(int(number))

    def _pickable(space) -> list:
        """Every project, grouped by workspace, with whether it is on Today.

        Shaped here rather than in the template because Jinja cannot group,
        and because `by_workspace()` is the workspace's own answer to "what
        belongs together" -- a second grouping written in a template is a
        second answer that drifts.
        """
        if space is None:
            return []

        pinned = set(favourites_module.read_pins())
        groups = []
        try:
            for name, _schema, items in space.by_workspace():
                # An empty workspace belongs on the workspace list, where it
                # can be opened and filled. It does not belong in a picker of
                # projects to put on Today, where it would be a heading with
                # nothing under it.
                if not items:
                    continue
                groups.append({
                    "name": name,
                    # `projects`, NOT `items`. Jinja resolves `group.items` to
                    # the dict's own `.items` METHOD before it looks for a key
                    # of that name, so the template iterated a built-in and
                    # died with "'builtin_function_or_method' object is not
                    # iterable" -- on the landing page, for every visitor.
                    "projects": [{"key": one.key, "title": one.title,
                                  "pinned": one.key in pinned}
                                 for one in items],
                })
        except Exception:                                 # noqa: BLE001
            # A workspace that cannot be grouped still has items. Falling back
            # to one unnamed group beats a Today page that will not render.
            groups = [{"name": "", "projects": [
                {"key": one.key, "title": one.title,
                 "pinned": one.key in pinned}
                for one in getattr(space, "items", []) or []]}]
        return [group for group in groups if group["projects"]]

    def _for_the_sheet(item) -> dict:
        """One waiting item, shaped for the sheet that opens over Today.

        Built here rather than in the template because Jinja has no list
        comprehension, and because deciding what a view needs is the view's
        job. The options carry only key and label: `approvals.answer` refuses
        anything that is not one of the item's own declared options, so an
        option invented at render time would produce a button that always
        fails.
        """
        return {
            "id": item.id,
            "title": item.title,
            "body": item.body,
            "kind": item.kind,
            "due": item.due,
            "project": item.project,
            "waiting_on": item.waiting_on,
            # Set only on drafts, and only when the draft check is on.
            "checked": item.checked,
            "created_at": item.created_at,
            "options": [{"key": one.key, "label": one.label}
                        for one in item.options],
        }

    @app.route("/")
    def today_page():
        """The landing page: usage, weather, what is waiting, the calendar."""
        import datetime as when_module

        from .. import today as today_module

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        page = today_module.gather(loaded)
        today = when_module.date.today()

        # A calendar you can walk through.
        #
        # Bounded to six months either way rather than infinite: past that the
        # subscription has nothing to show, and arrows that keep going into
        # empty months tell somebody the calendar is broken.
        shown = today_module.month_from(request.args.get("m", ""), today)
        picked = today_module.day_from(request.args.get("d", ""), today)

        busy = {event.start.date() for event in page.events
                if event.start is not None}

        # The six cards and the three columns.
        #
        # `favourites` is built from the SAME scan the rest of the page uses,
        # not a second one -- two scans of a folder tree taken a second apart
        # can disagree, and the disagreement would show as a card that is on
        # the page but not in the count beside it.
        try:
            space = workspace.scan(loaded)
        except Exception:                                    # noqa: BLE001
            space = None

        return render_template(
            "today.html",
            page=page,
            note=request.args.get("note", ""),
            me_time=me_time_module.read(),
            favourites=(favourites_module.cards_for(space) if space else []),
            favourites_max=favourites_module.HOW_MANY,
            # How many are PINNED, which is not always how many are drawn:
            # a pin whose project has been renamed is skipped as a card but
            # still counts against the six. Gating the `+` on the cards would
            # offer a button that `pin()` can only refuse.
            favourites_pinned=len(favourites_module.read_pins()),
            # Pins whose project is not there to draw. They still count
            # against the six, so at the cap they are why the `+` card has
            # gone and nothing on the page says so. five cards, six pins, one
            # of them pointing at a folder he had renamed in Explorer.
            favourites_lost=favourites_module.missing_pins(space),
            # Everything that COULD go on Today, grouped the way the workspace
            # groups itself. Built from the same scan as the cards, so the
            # picker and the row can never disagree about what exists.
            pickable=_pickable(space),
            # The three queues are in the shared context now, under
            # `queue_*`, because the bar that shows them is on every page.
            weeks=today_module.month_grid(shown),
            month_name=shown.strftime("%B %Y"),
            month_key=shown.strftime("%Y-%m"),
            previous_month=today_module.step_month(shown, -1, today),
            next_month=today_module.step_month(shown, +1, today),
            today_date=today,
            picked_day=picked,
            day_events=today_module.events_on(page.events, picked),
            busy_days=busy,
        )

    @app.route("/projects")
    def index():
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        space = workspace.scan(loaded)

        # The summary strip groups by the first enum field the user declared,
        # whatever it happens to be. If they declared none, there is no strip
        # -- which is correct, not a missing feature.
        grouping_field = next(
            (field for field in loaded.layout.schema.fields
             if field.type == "enum"), None)
        groups = (space.count_by_field(grouping_field.key)
                  if grouping_field else {})

        # With one workspace this page IS that workspace's screen -- the
        # detail page is never reached, so panels declared for it would
        # otherwise be invisible on exactly the simplest install.
        shown = []
        if len(loaded.layout.workspaces) <= 1:
            only = loaded.layout.workspaces[0] if loaded.layout.workspaces else None
            folder = (loaded.layout.resolved_workspaces().get(only) if only
                      else loaded.layout.work_root())
            shown = [panels.render(panel, space.items)
                     for panel in panels.panels_for(folder, space.items)]

        return render_template(
            "index.html",
            panels=shown,
            space=space,
            # Where the workspaces actually are. `space.root` is the
            # assistant's own folder, one level up, and printing that as
            # "Folder:" sent the maintainer looking in the wrong place.
            work_root=loaded.layout.work_root(),
            fields=[field for field in loaded.layout.schema.fields],
            grouping_field=grouping_field,
            groups=groups,
            sandboxes={path.name: path
                       for path in loaded.layout.sandbox_dirs()},
            # From the config, not from the scan: a workspace with
            # nothing in it yet is exactly the one somebody wants to
            # remove, and it appears in no group.
            workspaces=loaded.layout.workspaces,
        )

    # `path:` because a workspace name may itself be a path -- a real install
    # produced `01_Work/02_Piano`.
    @app.route("/workspace/<path:name>")
    def workspace_detail(name: str):
        """One workspace, and the projects in it.

        The front page is the list of workspaces; this is what opens when one
        is clicked (reported 2026-08-17). With one workspace the front page shows
        its projects directly and this page is simply never needed -- a person
        with one kind of work should not have to click through a list of one.
        """
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        space = workspace.scan(loaded)
        items = [item for item in space.items if item.workspace == name]
        if not items and name not in loaded.layout.workspaces:
            abort(404)

        schema = loaded.layout.schema_for(name)

        # The workspace's own screen. Panels are declared, never coded -- see
        # `panels.py`. A workspace that declares none and holds no panel data
        # gets an empty list and the page below is exactly what it was.
        folder = loaded.layout.resolved_workspaces().get(name)
        shown = [panels.render(panel, items)
                 for panel in panels.panels_for(folder, items)]

        return render_template(
            "workspace.html",
            space=space,
            name=name,
            items=items,
            schema=schema,
            panels=shown,
            sandbox=_sandbox_for(loaded, name),
        )

    # `path:` because an item key carries its workspace -- "01_Work/Project 1".
    # Without it the slash ends the segment and every item in a workspace 404s.
    @app.route("/item/<path:key>")
    def item_detail(key: str):
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        space = workspace.scan(loaded)
        item = space.item_by_key(key)
        if item is None:
            abort(404)

        return render_template("item.html", item=item, space=space)

    @app.route("/workspace/new", methods=["POST"])
    def workspace_new():
        """Add a workspace, and record it in the config in the same breath.

        Both from one action on purpose: the config saying `work` while the
        folder is called `01_work` is the mismatch that gave two real installs
        an empty dashboard with nothing reporting an error.
        """
        name = request.form.get("name", "").strip()
        if not name:
            return redirect(url_for("index"))

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        root = loaded.layout.root
        if not root:
            return redirect(url_for("index"))

        wanted = tuple(loaded.layout.workspaces) + (name,)
        the_plan = scaffold.plan(root, workspaces=wanted,
                                 schema=loaded.layout.schema,
                                 with_examples=False)
        scaffold.build(the_plan, confirmed=True, schema=loaded.layout.schema,
                       assistant_name=loaded.assistant.name,
                       user_name=loaded.user.name)

        if loaded.layout.workspaces != the_plan.workspaces:
            loaded.layout.workspaces = the_plan.workspaces
            config_module.save(loaded)

        return redirect(url_for("index"))

    @app.route("/workspace/rename", methods=["POST"])
    def workspace_rename():
        """Rename any number of workspaces in one go.

        One Edit button turns every name into a field, and Save sends them
        all together -- so this takes parallel lists rather than one pair.

        Folder and config move together, or neither does. The reason is at
        the top of `workspace_new`: a config saying `work` beside a folder
        called `01_work` is the mismatch that gave two real installs an empty
        dashboard with nothing reporting an error.
        """
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        # `getlist` keeps browser order, so the two lists line up.
        before = request.form.getlist("was")
        wanted = request.form.getlist("to")

        done: list[str] = []
        refused: list[str] = []
        for old_name, new_name in zip(before, wanted):
            old_name, new_name = old_name.strip(), new_name.strip()
            if not new_name or new_name == old_name:
                continue
            ok, said = workspace.rename_workspace(loaded, old_name, new_name)
            if ok:
                favourites_module.rename_workspace_in_pins(old_name, new_name)
                done.append(f"{old_name} → {new_name}")
            else:
                refused.append(f"{old_name}: {said}")

        if done:
            # Saved once, after the folders have actually moved. A save per
            # rename would leave the config half-written if the third one
            # failed.
            config_module.save(loaded)

        if not done and not refused:
            said = "Nothing was renamed."
        else:
            parts = []
            if done:
                parts.append("Renamed " + "; ".join(done) + ".")
            if refused:
                parts.append("Not renamed — " + " ".join(refused))
            said = " ".join(parts)

        return redirect(url_for("index", said=said))

    @app.route("/workspace/refresh", methods=["POST"])
    def workspace_refresh():
        """Read the folders again, and make the config match them.

        For when somebody renamed a folder in Explorer rather than here.

        Nothing on disk is touched. A button called Refresh must never be the
        one that deletes a folder.
        """
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        changed, said = workspace.rescan_workspaces(loaded)
        if changed:
            config_module.save(loaded)

        return redirect(url_for("index", said=said))

    @app.route("/workspace/remove", methods=["POST"])
    def workspace_remove():
        """Retire a workspace. The typed name is the second confirmation."""
        name = request.form.get("name", "").strip()
        typed = request.form.get("confirm", "")

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        root = loaded.layout.root
        sandboxes = loaded.layout.sandbox_dirs()
        if not root or not sandboxes or not name:
            return redirect(url_for("index"))

        # Under the work folder, not the root: `03_Workspace/01_Work`.
        # Built from the root it named a folder that does not exist, so
        # the removal quietly did nothing and reported success.
        base = loaded.layout.work_root() or Path(root)
        the_plan = retire.plan(Path(base) / name, sandboxes[0],
                               f"The {name} workspace")
        ok, message = retire.perform(the_plan, typed)

        if ok:
            loaded.layout.workspaces = tuple(
                space for space in loaded.layout.workspaces if space != name)
            config_module.save(loaded)

        return redirect(url_for("index", said=message))

    def _title_of(loaded, key: str) -> str:
        """What this item is called on screen right now, or "" if it is gone."""
        found = workspace.scan(loaded).item_by_key(key)
        return found.title if found is not None else ""

    @app.route("/item/refresh", methods=["POST"])
    def item_refresh():
        """Take every name in this workspace from its folder.

        The companion to the workspaces list's own Refresh, and the same
        promise: nothing on disk is created, moved or deleted.
        """
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        which = request.form.get("workspace", "").strip()
        back = request.form.get("back") or url_for("index")
        _, said = workspace.refresh_titles(loaded, which)
        return redirect(f"{back}{'&' if '?' in back else '?'}said={said}")

    @app.route("/item/rename", methods=["POST"])
    def item_rename():
        """Rename any number of projects in one go.

        The same shape as `/workspace/rename`, because the maintainer asked for the
        same behaviour.
        """
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        keys = request.form.getlist("was")
        wanted = request.form.getlist("to")
        back = request.form.get("back") or url_for("index")

        done: list[str] = []
        refused: list[str] = []
        for key, new_name in zip(keys, wanted):
            key, new_name = key.strip(), new_name.strip()
            if not new_name:
                continue
            # SKIPPED ONLY WHEN NOTHING WOULD CHANGE, which means the
            # folder AND the title already read that way.
            #
            # It used to compare the folder alone. The field showed the folder
            # name too, so on a project whose `state.md` still said
            # `01_Project 1` the box opened with `01_Travel` already in it,
            # Save found no difference, and the page went on showing the
            # stale one.
            folder = key.split("/")[-1]
            current = _title_of(loaded, key)
            if new_name == folder and new_name == current:
                continue

            ok, said = workspace.rename_item(loaded, key, new_name)
            if ok:
                head = key.rsplit("/", 1)[0] if "/" in key else ""
                favourites_module.rename_key_in_pins(
                    key, f"{head}/{new_name}" if head else new_name)
                # Reported by the name that was ON SCREEN, not the folder.
                # Reporting the folder produced "Renamed 01_Sermon ->
                # 01_Sermon" for a project that had just stopped calling
                # itself 01_Project 1 -- true about the half nobody was
                # looking at.
                done.append(f"{current or folder} -> {new_name}")
            else:
                refused.append(f"{current or folder}: {said}")

        if not done and not refused:
            said = "Nothing was renamed."
        else:
            parts = []
            if done:
                parts.append("Renamed " + "; ".join(done) + ".")
            if refused:
                parts.append("Not renamed - " + " ".join(refused))
            said = " ".join(parts)

        return redirect(f"{back}{'&' if '?' in back else '?'}said={said}")

    @app.route("/item/new", methods=["POST"])
    def item_new():
        name = request.form.get("name", "").strip()
        space_name = request.form.get("workspace", "").strip()
        if not name:
            return redirect(url_for("index"))

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        root = loaded.layout.root
        if not root:
            return redirect(url_for("index"))

        the_plan = scaffold.plan_project(root, space_name, name,
                                         schema=loaded.layout.schema_for(space_name))
        if the_plan.warning or the_plan.is_empty:
            return redirect(url_for("workspace_detail", name=space_name))

        scaffold.build(the_plan, confirmed=True,
                       schema=loaded.layout.schema_for(space_name),
                       assistant_name=loaded.assistant.name,
                       user_name=loaded.user.name)
        return redirect(url_for("workspace_detail", name=space_name))

    @app.route("/item/remove", methods=["POST"])
    def item_remove():
        """Retire one project. Moved into the sandbox, never deleted."""
        space_name = request.form.get("workspace", "").strip()
        folder = request.form.get("folder", "").strip()
        typed = request.form.get("confirm", "")

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        root = loaded.layout.root
        sandboxes = loaded.layout.sandbox_dirs()
        if not root or not sandboxes or not folder:
            return redirect(url_for("index"))

        base = loaded.layout.work_root() or Path(root)
        the_plan = retire.plan(Path(base) / space_name / folder,
                               sandboxes[0], folder)
        _, message = retire.perform(the_plan, typed)
        return redirect(url_for("workspace_detail", name=space_name,
                                said=message))

    def _stop_serving() -> None:
        """End this process, a moment from now.

        Werkzeug removed `werkzeug.server.shutdown` in 2.1, and there is no
        replacement that works for the plain `app.run()` this uses. So: reply
        first, then leave. The delay is what lets the reply reach the browser
        -- killing the process inside the request handler shows the person a
        connection error and leaves them wondering whether it worked.

        `os._exit` rather than `sys.exit`: this runs on a timer thread, where
        SystemExit would end the thread and nothing else.
        """
        import os
        import threading

        threading.Timer(0.7, lambda: os._exit(0)).start()

    @app.route("/shutdown", methods=["POST"])
    def shutdown():
        """Stop the dashboard. The assistant itself is untouched."""
        app.config["PERSONAL_AGENT_STOPPER"]()
        return render_template("stopped.html")

    app.config["PERSONAL_AGENT_STOPPER"] = _stop_serving

    @app.route("/safety")
    def safety_page():
        """What the gate refuses, and what it has refused.

        The second half is new. The gate has blocked irreversible commands
        since it was written and kept no record, so "it has never fired" and
        "it fired last Tuesday and saved your documents" looked identical.
        """
        from .. import safety_gate

        return render_template(
            "safety.html",
            hard_rules=safety_gate.describe(),
            blocked=safety_gate.recent(),
            log_path=safety_gate.log_file(),
        )

    @app.route("/update", methods=["POST"])
    def update_now():
        """Move to a newer release, then stop, so the new code is what runs."""
        from .. import engine

        source, problem = engine.source_for_upgrade(None)
        if source is None:
            return render_template("updated.html", lines=[problem], ok=False)

        lines = [f"Upgrading from {engine.version_of(source) or 'unknown'} "
                 f"in {source}"]
        the_plan = engine.plan(source=source)

        ok, message = engine.copy_engine(the_plan)
        lines.append(message)
        if ok:
            ok, message = engine.reinstall(the_plan.target)
            lines.append(message)
        if ok:
            lines += engine.refresh_plugin(the_plan.target)

        if ok:
            # Serving from a folder that has just been replaced is asking for
            # a half-old page. Stopping is the honest end of this action.
            app.config["PERSONAL_AGENT_STOPPER"]()

        return render_template("updated.html", lines=lines, ok=ok)

    @app.route("/workflows")
    def workflows_page():
        """Whole jobs the assistant can run, and what installing one means."""
        rows, problems = _workflow_rows()
        from .. import workflows as workflows_module
        return render_template(
            "workflows.html",
            workflows=rows,
            workflow_problems=problems,
            workflows_dir=workflows_module.workflows_dir(),
            pending=_pending_workflow(request.args.get("check", "")),
            note=request.args.get("note", ""),
            # Open while adding, and open again while looking at what was
            # picked -- otherwise pressing "Look at it" would close the sheet
            # and drop the answer behind it.
            showing_form=bool(request.args.get("add")
                              or request.args.get("check")),
        )

    @app.route("/workflows/check", methods=["POST"])
    def workflows_check():
        """Look at a folder or zip and show what installing it WOULD add."""
        return redirect(url_for("workflows_page",
                                check=request.form.get("source", "")))

    @app.route("/workflows/switch", methods=["POST"])
    def workflows_switch():
        """On or off.

        Off leaves everything on disk and only stops it being run -- which is
        the control a plugin's workflow needs, since removing one of those
        would delete part of the plugin.
        """
        from .. import workflows as workflows_module

        _ok, message = workflows_module.set_on(
            request.form.get("name", ""),
            request.form.get("state") == "on")
        return redirect(url_for("workflows_page", note=message))

    @app.route("/workflows/add", methods=["POST"])
    def workflows_add():
        """Install, having shown what it contains. Nothing in it runs now."""
        from .. import workflows as workflows_module

        candidate = workflows_module.examine(request.form.get("source", ""))
        try:
            if candidate.workflow is None:
                return redirect(url_for("workflows_page", note=candidate.problem))
            ok, message = workflows_module.install(candidate)
        finally:
            workflows_module.cleanup(candidate)
        return redirect(url_for("workflows_page", note=message))

    @app.route("/workflows/remove", methods=["POST"])
    def workflows_remove():
        from .. import workflows as workflows_module

        ok, message = workflows_module.remove(request.form.get("name", ""))
        return redirect(url_for("workflows_page", note=message))

    @app.route("/workflows/run", methods=["POST"])
    def workflows_run():
        """Run one, and say plainly that this is somebody else's code.

        Synchronous on purpose for now: a workflow that wants to run for an
        hour belongs behind the scheduler, and pretending a long job finished
        because a page returned would be worse than making the wait visible.
        """
        from .. import workflows as workflows_module

        name = request.form.get("name", "")
        code, message = workflows_module.run(name)
        if message:
            note = message
        elif code == 0:
            note = f"{name} finished."
        else:
            note = f"{name} stopped with code {code}. Its own output says why."
        return redirect(url_for("workflows_page", note=note))

    @app.route("/library")
    def library_page():
        """Everything the package ships, filtered."""
        from .. import library as library_module

        found = library_module.search(
            query=request.args.get("q", ""),
            category=request.args.get("category", ""),
            industry=request.args.get("industry", ""),
            kind=request.args.get("kind", ""))

        return render_template(
            "library.html",
            items=found,
            total=len(library_module.catalogue()),
            active=library_module.active_keys(),
            categories=library_module.categories(),
            industries=library_module.industries(),
            chosen={"q": request.args.get("q", ""),
                    "category": request.args.get("category", ""),
                    "industry": request.args.get("industry", ""),
                    "kind": request.args.get("kind", "")})

    @app.route("/library/<key>")
    def library_item(key: str):
        """One item in full, with the form that forks it."""
        from .. import library as library_module

        item = library_module.by_key(key)
        if item is None:
            abort(404)
        return render_template("library_item.html", item=item,
                               active=library_module.active_keys())

    @app.route("/library/toggle", methods=["POST"])
    def library_toggle():
        from .. import library as library_module

        key = request.form.get("key", "")
        if request.form.get("state") == "on":
            _, message = library_module.activate(key)
        else:
            _, message = library_module.deactivate(key)
        return redirect(request.form.get("back") or url_for("library_page"),
                        code=303)

    @app.route("/library/fork", methods=["POST"])
    def library_fork():
        """Save an edited copy. The library entry is never written to."""
        from .. import library as library_module

        ok, message = library_module.fork(request.form.get("key", ""),
                                          request.form.get("name", ""),
                                          request.form.get("body", ""))
        return redirect(url_for("library_page", said=message), code=303)

    @app.route("/mcp")
    def mcp_page():
        """MCP servers: what is connected, and adding one."""
        from .. import mcp as mcp_module

        return render_template("mcp.html",
                               servers=mcp_module.read(),
                               where=mcp_module.project_file())

    @app.route("/mcp/add", methods=["POST"])
    def mcp_add():
        from .. import mcp as mcp_module

        args = tuple(part for part in
                     request.form.get("args", "").split() if part)
        _, message = mcp_module.add(request.form.get("name", ""),
                                    request.form.get("command", ""), args)
        return redirect(url_for("mcp_page", said=message), code=303)

    @app.route("/mcp/remove", methods=["POST"])
    def mcp_remove():
        from .. import mcp as mcp_module

        _, message = mcp_module.remove(request.form.get("name", ""))
        return redirect(url_for("mcp_page", said=message), code=303)

    @app.route("/activity")
    def activity():
        """Kept as a door, not a page.

        This used to render fourteen days of narrative as folded cards, and
        History included the same block. The Daily log tab replaces both with
        something you can actually navigate -- a calendar and one day at a
        time -- so the two accounts of the same files are now one.

        The route stays because addresses outlive redesigns: it is written
        down in the docs and sitting in somebody's browser history.
        """
        return redirect(url_for("history_page", tab="eod"), code=302)

    @app.route("/notifications")
    def notifications():
        from .. import channels as channels_module

        installed = set(schedule.installed_names_or_empty())
        try:
            loaded = load_config()
            settings = loaded.notifications
        except config_module.ConfigError:
            settings = None

        # "never" is stored where it always was -- `announces` routes a
        # task's output to the log instead of a channel -- so switching a
        # task off here keeps working the way it already did. What is new is
        # everything between "always" and "never".
        assigned = {}
        for task in schedule.all_tasks():
            if not schedule.announces(task.key):
                assigned[task.key] = "never"
            else:
                assigned[task.key] = quiet_module.mode_for(task.key)

        return render_template(
            "notifications.html",
            held=notify.read_held(),
            settings=settings,
            # The channels that EXIST, not the ones somebody has already
            # switched off. `Notifications.channels` starts empty and its only
            # writer is the chip the template renders from it, so on a fresh
            # install no chip rendered and the line promising that a noisy
            # sender "gets switched off in one click" had no click behind it
            # until the YAML was edited by hand. Added 2026-09-05.
            channel_names=channels_module.registered_names(),
            note=request.args.get("note", ""),
            modes=quiet_module.read_modes(),
            weekdays=quiet_module.WEEKDAYS,
            tasks=schedule.all_tasks(),
            assigned=assigned,
            is_installed={one.key: schedule.is_installed(one, installed)
                          for one in schedule.all_tasks()},
        )

    @app.route("/queues/seen", methods=["POST"])
    def queues_seen():
        """Remember that a queue has been looked at, so its light goes out."""
        approvals.mark_seen(request.form.get("kind", "").strip())
        return ("", 204)

    @app.route("/notifications/channel", methods=["POST"])
    def notifications_channel():
        """Turn one sender on or off.

        The reader existed and the writer did not: `notify.send` consults
        `notifications.channels`, and nothing anywhere set it.
        """
        name = request.form.get("name", "").strip()
        wanted = request.form.get("state", "").strip() == "on"
        if not name:
            return redirect(url_for("notifications"))

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return redirect(url_for("notifications", note=str(exc)))

        channels_now = dict(loaded.notifications.channels or {})
        channels_now[name] = wanted
        loaded.notifications.channels = channels_now
        config_module.save(loaded, app.config["PERSONAL_AGENT_CONFIG_PATH"])

        return redirect(url_for(
            "notifications",
            note=(f"{name} will send again." if wanted
                  else f"{name} is off. Nothing will be sent there until you "
                       "turn it back on.")))

    @app.route("/notifications/release", methods=["POST"])
    def notifications_release():
        """Deliver the backlog now, rather than waiting for 08:05."""
        from .. import tasks

        # No channel named: `run_one` picks the best one for this config,
        # which is the same choice the scheduled run makes.
        outcome = tasks.run_one("release-held")
        return redirect(url_for("notifications", note=outcome.message))

    @app.route("/notifications/clear", methods=["POST"])
    def notifications_clear():
        """Bin the backlog. Deliberately separate from delivering it.

        `notify.clear_held` has said since it was written that it "exists
        because a user may genuinely want to bin a backlog". Until now there
        was nothing to press.
        """
        gone = notify.clear_held()
        return redirect(url_for(
            "notifications",
            note=(f"Discarded {gone} held message(s). They were not "
                  "delivered anywhere." if gone else "Nothing was waiting.")))

    @app.route("/notifications/mode", methods=["POST"])
    def notifications_mode():
        """Add or change one quiet mode."""
        form = request.form
        days = tuple(day for day in quiet_module.WEEKDAYS
                     if form.get(f"day_{day}"))
        key = form.get("key", "").strip()

        # A shipped mode keeps its name; only its window and days are the
        # user's to change. Renaming "Daily" to something else would leave
        # every task pointing at a word that no longer means anything.
        shipped = quiet_module.get_mode(key) if key else None
        name = (shipped.name if shipped is not None and shipped.built_in
                else form.get("name", "").strip())

        mode = quiet_module.Mode(
            key=key, name=name,
            start=form.get("start", "").strip(),
            end=form.get("end", "").strip(),
            days=days,
            built_in=bool(shipped is not None and shipped.built_in),
        )
        if mode.built_in:
            saved, problems = quiet_module.save_built_in(mode)
        else:
            saved, problems = quiet_module.save_mode(mode)

        return redirect(url_for(
            "notifications",
            note=" ".join(problems) if problems
            else f"{saved.name}: {saved.when()}."))

    @app.route("/notifications/mode/delete", methods=["POST"])
    def notifications_mode_delete():
        key = request.form.get("key", "").strip()
        gone = quiet_module.delete_mode(key)
        return redirect(url_for(
            "notifications",
            note=("Deleted. Anything set to it is back to reaching you."
                  if gone else "That mode is not yours to delete.")))

    @app.route("/notifications/assign", methods=["POST"])
    def notifications_assign():
        """When one task is allowed to reach you."""
        key = request.form.get("key", "").strip()
        chosen = request.form.get("mode", quiet_module.ALWAYS).strip()
        task = schedule.get_task(key)
        if task is None:
            abort(404)

        if chosen == "never":
            schedule.set_announce(key, False)
            quiet_module.assign(key, quiet_module.ALWAYS)
            said = f"{task.title} stays in the log and will not reach you."
        else:
            schedule.set_announce(key, True)
            quiet_module.assign(key, chosen)
            if chosen == quiet_module.ALWAYS:
                said = f"{task.title} will always reach you."
            else:
                mode = quiet_module.get_mode(chosen)
                said = (f"{task.title} is held during "
                        f"{mode.name if mode else chosen}.")

        return redirect(url_for("notifications", note=said))

    @app.route("/today/eod", methods=["POST"])
    def today_eod():
        """Write the day up now, rather than at half past six.

        Deliberately the SAME task the schedule runs at 18:30 rather than a
        second implementation. The maintainer asked for the day's account to land in
        History as the day log, and that is where `evening-wrapup` already
        writes -- a separate "EOD" writer would give him two accounts of one
        day that could disagree.
        """
        from .. import tasks

        outcome = tasks.run_one("evening-wrapup")
        said = outcome.report() or "Wrote the day up."
        return redirect(url_for(
            "today_page",
            note=f"{said} It is on History, under today."
            if getattr(outcome, "ok", False)
            else f"The day could not be written up: {said}"))

    @app.route("/today/me-time", methods=["POST"])
    def today_me_time():
        """On, or off. Pressing it again is how it stops."""
        state = me_time_module.toggle()
        if not state.on:
            return redirect(url_for("today_page", note="Me time off. Welcome back."))

        try:
            loaded = load_config()
            working = loaded.user.is_working()
            hours = loaded.user.working_hours_sentence()
        except config_module.ConfigError:
            # `loaded` stays None on purpose: the lines below read the
            # mailbox off it, and an unreadable config is not evidence that a
            # mailbox is connected.
            loaded, working, hours = None, True, ""

        # Both sentences used to promise that work email was being watched
        # when nothing did. Corrected 2026-09-05 in the other direction: the
        # watcher HAS since been built (`me-time-watch`, every ten minutes,
        # `tasks.py` -> `me_time.look_for_something_urgent`), and the note
        # went on saying "that half is not built" unconditionally -- while
        # `me_time.sentence()` on the same page said it was watching. One
        # page, two answers, and the reassuring one was the wrong one.
        #
        # The condition is the same one `sentence()` uses: a watcher with no
        # mailbox to watch is still nothing, and saying otherwise to somebody
        # walking away from their desk is believed at exactly the moment it
        # cannot be checked.
        watching = bool(getattr(getattr(loaded, "connections", None),
                                "mail", ()) or ())
        inbox = ("Watching your mail every ten minutes for the words you "
                 "marked urgent." if watching else
                 "No mailbox is connected, so there is nothing to watch — "
                 "add one on Connections.")
        if working:
            said = ("Me time on. Aki knows you have stepped away. " + inbox)
        else:
            said = (f"Me time on — and it is outside your working hours "
                    f"({hours}). " + inbox)
        return redirect(url_for("today_page", note=said))

    @app.route("/projects/arrange", methods=["POST"])
    def projects_arrange():
        """Move one favourite card one place left or right.

        The maintainer asked for iPhone-style arranging and chose the simpler of the
        two shapes I offered. Dragging
        would need hand-written touch handling -- this dashboard loads no
        outside scripts -- and the arrows work the same on a phone.
        """
        # A whole order when the page had script to rearrange itself, and a
        # single step when it did not. The second is what the arrows fall
        # back to with JavaScript off, and it is one line to keep.
        order = request.form.getlist("order")
        if order:
            _, said = favourites_module.set_order(order)
        else:
            key = request.form.get("key", "").strip()
            try:
                by = int(request.form.get("by", "0"))
            except ValueError:
                by = 0
            _, said = favourites_module.move(key, by)
        back = request.form.get("back") or url_for("today_page")
        return redirect(f"{back}{'&' if '?' in back else '?'}note={said}")

    @app.route("/projects/pin", methods=["POST"])
    def projects_pin():
        """Put a project on Today, or take it off."""
        key = request.form.get("key", "").strip()
        _, said = favourites_module.toggle(key)
        back = request.form.get("back") or url_for("index")
        return redirect(f"{back}{'&' if '?' in back else '?'}note={said}")

    # -- scheduled work ----------------------------------------------------

    @app.route("/schedule")
    def scheduled():
        # Editing an existing task, or starting from a copy of a built-in
        # one. Both fill the same panel; what differs is whether the key
        # travels with it. reported 2026-08-21: built-in tasks get [Custom]
        # ("duplicate 左嘅參數落下面個 edit panel"), the user's own get
        # [Edit].
        tab = (request.args.get("tab") or "loop").strip()
        if tab not in schedule.KINDS_OF_WORK:
            tab = "loop"

        wanted = request.args.get("edit") or request.args.get("custom") or ""
        editing = schedule.get_task(wanted) if wanted else None
        copying = bool(request.args.get("custom")) and editing is not None

        # THE TASK DECIDES THE TAB, not the address.
        #
        # The form now draws whichever trigger the tab owns, so a mismatch
        # is not a cosmetic problem: opening an Event task on the Loops tab
        # would render time fields, and saving would silently replace its
        # trigger with 09:00 daily. `?tab=` is written into every Edit and
        # Custom link, but a hand-typed or bookmarked address without one
        # would default to Loops and quietly eat the task.
        if editing is not None:
            tab = editing.work

        # Both read once and passed down. Each was previously recomputed
        # inside a comprehension over the tasks.
        every_task = schedule.all_tasks()
        installed_now = schedule.installed_names_or_empty()

        return render_template(
            "schedule.html",
            note=request.args.get("note", ""),
            tab=tab,
            kinds=schedule.KINDS_OF_WORK,
            kind_note=schedule.KINDS_OF_WORK[tab][1],
            editing=editing,
            # A copy keeps the settings and loses the key, which is what
            # makes it a new task rather than an edit of the shipped one.
            editing_key="" if copying or editing is None else editing.key,
            copying=copying,
            editing_triggers=[one.to_dict() for one in editing.triggers]
                             if editing else [],
            tasks=every_task,
            installed=installed_now,
            announces={one.key: schedule.announces(one.key)
                       for one in every_task},
            # Asked, not re-derived. This template had the only correct copy
            # of the comparison; now there is only one copy anywhere.
            #
            # Asked ONCE, too (2026-08-23). This comprehension used to call
            # `installed_names()` per task, and each call shells out to
            # `schtasks /Query` over every job on the machine -- 1.3s each on
            # The maintainer's, which has 403. Seven tasks meant seven queries and the
            # page took 9.4 seconds to answer a button press.
            is_installed={one.key: schedule.is_installed(one, installed_now)
                          for one in every_task},
            platform=paths.platform_label(),
            triggers=schedule.supported_triggers(),
            trigger_names=schedule.KIND_NAMES,
            trigger_caveats=schedule.trigger_caveats(),
            # WHAT THIS TAB IS ALLOWED TO OFFER.
            #
            # Loops and Heartbeat get exactly one kind each, which is what
            # let the "+ Add trigger" row go -- there was nothing left to
            # pick. and -- that second one is not a rename, it is this
            # list: Heartbeat can only be an interval now.
            tab_triggers=schedule.TRIGGERS_FOR_WORK.get(tab, ("time",)),
            event_kinds=schedule.EVENT_KIND_NAMES,
            weekdays=schedule.WEEKDAYS,
            # Whether the dialog is open, decided by the ADDRESS rather than
            # by a button press. it is a link that lands here, so Add,
            # Edit and Custom all still work with JavaScript switched off,
            # which a dialog opened by script would have quietly cost.
            showing_form=bool(request.args.get("add") or wanted),
            # The form needs the task's own default, not the effective
            # setting: `announces()` folds in an override the user made on
            # Notifications, and showing that here would make an edit of the
            # task silently rewrite a choice made somewhere else.
            editing_announce=editing.announce if editing else True,
        )

    @app.route("/health/repair", methods=["POST"])
    def health_repair():
        """Re-point everything and bring the workspace notes up to date.

        WHY THIS IS A BUTTON (reported 2026-08-20)
        ----------------------------------------
        `doctor` printed a command to type. He asked, reasonably, where he was
        supposed to type it -- and that question is the whole answer. This
        package's premise is that its users do not open a terminal, and a fix
        offered only as a command line is a fix that is not offered to the
        people it is for.

        Same work as `cli repair --yes`, one press.
        """
        # The same `_repoint` the CLI uses, not a second implementation of
        # it. Two copies of "put everything back where it should be" is two
        # copies that will disagree the day one of them is improved.
        from ..cli import _repoint
        from .. import scaffold as scaffold_module

        done: list[str] = []

        try:
            loaded = load_config()
        except config_module.ConfigError:
            loaded = None

        if loaded is not None and loaded.layout.root:
            said = scaffold_module.top_up(loaded.layout.root)
            if said:
                done.append(said)

        failures = _repoint()
        done.append("re-pointed the launcher and the scheduled work"
                    if not failures else
                    "some of it did not re-point — see the checks below")

        return redirect(url_for("health", note="; ".join(done) or "nothing "
                                "needed changing"))

    def _outcome(ok: bool, done: str, failed: str, detail: str) -> str:
        """One sentence saying what happened, in that order.

        Windows answers a successful `schtasks /Delete` with its own text and
        a failed one sometimes with nothing at all -- so handing the raw
        message straight to the page produced either jargon or, worse, a
        blank note that read as "nothing happened".
        """
        detail = (detail or "").strip()
        if ok:
            return done
        return f"{failed}. {detail}" if detail else f"{failed}."

    @app.route("/schedule/folders/native", methods=["POST"])
    def schedule_folders_native():
        """Open the machine's own folder dialog and answer with the choice.

        This blocks until the dialog is closed, which is the point: the
        person is looking at it. If there is no desktop to draw on -- a
        service, an SSH session, a machine without Tk -- it says so and the
        page falls back to the list it can draw itself.
        """
        # A probe asks only whether a dialog COULD be opened. Without it the
        # single way to find out is to open one -- which, checked remotely,
        # leaves a dialog sitting on somebody's desktop.
        if request.form.get("probe"):
            return jsonify({"can": folders_module.can_open_a_window()})
        return jsonify(folders_module.ask_for_folder(
            request.form.get("at", "")))

    @app.route("/schedule/folders", methods=["POST"])
    def schedule_folders():
        """List the folders inside one folder, for the Browse button.

        POST, not GET, so it passes through `guard_mutations` and therefore
        needs this dashboard's token -- it changes nothing, but "which
        folders exist on this machine" is not something a page in another tab
        should be able to ask.
        """
        return jsonify(folders_module.listing(request.form.get("at", "")))

    # `/schedule/announce` was removed on 2026-08-23, as a dead duplicate.
    #
    # The switch it served moved to Notifications on 2026-08-21, at the maintainer's
    # request. Schedule is about when work happens;
    # Notifications is about when you get interrupted, and the switch answers
    # the second question. `/notifications/assign` does that job and does more
    # of it -- it sets the quiet mode as well as the announce flag, which this
    # route never did, so the two were not even equivalent.
    #
    # The route survived the move with nothing posting to it. Kept as a
    # comment rather than silently dropped because the first instinct on
    # finding it in an audit is to wire it back up, and doing so puts a
    # control back on a page somebody deliberately took it off.

    def _clock(form, hour_field: str, minute_field: str) -> tuple[int, int]:
        """Read a time however the form spelled it.

        The card uses `<input type="time">`, which posts "00:00" -- one field
        holding both halves. The first version split it in JavaScript just
        before submitting, and midnight came through as nine o'clock the
        first time a submit happened any other way: `form.submit()` does not
        fire the submit event, so the handler never ran and "00:00" fell
        through `_as_int` to its default.

        A default that is silently wrong is the worst kind. So the split
        happens here, where nothing can skip it, and the page posts what the
        control actually holds.
        """
        raw = (form.get(hour_field) or "").strip()
        if ":" in raw:
            first, _, second = raw.partition(":")
            return (_as_int(first, 9, 0, 23), _as_int(second, 0, 0, 59))
        return (_as_int(raw, 9, 0, 23),
                _as_int(form.get(minute_field), 0, 0, 59))

    def _triggers_from(form) -> tuple:
        """Read however many trigger cards the page sent.

        The cards are numbered rather than repeated, because a trigger is
        several fields that have to stay together: `t0_kind` with `t0_hour`,
        `t1_kind` with `t1_path`. Repeated field names would arrive as
        several parallel lists, and lining them back up depends on every list
        having the same length -- which stops being true the moment one card
        has no folder in it.

        Numbering also means the form still posts without JavaScript: what is
        on the page is what is read.
        """
        found = []
        index = 0
        while True:
            kind = form.get(f"t{index}_kind")
            if kind is None:
                break
            kind = kind.strip() or "time"
            hour, minute = _clock(form, f"t{index}_hour",
                                  f"t{index}_minute")
            found.append(schedule.Trigger(
                kind=kind,
                hour=hour,
                minute=minute,
                weekdays=tuple(
                    day for day in schedule.WEEKDAYS
                    if form.get(f"t{index}_day_{day}")),
                every_minutes=_as_int(form.get(f"t{index}_every"),
                                      60, 1, 10_080),
                watch_path=form.get(f"t{index}_path", "").strip(),
                # Only meaningful when the kind is "happening"; harmless
                # otherwise, and reading them unconditionally keeps this
                # loop free of one branch per kind.
                event_kind=(form.get(f"t{index}_event") or "any").strip(),
                match=form.get(f"t{index}_match", "").strip(),
            ))
            index += 1
        return tuple(found)

    @app.route("/schedule/save", methods=["POST"])
    def schedule_save():
        form = request.form
        triggers = _triggers_from(form)

        task = schedule.ScheduledTask(
            key=form.get("key", "").strip(),
            title=form.get("title", "").strip(),
            why=form.get("why", "").strip(),
            prompt=form.get("prompt", "").strip(),
            # No `work=`. It is derived from the trigger now, so there is
            # nothing for the form to say about it -- which is what let the
            # "What kind of work" dropdown go.
            triggers=triggers,
            # This field already existed and Notifications already
            # reads it -- `announces(key) == False` shows there as "never".
            # It had simply never been reachable from this form.
            announce=bool(form.get("announce")),
        )
        saved, problems = schedule.save_user_task(task)

        # An edit that stops at the file is an edit that did not happen.
        #
        # Saving wrote schedule.json and nothing else, so a task that was
        # already switched on kept running to its OLD definition -- while
        # this page, which reads the file, showed the new one. The maintainer,
        # 2026-08-23. He was exactly right.
        #
        # Only re-registered if the task is currently installed: saving a
        # draft must not switch anything on by itself.
        if schedule.is_installed(saved):
            runner_path = schedule.runner_script()
            if runner_path.exists():
                ok, said = schedule.install(saved, runner_path, confirmed=True)
                if not ok:
                    problems = list(problems) + [
                        f"Saved, but the scheduler still has the old times: "
                        f"{said}"]

        # Back to the tab the task actually landed on, which since 2026-09-05
        # is read off its trigger rather than chosen. Without this, saving a
        # Heartbeat dropped you on Loops and the task looked like it had not
        # been saved at all.
        landed = saved.work

        if problems:
            # Saved either way -- a half-finished task the person can come
            # back to beats one that vanishes on submit -- but they are told.
            return redirect(url_for("scheduled", tab=landed,
                                    note=" ".join(problems)))
        # "Not running yet" is only true of a task that is not running. An
        # edit to an installed task re-registers it a few lines above, and
        # then told the person to go and switch on something already on.
        # 2026-09-05.
        if schedule.is_installed(saved, schedule.installed_names_or_empty()):
            said = f"Saved {task.title}. It is running with the new settings."
        else:
            said = (f"Added {task.title}. It is not running yet -- switch it "
                    "on when you are ready.")
        return redirect(url_for("scheduled", tab=landed, note=said))

    @app.route("/schedule/delete", methods=["POST"])
    def schedule_delete():
        # The note matters. Deleting the task now also uninstalls it from the
        # scheduler, and if that half fails the person needs to know an entry
        # may still be firing -- silently succeeding here is what left orphans
        # behind before.
        key = request.form.get("key", "")
        # The tab, read BEFORE the task goes, or there is nothing left
        # to read it from. Without it, deleting a Heartbeat dropped you
        # on Loops -- the same defect that was fixed for Save on
        # 2026-09-05 and left in the three switches beside it.
        going = schedule.get_task(key)
        landed = going.work if going else None
        deleted, note = schedule.delete_user_task(key)
        if deleted and note:
            return redirect(url_for("scheduled", tab=landed, note=note))
        return redirect(url_for("scheduled", tab=landed))

    @app.route("/schedule/install", methods=["POST"])
    def schedule_install():
        task = schedule.get_task(request.form.get("key", ""))
        if task is None:
            abort(404)
        # The scheduler must point at a file that actually exists. An earlier
        # version pointed at `~/.aki-agent/run-task`, which was never
        # written -- so tasks installed "successfully" and then failed
        # silently every time they fired, with the dashboard cheerfully
        # showing "installed: yes" beside something that had never run.
        runner_path = schedule.runner_script()
        if not runner_path.exists():
            return redirect(url_for(
                "scheduled",
                note=(f"The task runner is missing at {runner_path}. "
                      "Reinstall the package rather than scheduling something "
                      "that cannot run.")))

        ok, message = schedule.install(task, runner_path, confirmed=True)
        if ok and not task.enabled:
            # Switching it on has to mean switching it on. The three Event
            # examples ship `enabled=False`, and registering them with the
            # operating system left `run_one` returning "switched off,
            # nothing to do" every ten minutes -- a task that read "on",
            # recorded a clean run each time, and never did anything.
            # 2026-09-05.
            schedule.set_enabled(task.key, True)
        # A page, not JSON.
        #
        # These two returned `jsonify(...)`, so pressing the button replaced
        # the dashboard with a screenful of `{"ok": false, ...}`. The maintainer,
        # 2026-08-21: -- that was the JSON. The removal may well have
        # worked; what failed was saying so.
        return redirect(url_for("scheduled", tab=task.work, note=_outcome(
            ok, f"{task.title} now runs on its own.",
            f"{task.title} could not be scheduled", message)))

    @app.route("/schedule/remove", methods=["POST"])
    def schedule_remove():
        task = schedule.get_task(request.form.get("key", ""))
        if task is None:
            abort(404)
        ok, message = schedule.remove(task)
        if ok:
            # The other half of the switch: forget the decision rather than
            # storing "off". A user task taken out of the scheduler must
            # still run when somebody presses Run now; an Event example must
            # go back to its shipped `enabled=False`. One `set_enabled(False)`
            # would have got the first of those quietly wrong.
            schedule.forget_enabled(task.key)
        return redirect(url_for("scheduled", tab=task.work, note=_outcome(
            ok, f"{task.title} no longer runs on its own. It is still here "
                "and can be switched back on.",
            f"{task.title} could not be switched off", message)))

    # -- skills ------------------------------------------------------------

    @app.route("/skills")
    def skills():
        """The old address for the skills list, which is a tab of Tools now.

        A redirect rather than a second render of the same partial. The
        partial gained a dialog that the Tools route fills -- rendering it
        from here as well would mean two places deciding what an edit form
        contains, and the second one would be wrong first.

        The address stays alive because it is linked from guides, from
        earlier notes, and from whatever the user bookmarked.
        """
        return redirect(url_for("yours_page", tab="skills"), code=302)

    @app.route("/skills/save", methods=["POST"])
    def skills_save():
        form = request.form
        # The return value was discarded, so the ONE refusal this function
        # can make -- "there is already a skill called X that was not created
        # here, it has been left alone" -- reached nobody. The page redirected
        # exactly as it does on success, the file was untouched, and the user
        # had no way to know their skill had not been saved. 2026-09-05.
        _saved, problems = skills_store.save(
            name=form.get("name", ""),
            description=form.get("description", ""),
            body=form.get("body", ""),
            key=form.get("key") or None,
        )
        return redirect(url_for("yours_page", tab="skills",
                                note=" ".join(problems) if problems else ""))

    @app.route("/skills/delete", methods=["POST"])
    def skills_delete():
        skills_store.delete(request.form.get("key", ""))
        return redirect(url_for("yours_page", tab="skills"))

    # -- chat, mirroring every channel -------------------------------------

    @app.route("/specialists")
    def specialists_page():
        """Same as `/skills` above: one page draws this list now."""
        return redirect(url_for("yours_page", tab="specialists"), code=302)

    @app.route("/specialists/sentinel", methods=["POST"])
    def specialists_sentinel():
        from .. import sentinel

        if request.form.get("state") == "off":
            sentinel.turn_off()
        else:
            sentinel.turn_on()
        return redirect(url_for("yours_page", tab="specialists"))

    @app.route("/specialists/save", methods=["POST"])
    def specialists_save():
        form = request.form
        specialists.save(specialists.Specialist(
            key=form.get("key", "").strip(),
            name=form.get("name", "").strip(),
            purpose=form.get("purpose", "").strip(),
            brief=form.get("brief", "").strip(),
            reads=tuple(part.strip() for part in
                        form.get("reads", "").split(",") if part.strip()),
            may_write=bool(form.get("may_write")),
            timeout_seconds=_as_int(form.get("timeout_seconds"), 600, 30,
                                    3600),
        ))
        return redirect(url_for("yours_page", tab="specialists"))

    @app.route("/specialists/delete", methods=["POST"])
    def specialists_delete():
        specialists.delete(request.form.get("key", ""))
        return redirect(url_for("yours_page", tab="specialists"))

    @app.route("/notifications/quiet", methods=["POST"])
    def notifications_quiet():
        """Save the quiet hours from the page that shows them.

        The same values are also on the Settings page, and both write through
        `settings.apply` so there is one validator rather than two that will
        eventually disagree about what "22:00" means.
        """
        loaded = load_config()
        updated, _problems = settings.apply_form(loaded, request.form)
        settings.save(updated, app.config["PERSONAL_AGENT_CONFIG_PATH"])
        return redirect(url_for("notifications"))

    @app.route("/rules")
    def rules_page():
        from .. import safety_gate

        from .. import house_rules

        current = house_rules.read()
        return render_template(
            "rules_and_limits.html",
            rules=[(one, house_rules.backed_by_code(one)) for one in current],
            suggestions=[one for one in house_rules.SUGGESTIONS
                         if one not in current],
            rules_file=house_rules.rules_file(),
            # The hard limits, on the same page. They used to be a page of
            # their own that opened by explaining it was not this one.
            # `hard_rules` rather than `rules`: both pieces are here now.
            hard_rules=safety_gate.describe(),
            blocked=safety_gate.recent(),
            log_path=safety_gate.log_file(),
        )

    @app.route("/rules/add", methods=["POST"])
    def rules_add():
        from .. import house_rules

        house_rules.add(request.form.get("rule", ""))
        return redirect(url_for("rules_page"))

    @app.route("/rules/remove", methods=["POST"])
    def rules_remove():
        from .. import house_rules

        house_rules.remove(request.form.get("rule", ""))
        return redirect(url_for("rules_page"))

    @app.route("/theme")
    def theme_page():
        try:
            current = load_config().assistant.safe_colour()
        except config_module.ConfigError:
            current = theme_list.DEFAULT.accent

        return render_template(
            "theme.html",
            themes=theme_list.THEMES,
            current=current,
            chosen=theme_list.matching(current),
            # `_theme.html` has always had `{% if note %}` and nothing has
            # ever passed one, so the branch could not be true. Choosing a
            # theme redirects to a page that looks identical apart from one
            # highlighted card -- which, if you picked a theme close to the
            # one you were on, reads as nothing having happened.
            note=request.args.get("note", "")[:200],
        )

    @app.route("/theme/choose", methods=["POST"])
    def theme_choose():
        """Pick one. Writes the accent, which is the whole of a theme here."""
        loaded = load_config()
        picked = theme_list.by_key(request.form.get("theme", ""))
        loaded.assistant.colour = picked.accent
        settings.save(loaded, app.config["PERSONAL_AGENT_CONFIG_PATH"])
        # Say which one, by name. `by_key` falls back to the nearest survivor
        # for a retired theme, so the thing chosen and the thing applied are
        # not always the same word -- and that is exactly when somebody needs
        # telling.
        return redirect(url_for("theme_page",
                                note=f"{picked.name} is on."))

    # -- settings ----------------------------------------------------------

    # -- the door: three pages, and nothing else is reachable without them --

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """The door, now with a throttle behind it.

        The PIN was six digits before today and stays six. Length was never
        the part that mattered once the maintainer decided people should be able to
        reach this through a tunnel: a million combinations is an afternoon
        for a script and a lifetime for a person. What changes the arithmetic
        is refusing to answer quickly. See `dashboard_auth`.
        """
        wanted = request.args.get("next", "/")
        if request.method == "POST":
            held, seconds = dashboard_auth.locked_out()
            if held:
                # Counted, not answered. Telling them the PIN was also wrong
                # would hand a script one bit of information per attempt while
                # it waits, which is the whole thing the wait is denying it.
                return render_template(
                    "login.html", locked=True, wanted=wanted,
                    problem=("Too many wrong tries. Try again in "
                             f"{dashboard_auth.how_long(seconds)}."))
            if dashboard_auth.check(request.form.get("pin", "")):
                dashboard_auth.clear_failures()
                flask_session["in"] = True
                # Straight to choosing a real one if this was the shipped PIN,
                # rather than letting them work for a week on 000000.
                if dashboard_auth.is_default():
                    return redirect(url_for("first_pin"))
                return redirect(request.form.get("next") or "/")
            counted = dashboard_auth.record_failure()
            if not counted and _came_from_away():
                # THE THROTTLE IS THE ONLY THING GUARDING SIX DIGITS (2026-09-05)
                # ---------------------------------------------------------------
                # A count that cannot be written is not a slow door, it is an
                # open one: every attempt starts from zero failures, forever.
                # On this machine that is a person typing and the trade is
                # fine. Reached through the declared remote name it is a
                # script with all night and a million combinations, so the
                # honest answer is to stop answering rather than to answer
                # quickly and pretend there is a limit.
                #
                # Deliberately not applied to local requests: locking the
                # owner out of their own dashboard because a file went
                # unwritable would be the safety check that gets removed.
                return render_template(
                    "login.html", locked=True, wanted=wanted,
                    problem=("Remote sign-in is closed: this assistant "
                             "cannot keep count of wrong tries at the "
                             "moment, so it will not accept them from away "
                             "from the machine. Sign in on the computer "
                             "itself, and run Doctor to see why."))
            held, seconds = dashboard_auth.locked_out()
            problem = "That is not the PIN."
            if held:
                problem += (" Too many tries — the next one is in "
                            f"{dashboard_auth.how_long(seconds)}.")
            return render_template("login.html", locked=True, wanted=wanted,
                                   problem=problem)
        return render_template("login.html", locked=True, wanted=wanted, problem="")

    @app.route("/login/forgot", methods=["POST"])
    def forgot_pin():
        """Reset to a new PIN and get it to them.

        RESET, not reveal. Showing the old one would mean this program could
        read it back, and anything it can read so can anyone holding the
        folder -- which would leave the PIN protecting nothing.

        To their phone first, and only to a file if there is no phone to send
        to. A reset that needs a working connection is not a reset: it fails
        exactly when the assistant is already unwell, which is when somebody
        is most likely to be trying to get in and find out why.

        TWO LIMITS ON A DOOR THAT TAKES NO PASSWORD (2026-09-06)
        --------------------------------------------------------
        This route cannot ask for the PIN -- it is what you press when the
        PIN is gone. That made it the one unauthenticated write in the
        dashboard, and it had no limit at all, so pressing it in a loop
        locked the owner out permanently while their phone filled with
        superseded PINs.

        It is now (a) refused from away, because a reset lands on the phone
        or the Desktop of somebody standing at the machine and is no use to
        anybody who is not, and (b) allowed once every ten minutes.
        """
        if _came_from_away():
            return render_template(
                "login.html", locked=True, wanted="/",
                problem=("A PIN can only be reset from the computer the "
                         "assistant runs on. The new one is sent to that "
                         "machine, so resetting it from here would lock you "
                         "out rather than let you in."))

        may, wait = dashboard_auth.reset_allowed()
        if not may:
            return render_template(
                "login.html", locked=True, wanted="/",
                problem=(f"Your PIN was already reset in the last few "
                         f"minutes — check your phone, or your Desktop, for "
                         f"the new one. You can reset it again in "
                         f"{dashboard_auth.how_long(wait)}."))

        try:
            loaded = load_config()
            who = loaded.assistant.name or "your assistant"
        except Exception:                                # noqa: BLE001
            who = "your assistant"

        # Counted BEFORE the PIN changes, and refused outright if the count
        # cannot be kept. A reset this software cannot rate-limit is exactly
        # the door that was open, and "we could not write the file" must not
        # quietly reopen it.
        try:
            dashboard_auth.record_reset()
        except Exception:                                # noqa: BLE001
            return render_template(
                "login.html", locked=True, wanted="/",
                problem=("I could not record this reset, so I have not done "
                         "it — otherwise it could be repeated without limit. "
                         "Ask your assistant in Claude Code to run "
                         "`forgot-pin`."))

        fresh = dashboard_auth.reset_to_new()
        # The old failures were against a PIN that no longer exists. Leaving
        # them counted would hand somebody a fresh PIN and a locked door.
        dashboard_auth.clear_failures()

        could_not_send = dashboard_auth.send_to_phone(fresh, who)
        if not could_not_send:
            return render_template("login.html", locked=True, wanted="/", problem="",
                                   sent_to_phone=True)

        try:
            where = dashboard_auth.write_reset_file(fresh, who)
        except OSError as problem:                       # pragma: no cover
            # Never fall back to printing it on the page: the screen may be
            # the thing somebody else is looking at, which is the situation
            # this whole feature exists for. The PIN has already changed, so
            # say that plainly rather than pretending nothing happened.
            return render_template(
                "login.html", locked=True, wanted="/",
                problem=("Your PIN was reset, but it could not be sent or "
                         f"saved ({could_not_send}; {problem}). Ask your "
                         "assistant in Claude Code to run `forgot-pin` and "
                         "read it out."))

        return render_template("login.html", locked=True, wanted="/", problem="",
                               reset_file=str(where), why_a_file=could_not_send)


    @app.route("/first-pin", methods=["GET", "POST"])
    def first_pin():
        """Change the PIN it came with. Not skippable."""
        if not flask_session.get("in"):
            return redirect(url_for("login", next="/first-pin"))

        problem = ""
        if request.method == "POST":
            problem = dashboard_auth.set_pin(request.form.get("pin", ""))
            if not problem:
                return redirect("/")
        return render_template("first_pin.html", locked=True, problem=problem,
                               length=dashboard_auth.PIN_LENGTH)

    # POST only. As a GET it was reachable by any page the user happened to
    # be looking at -- an `<img src="http://127.0.0.1:4321/logout">` on any
    # site is enough -- because `guard_mutations` deliberately lets reads
    # through without the token. Not dangerous, but it is a stranger deciding
    # something about this dashboard, and there is no reason to allow it.
    # Nothing links here yet; see the note in the Lane 3 findings.
    @app.route("/logout", methods=["POST"])
    def logout():
        flask_session.clear()
        return redirect(url_for("login"))


    @app.route("/settings")
    def settings_page():
        from .. import today as today_module_for_location

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        return render_template(
            "settings.html",
            config=loaded,
            # Which of the two location inputs is the live one. Derived from
            # the value rather than stored: a pair of numbers can only have
            # come from the browser, and words can only have been typed.
            located_here=today_module_for_location.coordinates(
                loaded.user.location) is not None,
            field_types=settings.field_types(),
            describe_type=settings.describe_type,
            config_path=loaded.source_path or paths.config_file(),
            problems=request.args.getlist("problem"),
            # The theme picker moved onto this page in the 2026-08-21
            # redesign, and its piece needs these. Without them Jinja renders
            # the swatch loop over nothing and the section is a heading with
            # empty space under it -- which is what shipped, and what the maintainer
            # found within the hour by asking where the colours had gone.
            themes=theme_list.THEMES,
            current=loaded.assistant.safe_colour(),
            chosen=theme_list.matching(loaded.assistant.safe_colour()),
        )

    @app.route("/settings/save", methods=["POST"])
    def settings_save():
        loaded = load_config()
        updated, problems = settings.apply_form(loaded, request.form)
        settings.save(updated, app.config["PERSONAL_AGENT_CONFIG_PATH"])
        return redirect(url_for("settings_page", problem=problems))

    @app.route("/settings/field", methods=["POST"])
    def settings_field():
        loaded = load_config()
        updated, problems = settings.apply_field(loaded, request.form)
        if not problems:
            settings.save(updated, app.config["PERSONAL_AGENT_CONFIG_PATH"])
        return redirect(url_for("settings_page", problem=problems))

    @app.route("/settings/field/delete", methods=["POST"])
    def settings_field_delete():
        loaded = load_config()
        updated = settings.remove_field(loaded, request.form.get("key", ""))
        settings.save(updated, app.config["PERSONAL_AGENT_CONFIG_PATH"])
        return redirect(url_for("settings_page"))

    # -- moved out of this file (2026-08-28) -------------------------------
    #
    # First slice of "拆 dashboard". Registered here rather than imported at
    # the top so the import graph still reads top-down, and so that a slice
    # that fails to import fails while building the app rather than at
    # interpreter start.
    from .routes import access as access_routes
    access_routes.register(app)

    # Second slice, and the first one written straight into the pattern rather
    # than moved into it: the [+] / [-] beside the chat panel.
    from .routes import clones as clone_routes
    clone_routes.register(app)

    # The installable app and the notification it sends. Dropping Telegram
    # removed the tap on the shoulder as well as the transport; this is what
    # puts it back without a third party.
    from .routes import push as push_routes
    push_routes.register(app)

    # -- connections -------------------------------------------------------

    @app.route("/connections")
    def connections():
        """Where secrets are managed, and never shown.

        Every entry reports whether a secret EXISTS. None displays one, and
        none is pre-filled into a form field where a browser could remember
        it.
        """
        # These two were hardcoded empty lists for as long as the page
        # existed: it advertised email providers and offered no way to add an
        # account, and had no calendar section at all, while the code for both
        # sat finished and unreachable one folder away.
        calendars: list[dict] = []
        accounts: list[dict] = []
        try:
            loaded = load_config()
            channels_configured = dict(loaded.notifications.channels)
            accounts = [
                {"address": one.address, "label": one.label or one.address,
                 "imap_host": one.imap_host, "may_send": one.may_send,
                 "has_password": bool(
                     secrets_module.get_secret(one.secret_key())),
                 # Asked of the mail module rather than worked out here, so
                 # the page cannot disagree with what a send would actually
                 # do. Without it a Google-signed mailbox reads "Password:
                 # not set", which is true and sounds broken.
                 "google": mail.signs_in_with_google(
                     mail.Account(address=one.address))}
                for one in loaded.connections.mail
            ]
            calendars = [
                {"name": one.name,
                 "subscribed": bool(calendar_module.Calendar(
                     name=one.name).url())}
                for one in loaded.connections.calendars
            ]
        except config_module.ConfigError:
            channels_configured = {}

        from .. import telegram_chat as telegram_chat_module

        chat_status = telegram_chat_module.status()

        return render_template(
            "connections.html",
            telegram=telegram_setup.status(),
            telegram_next=telegram_setup.status().next_step(),
            # The bot number and last four characters -- enough to tell which
            # token is saved, never enough to use it. See `token_fingerprint`.
            telegram_fingerprint=telegram_setup.token_fingerprint(),
            chat=chat_status,
            chat_next=telegram_chat_module.next_step(chat_status),
            note=request.args.get("note", ""),
            google=_google_state(),
            gmail=_gmail_state(),
            drive=_drive_state(),
            allowed_ids=telegram_setup.allowed_ids(),
            install_command=telegram_setup.install_plugin_command(),
            mail_providers=mail.PROVIDERS,
            accounts=accounts,
            calendars=calendars,
            stores=files_connector.detect(),
            channels=channels_configured,
            using_os_store=secrets_module.using_os_store(),
            fallback_warning=secrets_module.fallback_warning(),
            # ?tab= is the state, so a reload -- and every form
            # on this page, all of which redirect back here --
            # lands where you were reading.
            tab=(request.args.get("tab") or "gateway").strip(),
        )

    def _google_state() -> dict:
        """Enough to draw the section, and honest about what it cannot tell.

        Three states again rather than two, for the reason the chat light has
        three: a credential store that refuses to answer must not be reported
        as "not connected", because the two need different things done about
        them.
        """
        from ..connectors import google_calendar

        try:
            client_id, client_secret = google_calendar.app_credentials()
            return {
                "has_client": bool(client_id and client_secret),
                "connected": google_calendar.connected(),
                "problem": "",
                "how": google_calendar.how_to_set_up(),
                "revoke": google_calendar.REVOKE_HELP,
            }
        except Exception as exc:                          # noqa: BLE001
            return {"has_client": False, "connected": False,
                    "problem": f"Could not check: {type(exc).__name__}",
                    "how": "", "revoke": google_calendar.REVOKE_HELP}

    def _drive_state() -> dict:
        """Read-only Drive, reported separately from the other two grants."""
        from ..connectors import google_account, google_drive

        try:
            client_id, client_secret = google_account.app_credentials()
            return {
                "has_client": bool(client_id and client_secret),
                "connected": google_drive.connected(),
                "describes": google_drive.describe(),
                "problem": "",
                "revoke": google_account.REVOKE_HELP,
            }
        except Exception as exc:                          # noqa: BLE001
            return {"has_client": False, "connected": False,
                    "describes": "",
                    "problem": f"Could not check: {type(exc).__name__}",
                    "revoke": google_account.REVOKE_HELP}

    def _gmail_state() -> dict:
        """The same three states for the mail side of the same account.

        Separate from `_google_state` because they are separate grants: the
        client is shared, the permission is not, and a page that showed one
        light for both would say a mailbox was connected because a diary was.
        """
        from ..connectors import google_account

        try:
            client_id, client_secret = google_account.app_credentials()
            return {
                "has_client": bool(client_id and client_secret),
                "connected": google_account.connected(google_account.GMAIL),
                "address": google_account.account_address(
                    google_account.GMAIL),
                "problem": "",
                "revoke": google_account.REVOKE_HELP,
            }
        except Exception as exc:                          # noqa: BLE001
            return {"has_client": False, "connected": False, "address": "",
                    "problem": f"Could not check: {type(exc).__name__}",
                    "revoke": google_account.REVOKE_HELP}

    def _a_port(typed, fallback: int) -> int:
        """A port out of a form box, or the provider's own if it is unusable.

        Blank is the normal case and means "the usual one". Anything that is
        not a port number falls back rather than being stored: a mailbox
        saved with port 0 fails at connection time, a long way from the box
        that caused it.
        """
        try:
            port = int(str(typed or "").strip())
        except (TypeError, ValueError):
            return int(fallback)
        return port if 1 <= port <= 65535 else int(fallback)

    @app.route("/connections/mail", methods=["POST"])
    def connections_mail():
        from .. import config as cfg

        address = request.form.get("address", "").strip()
        if not address:
            return back_to_connections()

        loaded = load_config()
        guess = mail.guess_provider(address)
        account = cfg.MailAccount(
            address=address,
            label=request.form.get("label", "").strip() or address,
            imap_host=(request.form.get("imap_host", "").strip()
                       or (guess.imap_host if guess else "")),
            smtp_host=(request.form.get("smtp_host", "").strip()
                       or (guess.smtp_host if guess else "")),
            imap_port=_a_port(request.form.get("imap_port"),
                              guess.imap_port if guess else 993),
            smtp_port=_a_port(request.form.get("smtp_port"),
                              guess.smtp_port if guess else 587),
            may_send=bool(request.form.get("may_send")),
        )
        password = request.form.get("password", "")
        if password:
            # Straight to the OS credential store. It is never written to the
            # config, never echoed back into the form, and never logged.
            secrets_module.set_secret(account.secret_key(), password)

        others = [one for one in loaded.connections.mail
                  if one.address != account.address]
        # `replace` rather than a fresh Connections(): rebuilding it by hand
        # drops every field this line does not mention, which is how saving a
        # mailbox silently deleted the user's API keys and calendars.
        loaded.connections = _dataclasses.replace(
            loaded.connections, mail=tuple(others) + (account,))
        config_module.save(loaded)
        return back_to_connections()

    @app.route("/connections/calendar", methods=["POST"])
    def connections_calendar():
        from .. import config as cfg

        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        if not (name and url):
            return back_to_connections()

        calendar_module.Calendar(name=name).save_url(url)

        loaded = load_config()
        others = [one for one in loaded.connections.calendars
                  if one.name != name]
        loaded.connections = _dataclasses.replace(
            loaded.connections,
            calendars=tuple(others) + (cfg.CalendarFeed(name=name, url=""),))
        config_module.save(loaded)
        return back_to_connections()

    @app.route("/connections/mail/forget", methods=["POST"])
    def connections_mail_forget():
        """Disconnect a mailbox, and take the password with it.

        WHY THIS EXISTS (reported 2026-08-20)
        -----------------------------------
        *"Email 都係,要有得俾人 remove"*. There was a way in and no way out:
        a mistyped address stayed on the page for ever, and the app password
        it had put in the credential store stayed there with it. A connection
        somebody cannot undo is one they hesitate to make.

        Both halves go. Removing the row and leaving the password behind
        would be worse than not removing anything -- it would look gone while
        still being a live credential on the machine.
        """
        address = request.form.get("address", "").strip()
        if not address:
            return back_to_connections()

        loaded = load_config()
        account = mail.Account(address=address)
        forgotten = account.forget_password()

        kept = [one for one in loaded.connections.mail
                if one.address != address]
        if len(kept) == len(loaded.connections.mail):
            return back_to_connections(
                f"No account here called {address}.")

        loaded.connections = _dataclasses.replace(
            loaded.connections, mail=tuple(kept))
        config_module.save(loaded)

        note = f"Disconnected {address}"
        note += (" and deleted its app password from this computer."
                 if forgotten else
                 ". There was no stored password to delete.")
        note += (" Nothing was changed at your email provider — the app "
                 "password is still valid there until you revoke it.")
        return back_to_connections(note)

    @app.route("/connections/calendar/forget", methods=["POST"])
    def connections_calendar_forget():
        """Unsubscribe from a calendar, and delete the address.

        The address is the credential here -- anyone holding it can read the
        whole calendar without a password -- so leaving it in the store after
        the calendar has visibly gone is the same mistake as above.
        """
        name = request.form.get("name", "").strip()
        if not name:
            return back_to_connections()

        loaded = load_config()
        forgotten = calendar_module.Calendar(name=name).forget()

        kept = [one for one in loaded.connections.calendars
                if one.name != name]
        if len(kept) == len(loaded.connections.calendars):
            return back_to_connections(
                f"No calendar here called {name}.")

        loaded.connections = _dataclasses.replace(
            loaded.connections, calendars=tuple(kept))
        config_module.save(loaded)

        note = f"Unsubscribed from {name}"
        note += (" and deleted its address from this computer."
                 if forgotten else ". There was no stored address to delete.")
        note += (" That address still works for anyone else who has it — "
                 "reset it in your calendar's own settings if you think it "
                 "has been shared.")
        return back_to_connections(note)

    # -- Google Calendar, the writing kind ---------------------------------
    #
    # The dashboard hosts the OAuth redirect itself. A Google "Desktop app"
    # client accepts any loopback address, so there is nothing to register
    # with Google and nothing to keep in step when a port changes -- and no
    # second local web server has to be started and torn down for one round
    # trip, which is the usual shape of this and is worse in every way.

    def _google_redirect() -> str:
        from ..connectors import google_calendar

        return f"http://127.0.0.1:{DEFAULT_PORT}{google_calendar.REDIRECT_PATH}"

    @app.route("/connections/google/credentials", methods=["POST"])
    def connections_google_credentials():
        from ..connectors import google_calendar

        _, message = google_calendar.save_client(
            request.form.get("client_id", ""),
            request.form.get("client_secret", ""))
        return back_to_connections(message)

    @app.route("/connections/google/connect", methods=["POST"])
    def connections_google_connect():
        """Send the browser to Google to ask the person.

        Which power is being asked for comes from the form, because the
        client, the callback and this route are shared by all of them --
        An unknown name is refused
        rather than defaulted: defaulting would send somebody who pressed the
        Gmail button to a consent screen asking for their diary.
        """
        from ..connectors import google_account

        try:
            wanted = google_account.service(
                request.form.get("service", "calendar"))
            where, _state = google_account.start(wanted, _google_redirect())
        except google_account.GoogleError as exc:
            return back_to_connections(str(exc))
        return redirect(where)

    @app.route("/connections/google/callback")
    def connections_google_callback():
        """Where Google sends them back.

        A GET, and the only one on this page that changes anything -- the
        mutation guard lets it through because it is a GET, so the protection
        here is the `state` value, which was generated in this process and is
        checked before the code is worth anything.
        """
        from ..connectors import google_account

        refused = request.args.get("error")
        if refused:
            return back_to_connections(
                f"Google did not connect: {refused}. Nothing changed.")

        ok, message, which = google_account.finish(
            request.args.get("code", ""), request.args.get("state", ""),
            _google_redirect())
        # Back to the tab the button was on -- Gmail's lives under Email.
        tab = {"gmail": "mail", "drive": "files"}.get(
            which.key if which is not None else "", "")
        return back_to_connections(message, tab=tab)

    @app.route("/connections/google/disconnect", methods=["POST"])
    def connections_google_disconnect():
        from ..connectors import google_account

        try:
            wanted = google_account.service(
                request.form.get("service", "calendar"))
        except google_account.GoogleError as exc:
            return back_to_connections(str(exc))
        _, message = google_account.disconnect(wanted)
        tab = {"gmail": "mail", "drive": "files"}.get(wanted.key, "")
        return back_to_connections(message, tab=tab)

    @app.route("/connections/telegram", methods=["POST"])
    def connections_telegram():
        action = request.form.get("action", "")
        message = ""

        if action == "token":
            _, message = telegram_setup.save_token(
                request.form.get("token_value", ""), confirmed=True)
        elif action == "allow":
            _, message = telegram_setup.allow_user(
                request.form.get("user_id", ""), confirmed=True)
        elif action == "remove":
            # Being able to add without being able to remove is not an access
            # list, it is a ratchet.
            _, message = telegram_setup.remove_allowed(
                request.form.get("user_id", ""))

        return back_to_connections(message)

    # -- outside services --------------------------------------------------
    #
    # Separate from /connections on purpose. Connections are things the user
    # already has and is plugging in; these cost money per use. Mixing "read my
    # email" with "generate video at a pound a clip" on one page makes the
    # second one look as routine as the first.

    @app.route("/tools")
    def tools_page():
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))

        return render_template(
            "tools.html",
            saved=apis.listing(loaded),
            overview=apis.jobs_overview(loaded),
            catalogue=apis.catalogue(),
            jobs=apis.JOBS,
            job_labels={one.key: one.label for one in apis.JOBS},
            # Which listed services are not set up yet -- the "add one" list.
            # A dropdown that still offers what you already added is a dropdown
            # that invites you to add it twice.
            unused=[one for one in apis.catalogue()
                    if one.key not in {row["tool"]
                                       for row in apis.listing(loaded)}],
            note=request.args.get("note", ""),
            problems=request.args.getlist("problem"),
            using_os_store=secrets_module.using_os_store(),
            fallback_warning=secrets_module.fallback_warning(),
        )

    @app.route("/tools/save", methods=["POST"])
    def tools_save():
        """Add or update one service: its jobs, and its key if one was typed."""
        loaded = load_config()

        tool_key = (request.form.get("tool", "")
                    or request.form.get("custom_tool", ""))
        chosen_jobs = tuple(request.form.getlist("jobs"))

        # An unticked checkbox is not posted at all, so "absent" and "switched
        # off" arrive identically. The form therefore says whether it had the
        # switch on it; without this, a service could never be turned off --
        # the same trap the notifications form documents.
        if request.form.get("enabled_present"):
            enabled = bool(request.form.get("enabled"))
        else:
            enabled = True

        loaded, problems = apis.put(
            loaded, tool_key, chosen_jobs,
            label=request.form.get("label", ""),
            enabled=enabled)

        note = ""
        supplied = request.form.get("api_key", "")
        if supplied.strip():
            # Straight to the credential store. Never into the config, never
            # echoed back into the form, never logged.
            where = apis.save_key(apis.normalise(tool_key), supplied)
            note = f"The key went into {where}."
        elif not apis.has_key(apis.normalise(tool_key)):
            note = ("Saved, but there is no key for it yet, so nothing can "
                    "use it.")

        if not chosen_jobs:
            note = (note + " " if note else "") + (
                "No job was chosen, so it will not be used for anything until "
                "you pick one.")

        config_module.save(loaded)
        return redirect(url_for("tools_page", note=note, problem=problems))

    @app.route("/tools/prefer", methods=["POST"])
    def tools_prefer():
        loaded = load_config()
        loaded, problems = apis.prefer(loaded, request.form.get("tool", ""))
        config_module.save(loaded)
        return redirect(url_for("tools_page", problem=problems))

    @app.route("/tools/remove", methods=["POST"])
    def tools_remove():
        loaded = load_config()
        tool_key = request.form.get("tool", "")
        loaded, problems = apis.remove(loaded, tool_key)
        config_module.save(loaded)
        return redirect(url_for(
            "tools_page",
            note="Removed, and its key was deleted from the credential store.",
            problem=problems))

    # -- sessions ----------------------------------------------------------

    @app.route("/sessions")
    def sessions():
        # The guard lives on this page rather than a new one. Whether the
        # session is healthy, and whether it is about to be restarted, are the
        # same question asked twice -- and splitting one question across two
        # pages is how neither gets found.
        from .. import guard

        marker = session.read_marker()
        advice = recycle.should_recycle()
        state = memory.read_working_state()

        return render_template(
            "sessions.html",
            marker=marker,
            advice=advice,
            state=state,
            order=session.shutdown_order(holds_connection=True),
            watch=guard.assess(),
            switches=guard.settings(),
            footer=guard.FOOTER,
        )

    @app.route("/sessions/checkpoint", methods=["POST"])
    def sessions_checkpoint():
        recycle.checkpoint()
        return redirect(url_for("sessions"))

    @app.route("/sessions/recycling", methods=["POST"])
    def sessions_recycling():
        """The two switches and the hour."""
        from .. import guard

        guard.save_settings(
            auto_recycle=bool(request.form.get("auto_recycle")),
            nightly_recycle=bool(request.form.get("nightly_recycle")),
            recycle_hour=_as_int(request.form.get("recycle_hour"), 4, 0, 23),
        )
        return redirect(url_for("sessions"))

    @app.route("/sessions/recycle-now", methods=["POST"])
    def sessions_recycle_now():
        """The button, and it means it.

        It DOES skip the idle check -- changed on the owner\'s instruction,
        2026-09-03, after a press that declined in silence. The reasoning it
        used to carry ("they have not decided to lose whatever the session
        was in the middle of") is sound for the AUTOMATIC recycle, which
        nobody asked for and which must never interrupt. It is not sound for
        a button pressed deliberately, by the one person whose work is at
        stake, behind a confirm dialog.

        The scheduled path, `recycle.checkpoint()`, still obeys the idle
        check and has no way to ask for this.
        """
        from .. import guard, launcher as launcher_module

        script = launcher_module.launcher_path()
        if not script.exists():
            return redirect(url_for("sessions", said=(
                f"Nothing was restarted: the launcher is missing ({script}). "
                "Run setup again and it will be written back.")), code=303)

        # The report was being thrown away, and every outcome -- declined,
        # failed to start, started but unverified -- redirected to a page that
        # said nothing. Pressing the button and watching nothing happen is
        # indistinguishable from a dead button, and that is what it looked
        # like on 2026-09-03: it had declined, correctly, because the session
        # was not idle yet. The decision was right; the silence was the bug.
        report = recycle.perform([str(script)], holds_connection=True,
                                 confirmed=True, force=True,
                                 idle_seconds_required=guard.IDLE_MINUTES * 60)
        return redirect(url_for("sessions", said=report.summary()), code=303)

    # -- raw logs ----------------------------------------------------------

    @app.route("/logs")
    def logs():
        """The files themselves, for when a summary is not enough."""
        directory = paths.log_dir()
        found = []
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                found.append({
                    "name": path.relative_to(directory).as_posix(),
                    "size": stat.st_size,
                    "modified": _dt.datetime.fromtimestamp(stat.st_mtime),
                })

        chosen = request.args.get("file", "")
        body = ""
        refused = ""

        if chosen:
            target = (directory / chosen).resolve()
            # Never serve a file outside the log folder, whatever the query
            # string says. A dashboard that reads arbitrary paths is a file
            # browser with no permissions model.
            #
            # And say so when it is refused. The first version rendered a
            # heading with an empty body, which reads as "this log is empty"
            # rather than "I would not open that" -- the same failure as any
            # other panel that shows nothing without saying why.
            if directory.resolve() not in target.parents:
                refused = ("That is outside the log folder, so it was not "
                           "opened.")
            elif not target.is_file():
                refused = "There is no such log file."
            else:
                try:
                    text = target.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    text = f"(could not read: {exc})"
                body = secrets_module.redact(text[-40_000:])

        return render_template("logs.html", files=found, chosen=chosen,
                               body=body, refused=refused)

    # -- verdicts, which are what the learning loop runs on ----------------

    # `/verdict` was removed on 2026-08-23. Nothing posted to it -- no form
    # in any of the sixty templates named it -- and it was a second way into
    # `traces.record_verdict`, which `approvals.answer` already calls on the
    # path a person actually takes. An endpoint with no caller is not free:
    # it is a POST that writes to the learning store, reachable by anything
    # holding the token, that nobody would think to look at.

    # -- knowledge ---------------------------------------------------------

    @app.route("/knowledge")
    def _knowledge_page(error: str = "", keep_open: bool = False,
                        typed: dict | None = None):
        """One place this page is drawn from.

        It was drawn from two, with different context in each, and adding a
        section to the template broke the one that had not been updated --
        found by the suite rather than by anybody looking at the page, which
        is luck rather than design. Two renders of one template is the same
        shape as two stores of one conversation: they agree until the day
        somebody edits one.
        """
        from .. import semantic

        cards = []
        card_dir = traces.card_dir()
        if card_dir.exists():
            for path in sorted(card_dir.glob("*.md")):
                try:
                    cards.append((path.stem,
                                  path.read_text(encoding="utf-8")))
                except (OSError, UnicodeDecodeError):
                    continue

        # Three tabs since 2026-09-05. They were
        # already three sections of one page that had grown too long.
        tab = (request.args.get("tab") or "docs").strip()
        if tab not in ("docs", "learned", "meaning"):
            tab = "docs"

        return render_template("knowledge.html",
                               tab=tab,
                               cards=cards,
                               counts=traces.stats(),
                               entries=knowledge.read_all(),
                               broken=knowledge.broken(),
                               error=error,
                               note=request.args.get("note", ""),
                               # Opened by the address, like every other
                               # sheet in this dashboard, so Add still works
                               # with JavaScript switched off.
                               # `keep_open` so a refused entry comes back
                               # WITH the sheet still open and the typed
                               # title still in it. It used to re-render with
                               # `showing_form` false, because that reads the
                               # query string and this is a POST -- so the
                               # error appeared over a closed sheet and
                               # everything typed was gone. 2026-09-05.
                               showing_form=bool(request.args.get("add"))
                               or keep_open,
                               # `meaning` and `meaning_says` were dropped
                               # here the same day: matching by meaning moved
                               # to Memory > Vector store, the template stopped
                               # reading them, and the two calls stayed --
                               # parsing the whole vector index twice on every
                               # render of a page that had no use for it
                               # (243ms at 2,000 notes, measured).
                               typed=typed or {})

    @app.route("/knowledge/add", methods=["POST"])
    def knowledge_add():
        form = request.form
        error = ""
        try:
            knowledge.add(
                title=form.get("title", ""),
                kind=form.get("kind", "document"),
                target=form.get("target", ""),
                why=form.get("why", ""),
                tags=tuple(tag.strip() for tag in
                           form.get("tags", "").split(",") if tag.strip()),
            )
        except ValueError as exc:
            error = str(exc)

        if error:
            return _knowledge_page(error=error, keep_open=True,
                                   typed=form.to_dict())
        # Redirect after a successful POST, so a refresh does not add it
        # twice, and say that it worked -- this used to re-render silently at
        # the POST address with no note at all.
        return redirect(url_for("_knowledge_page",
                                note=f"Added {form.get('title', '').strip()}."))


    @app.route("/knowledge/files", methods=["POST"])
    def knowledge_files():
        """The fallback list, showing files as well as folders.

        A separate route from `/schedule/folders` rather than a flag on it:
        that one answers "which folder", is used by a page shipped an hour
        ago, and nothing is gained by making it answer two questions.
        """
        return jsonify(folders_module.listing(request.form.get("at", ""),
                                              want_files=True))

    @app.route("/knowledge/files/native", methods=["POST"])
    def knowledge_files_native():
        """The machine's own file dialog.

        Blocks until the window is closed, which is the point --
        the answer is the path, and there is nothing to report until there
        is one.
        """
        return jsonify(folders_module.ask_for_file(
            request.form.get("at", "")))

    @app.route("/knowledge/delete", methods=["POST"])
    def knowledge_delete():
        knowledge.remove(request.form.get("key", ""))
        return redirect(url_for("_knowledge_page"))

    @app.route("/health")
    def health():
        from .. import __version__, engine

        checks = doctor.run_all()

        # Looked up rather than asked for: the answer to "is there a newer
        # one" is a folder or a zip the person has already downloaded, and
        # making them find it again is how an update does not happen.
        waiting, problem = engine.source_for_upgrade(None)
        available = engine.version_of(waiting) if waiting else ""

        return render_template(
            "health.html", checks=checks,
            note=request.args.get("note", ""),
            version=__version__,
            available=available,
            available_from=str(waiting) if waiting else "",
            update_problem=problem,
            engine_here=engine.is_adopted(),
        )

    @app.route("/memory/meaning", methods=["POST"])
    def memory_meaning():
        """The switch, and the reindex button beside it."""
        from .. import semantic

        wanted = request.form.get("action", "")
        if wanted == "install":
            # The page used to print a pip command and stop, which offers
            # the fix only to people who open a terminal -- and the premise
            # of this package is that its users do not.
            #
            # Not switched on afterwards. Installing is answering "do I want
            # to spend the disk", and turning it on is answering "do I want
            # my searches to change"; doing the second because somebody
            # answered the first is deciding for them.
            _ok, message = semantic.install()
        elif wanted == "on":
            _ok, message = semantic.turn_on()
            if _ok:
                _count, said = semantic.rebuild()
                message = f"{message} {said}"
        elif wanted == "off":
            _ok, message = semantic.turn_off()
        else:
            _count, message = semantic.rebuild()
        # Back to the tab it belongs to, not to the top of the page.
        # It lives on Memory > Vector store since 2026-09-05.
        return redirect(url_for("history_page", tab="vectors",
                                note=message))

    @app.route("/learned")
    def learned():
        directory = traces.card_dir()
        cards = []
        if directory.exists():
            for path in sorted(directory.glob("*.md")):
                try:
                    cards.append((path.stem,
                                  path.read_text(encoding="utf-8")))
                except (OSError, UnicodeDecodeError):
                    continue
        return render_template("learned.html", cards=cards,
                               counts=traces.stats())

    # -- a small API, for anything that wants the data rather than the page --

    # -- the merged pages ---------------------------------------------------
    #
    # Each one renders the same template pieces the old pages rendered, with
    # the same context, unedited. Nothing here re-implements a page: if a
    # merge turns out wrong, the piece is pulled back out and its old route
    # still works.
    #
    # Two context names had to be renamed because two pieces now share a
    # page: `_safety.html` used `rules` for the hard-coded refusals while the
    # house rules beside it also used `rules`, and both specialists and skills
    # called their blank template `starter`. A silent collision there would
    # have drawn one list under the other's heading.

    @app.route("/inbox")
    def inbox_page():
        """Anything waiting for him: decisions, and messages held back."""
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))
        return render_template(
            "inbox.html",
            items=approvals.open_items(),
            summary=approvals.summary(),
            held=notify.read_held(),
            settings=loaded.notifications,
        )

    @app.route("/yours")
    def yours_page():
        """What he has added himself — skills and specialists together."""
        from .. import sentinel

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))
        occupation = getattr(loaded.user, "occupation", "")

        tab = (request.args.get("tab") or "skills").strip()
        if tab not in ("skills", "specialists"):
            tab = "skills"

        # Editing one, or writing a new one. Both fill the same dialog, and
        # which store to look in is decided by the tab -- a skill and a
        # specialist can share a key without meaning each other.
        #
        # Opened by the ADDRESS rather than by script, the same
        # as the Schedule form, so it still works with JavaScript off.
        wanted = (request.args.get("edit") or "").strip()
        if not wanted:
            editing = None
        elif tab == "specialists":
            editing = specialists.get(wanted)
        else:
            editing = skills_store.get(wanted)

        return render_template(
            "yours.html",
            tab=tab,
            note=request.args.get("note", ""),
            skills=skills_store.read_all(),
            starter=skills_store.starter(),
            specialists=specialists.read_all(),
            specialist_starter=specialists.starter(),
            questions=specialists.suggestions_for(occupation),
            built_in=specialists.built_in(),
            built_in_on=sentinel.is_on(),
            editing=editing,
            # An `?edit=` naming something that is not there opens a blank
            # form rather than a filled one, so it must not claim to be an
            # edit -- the Save would silently create a second thing.
            showing_form=bool(request.args.get("add") or editing),
        )

    @app.route("/running")
    def running_page():
        """Now: what it is doing, and the session it is doing it in."""
        from .. import guard

        try:
            loaded = load_config()
            folder = loaded.layout.root
        except config_module.ConfigError:
            folder = None
        recent, cursor = steps.read(folder, limit=120)
        marker = session.read_marker()
        return render_template(
            "running.html",
            # The tab lives in the address, so a reload lands where you were
            # and a link can point at one section.
            tab=(request.args.get("tab") or "now").strip(),
            steps=recent,
            cursor=cursor,
            working=steps.is_working(folder),
            marker=marker,
            advice=recycle.should_recycle(),
            state=memory.read_working_state(),
            order=session.shutdown_order(holds_connection=True),
            watch=guard.assess(),
            switches=guard.settings(),
            footer=guard.FOOTER,
        )

    # Two rules, one endpoint. `/memory` is what the rail links and what the
    # page calls itself since 2026-09-05; `/history` still answers because
    # every earlier note, guide and bookmark points at it. A redirect would
    # have done, but there is nothing to redirect FROM -- neither address is
    # more correct than the other, they are the same page.
    @app.route("/memory")
    @app.route("/history")
    def history_page():
        """Two accounts of what has already happened, and nothing else.

        It used to be the day log, then two hundred events, then a recursive
        listing of every log file, all down one scroll. The two named are
        the ones a person reads deliberately; the other two answer "what
        exactly did it do at 18:08", which is a question for the day
        something is wrong.

        So those two keep their own pages -- `/events` and `/logs`, which
        render themselves and are linked at the foot of this one. Dropping
        the tabs without the links would have orphaned both: nothing else in
        the dashboard points at them.
        """
        import datetime as when_module

        from .. import today as today_module

        # reported 2026-09-05, listed five: EOD, Handoff, Dreaming,
        # Self-Optimize, vector store. Three are here; the other two arrive
        # when they do something, because a tab whose settings save and whose
        # work never runs is the "saved, visible, and inert" failure this
        # package has written up three times.
        tab = (request.args.get("tab") or "eod").strip()
        if tab not in ("eod", "handoff", "dreaming", "optimise",
                       "vectors"):
            tab = "eod"

        today = when_module.date.today()

        # --- the daily log, by date ---------------------------------------
        shown = today_module.month_from(request.args.get("m", ""), today)
        picked = today_module.day_from(request.args.get("d", ""), today)

        # Written passages first, machine timings second. One file, two
        # kinds of line, and the wrap-up is the half somebody opened this
        # tab to read.
        day_entries, day_events = memory.split_day(
            secrets_module.redact(memory.read_day(picked)))

        # --- the handoffs, by when ----------------------------------------
        kind = (request.args.get("kind") or "all").strip()
        if kind not in ("all", memory.HANDOFF_SYSTEM, memory.HANDOFF_MANUAL):
            kind = "all"
        # Read once. Counting each kind off its own call would walk the
        # folder three more times to produce three numbers.
        every = memory.recent_handoffs(count=200)

        return render_template(
            "history.html",
            tab=tab,
            # the day log
            day_entries=day_entries, day_events=day_events,
            weeks=today_module.month_grid(shown),
            month_name=shown.strftime("%B %Y"),
            month_key=shown.strftime("%Y-%m"),
            previous_month=today_module.step_month(shown, -1, today),
            next_month=today_module.step_month(shown, +1, today),
            today_date=today,
            picked_day=picked,
            written_days=memory.logged_days(),
            # the handoffs
            handoffs=[one for one in every
                      if kind == "all" or one.kind == kind],
            handoff_kind=kind,
            opened=memory.read_handoff((request.args.get("h") or "").strip()),
            handoff_counts={
                "all": len(every),
                memory.HANDOFF_SYSTEM: sum(
                    1 for one in every if one.kind == memory.HANDOFF_SYSTEM),
                memory.HANDOFF_MANUAL: sum(
                    1 for one in every if one.kind == memory.HANDOFF_MANUAL),
            },
            # the reflection pass
            dreaming=dreaming_module.state(),
            # the vector store -- both halves of it. `meaning` came with
            # the switch when it moved off the Knowledge page; leaving it
            # behind would have made a working feature unreachable.
            vectors=vectors_module.state(),
            meaning=semantic_module.state(),
            # Only the tab that needs it pays for the Ollama
            # request. See `optimising.state`.
            optimise=optimising_module.state(
                ask_ollama=(tab == "optimise")),
            # What the last indexing run could not read, carried through the
            # redirect. A list of forty documents with three unreadable ones
            # has to name the three, or the count is just a smaller number
            # with no explanation.
            skipped=flask_session.pop("vector_skipped", []),
            note=request.args.get("note", ""),
        )

    @app.route("/memory/dreaming", methods=["POST"])
    def memory_dreaming():
        """On, off, or at a different time.

        One route for all three because they are one decision -- Dreaming is
        a scheduled task, and every button here writes the same task or takes
        it away. See `dreaming.py`.
        """
        wanted = request.form.get("action", "")
        hour = _as_int(request.form.get("hour"), dreaming_module.DEFAULT_HOUR,
                       0, 23)
        minute = _as_int(request.form.get("minute"),
                         dreaming_module.DEFAULT_MINUTE, 0, 59)

        if wanted == "off":
            _ok, message = dreaming_module.turn_off()
        else:
            # On and "change the time" are the same act: write the task at
            # the time asked for. Two routes would be two ways to end up with
            # a task at one time and a page showing another.
            _ok, message = dreaming_module.turn_on(hour, minute)

        return redirect(url_for("history_page", tab="dreaming",
                                note=message))

    @app.route("/memory/vectors", methods=["POST"])
    def memory_vectors():
        """Set it up, read the documents, or throw the store away."""
        wanted = request.form.get("action", "")

        if wanted == "install":
            _ok, message = vectors_module.install()
        elif wanted == "forget":
            _ok, message = vectors_module.forget()
        else:
            ok, answer = vectors_module.index()
            if not ok:
                message = str(answer)
            else:
                message = answer.sentence()
                # Named, not counted. Carried in the session because the
                # answer is a redirect and a query string is the wrong place
                # for forty file names.
                # `flask_session`, not `session` -- the bare name is this
                # package's own session module in this file, and using it
                # here would have set an attribute on a module rather
                # than raising.
                flask_session["vector_skipped"] = answer.skipped

        return redirect(url_for("history_page", tab="vectors", note=message))

    @app.route("/memory/optimise", methods=["POST"])
    def memory_optimise():
        """Install it, point it somewhere, fetch a model, or run it now."""
        wanted = request.form.get("action", "")

        if wanted == "install":
            _ok, message = optimising_module.install()

        elif wanted == "pull":
            _ok, message = optimising_module.pull_model(
                request.form.get("pull", ""))

        elif wanted == "now":
            message = optimising_module.run().sentence()

        else:
            provider = request.form.get("provider", "ollama")
            # Two fields, one setting. The form shows whichever belongs to
            # the chosen provider and hides the other -- but a hidden input
            # still posts, so the provider decides which one is read rather
            # than "whichever is not empty".
            model = (request.form.get("model_local", "")
                     if provider == "ollama"
                     else request.form.get("model_api", ""))

            settings = optimising_module.save_settings(
                provider, model,
                _as_int(request.form.get("hour"), 4, 0, 23),
                _as_int(request.form.get("minute"), 0, 0, 59))

            if request.form.get("on"):
                _ok, message = optimising_module.turn_on(
                    settings["hour"], settings["minute"])
            else:
                _ok, message = optimising_module.turn_off()
                message = "Saved. " + message

        return redirect(url_for("history_page", tab="optimise", note=message))

    @app.route("/keys")
    def keys_page():
        """What it can reach beyond this machine: paid keys, and MCP servers."""
        from .. import mcp as mcp_module

        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return render_template("not_configured.html", message=str(exc))
        return render_template(
            "keys.html",
            saved=apis.listing(loaded),
            overview=apis.jobs_overview(loaded),
            catalogue=apis.catalogue(),
            jobs=apis.JOBS,
            job_labels={one.key: one.label for one in apis.JOBS},
            unused=[one for one in apis.catalogue()
                    if one.key not in {row["tool"]
                                       for row in apis.listing(loaded)}],
            note=request.args.get("note", ""),
            problems=request.args.getlist("problem"),
            servers=mcp_module.read(),
            where=mcp_module.project_file(),
            using_os_store=secrets_module.using_os_store(),
            fallback_warning=secrets_module.fallback_warning(),
            plugins=_plugin_rows(),
            plugins_dir=plugins_module.plugins_dir(),
            pending=_pending_plugin(request.args.get("check", "")),
        )

    from .. import plugins as plugins_module

    @app.route("/plugins/check", methods=["POST"])
    def plugins_check():
        """Look at a folder or zip and show what installing it WOULD add.

        A separate step from installing, and the whole reason this is two
        buttons rather than one: a plugin is code that will run as the user,
        and nobody can agree to something they have not been shown. It is the
        page's version of the command line's dry run.
        """
        return redirect(url_for("keys_page",
                                check=request.form.get("source", "").strip())
                        + "#plugins", code=303)

    @app.route("/plugins/install", methods=["POST"])
    def plugins_install():
        candidate = plugins_module.examine(request.form.get("source", ""))
        if candidate.plugin is None:
            plugins_module.cleanup(candidate)
            return redirect(url_for("keys_page", note=candidate.problem)
                            + "#plugins", code=303)
        _ok, message = plugins_module.install(candidate)
        plugins_module.forget_loaded()
        return redirect(url_for("keys_page", note=message) + "#plugins",
                        code=303)

    @app.route("/plugins/remove", methods=["POST"])
    def plugins_remove():
        _ok, message = plugins_module.remove(request.form.get("name", ""))
        plugins_module.forget_loaded()
        return redirect(url_for("keys_page", note=message) + "#plugins",
                        code=303)

    @app.route("/waiting")
    def waiting_page():
        """Everything the assistant is waiting on a person for.

        One list, whether it is a draft to approve or a question to settle --
        a person has one queue of "things needing me", not several.
        """
        return render_template("waiting.html",
                               items=approvals.open_items(),
                               summary=approvals.summary())

    def _back_to() -> str:
        """Where to return after acting on a waiting item.

        The sheet on Today posts to these routes, so answering has to come
        back to Today. Checked rather than trusted: a redirect target taken
        from a form is a redirect somebody else can aim.
        """
        wanted = (request.form.get("back") or "").strip()
        if wanted.startswith("/") and not wanted.startswith("//"):
            return wanted
        return url_for("waiting_page")

    @app.route("/waiting/<item_id>/<option_key>", methods=["POST"])
    def waiting_answer(item_id: str, option_key: str):
        approvals.answer(item_id, option_key)
        return redirect(_back_to())

    @app.route("/waiting/<item_id>/reply", methods=["POST"])
    def waiting_reply(item_id: str):
        approvals.reply(item_id, request.form.get("text", ""))
        return redirect(_back_to())

    @app.route("/waiting/<item_id>/dismiss", methods=["POST"])
    def waiting_dismiss(item_id: str):
        approvals.dismiss(item_id)
        return redirect(_back_to())

    @app.route("/api/mobile/waiting")
    def api_mobile_waiting():
        return jsonify({"items": [item.as_dict()
                                  for item in approvals.open_items()]})

    @app.route("/api/mobile/answer", methods=["POST"])
    def api_mobile_answer():
        """Tap-to-answer: the option key selects, it never supplies wording.

        What comes back to the assistant is the text the item itself
        declared, so this endpoint cannot be used to say anything the
        assistant did not already offer -- which is what makes it safe to
        expose to a phone at all.
        """
        payload = request.get_json(silent=True) or {}
        ok, message = approvals.answer(str(payload.get("id", "")),
                                       str(payload.get("option", "")))
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.route("/api/mobile/reply", methods=["POST"])
    def api_mobile_reply():
        """Free text, deliberately narrower: it must name an open item."""
        payload = request.get_json(silent=True) or {}
        ok, message = approvals.reply(str(payload.get("id", "")),
                                      str(payload.get("text", "")))
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.route("/watching")
    def watching_page():
        """Watch it work, rather than read about it afterwards.

        Reads the transcript Claude Code already writes. Nothing here records
        anything; delete this page and the assistant behaves identically.
        """
        try:
            loaded = load_config()
            folder = loaded.layout.root
        except config_module.ConfigError:
            folder = None
        recent, cursor = steps.read(folder, limit=120)
        return render_template("watching.html", steps=recent, cursor=cursor,
                               working=steps.is_working(folder))

    @app.route("/api/session/steps")
    def api_session_steps():
        """Cursor-paginated, so polling costs the tail and not the file."""
        try:
            loaded = load_config()
            folder = loaded.layout.root
        except config_module.ConfigError:
            folder = None
        since = request.args.get("since", type=int, default=0)
        recent, cursor = steps.read(folder, since_line=since, limit=200)
        return jsonify({
            "cursor": cursor,
            "working": steps.is_working(folder),
            "steps": [step.as_dict() for step in recent],
        })

    @app.route("/events")
    def events_page():
        """What has been happening — the one page that answers "what have you
        been doing", from the single record every subsystem writes to."""
        return render_template(
            "events.html",
            entries=events.read(limit=200),
            summary=events.summary(),
            cursor=events.line_count(),
        )

    @app.route("/api/events")
    def api_events():
        """Cursor-paginated, so a live view can poll for only what is new.

        Pass `since` (the previous `cursor`) and get the entries added after
        it, oldest first. Without it, the most recent page, newest first.
        """
        since = request.args.get("since", type=int, default=0)
        limit = request.args.get("limit", type=int, default=100)
        entries = events.read(limit=limit, since_line=since)
        return jsonify({
            "cursor": events.line_count(),
            "events": [entry.as_dict() for entry in entries],
        })

    # -- the surface a companion app would use -----------------------------
    #
    # Built before any app exists, deliberately. The reference system learned
    # that a phone client which reimplements the web pages' logic drifts from
    # them; these two endpoints exist so a future app reads the SAME functions
    # the browser does. `pages` is a server-driven menu, so adding a dashboard
    # page never requires shipping a new build of the app.

    @app.route("/api/mobile/pages")
    def api_mobile_pages():
        return jsonify({"pages": [
            {"label": "Today", "path": "/", "group": "work"},
            {"label": "Activity", "path": "/activity", "group": "work"},
            {"label": "Happening", "path": "/events", "group": "work"},
            {"label": "Chat", "path": "/chat", "group": "talk"},
            {"label": "Schedule", "path": "/schedule", "group": "system"},
            {"label": "Sessions", "path": "/sessions", "group": "system"},
            {"label": "Health", "path": "/health", "group": "system"},
        ]})

    @app.route("/api/mobile/summary")
    def api_mobile_summary():
        """One round trip, because a phone on mobile data should not make six.

        Every value here comes from the same function the corresponding web
        page calls -- so the phone and the browser cannot tell different
        stories about the same machine.
        """
        try:
            loaded = load_config()
            space = workspace.scan(loaded)
            items = len(space.items)
            label = space.schema.item_label_plural
        except config_module.ConfigError:
            items, label = 0, "items"

        state = memory.read_working_state()
        return jsonify({
            "read_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "items": {"count": items, "label": label},
            "held_messages": notify.held_count(),
            "waiting": [item.as_dict() for item in approvals.open_items()],
            "scheduled": len(schedule.installed_names_or_empty()),
            "handoff": {
                "saved_at": state.generated_at.isoformat(timespec="seconds")
                            if state else "",
                "open": len(state.open_items) if state else 0,
                "waiting": len(state.waiting_on) if state else 0,
            },
            "recent": [entry.as_dict() for entry in events.read(limit=15)],
        })

    @app.route("/api/items")
    def api_items():
        try:
            loaded = load_config()
        except config_module.ConfigError as exc:
            return jsonify({"error": str(exc)}), 409

        space = workspace.scan(loaded)
        return jsonify({
            "read_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "item_label": space.schema.item_label,
            "problems": space.problems,
            "items": [
                {
                    "key": item.key,
                    "title": item.title,
                    "values": {
                        key: {
                            "display": value.display,
                            "ok": value.ok,
                            "present": value.present,
                            "problem": value.problem,
                        }
                        for key, value in item.values.items()
                    },
                    "missing_files": item.missing_files,
                    "problems": item.problems,
                }
                for item in space.items
            ],
        })

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("not_found.html"), 404

    @app.errorhandler(Exception)
    def went_wrong(error):
        """One page for everything that throws, and a record of it.

        There was no handler here but the 404 one, so any unhandled exception
        reached a non-technical student as Flask's debug traceback or a bare
        "Internal Server Error" — depending on a setting they have never
        heard of, and neither of which tells them whether they have lost
        anything.

        It is also the backstop for the rest of this group. `Unreadable` now
        raises rather than silently returning an empty list, which is the
        right behaviour precisely because *something* catches it and says so.
        Without this, that change would trade a silent data loss for a silent
        blank page.
        """
        import traceback

        from werkzeug.exceptions import HTTPException

        # 404s, 403s and the rest already say what they mean. Only genuine
        # faults belong here.
        if isinstance(error, HTTPException):
            return error

        trace = traceback.format_exc()
        try:
            events.record("problem", f"{request.path} failed: {error}",
                          source="dashboard",
                          detail={"path": request.path,
                                  "traceback": trace[-4000:]})
        except Exception:                    # noqa: BLE001
            pass

        # Re-raised in testing so a broken page fails a test loudly instead of
        # rendering a tidy apology that every assertion then passes against.
        if app.config.get("TESTING") and not app.config.get("SHOW_ERROR_PAGE"):
            raise error

        return render_template(
            "went_wrong.html",
            came_from=request.referrer if _is_ours(request.referrer) else "/",
            detail=trace[-3000:],
        ), 500

    return app


def _is_ours(url: str | None) -> bool:
    """Whether a referrer is somewhere on this dashboard.

    The "try that again" button points at it, so it is a place this page
    sends somebody. An off-site referrer is not ours to send anyone back to.
    """
    if not url:
        return False
    return url.startswith(request.host_url)


def _as_int(value, fallback: int, low: int, high: int) -> int:
    """Read a number out of a form field without ever raising.

    A form field is user input arriving over HTTP. Letting a bad one throw
    turns a typo into a 500 page, which for this audience reads as "the
    software is broken" rather than "I typed a letter in the hours box".
    """
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return max(low, min(number, high))


def run(port: int = DEFAULT_PORT, config_path: Path | None = None,
        open_browser: bool = True) -> None:
    """Start the dashboard and, unless told otherwise, open it.

    Opening the browser matters for this audience. "Go to 127.0.0.1 colon four
    three two one in your browser" is a sentence that loses people; a window
    appearing does not.
    """
    import socket

    app = create_app(config_path)

    # Take the socket here, before anything else happens.
    #
    # THE FAILURE THIS CLOSES
    # -----------------------
    # The browser was opened on a 1.2-second timer *before* the port was
    # bound, so it opened whatever the outcome: to a refused connection if
    # nothing was listening, or -- worse -- to whatever else already owned
    # port 4321, which the student would reasonably assume was the dashboard.
    #
    # And `dashboard.vbs` starts this with window mode 0, so the exception
    # that says "address already in use" was printed into a console nobody
    # would ever see. The whole symptom was a browser tab that did not work,
    # with no way to find out why.
    #
    # Binding first turns that into a sentence.
    #
    # The socket is bound, then closed, then Flask opens its own. Handing the
    # file descriptor straight to `run_simple` would close the gap entirely,
    # and this version of Werkzeug has no parameter for it. The window is
    # microseconds on a loopback port on somebody's own laptop; the failure it
    # cannot catch is another process grabbing 4321 in that instant, and that
    # failure is now a Flask exception with a real message rather than a
    # browser tab opening onto a stranger.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Windows and POSIX need opposite options here, and getting it wrong
        # fails in the direction that looks like success.
        #
        # On Windows, a plain bind to a port somebody else is already
        # listening on SUCCEEDS -- two sockets share the port and whichever
        # the kernel picks answers. The check appeared to pass and the
        # dashboard started "fine" on a port owned by something else. The
        # option that makes Windows behave the way this code assumes is
        # SO_EXCLUSIVEADDRUSE, and it has no POSIX equivalent.
        #
        # On POSIX, SO_REUSEADDR is what lets a restart re-take a port still
        # in TIME_WAIT from the process that just stopped -- without it,
        # "stop the dashboard, start it again" fails for a minute.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET,
                                socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        listener.bind((LOCALHOST, port))
        listener.listen(128)
    except OSError as exc:
        listener.close()
        _say_why_it_will_not_start(port, exc)
        raise SystemExit(1) from exc
    finally:
        listener.close()

    if open_browser:
        import threading
        import webbrowser

        # Now safe to open on a timer: the port is already ours, so the only
        # thing being waited for is Flask starting to answer on it.
        threading.Timer(
            0.6, lambda: webbrowser.open(f"http://{LOCALHOST}:{port}/")
        ).start()

    print(f"\n  Dashboard running at http://{LOCALHOST}:{port}/")
    print("  It is only reachable from this computer.")
    print("  Press Ctrl+C to stop.\n", flush=True)

    # debug=False deliberately: the debugger exposes an interactive console,
    # which on a personal machine holding someone's notes is not a trade worth
    # making for nicer error pages.
    app.run(host=LOCALHOST, port=port, debug=False)


def _say_why_it_will_not_start(port: int, exc: OSError) -> None:
    """Explain a refused port somewhere a person will actually see it.

    Written to a file as well as to the console, because the usual way this
    is started has no console at all -- `dashboard.vbs` asks for window mode
    0 precisely so that nothing pops up, which also means nothing can be read.
    """
    import errno
    import sys

    if exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", 10048)):
        lines = [
            f"The dashboard could not start: something is already using "
            f"port {port}.",
            "",
            "That is usually the dashboard itself, still running from "
            "earlier -- try opening it in your browser before starting "
            "another one:",
            f"    http://{LOCALHOST}:{port}/",
            "",
            "If it is something else, start the dashboard on a different "
            "port:",
            f"    aki-agent-dashboard --port {port + 1}",
        ]
    else:
        lines = [f"The dashboard could not start: {exc}"]

    for line in lines:
        print(f"  {line}", file=sys.stderr, flush=True)

    try:
        from .. import events, paths

        paths.ensure_app_dirs()
        (paths.state_dir() / "dashboard-last-error.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        events.record("problem", lines[0], source="dashboard")
    except Exception:                                    # noqa: BLE001
        pass


def main() -> int:
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Run the dashboard.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", type=Path, default=None,
                        help="use a specific config file (for demonstrations)")
    parser.add_argument("--no-browser", action="store_true")
    arguments = parser.parse_args()

    try:
        run(port=arguments.port, config_path=arguments.config,
            open_browser=not arguments.no_browser)
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
