# Example workflows

`hello-workflow` is the smallest thing that is still a workflow: a manifest, an
entry, and something it produces. Copy it, rename it, and put real work in
`steps/`.

    aki workflow add examples/workflows/hello-workflow --yes
    aki workflow list
    aki workflow run hello-workflow

## Why a workflow and not a tool

A **tool** answers a question — the reader inside `local-ics-calendar` answers
"can you read a calendar?", stateless, called, returns. A **workflow** does a
job: it owns a project folder, carries sign-off gates, stops for judgements
only a person can make, resumes, and ends in a deliverable.

The distinction decides which one you are writing. If the assistant would call
your code without knowing it exists, write a tool. If somebody would say "run
the X" and then wait, write a workflow.

A **plugin** is neither — it is the box. One plugin can carry tools, skills,
workflows and panels together, which is how a whole trade arrives as one thing
and is removed as one thing:

    my-plugin/
    ├── PLUGIN.md
    ├── plugin.py      only needed to add tools
    ├── skills/
    ├── workflows/     <- what this folder's examples go in
    └── panels/

`aki workflow add` installs a bare workflow on its own; `aki plugin add`
installs a whole box. Both are real doors and neither is a workaround for the
other. `docs/PACKAGES.md` has the full model.
