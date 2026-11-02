# Developer tools

The normal client needs only `bridge/` and the packaged renderer. These opt-in probes support regression work and are not part of startup.

Run `python dev/run.py <name> [arguments]` from the repository root. The wrapper gives nested Python processes the runtime and diagnostic import paths. Read the module docstring: some probes generate bounded native input, manipulate a disposable fixture, or need diagnostic UE flags. They are not unattended tests of an existing personal save.

Start with `benchmark`, `profile_bridge`, `check_first_person_motion`, `check_native_motion`, `check_render_stability`, `check_native_shadows` or `check_focus_stages`. The latter and some GPU/offline tools need optional psutil; the core runtime does not. Existing reports/surveys/failed recording experiments were archived locally rather than promoted as installation requirements.

`launchers/` contains explicit experimental variants. The supported default is the root `Start-UEMW.cmd`, using separate windows. See [development](../docs/DEVELOPMENT.md) for build/test commands and measurement limits.
