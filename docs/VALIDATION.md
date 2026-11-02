# Source release validation

Local verification on 2026-11-02 used Windows x64, Steam Morrowind GOTY with the documented executable hash, UE 5.2.1, MSVC 14.34.31933, Windows SDK 10.0.26100.0 and CPython 3.12 x64. This is one machine, not a claim of validation on arbitrary installations.

- Full setup/build in the existing checkout: 296 Python tests passed and all 26 packaged UE automation tests passed.
- Fresh source export in a separate folder containing spaces: dependency discovery, a new isolated Python environment, fresh vanilla private-game preparation, pinned-wrapper download, material generation and full UE compilation/cooking/packaging succeeded. No configuration, generated Content or build outputs were copied into that export.
- The fresh export's Python tests passed with four optional crash-watchdog cases skipped because those opt-in diagnostic helpers were absent. The real owned-allocation read-helper tests ran. All 26 packaged UE automation tests passed.
- Portability checks covered a separate Steam library, paths containing spaces, nondefault compiler/SDK roots, PowerShell syntax and identification of actual Python worker PIDs behind Windows venv launchers.
- Compared 73 renderer C++/shader files with the pre-cleanup source baseline; their contents were unchanged. All 31 protected private saves matched their recorded hashes.
- Publication checks audited the exact public source inventory and source ZIP hashes, excluding installed game/engine files, saves, generated assets, binaries, local configuration and logs.
- Live restart smoke check: after explicitly closing the hung private game, the supported Steam-managed launcher started a fresh original process, bridge, packaged renderer and watchdog. Twelve advancing accepted frames matched 768 submitted skin palettes against their exact original source frames, with 42 shapes showing changing poses. A one-shot image from UE's own viewport visually confirmed actual geometry/textures and the third-person player in the current Balmora scene; the original window remained responsive and the passive UE view reported visible. This check sent no gameplay input and wrote no saves.

The source export deliberately has no registered Steam shortcut. Setup reports the required Steam UI step instead of silently editing the Steam library. Source-only CI is supplied; no remote GitHub Actions run was performed before publication.

This work validates source preparation, building, owned-data regressions and a bounded live launch/rendering smoke check. It is not a new full gameplay acceptance run or a rendering-performance improvement. See [status](STATUS.md) for the preceding bounded live rendering checks and outstanding hitches. Local build/test/audit evidence and the diagnostic image remain in ignored `logs/`.
