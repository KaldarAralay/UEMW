# Rendering hitches and transient visibility

The current build fixes a source ownership error and removes repeated work from the UE game thread. It keeps the original engine authoritative and preserves the visual settings.

- Live TES cell slots own cell render roots. A captured temporary parent change no longer invalidates the entire cell. Traversal stops at the owned root; root type, root/land slot replacement, native hide flags, child identities, switches and actor references still gate visibility.
- Immutable binding tables and their parsed ID indices are shared from the reader worker. Catalog preparation builds pose-rebase indices off the game thread. Promotion moves the latest accepted pose storage rather than copying its palettes. Every candidate is still compared against the incoming frame.
- Resource invalidations remain per instance. Resource-ownership maps are prepared in the catalog worker. New/rebuilt resources remain hidden until a fresh original pose is available.
- Reverse asset membership updates camera/texture/material selections incrementally. Dense binding traits avoid repeated string lookups across static world geometry.
- Retained streaming uses the parser's immutable incoming index and reuses destination capacity. Every slot receives the current native state or an explicit hide. No old sample is relabeled.
- Presentation file reads and writes use one bounded background task. Sample timestamps are preserved through delayed I/O; existing source/controller expiry and physical-window safety checks remain.
- Expensive membership and detailed visibility diagnostics are opt-in. Small health reports and scene-hide transitions remain available normally.

## Local observations

Windows x64, UE 5.2.1, D3D11, 1920×1080 client with native 4:3 framing, original rendering enabled, enhanced textures and unchanged visual settings. Short walks used the disposable Seyda Neen checkpoint with the first-person iron longsword drawn.

| Game-thread measurement | Previously reported build/run | Preserved client with repaired bridge | Final client |
|---|---:|---:|---:|
| Frame intervals sampled | 901 | 1,045 | 1,078 |
| Median | 18.88 ms | 16.67 ms | 16.67 ms |
| 95th percentile | 28.26 ms | 21.15 ms | 16.69 ms |
| 99th percentile | 30.83 ms | 22.33 ms | 19.43 ms |
| Worst interval | 78.60 ms | 23.08 ms | 31.67 ms |
| Intervals over 33.33 ms | 8 | 0 | 0 |
| Actor ticks/second | 49.50 | 57.54 | 59.62 |

The preserved-client/final-client pair used the same running original process and source session, restored the same checkpoint and repeated the same input pattern. Median complete-world apply time decreased from 12.08 to 8.20 ms. The final run performed 499 resource jobs versus 68 in the preserved-client run; its maximum was worse, despite better p95/p99. Original AI, preparation and streaming continued, so these are bounded observations, not an isolated benchmark. Earlier candidates and their regressions remain in local logs.

The previously reported column is historical context, with different preparation work; it does not isolate this patch. An initial trace of the prior renderer captured a 76.8 ms actor tick stacking catalog adoption, selection rebuilding, cache rebasing and geometry submission. Subsequent traces identified incoming-remap allocation and presentation file I/O. The corresponding work has been moved, shared or reduced.

These are **actor/game-thread intervals, not scanout FPS or input latency**. The final run did not reproduce the approximately 79 ms stalls, and the earlier median regression did not recur. A 31.67 ms frame still exceeds the 16.67 ms budget. Locked 60 FPS, every-frame visibility and long-session stability remain unproven. Original pose publication is also slower than the UE tick rate.

## Visibility finding and verification

A source trace captured the current cell root changing parents. Three otherwise unhidden skin bindings were marked invisible by the old parent-identity rule; checking the live cell confirmed that it still owned that root. The repair captures the actual root slots with each pose and rejects real retirement/replacement independently of temporary ancestry above that boundary.

All 299 owned-data Python tests and all 26 packaged UE tests passed. Regressions cover cell/land root retirement, type changes and native hiding, preparation-process transfer, shared binding lifetime, fresh palettes, cache reordering/ownership, indexed remap equivalence and mismatched-index rejection.

A separate four-second capture request produced 18 UE backbuffer images during native strafing near Indrele Rathryon. Manual review showed the NPC present in every captured image and no black viewport frames. Eight exact accepted-frame NPC palette samples matched, with no visibility mismatches; the observer then encountered an expired shared-ring frame. Recording stalls and skips requests, so this is not a continuous GPU-frame or performance proof. A separate AITravel fixture failed its movement-distance criterion because the original NPC moved only about six units; its palette samples matched, but it is not counted as successful NPC travel acceptance.

The final first-person check and disconnect/recovery check are recorded in `logs/hitch02-*.json` and the renderer test logs. The disconnect test observed a fresh non-live renderer heartbeat while the original stayed alive, then recovered into a new live source session with a responsive original window. All 32 protected private saves retained their hashes.

Use the normal [build/launch procedure](DEVELOPMENT.md) and `Start-UEMW.cmd`. Normal startup records nothing and disables the heavy diagnostics. Local captures, game data, binaries, traces and measurements stay outside Git; the source-only archive/audit is refreshed separately.
