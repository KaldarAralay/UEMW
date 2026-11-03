# Development

Run the [setup procedure](SETUP.md) before a full build. Normal source changes live in `bridge/`, `native/`, `shaders/` and `ue/UEMorrowind/Source`. Project materials are generated from source; do not check in `Content`, `Binaries`, `Intermediate`, `Saved` or DDC outputs.

## Tests

```bat
Test-UEMW.cmd -Repository
Test-UEMW.cmd -Renderer
```

The first runs the Python suite and public-file audit. The second also runs all 33 owned-data checks in the packaged UE executable. `python tools/run_tests.py` is the direct unit-test entry point; it sets the runtime/developer/test import paths. Tests need Windows/Python/NumPy/Pillow, not game data or UE. Build `tools/build-read-batch.ps1` to include the real owned-allocation native ABI tests. Four optional crash-watchdog tests skip unless the separate diagnostic helpers were built with `tools/build-diagnostics.ps1 -IncludeTests`. CI uses `-AllowNewerCompiler` only for the small read helper; it does not relax the full UE build's 14.34 pin.

The optional `tools/test-client-alpha-gpu.ps1` uses the packaged D3D11 client and owned textures to check all eight native alpha comparisons immediately below, at and above a byte threshold, for masked and translucent policies. It runs hidden, writes a fresh diagnostic log, records no video and is separate from the NullRHI tests.

`tools/test-portability.ps1` checks PowerShell syntax, nondefault Steam-library discovery, path spacing and actual venv worker PID identification using owned fixtures. Full setup was designed to be repeatable and to report all missing build prerequisites before installing packages or changing private files.

After stopping this project's UE view/bridge:

```bat
tools\run-powershell.cmd -NoProfile -ExecutionPolicy Bypass -File tools\package-client.ps1
```

The build discovers the configured compiler/SDK, compiles the editor module and small native helpers, generates project-owned materials/probes if needed, then cooks/stages the runtime under `local/client`. `local/client/build-info.json` records source/binary hashes. Shader changes belong in `shaders/`; `tools/build_materials.py` constructs the UE material graph and embeds that source. Use `Setup-UEMW.cmd` to repeat the complete dependency/preparation/build/test flow.

## Live diagnostics

Developer probes live in `dev/diagnostics`; invoke them through `python dev/run.py <name> [arguments]` so child processes inherit the correct import paths. Some probes generate ordinary original-game input or need a disposable fixture/save. They are opt-in and never run at normal startup. Read their module docstrings before using them. Do not run a survey as proof that the game is broadly playable.

Useful starting points include `benchmark`, `profile_bridge`, `check_first_person_motion`, `check_native_motion`, `check_render_stability` and `check_focus_stages`. A current first-person probe is `python dev/run.py check_first_person_motion --pid <private-PID> --seconds 12 --draw-cycles 2`; it expects the equipped eighteen-section iron sword/hands fixture and the original focused. Reload a disposable checkpoint afterwards.

Default launch is passive two-window D3D11 with the original rendering enabled. `Start-UEMW-Unified.cmd` (or `tools/start-session.ps1 -Overlay`) translates native UI over the UE scene; `-Editor`, `-DiagnosticScreenshots`, `-DiagnosticTrace`, `-PresentationStats` and crash capture are explicit development options. Alternate launchers are under `dev/launchers`. Normal launch records nothing. Measurements must distinguish actor ticks, applied state rate, GPU timestamps and actual displayed frames.

Full-world and per-cell membership hashes are expensive and disabled during normal play. For a focused diagnostic run, set `UEMW_MEMBERSHIP_DIAGNOSTICS=1` before starting a new renderer (or pass the renderer argument `-UEMWDiagnosticMembership`). The small health/performance reports and independent fail-safe heartbeat remain enabled.

For transient visibility diagnosis, `UEMW_VISIBILITY_DIAGNOSTICS=1` logs renderer scene/skin visibility transitions. `UEMW_VISIBILITY_TRACE=hitch` on a newly started bridge records source skin visibility/parent changes under ignored `logs/`. These are expensive opt-in diagnostics; disable them for performance comparisons. Scene-hide transitions remain logged normally. A diagnostic renderer also accepts `check_native_motion.witness(ids, record_seconds=4)` for a bounded image check; this is not a performance benchmark or an every-frame visibility guarantee.

## Optional local texture enhancement

The normal build uses your original textures plus UEMW materials. It does not need PyTorch or downloaded model weights. The optional `tools/texture_upscale.py` can bake local enhanced textures from your own game; it requires a separately installed CUDA-capable PyTorch environment plus psutil. Use `--help` for modes and `--download-model` only when you want its hash-pinned Real-ESRGAN model. Close the project game/view before an offline GPU bake. Output, model weights and the enhancement index stay under ignored `local/`. The original-texture path remains available by setting `UEMW_TEXTURE_UPGRADES=0` before launch. See [third-party notices](../THIRD_PARTY_NOTICES.md).

## Publication boundary

`python tools/audit_repository.py` examines exactly what Git would publish, including accidentally staged ignored files. It rejects game/converted/binary artifacts, private/generated directories, personal absolute paths, obvious credential patterns and broken public Markdown links. Source exports without `.git` use the same public/private directory boundary.

```bat
tools\run-powershell.cmd -NoProfile -ExecutionPolicy Bypass -File tools\package-source.ps1
tools\run-powershell.cmd -NoProfile -ExecutionPolicy Bypass -File tools\audit-source-package.ps1
```

The source ZIP is generated in ignored `local/distribution`, with a content-hash manifest and no game/assets/binaries. Do not upload the entire working folder or generated client as a source archive. Existing milestone notes, experiments and local evidence are archived under ignored `local/archive` and `logs`; they are not dependencies of a fresh build.

The public GitHub workflow runs owned-data tests and the repository audit on Windows, without Steam or UE. Full build/live checks require the separately installed licensed dependencies. Rendering changes should include their actual local verification and limitations in the PR description.
