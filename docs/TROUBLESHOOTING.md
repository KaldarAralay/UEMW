# Troubleshooting

Run `Doctor-UEMW.cmd` first. It checks dependencies, local Python packages, the private executable, packaged hashes and the Steam shortcut without starting the game. `Doctor-UEMW.cmd -DependenciesOnly` checks the build tools only.

| Symptom | Action |
|---|---|
| PowerShell 7 not found | Install it in a normal location, add it to PATH, or use `UEMW_POWERSHELL`/`local/powershell.path`; see [setup](SETUP.md). |
| Unsupported executable hash | Restore a clean supported Steam executable. Different editions, localizations and executable patches need layout revalidation, not bypassing the check. |
| MSVC toolset missing | Add 14.34/17.4 x64/x86 in Visual Studio Installer. The latest C++ workload alone may not include that older toolset. |
| Wrong UE version | Install 5.2.1 and pass its folder using `-EngineRoot`. The current source does not claim support for later releases. |
| Steam shortcut missing/ambiguous | Add exactly one shortcut targeting this checkout's `local/bin/uemw-game-start.exe`, using Steam's UI. Remove/update obsolete duplicates there. Keep Steam running in the same Windows account. |
| Windows Firewall prompt for UnrealGame/UnrealEditor | Choose Cancel. UEMW's local shared-memory/files bridge needs no network permission. UE development tooling can trigger this prompt; no firewall-rule or security-setting change is part of setup. |
| Morrowind launcher appears instead of the game | Start using `Start-UEMW.cmd` after adding the bootstrap shortcut. Do not directly launch the private Morrowind.exe or substitute Steam's normal Morrowind library entry. Check `logs/native-startup.json` and `logs/native-bootstrap.json`. |
| Another Morrowind process exists | Save/exit the other game normally. UEMW refuses to adopt the installed original or another checkout's private game. |
| Bridge/watchdog did not initialize | Read `logs/bridge-session.stderr.log` / `logs/renderer-guard.stderr.log`; rerun setup if the local Python environment/helper is incomplete. The launch code verifies the actual Python worker PID, including Windows venv redirectors. |
| Blank/loading/disconnected UE view | Load a game/new character in the original window and wait for conversion/resources. Read `logs/ue-runtime.log` and bridge stderr. A stale/invalid scene hides safely; it does not take gameplay authority. |
| Original view remains after travel, a door or rest | Current presentation automatically returns after the new scene and native UI are complete and continuously fresh for 500 ms. Check `local/bridge/presentation.json`: `fallback_cause`, `recovery_count` and `reason` distinguish a temporary fallback from a renderer exit. Old controllers need one ordinary session restart to load this repair. A persistent fallback still needs diagnosis; do not disable the watchdog or freshness checks. |
| D3D12 startup/driver problem | Try `Start-UEMW-Unified.cmd -RHI d3d11` or `Start-UEMW.cmd -RHI d3d11`. Both backends are cooked. The fallback restarts only the verified renderer, retaining the private original game. Keep the failing runtime log for diagnosis. |
| UE closes but Morrowind stays open | The independent cutoff may have detected renderer loss or prolonged native-window nonresponse. Inspect `logs/renderer-guard.stdout.log` and `local/bridge/renderer-guard.json`. Restart explicitly after checking the original. |
| Build or material generation fails | Inspect `logs/setup-build.log`, `logs/ue-build.log`, `logs/material-build.log` and `logs/client-package.log`. Confirm the pinned toolchain and SDK. No global driver/security changes are part of setup. |
| Choppy rendering | This is an experimental alpha; general frame-time hitches remain. Report cell, view mode and which window is affected. Actor tick counts do not establish displayed FPS. |
| Original game hangs while aiming precisely at the sun | The automated solar check exposed a native weather-angle hang: original main thread at `0x45321F`, with x87 NaN inside its angle-normalization loop. The watchdog exposes the original and stops UE; restarting the private session is needed. An off-center diagnostic aim avoids deliberately targeting that edge case. This renderer update does not patch the original executable; see PERFORMANCE.md for the reproduced failure and verification scope. |

All diagnostics are local and ignored by Git. When filing an issue, paste relevant lines after removing personal paths. Do not upload the private game, converted assets, saves or memory dumps. Original rendering/native menus remain available if UE disconnects.
