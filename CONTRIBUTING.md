# Contributing

Start with [architecture](docs/ARCHITECTURE.md) and [development](docs/DEVELOPMENT.md). Keep changes scoped and include the checks you actually ran.

Morrowind.exe remains authoritative. Do not add UE gameplay, collision, AI, animation events or save logic. Native-state reads must retain executable, process, scene, ownership, bounds and freshness validation. Normal launches must not inject input, record video, change installed game files or require administrator privileges.

Use owned synthetic data in automated tests. Never commit game files, saves, converted assets, engine-generated content, model weights or local diagnostics. Run `Test-UEMW.cmd -Repository`; rendering changes also require the packaged UE checks and a bounded live check using a disposable save. Report frame timing honestly: actor ticks are not displayed FPS.

The public CI runs on Windows without Morrowind or UE and builds only the small native read helper. Full packaging is a local, licensed-toolchain check. Avoid mixing a rendering fix with unrelated setup changes. Third-party adaptations must retain their applicable attribution/license.
