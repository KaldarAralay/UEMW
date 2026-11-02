# Security and data boundaries

The bridge opens only the exact project-private, hash-validated original game with query/read access. It does not expose a network service, inject a DLL into Morrowind, write game memory or automatically attach to another process. Normal controls go directly to the original window. Optional developer crash capture and input probes are explicit tools, not normal launch behavior.

Setup downloads pinned dependencies into ignored local directories, validates the graphics-wrapper digest before copying it, and leaves the Steam installation and existing saves unchanged. Steam shortcut registration uses Steam's own UI. No administrator mode is required by the application.

For a suspected vulnerability, share the affected source path, commit and an owned/synthetic reproduction. Do not publish game assets, private save data, credentials or memory dumps in an issue. This experimental renderer is intended for local single-user use, with source and dependencies you trust.
