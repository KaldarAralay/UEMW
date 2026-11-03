# Rendering hitches and transient visibility



Latest milestone: goal 2 streaming continuity, described below. Historical measurements remain for comparison; they are not current scanout guarantees.



## Rendering goal 2: compatible resource handoff



The packaged client retains compatible GPU meshes, skin components/palette textures and mutable sections through native lighting-driven asset changes. It stages materials before committing binding order, and applies fresh incoming original poses throughout. Real replacements, native hides, removed IDs and cell/session changes keep their existing exclusion rules. Old pose-cache reuse remains strict by asset.



An initial candidate exposed a separate 420 ms full-catalog decode on the motion reader, sufficient to trip the unchanged 500 ms watchdog. UBI2 now moves catalog-derived binding identities into a bounded immutable binary table prepared separately. The resource worker independently cross-checks it against the full catalog. We retained the failed candidate evidence rather than counting its earlier short benchmark as success.



The final guarded 18-second walk measured 56.30 distinct original captures/sec and 54.66 distinct original frames applied/sec (47.14 complete + 7.52 partial). Complete/partial age p95 was 38.08/43.67 ms. Game-thread intervals median/p95/max were 16.67/16.67/37.21 ms; GPU duration median/p95/max 16.26/22.08/43.69 ms. Motion-reader decode median/p95/max was 1.88/2.29/51.29 ms. There were 60 compatible resource retargets, zero rebind hides, ten shared GPU mesh aliases and 128 resource jobs. Partial frames still occur for newly discovered or genuinely incompatible resources; those counts are explicit, not a claim of full-world completeness or locked 60 displayed FPS.



Verification: 315 Python tests and 27 packaged UE tests passed. The native weapon check passed 54 exact pose/placement witnesses and two draws (~511/545 ms, including original animation and polling); near-pose age p95/max was 32.84/45.02 ms. Ten exact NPC witnesses passed during walking/turning. A native 206-unit walk crossed an adjacent resident-cell boundary without resetting the scene epoch; entry into the tradehouse and original Space activation of its exit door produced live new epochs. No stale-snapshot scene hides occurred in the roughly four-minute acceptance log, including these checks; native reload/menu/loading hides remain intentional. This is bounded verification, not continuous displayed-frame proof.



A current-session disconnect produced a fresh non-live heartbeat while Morrowind stayed alive; a distinct new bridge session recovered in the same renderer. All 32 protected saves retained their hashes. An initial disconnect attempt raced native reload and was discarded; only the repeated fresh-identity check counts. Local evidence: `logs/hitch02-matched-stream02.json`, `stream02-ubi2-weapon-regression.json`, `stream02-ubi2-npc-visual.json`, `stream02-ubi2-transitions.json`, `stream02-ubi2-disconnect.json`, `stream02-ubi2-recovery.json`, `stream02-ubi2-save-integrity.json`, and `hitch02-ubi2-verified-ue-runtime.log`. Normal startup records nothing.



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





## Rendering goal 1: native motion cadence



The final 18-second guarded native walk used the packaged D3D11 client at 1920x1080, with original rendering enabled and no recording. Nine resident exterior cells were prepared; original AI, particles, lighting allocations and streaming kept running. Local evidence is `logs/cadence01-results.json` and `cadence01-final-benchmark.json`.



| Measurement | Previous hitch build | Goal 1 candidate |

|---|---:|---:|

| Distinct captured original frames/sec | 26.44 | 55.94 |

| Complete UE state applications/sec | 21.68 | 49.07 |

| Partial UE state applications/sec | 3.60 | 4.14 |

| Distinct original frames applied/sec, including partial | Not counted separately | 53.21 |

| Complete pose age p95 at game-thread apply | See previous result | 40.48 ms |

| Partial pose age p95 at game-thread apply | See previous result | 42.07 ms |

| UE actor interval median / p95 / maximum | 16.67 / 16.69 / 31.67 ms | 16.67 / 16.69 / 29.66 ms |



These runs are bounded observations with different ongoing streaming work, not isolated GPU benchmarks. Motion delivery improved; this does not mean displayed FPS doubled. The source interval still reached 67.88 ms, so streaming pauses remain. This run built 224 resource jobs and still had partial frames; those are explicitly the next goal.



Native matrices now remain in owned float32 blocks through complete/retained packet encoding, with sparse current deformation payloads. Skin equations use batched float64 calculations with the same association and float32 output as the scalar path. All 11,023 palettes sampled from 94 real native captures matched the scalar equations exactly. Immutable binding/particle metadata is cached; captured poses and timestamps are not renewed or predicted. Node-copy fences are read before CPU classification; later particle/morph/metadata spans remain separately reported and are not an atomic whole-engine snapshot claim.



The final candidate passed 311 Python tests and all 26 packaged UE renderer tests. A separate native walking/draw check passed 54 exact near-pose/placement witnesses and two draws at approximately 398/428 ms, including original draw timing and observer polling. Disconnect produced a fresh non-live renderer heartbeat while Morrowind stayed alive; a new producer session restored normal operation. All 32 protected save hashes remained unchanged.



GPU duration in the walking run was 15.99 ms median, 23.73 ms p95 and 35.29 ms maximum. Own-swapchain statistics are reported separately in the result: successful submissions and observed display changes differ, and ID gaps are ambiguous. This is not locked 60 FPS, continuous scanout visibility or input-to-photon proof. No ETW trace, video or native render suppression was used.



## Rendering goal 3: native material stages



The packaged D3D11 client passed 325 Python and 28 UE tests. Actual installed Fireblade equipment supplied the original 32-pointer enchantment palette; the final live check matched 12 changing indices and all projection/sampler uniforms to exact accepted source captures. The installed in_lava_256 geometry supplied 16 distinct UV hashes, all matching the original resolved NiUVController buffer. No controller clock or gameplay was recreated. A full render-selection rebuild previously dropped stage-only controllers; the repair and regression test preserve their updates. Short separate original/UE visual observations showed the real animated lava plane and drawn weapon.



The bounded 18-second native walk measured 53.93 distinct source frames/sec, 51.45 applied native frames/sec (43.51 complete plus 7.94 partial), and complete/partial pose-age p95 44.02/47.49 ms. Actor interval median/p95/max was 16.67/19.13/51.00 ms; GPU duration 15.91/26.39/42.75 ms. Game-thread work median was 8.69 ms versus the earlier goal-2 run's 6.57 ms, with different active streaming work. Motion decode reached 79.48 ms on a catalogue change; isolated streaming costs remain. The material implementation meets the bounded motion-rate/age target, not locked 60 displayed FPS or every-frame visibility.



Weapon regression passed 54 exact pose/placement witnesses and two draws at approximately 472/463 ms; ten exact NPC submission checks passed. Disconnect produced a fresh non-live state while the original remained alive, and a new source session recovered. The same disposable checkpoint was restored after unsaved native fixtures. All 32 protected save hashes were unchanged. Local evidence: logs/material03-live-materials.json, material03-native-effect-capture.json, material03-native-uv-animation.json, material03-weapon-regression.json, material03-npc-visual.json, material03-disconnect.json, material03-recovery.json, material03-save-integrity.json and material03-walk-summary.json.



Additional decals, animated secondary UV sets, high UV-set indices, non-sphere effect mapping and in-memory/rendered textures are explicit unsupported cases. Terrain/water environment combinations, bump packed-format/luminance and exact original environment compositing still lack parity. No global visual-quality reduction was used to make the new shaders fit; shared sampling avoids the shader-model-5 sampler limit.



## Rendering goal 4: particles and alpha comparison



The packaged D3D11/Vulkan build passed 329 Python and 29 NullRHI renderer tests. A separate packaged D3D11 test passed 48 GPU comparisons (all eight functions, alpha immediately below/at/above the source reference, masked and translucent policies). Coverage is separate from colour shading so depth/shadow passes do not pull in the full lighting graph. Native comparisons use source-alpha textures rather than generic coverage-adjusted alpha.



An unsaved original Light_Fire fixture supplied four real flame/smoke systems: 20 exact capture witnesses matched 80 changing geometry hashes and 44 colour hashes while turning. Their vanilla draw path ignores stored quaternion/geometry-UV arrays; corner and fixed-UV translation now matches the installed draw routine. A native Fireball spent original magicka and travelled about 1,271 units across four exact submitted projectile rows. That observer skipped 28 unavailable/expired source attempts, so it establishes sampled correctness, not every-frame visibility. Six separate actual rain checks matched 23–39 active source drops per sample. Source retirement remains authoritative. Short original/UE visual observations showed the flame behind an occluding NPC.



The bounded walk delivered 55.59 distinct original captures/sec and 53.28 applications/sec, including 5.86 partial applications/sec. Complete/partial pose-age p95: 41.80/42.07 ms. Game-thread interval median/p95/max: 16.67/16.67/44.20 ms; work median 7.68 ms. GPU median/p95/max: 16.13/23.18/53.41 ms. Decoder maximum was 13.94 ms in this run; 58 compatible retargets produced zero rebind hides. These are separate timing measures, not locked 60 displayed FPS. New resources still have an explicit loading interval; the effect acceptance waited for actual bindings and resource readiness before comparing poses.



54 exact weapon witnesses, two draws at roughly 440/381 ms, ten exact NPC witnesses, original checkpoint restore, current-session disconnect/new-session recovery and 32 protected save hashes passed. Evidence: logs/particles04-walk.json, particles04-live-effects.json, particles04-spell.json, particles04-rain.json, particles04-weapon-regression.json, particles04-npc-visual.json, particles04-disconnect.json, particles04-recovery.json and particles04-save-integrity.json.



UE component sorting still approximates original sorter overrides and intersecting transparency. Mesh-based particle subclasses and arbitrary mod blend factors are not general support claims. Water reflection transparency/shadows remain goal 5.



## Water/reflection ownership and fidelity (rendering goal 5)

The packaged client now alternates two 640-pixel HDR targets on a phase-preserving 30 Hz schedule. CaptureScene enqueues the image before an asynchronous render-command fence; a later tick promotes only the completed target together with its exact camera, lens, sky, source/camera sequence and epoch. The displayed target is never the pending write target. Stale images expire after 250 ms without renewing their timestamps. Epoch/water-plane changes and underwater/menu/disconnect states invalidate reflection presentation. There are no CPU waits or catch-up bursts.

Original world transparency and bounded dynamic shadows participate. Source culling includes the mirrored camera while retaining native hide, owner and retirement checks; rain, water and first-person geometry remain excluded. The native particles still use their main-camera quad orientation. UE 5.2 HDR scene-color capture bypasses post-processing, verified in the installed engine source; capture FXAA/TAA are disabled and the existing five-tap water sampling filter remains.

330 Python and 30 packaged NullRHI tests pass. An additional D3D11 WaterImageOwnership fixture measures actual central HDR pixels: opaque green (0, .999512, 0), then 50% red transparency (.5, .499756, 0). Its first fixture incorrectly treated the material placeholder texture as underwater environment; using the typed disabled environment table corrected the fixture, and the final GPU run passes. This was a fixture failure, not evidence of successful transparency in the failed run.

A matched daylight off/on pair measured median GPU 16.173/16.738 ms, p95 18.602/20.523 ms; enabled maximum 52.175 ms. Game-thread work median/p95/max enabled: 6.770/10.795/41.080 ms. Enabled distinct original applications: 51.90/sec; complete pose age median/p95/max 36.22/41.84/46.13 ms. Capture counters advanced about 30/sec. Earlier baseline/candidate captures used different original time/lighting and are not an isolated causal performance comparison. No timing run includes screenshot recording, and these are not scanout measurements or a locked-60 claim.

Actual installed shoreline images show reflected scenery/NPCs; an unsaved Light_Fire across the water is visible in the raw reflection target. Six native movement checks, original underwater suppression, 22 units of native swimming and resurfacing passed. Ten exact NPC submissions covered 162.81 units of native movement. Weapon walking/two draws, same-checkpoint reload, fresh disconnect/recovery and 32 protected save hashes pass. The first weapon attempt timed out during post-load synchronization; the focused retry passed. Source archives contain no game assets or local evidence images.

Evidence: logs/water05-day-off.json, water05-day-on.json, water05-day-pair-captures.json, water05-live-pairing.json, water05-transitions.json, water05-effect.json, water05-npc-visual.json, water05-weapon-regression.json, water05-disconnect.json, water05-recovery.json, water05-save-integrity.json and client-reflection-gpu.log. Exact whole-game water/shadow parity and continuous every-frame visibility remain unproven.


## Lighting selection and shadow coverage (rendering goal 6)

Selection previously subtracted NiPointLight's native object-selection radius from camera distance. That radius is not the original D3D attenuation reach, and can contain unusually large values. The source now ranks current enabled identities using original nominal colour and reciprocal attenuation, with canonical row order and 35% incumbent hysteresis. The history follows compatible same-epoch resource adoption and resets for foreign scenes. Native per-object light lists still gate desired diffuse lighting.

A live exterior test exposed another problem in the initial candidate: candle dimmer animation reshuffled the 32-light budget. Ranking now uses the nominal original colour with max(1, dimmer); actual dimmer values remain unchanged in shader pixels. Both packed URD metadata and JSON decoding retain the same nominal peaks separately. Local shadow ranking likewise uses nominal attenuation-based importance. There are still at most four interior/two exterior local shadow owners and 32 selected lights. Disabled, retired and out-of-range lights cannot survive merely through hysteresis.

Directional shadow reach now follows the captured native far plane, capped at 8192 units outside and 4096 inside, rather than ending at a second hard 6000-unit edge inside the native horizon. Four outdoor cascades use exponent two and 25% overlap/fade. Their resolutions/budgets remain bounded. UE filtering, native per-object light limitations and exact original shadow parity remain approximations.

334 Python and 30 packaged UE tests pass. A static tradehouse shadow on/off comparison measured mean scene-ROI darkening 2.085 display-luma levels; 53.09% of pixels darkened by over two levels and .016% brightened. The initial comparison was invalidated by native idle vanity motion; the diagnostic now waits for vanity cancellation and first-person stabilization. Six turns each in the tradehouse, exterior day and exterior night retained the same selected light/owner sets. The exterior had 66 original candidates, 34 omitted by the explicit budget. Native cloudy weather and different original sun/ambient/sky values were observed; no renderer weather clock was created.

Final checkpoint walk: 49.24 distinct native applications/sec, complete/partial pose-age p95 44.116/43.954 ms, GPU median/p95/max 16.287/23.680/44.430 ms; actor intervals 16.667/16.733/47.800 ms, zero rebind hides, four compatible retargets. A crowded shore at a different view/time/workload measured 39.72 applications/sec and GPU 22.777/33.702/47.899 ms, with game-thread work maximum 50.593 ms. These are not matched before/after causality measurements or scanout FPS, and sustained 60 FPS remains unproven. An earlier interior sample with the same coverage settings measured GPU 16.609/19.242/20.247 ms and pose-age p95 26.632 ms; nominal selection was subsequently repaired.

54 exact weapon witnesses, two draws (490/403 ms), ten exact NPC submissions, original disposable checkpoint restoration, fail-safe disconnect/new-session recovery and 32 protected save hashes pass. Short tests do not establish all-weather or every-frame visibility. Evidence: logs/lighting06-python.log, lighting06-headless-release.log, lighting06-acceptance.json, lighting06-checkpoint-walk.json, lighting06-exterior-benchmark.json, lighting06-interior-benchmark.json, lighting06-weapon-regression.json, lighting06-npc-visual.json, lighting06-disconnect.json, lighting06-recovery.json, lighting06-save-integrity.json and shadow-lighting06-tradehouse-pair.json.


## Geometry coverage (rendering goal 7)

NiTriStrips now preserves the supported executable's strip order/restarts and degenerates while publishing the existing triangle-list format. NiLines uses source vertex-to-next flags plus explicit last-to-first closure, original model positions/UVs/packed colours, and a dedicated GPU PT_LineList proxy. The DX8 line path omits normals and a skin palette. It remains unlit and all gameplay/collision stays in Morrowind. The UML2 local carrier never enters triangle instancing; direct validated section storage avoids UE's deliberate degenerate-triangle removal, which the first real GPU fixture correctly exposed. CPU line updates rebuild only when current source vertices/transform actually change; their whole-game frequency is unmeasured.

340 source tests and 31 packaged UE tests pass. A separate D3D11 run measured 57 red pixels from two owned line segments; it also checks exact native transform placement, no triangle batch, native hide and epoch retirement. Source tests cover actual traversal/conversion, invalid counts/types/indices, strip parity/restarts, disconnected/closed lines, changed topology cache identity and mutable storage fencing.

An installed archive format lookup found zero NiTriStripsData/NiLinesData strings among 7,320 NIF entries in Morrowind/Tribunal/Bloodmoon. These were assumed coverage gaps. The implementation is validated with owned format fixtures; there is no claim of a live vanilla example of either type, arbitrary mod compatibility, or a static substitute level satisfying live acceptance.

The ordinary original scene passed 54 exact weapon witnesses, two native draws (366/426 ms), ten NPC submissions across 578.59 units of original movement, same-checkpoint reload, disconnect/new-session recovery and 32 protected save hashes. A six-second walk measured 50.39 distinct original applications/sec; complete/partial pose-age p95 45.019/56.321 ms, GPU median/p95/max 16.538/25.981/57.383 ms, actor interval 16.667/21.806/57.063 ms. 177 compatible retargets caused zero rebind hides. These scene-dependent results retain isolated streaming/GPU stalls and partial age above 50 ms; they are not a locked-60, scanout or every-frame visibility claim.

Evidence: logs/geometry07-python.log, geometry07-headless-command.log, geometry07-gpu-command.log, client-topology-gpu.log, geometry07-installed-formats.json, geometry07-walk.json, geometry07-weapon-regression.json, geometry07-npc-visual.json, geometry07-reload-command.log, geometry07-disconnect.json, geometry07-recovery.json and geometry07-save-integrity.json.


## Rendering goal 8: bounded installed distant scenery

The normal producer owns a separate below-normal-priority read-only conversion/state worker. A 7x7 halo uses original LAND heights/normals/colors and swizzled LTEX paint, plus static NIF hierarchy/material/texture data. Native persistent/modified/moved lists override original placement and enable/delete/scale state. Resource preparation is bounded and asynchronous; native resident envelopes and all active native catalog cells exclude overlapping distant draws. No UE gameplay, actors, collision or animation events are created.

The Seyda Neen halo prepared 49 terrain cells and 935 eligible static references in 2.55 seconds cold (first measured bake), 4,096 bindings and 759 definitions / 70,533 distinct vertices. The local immutable set was about 13.5 MB; later halos and retained generations add to that. Approximately 40–65 ms separate-worker state work at 5 Hz was observed; this is not a main-bridge pose read. The per-halo instance cap omitted 3,741 lower-priority references in the initial halo. Fixed terrain LOD uses every fourth interior sample while retaining all real border samples. Budgeted exclusions are explicit, not whole-world visual parity.

350 Python / 32 packaged UE tests cover source records/identity, exact terrain borders/area, native move lists, corruption, exported indices, conversion-time mutation rejection, lease expiry/source/epoch rejection, cache protection, residency union and actual resource submission. A separate D3D11 fixture measured 54 pixels changed by actual auxiliary geometry. Its first background-dependent pixel assertion failed while the real source was running; comparing an empty capture to the same capture with owned geometry fixed the test without changing production rendering.

Installed/native parity compared 32 static shapes / 3,924 vertices, within recorded float32 world-composition tolerance. Thirty-two actual paint assignments matched; their 800 terrain vertices had zero height error. The original console moved the private player across cells from Seyda Neen to (0,-9); an enabled original dock plank then rendered as nonresident geometry. Native scale 0.75, disable and re-enable reached actual UE submissions with fresh independent static timestamps. These were unsaved diagnostic changes; the same disposable checkpoint was reloaded. Early walking-based fixture attempts encountered steep terrain/vanity orientation, and a console close was initially ignored during original cell loading; those failed attempts were not counted as passes.

The first live candidate reapplied static geometry too often. Final code caches conservative native-cell membership and reuses unchanged submissions. Matched six-second checkpoint walking with scenery off/on: distinct native applications 49.49/48.95 per second; complete pose-age p95 44.81/45.30 ms; partial p95 41.61/43.64 ms. GPU median 16.153/16.891 ms, p95 25.542/26.342 ms, max 30.385/34.552 ms. Game-thread interval median 16.667 ms in both, enabled p95/max 18.811/32.136 ms. Zero rebind hides occurred in both. These sequential short runs contain native activity and do not prove a fixed causal cost, continuous scanout visibility or locked 60 FPS. The earlier crowded-view candidate measured 22.44 ms median GPU and a 72.34 ms actor-interval outlier; it is preserved separately.

Fifty-three exact weapon witnesses and two draws (351/339 ms), ten exact NPC submissions over 3.62 units of native movement, original checkpoint reload, fresh-session disconnect/recovery and all 32 protected save hashes passed. Disconnect hid the entire distant owner immediately; the old worker exited with its source. Native fog remains unchanged. Early horizon samples were occluded by nearby terrain, and the old exterior-fog diagnostic only disabled the completed-scene pass while material fog remained. A final original-engine noclip/SetPos viewpoint at Z=6000 with ordinary downward mouse-look verified the actual converted distant ridge and statics in the UE backbuffer. A gated distant-material fog bypass plus completed-fog bypass exposed the geometry; normal native fog obscured it as expected. The central white region in that diagnostic is the deliberately excluded resident envelope still using original material fog, not missing distant terrain in normal play. Original collision, fog and the checkpoint were restored. See distant08-surface-horizon.json and the two visual-distant08-surface images.

Limits: only the original three masters; no arbitrary plugins, source-ID-zero created STAT coverage, distant actors, dynamic/controller NIFs, small props, far shadows/reflections or guaranteed continuous loading coverage. Vanilla fog can mask nearly all beyond-residency geometry. A separate visual-distance enhancement would require an explicit rendering policy; this milestone does not silently change native fog or claim a visibly extended normal-play horizon. Broader regions, sharp terrain LOD error and sustained memory/performance remain unproven.

## Rendering goal 9: unified original UI

The packaged client now translates genuine original menu-camera geometry and UI pixels over its 3D scene. Original glyphs, wrapping, layout, maps, item icons, colours, cursor, journal pages, menu content and actions remain native. `Start-UEMW-Unified.cmd` selects the passive overlay; `Start-UEMW.cmd` retains the separate-window baseline. A small original inventory portrait region remains visible through the overlay because that native GPU target has no CPU readback. It is explicitly hybrid UI presentation, with no game-window video feed, injected readback or recreated portrait/menu logic.

Final verification: 363 Python tests, 33 packaged UE tests and a separate actual D3D11 Canvas check passed. The GPU background stayed (0,255,0) beneath alpha-zero full-screen geometry and became (128,127,0) under the owned half-alpha red UI inset. The final live cycle passed inventory, world map, inventory filter, HUD, journal, pause, load list/thumbnail and restored HUD while UE stayed presented. Actual NPC dialogue, a latest-rumors topic and Goodbye passed. Native save-name text entry produced exactly `_ui09|`, then all dialogs were cancelled without saving. Six distinct accepted native cursor geometries advanced during continuous mouse movement; the runtime sent zero input events.

Native reload exposes original progress/loading, then automatically recovers after the new source/catalog/UE resources are ready. A failed candidate incorrectly latched fallback when loading ended before geometry preparation; a bounded twenty-second post-load recovery now handles this case. True source disconnect produced a fresh non-live renderer heartbeat, stopped its owned UI worker and left Morrowind alive. A new source session restored the unified view. All 32 protected save hashes remained unchanged; the final private game was left paused.

Final short walking observation: 45.17 distinct original applications/sec; complete/partial pose-age p95 45.20/45.93 ms; actor interval median/p95/max 18.47/26.32/54.29 ms; GPU median/p95/max 19.68/28.13/39.84 ms; zero rebind hides. Fifty-two exact weapon witnesses and two draws (430/384 ms) passed, as did ten exact NPC witnesses across 4.96 units of original movement. This scene/time/workload is not an isolated before/after cost comparison or locked-60 claim. An earlier crowded third-person overlay sample had 31.09 ms median GPU time and a 79.02 ms actor outlier; it is preserved as a failed/expensive candidate observation rather than hidden.

UI cadence is separate from world/weapon cadence. Initial inventory capture was about 160 ms warm; owned page snapshots and exact-input geometry reuse reduced standalone warm samples to roughly 31–43 ms (first capture about 258 ms). The source worker remains capped at 20 Hz, with lower adoption rates under combined load. In the final eight 0.7-second UI observations, six or seven distinct UI frames were adopted per phase. Median UI capture-to-observer ages ranged from 173 to 272 ms; maximum was 359 ms. This latency is visible and remains a performance limitation. Frames expire after 500 ms, with no timestamp renewal or invented cursor interpolation.

Other failed candidates exposed and fixed opaque Canvas defaults blackening the scene, unknown XRGB thumbnail masks, transient shared-copy contention being mistaken for disconnect, and duplicate clipping of already-resolved native UI meshes. The last issue cropped journal text, borders and page-number anchors; final screenshots show full original pages, both numbers and load-menu borders. Source identity/layout fences remain; ordinary cursor motion is not destruction.

Limits: approximate Canvas depth/painter ordering and colour/filter parity; 20 Hz sampling cap and measured UI latency; bounded texture/image budgets; hybrid portrait region; unsupported arbitrary rendered targets, unusual animated 3D UI, intro/video surfaces, external OS dialogs and mod-specific shaders/menus. Unsupported/stale cases expose the original; a latched failure needs explicit relaunch. Loading uses the original progress view. Broad UI/pixel parity, long-session stability and sustained 60 FPS remain unproven.

Evidence: `logs/ui09-core-acceptance.json`, `ui09-dialogue-acceptance.json`, `ui09-text-entry-acceptance.json`, `ui09-cursor-acceptance.json`, `ui09-reload-acceptance.json`, `ui09-recovery.json`, `ui09-disconnect.json`, `ui09-save-integrity.json`, `ui09-weapon-regression.json`, `ui09-npc-visual.json`, `ui09-walk.json`, `ui09-final-live.stdout.log`, `ui09-python-tests.log`, `client-headless-tests.log`, `client-ui-gpu.log`, and one-shot `visual-ui09-*.png` images. These local diagnostics/derived images are excluded from source distribution; no long recording was made.

Evidence: logs/distant08-translation-parity.json, distant08-live-acceptance.json, distant08-paired-performance.json, distant08-weapon-regression.json, distant08-npc-visual.json, distant08-disconnected-scenery.json, distant08-recovery.json, distant08-save-integrity.json, client-distant-gpu.log and distant08-first-walk.json. Generated game derivatives and local evidence remain excluded from public source archives.
