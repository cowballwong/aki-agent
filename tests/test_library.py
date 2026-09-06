"""The shipped library: what it contains, and the three rules it runs under.

The maintainer's design, 2026-08-19:

  1. the library is **read-only** — we write it, nobody edits it in place;
  2. **activation is per user** — setup switches on what fits their work, and
     they change it from the dashboard afterwards;
  3. **editing forks** — changing an item produces a new one of their own and
     leaves the shipped one alone.

Rule 3 is what makes an upgrade able to replace the whole library without
asking anybody anything, so most of what is tested here is that the shipped
files are never written to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import library, secrets, skills_store


@pytest.fixture
def own_home(tmp_path, monkeypatch):
    """A machine of one's own: skills folder, config folder, nothing shared."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(library.paths, "home", lambda: home)
    monkeypatch.setattr(skills_store.paths, "home", lambda: home)
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    return home


# ---------------------------------------------------------------------------
# What ships


def test_the_library_is_actually_stocked():
    items = library.catalogue()

    assert len(items) >= 100, (
        f"only {len(items)} items — the point of this was a assistant that "
        "does something on install day")
    assert any(item.kind == "specialist" for item in items)


def test_every_item_says_what_it_is_for():
    """A skill whose description is vague is a skill that never triggers —
    the single most common way a hand-written skill fails."""
    thin = [item.key for item in library.catalogue()
            if len(item.description) < 40]

    assert not thin, f"these have no usable description: {thin}"


def test_every_item_says_who_wants_it():
    orphans = [item.key for item in library.catalogue() if not item.industries]

    assert not orphans, (
        f"these belong to nobody, so setup can never suggest them: {orphans}")


def test_the_core_is_shared_and_the_rest_is_not():
    core = [item for item in library.catalogue() if item.core]

    assert len(core) >= 15, "the core is what everybody gets on day one"
    assert len(core) < len(library.catalogue()) / 2, (
        "if most of it is core, the occupation question is decorative")


def test_drafts_are_labelled_as_drafts():
    """Written from the shape of the work rather than first-hand practice.
    Saying so is what lets somebody in that trade correct it."""
    drafts = [item for item in library.catalogue()
              if item.confidence != "high"]

    assert drafts, "some of this was written without first-hand knowledge"
    assert all(item.confidence == "draft" for item in drafts)


def test_nothing_in_the_library_looks_like_a_credential():
    for item in library.catalogue():
        text = item.path.read_text(encoding="utf-8", errors="replace")
        assert not secrets.scan_for_committed_secrets(text), item.key


# ---------------------------------------------------------------------------
# Finding things in a hundred of them


def test_search_reads_the_keywords_including_chinese():
    """The Chinese trade terms live in the keyword list, and a Hong Kong user
    will search in them."""
    assert any(item.key == "quote-and-invoice"
               for item in library.search("報價"))
    assert any(item.key == "bilingual-rewrite"
               for item in library.search("繁體"))


def test_filters_compose():
    built = library.search(category="Built environment", kind="skill")
    architect = library.search(industry="architect")

    assert built and architect
    assert all(item.category == "Built environment" for item in built)
    assert all("architect" in item.industries for item in architect)


def test_an_occupation_gets_the_core_plus_its_own():
    for occupation in ("architect, small practice",
                       "I run a beauty salon",
                       "secondary school teacher"):
        offered = library.suggest(occupation)
        assert len(offered) >= 20, occupation
        assert len(offered) < len(library.catalogue()), (
            f"{occupation} was offered everything, which is the same as "
            "offering nothing")


def test_an_unrecognised_occupation_still_gets_the_core():
    offered = library.suggest("professional dog walker")

    assert offered, "nobody should be left with an empty assistant"
    assert all(item.core for item in offered)


# ---------------------------------------------------------------------------
# Switching on and off — checked by what lands in the skills folder


def test_activating_puts_it_where_claude_code_reads(own_home):
    ok, message = library.activate("file-this")
    landed = skills_store.skills_dir() / "file-this" / "SKILL.md"

    assert ok, message
    assert landed.is_file(), (
        "saved somewhere tidier and never read is this package's oldest bug")
    assert library.FROM_LIBRARY in landed.read_text(encoding="utf-8")


def test_deactivating_removes_only_our_copy(own_home):
    library.activate("file-this")
    library.deactivate("file-this")

    assert not (skills_store.skills_dir() / "file-this").exists()
    assert library.by_key("file-this").path.is_file(), "the library keeps its own"


def test_deactivating_will_not_delete_somebody_elses_work(own_home):
    folder = skills_store.skills_dir() / "file-this"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# my own, same name\n", encoding="utf-8")

    ok, message = library.deactivate("file-this")

    assert not ok
    assert (folder / "SKILL.md").read_text(encoding="utf-8").startswith("# my")
    assert "your own" in message


def test_active_keys_reports_what_is_really_there(own_home):
    assert library.active_keys() == set()
    library.activate("meeting-to-actions")
    assert "meeting-to-actions" in library.active_keys()


# ---------------------------------------------------------------------------
# Rule 3: editing forks


def test_editing_saves_a_copy_and_leaves_the_original_alone(own_home):
    original = library.by_key("weekly-writeup")
    before = original.path.read_text(encoding="utf-8")

    ok, message = library.fork("weekly-writeup", "My Monday note",
                               "# Mine\n\nJust the numbers.\n")

    assert ok, message
    assert original.path.read_text(encoding="utf-8") == before, (
        "the library was written to — an upgrade would now have to ask "
        "everybody whether they had changed anything")

    mine = [skill for skill in skills_store.read_all()
            if skill.name == "My Monday note"]
    assert mine, "the fork was not saved"


def test_a_fork_never_ends_up_with_the_same_name(own_home):
    ok, message = library.fork("weekly-writeup", "Weekly write-up", "# mine")

    assert ok, message
    assert "(mine)" in message, (
        "two abilities with one name is a coin toss over which one applies")


# ---------------------------------------------------------------------------
# The page a person browses a hundred of these on


def _browser(tmp_path):
    import yaml

    from aki_agent.dashboard import create_app

    root = tmp_path / "Assistant"
    (root / "01_Config").mkdir(parents=True)
    config_path = root / "01_Config" / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "assistant": {"name": "Mira"}, "user": {"name": "Sam"},
        "layout": {"root": str(root), "item_label": "Project",
                   "item_label_plural": "Projects"},
    }), encoding="utf-8")
    app = create_app(config_path)
    app.config["TESTING"] = True
    return app


def test_the_library_page_filters(own_home, tmp_path):
    client = _browser(tmp_path).test_client()

    everything = client.get("/library").get_data(as_text=True)
    core_only = client.get("/library?category=Core").get_data(as_text=True)
    searched = client.get("/library?q=%E5%A0%B1%E5%83%B9").get_data(as_text=True)

    assert "Add" in everything
    assert len(core_only) < len(everything), "the category filter did nothing"
    assert "Quote, invoice and chase" in searched, "Chinese search missed"


def test_turning_one_on_from_the_page_really_installs_it(own_home, tmp_path):
    from aki_agent.dashboard import app as dashboard_app

    client = _browser(tmp_path).test_client()
    client.post("/library/toggle", data={
        "token": dashboard_app.SESSION_TOKEN,
        "key": "file-this", "state": "on"})

    assert (skills_store.skills_dir() / "file-this" / "SKILL.md").is_file()


def test_forking_from_the_page_leaves_the_shipped_one_alone(own_home, tmp_path):
    from aki_agent.dashboard import app as dashboard_app

    original = library.by_key("weekly-writeup")
    before = original.path.read_text(encoding="utf-8")

    client = _browser(tmp_path).test_client()
    client.post("/library/fork", data={
        "token": dashboard_app.SESSION_TOKEN, "key": "weekly-writeup",
        "name": "My version", "body": "# mine"})

    assert original.path.read_text(encoding="utf-8") == before


def test_nothing_can_be_switched_on_without_the_dashboards_token(own_home,
                                                                 tmp_path):
    client = _browser(tmp_path).test_client()

    response = client.post("/library/toggle",
                           data={"key": "file-this", "state": "on"})

    assert response.status_code == 403
    assert not (skills_store.skills_dir() / "file-this").exists()


# ---------------------------------------------------------------------------
# The scanner that nearly got switched off


def test_a_citation_url_is_not_a_credential():
    """A scanner that flags every long link gets allowlisted around, and the
    next real key lands in an allowlisted file."""
    from fake_credentials import INNOCENT_LONG_URL

    assert not secrets.scan_for_committed_secrets(f"[cic]: {INNOCENT_LONG_URL}")


def test_a_credential_inside_a_url_is_still_caught():
    """The exemption is for links, not for keys that happen to be in one."""
    from fake_credentials import FAKE_URL_WITH_KEY, FAKE_URL_WITH_TOKEN

    for line in (FAKE_URL_WITH_KEY, FAKE_URL_WITH_TOKEN):
        assert secrets.scan_for_committed_secrets(line), line


# ---------------------------------------------------------------------------
# MCP, and the file this package is not allowed to write


def test_mcp_writes_only_the_workspace_file(tmp_path, monkeypatch):
    """`~/.claude.json` belongs to Claude Code and to every other project on
    the machine. Reading it to show what is connected is fine; writing it is
    not ours to do."""
    from aki_agent import mcp

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(mcp.paths, "home", lambda: home)
    claude = home / ".claude.json"
    claude.write_text('{"mcpServers": {"theirs": {"command": "x"}},'
                      ' "somethingElse": 1}', encoding="utf-8")
    before = claude.read_text(encoding="utf-8")

    ok, message = mcp.add("mine", "npx", ("-y", "thing@latest"),
                          root=tmp_path)

    assert ok, message
    assert claude.read_text(encoding="utf-8") == before, (
        "this package wrote into Claude Code's own configuration")
    assert (tmp_path / ".mcp.json").is_file()


def test_mcp_shows_both_scopes_and_marks_which_is_editable(tmp_path,
                                                           monkeypatch):
    from aki_agent import mcp

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(mcp.paths, "home", lambda: home)
    (home / ".claude.json").write_text(
        '{"mcpServers": {"theirs": {"command": "x"}}}', encoding="utf-8")
    mcp.add("mine", "npx", root=tmp_path)

    servers = {server.name: server for server in mcp.read(root=tmp_path)}

    assert servers["mine"].editable
    assert not servers["theirs"].editable


def test_mcp_refuses_to_silently_replace_a_working_server(tmp_path,
                                                          monkeypatch):
    from aki_agent import mcp

    monkeypatch.setattr(mcp.paths, "home", lambda: tmp_path / "nohome")
    mcp.add("mine", "npx", root=tmp_path)

    ok, message = mcp.add("mine", "different", root=tmp_path)

    assert not ok
    assert "already there" in message


def test_mcp_will_not_remove_claude_codes_own(tmp_path, monkeypatch):
    from aki_agent import mcp

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(mcp.paths, "home", lambda: home)
    (home / ".claude.json").write_text(
        '{"mcpServers": {"theirs": {"command": "x"}}}', encoding="utf-8")

    ok, message = mcp.remove("theirs", root=tmp_path)

    assert not ok
    assert "claude mcp remove" in message


def test_motion_is_disabled_for_people_who_asked_for_that():
    """Some people get migraines from moving interfaces and the operating
    system already knows who they are."""
    from pathlib import Path as _Path

    css = (_Path(__file__).resolve().parent.parent / "src" / "aki_agent"
           / "dashboard" / "templates" / "base.html").read_text(
        encoding="utf-8")

    assert "prefers-reduced-motion: no-preference" in css
    animated = css.split("prefers-reduced-motion: no-preference", 1)[1]
    assert "@keyframes flip" in animated, "the clock flip must be inside it"
    assert "animation: settle" in animated, "the page fade must be inside it"
