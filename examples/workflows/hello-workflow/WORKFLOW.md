---
name: hello-workflow
title: Hello workflow
version: 0.1.0
description: A two-file workflow, to prove the shape works end to end.
entry: steps/run.py
deliverable: out/hello.txt
gates: [G1]
requires_capabilities: [web_search]
keywords: [example, 示範]
---

# Hello workflow

The smallest thing that is still a workflow: a manifest, an entry, and a
deliverable. Copy it, rename it, and put real work in `steps/`.
