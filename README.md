# UEMW

**An experimental Unreal Engine 5 rendering frontend for original Morrowind.**

Morrowind.exe runs the game; UE renders actual live geometry translated from your own installation. Quests, scripts, AI, combat, collision, animation timing, inventory and saves stay in the original engine. This uses neither OpenMW nor a video feed, and does not rebuild gameplay in Unreal.

Windows x64 only. The supported combination is **unmodified Steam Morrowind GOTY 1.6.1820 + UE 5.2.1**. This is a source alpha with known rendering hitches and incomplete visual/mod compatibility—not a finished full-game port. Read [status and limits](docs/STATUS.md).

## Install

Install the prerequisites first:

- Your own Steam Morrowind GOTY, including Tribunal/Bloodmoon. Run it from Steam once to configure/test it, then exit it.
- Unreal Engine **5.2.1** through Epic Games Launcher.
- Visual Studio 2022/Build Tools with **MSVC 14.34/17.4 x64/x86**, plus a supported Windows SDK.
- **Python 3.12 x64** and **PowerShell 7**.

See [the setup guide](docs/SETUP.md) for component names, supported executable hash, download links and nondefault paths. The newest UE/compiler is not a substitute for these pinned versions.

Clone/extract this repository into a writable folder, open a terminal there, and run:

```bat
Setup-UEMW.cmd -CheckOnly
Setup-UEMW.cmd
```

The first command reports missing prerequisites without changing anything. The second creates an isolated Python environment and private vanilla game copy, fetches the hash-pinned graphics wrapper, generates materials, builds/packages UE and runs tests. The first shader build can take several minutes. It does not install system software, overwrite the Steam game, copy existing saves or edit your Steam library.

**One-time Steam step:** Add `<your UEMW folder>\local\bin\uemw-game-start.exe` using **Steam → Add a Game → Add a Non-Steam Game → Browse**. Add that bootstrap once; setup detects an existing correct shortcut. Then keep Steam running:

```bat
Doctor-UEMW.cmd
Start-UEMW.cmd
```

For another Steam library/engine location:

```bat
Setup-UEMW.cmd -GameRoot "D:\SteamLibrary\steamapps\common\Morrowind" -EngineRoot "E:\Epic\UE_5.2"
```

Paths are otherwise discovered and saved in ignored `local/config.json`. No coding-agent tools or global Python packages are required. [Troubleshooting](docs/TROUBLESHOOTING.md) covers prerequisite, Steam, startup and rendering failures.

## Play

Load a disposable save or start a new character in **original Morrowind**, and keep that window focused. Keyboard and mouse go directly to Morrowind exactly once; UE stays passive. `Start-UEMW.cmd` retains the separate-window baseline. **`Start-UEMW-Unified.cmd`** places UE over the original play area and translates the original HUD, menus, maps, journal and dialogue geometry/textures over its scene. Both use the same packaged client.

Unified presentation keeps the small GPU-only inventory portrait on the original UI surface through a bounded opening in the passive overlay. It does not capture the game window or rebuild UI logic. Loading exposes the original progress view until UE resources are ready; unsupported or stale UI falls back to the original. A latched fault needs an explicit relaunch. Native UI sampling is bounded at 60 Hz for menus and 30 Hz for the HUD; actual capture/adoption rates depend on workload. This is not pixel-perfect UI parity or a locked-60 guarantee. See [rendering evidence and limits](docs/PERFORMANCE.md).

The packaged client defaults to D3D12/SM5 with a separate rendering submission thread. Unified mode uses capped VSync on measured 59/60 Hz outputs. For a D3D11-only GPU or a backend-specific problem, run `Start-UEMW-Unified.cmd -RHI d3d11` (or `Start-UEMW.cmd -RHI d3d11` for separate windows). This switches only this project's renderer; it leaves the original game running.

`Stop-UE-View.cmd` closes UE and its bridge while leaving the game open. Save/exit the original normally. `Stop-UEMW.cmd` force-stops the whole private session, discarding unsaved progress. Normal launches do not record video or screenshots.

Your private game/saves are under `local/Morrowind`; converted assets are under `local/assets`. They are generated from **your own** game and must not be committed or uploaded as source. All game/engine assets, binaries, downloads and local diagnostics are excluded from Git. See [third-party notices](THIRD_PARTY_NOTICES.md).

## Source layout

| Path | Purpose |
|---|---|
| `bridge/` | Read-only native state, asset conversion, IPC, presentation and watchdog runtime |
| `native/` | Small Windows startup/read helpers and optional diagnostics |
| `ue/UEMorrowind/Source/` | UE renderer and packaged owned-data checks |
| `shaders/` | Material/shader source, generated/cooked locally |
| `tools/` | Setup/discovery, build, tests and publication audit |
| `tests/` | Owned-data Python tests; no game or UE installation required |
| `dev/` | Opt-in live diagnostics and experimental launch variants |
| `docs/` | Setup, architecture, protocol, development and known limits |

[Architecture](docs/ARCHITECTURE.md) · [Protocol](docs/PROTOCOL.md) · [Development](docs/DEVELOPMENT.md) · [Validation](docs/VALIDATION.md) · [Contributing](CONTRIBUTING.md)

```bat
Test-UEMW.cmd -Repository
Test-UEMW.cmd -Renderer
```

GitHub CI runs Windows owned-data tests without Morrowind/UE. Full UE builds/live tests require the separately installed licensed dependencies. See [rendering performance work](docs/PERFORMANCE.md) for the current hitch reductions, measurements and remaining limits.

Original project code is [MIT licensed](LICENSE). Optional Real-ESRGAN adaptations retain their BSD-3-Clause notice; all third-party/game/engine licenses remain separate. UEMW is not affiliated with Bethesda, Valve or Epic.
