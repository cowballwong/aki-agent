"""A general-purpose personal AI agent you install on your own machine.

The package is deliberately small and readable. It is teaching material as
much as it is software: it gets opened in class and taken apart layer by
layer, so an obvious implementation always beats a clever one.

Layout
------
    paths.py      where everything lives, on both Windows and macOS
    schema.py     the declarative item schema -- read this one first
    config.py     the single configuration object
    workspace.py  reading the user's folders off disk
    doctor.py     plain-language health check

Nothing in this package knows what job its user does. Every profession-specific
word lives in the user's own config file. If you find one in here, it is a bug.
"""

__all__ = ["paths", "schema", "config", "workspace", "doctor"]

# Kept separate from any product name on purpose -- the package has not been
# named yet, and the version is about the code, not the branding.
__version__ = "0.48.10"
