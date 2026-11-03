# Setup on Windows

UEMW builds its UE frontend from source and prepares a private copy of your installed game. All generated files stay in `local/`, `logs/`, `third_party/` or Unreal output folders. No Bethesda assets or prebuilt game/engine binaries are supplied.

## Required installations

| Prerequisite | Supported configuration |
|---|---|
| OS | 64-bit Windows 10/11 on x64; D3D12/SM5 GPU/driver for default launch, or D3D11 with the explicit `-RHI d3d11` launcher fallback |
| Game | User-owned Steam Morrowind GOTY, app 22320, including Tribunal and Bloodmoon |
| Executable | Unmodified Steam 1.6.1820, SHA256 `eac72e1b3524ee0012d080d3c2e2e00e401464e41ee54f9afd6aaaadf2c221f5` |
| Unreal | **UE 5.2.1**, installed through Epic Games Launcher, with editor/C++ and built-in ProceduralMeshComponent/Paper2D content |
| Compiler | Visual Studio 2022 or Build Tools, C++ x64/x86 tools, including **MSVC v143 14.34 (17.4)** |
| SDK | Windows SDK **10.0.26100.0** (tested), 10.0.22621.0 or 10.0.19041.0 |
| Python | **CPython 3.12 x64**; setup installs pinned NumPy/Pillow into the project venv |
| Shell | **PowerShell 7 x64**; no global execution-policy change is needed |

Install [PowerShell](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows), [Python](https://www.python.org/downloads/windows/), [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/) and [Epic Games Launcher](https://www.unrealengine.com/download) from their publishers. In Visual Studio Installer's **Individual components**, select the 14.34/17.4 x64/x86 toolset as well as a listed SDK; having only the newest compiler is insufficient for this pinned UE version. The component ID is `Microsoft.VisualStudio.Component.VC.14.34.17.4.x86.x64`; see Microsoft's [component catalog](https://learn.microsoft.com/visualstudio/install/workload-component-id-vs-build-tools?view=vs-2022) and Epic's [Visual Studio compatibility table](https://dev.epicgames.com/documentation/en-us/unreal-engine/setting-up-visual-studio-development-environment-for-cplusplus-projects-in-unreal-engine).

Other game executables/localizations, modified executables, GOG, OpenMW and newer UE versions are not silently accepted. Mod compatibility is deferred. Use a clean Steam game installation. Run the original game from Steam once to configure it and confirm it works, then exit it before your first UEMW session. UE and the compiler are build prerequisites; normal packaged play does not run UnrealEditor. ffmpeg, Blender, MWSE, MGE and PyTorch are not required for normal setup/play.

## Install and build

1. Clone or extract the source into a writable, reasonably short folder, for example `%USERPROFILE%\source\UEMW`. Keep it out of Program Files. A first build needs several GB beyond the private game copy; allow at least 20 GB free for UE intermediates/caches.
2. Open a terminal in that folder and run `Setup-UEMW.cmd -CheckOnly`. This discovers Steam libraries, UE, Python, all VS 2022 editions/Build Tools and supported SDKs. It reports missing prerequisites before making changes.
3. Run `Setup-UEMW.cmd`. It creates the local venv, installs the two pinned Python dependencies, copies vanilla game files without existing saves or loose mods, installs the hash-pinned private graphics wrapper, generates project materials, builds/cooks/packages UE and runs owned-data tests. The first shader build can take several minutes. Its build log is `logs/setup-build.log`.
4. In Steam, choose **Add a Game → Add a Non-Steam Game → Browse** and select **`<your UEMW folder>\local\bin\uemw-game-start.exe`**. Add it once. Its display name is your choice; do not add Morrowind.exe or UnrealEditor instead. Setup/Doctor detects an existing correct shortcut and does not edit your Steam library.
5. Keep Steam running, run `Doctor-UEMW.cmd`, then double-click `Start-UEMW.cmd`.

The source bootstrap must stay in `local/bin`; it derives the private working directory from its own location. If you move the whole checkout later, rerun setup and update/re-add its Steam shortcut. Your actual game stays in `local/Morrowind`; converted meshes/textures appear in `local/assets` as you play. Neither folder belongs in Git.

## Paths and configuration

For installations discovery cannot resolve, pass explicit paths:

```bat
Setup-UEMW.cmd -GameRoot "D:\SteamLibrary\steamapps\common\Morrowind" -EngineRoot "E:\Epic\UE_5.2"
```

Other supported overrides are `-SteamExe`, `-PythonPath`, `-ToolchainRoot`, `-SdkRoot` and `-SdkVersion`. Steam's client can be on a different drive from its game library. Detected paths are saved only in ignored `local/config.json`; `config.example.json` shows the schema. The local venv is always preferred by project scripts, without changing system Python or the user's PATH permanently.

The `.cmd` launchers discover an installed PowerShell 7 in normal locations/PATH. For a portable shell, set `UEMW_POWERSHELL` to the full `pwsh.exe` path, or place that path alone in ignored `local/powershell.path`. No coding-agent installation is needed.

Setup and Doctor keep their console open so their results and the one-time Steam step remain visible. Automated callers can set `UEMW_NO_PAUSE=1`; all root launchers preserve the tool's exit status.

Rerunning setup reuses a verified private copy, preserves its INI/preferences and saves, and reuses pinned downloads. It does not merge a modded installed Data Files tree. An incomplete/unsupported existing private folder causes a clear error instead of being overwritten. Rename/move it yourself if you intend to replace it. `-SkipBuild` prepares dependencies/private files only and is for development; it is not a ready-to-play installation.

## Play and stop

Load a disposable private save or start a new character in original Morrowind. Keep that original window focused; controls and native menus/dialogue go to it exactly once. UE is a passive visual window. The default is two windows; the experimental overlay is documented in [development](DEVELOPMENT.md).

The original input bindings apply, typically W/A/S/D and mouse look, F to ready a weapon, Tab for view mode, Space to activate, right-click for inventory and Escape for menus. Idle vanity mode belongs to the original game; walking cancels it. Normal launch records no screenshots/video.

`Stop-UE-View.cmd` stops UE and the bridge while keeping the original game open. Exit/save the original normally. `Stop-UEMW.cmd` stops the whole private session and discards unsaved progress. Do not use it as a substitute for saving. Startup and process guards refuse unrelated game processes.

See [troubleshooting](TROUBLESHOOTING.md) if a check or launch fails, and [status](STATUS.md) for rendering limits.
