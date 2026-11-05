# Rendering hitches and transient visibility

## Temporary-page cleanup and allocator selection (hitch05)

The earlier light08 normal walk recorded a 96.389 ms CPU frame interval without a detailed trace. Its exact composition is unknown. A new engine trace reproduces **43.001 ms in automatic `FMemory::Trim`**, inside incremental GC cleanup and outside the live-scene actor tick. That frame spends 59.527 ms in the engine tick, 49.418 ms in the world tick and 6.05 ms in the live actor. The allocator's task-graph broadcast is only 0.471 ms at most. This identifies a real cleanup bottleneck, without proving it explains every millisecond of the earlier 96 ms interval.

Installed UE 5.2.1 source shows that memory trim first broadcasts registered cleanup callbacks, including draining the temporary-page free pool, and then calls the selected heap allocator's trim. Normal launcher and packaged checks now select UE's existing **mimalloc** implementation. Binned3 and Binned2 remain explicit comparison choices through `UEMW_ALLOCATOR`; invalid values fail before launch and runtime logs/witnesses verify the actual allocator. No engine patch, GC suppression, deferred cleanup, visual reduction or native-game change is involved.

An opt-in diagnostic times that same cleanup order separately, while the original is paused. It acquires owned 64 KiB temporary pages, returns them, and measures cleanup; page allocation/preparation is excluded. Pool bytes reach zero afterwards. Both allocators use the same diagnostic binary, with the order reversed for the large comparison. These are explicit stress measurements, not ordinary frame times or identical allocation histories.

| Returned temporary pool | Binned3 cleanup, two repeats | mimalloc cleanup, two repeats |
|---|---:|---:|
| 64 MiB | 12.228 / 10.951 ms | 3.057 / 3.527 ms |
| 256 MiB | 53.740 / 51.186 ms | 20.979 / 19.466 ms |

Registered callbacks dominate these samples: at 256 MiB, Binned3 spends 53.073/50.729 ms there and mimalloc 20.683/19.198 ms. The subsequent allocator trim is 0.671/0.461 and 0.303/0.273 ms respectively. Cleanup cost is reduced, not eliminated, and the larger stress still exceeds a 60 Hz frame budget. Reproduce with the bounded paused diagnostic in DEVELOPMENT.md; stress requests never run at normal startup.

Sequential 24-second traced walks have similar CPU median/p95/max: Binned3 16.667/17.724/32.439 ms; mimalloc 16.667/17.621/32.113 ms. They do **not** establish a general pacing speedup. Native time and allocation history differ, and tracing adds overhead. The mimalloc trace's maximum incremental-GC scope is 1.397 ms, but that one run cannot bound future cleanup.

The final **normal launch**, with heavy trace/capture/presentation diagnostics disabled, retains D3D12/SM5, the RHI thread, VSync, the 60 FPS cap, original rendering and the preceding lighting/material features. Actual fitted viewport is **1024x768**. A 60-second walking collection reports:

| CPU/GPU scope | Median | p95 | Maximum |
|---|---:|---:|---:|
| UE game-thread frame interval | 16.667 ms | 19.388 ms | 47.883 ms |
| Live-scene actor tick | 7.998 ms | 15.161 ms | 33.394 ms |
| GPU timestamps | 1.785 ms | 2.939 ms | 4.127 ms |

Catalog staging peaks at 7.698 ms, with zero resource-rebind hides. Exact first-person checks pass 39 observations of all eighteen native-visible sections, plus four draws taking 437/579/458/464 ms including native animation and polling. The native sword fixture also contains a hidden shadow helper; the diagnostic now checks that helper stays hidden instead of incorrectly requiring all nineteen native shapes visible. Production pose/visibility checks are unchanged. All **411 source tests, 37 packaged renderer tests and eight GPU runs** pass with the selected allocator, including both lighting backends, mutable attributes, skin, rigid transforms, terrain, reflections and alpha boundaries.

No 96 ms interval appears in the final minute, but **47.883 ms remains a hitch**. Cold tracing also records an 81.194 ms engine tick with 34.075 ms in distant scenery, including 15.765 ms resource preparation; this precedes the measured warm walk and is a separate unresolved cost. Other material/resource work, longer sessions, other scenes and actual display pacing remain open. These CPU intervals/GPU scopes are not displayed FPS or proof of locked 60. Final process working set is about 1.54 GiB and private bytes 2.45 GiB; there is no matched memory-reduction or long-session stability claim.

Evidence is retained under ignored `logs/hitch05-*`: baseline and allocator traces/exports, pool comparisons, normal walk/weapon results, tests, build identity and final audit. The first baseline weapon-readiness attempt was rejected because of the native-hidden helper. A mistakenly requested 75-second collection was rejected by the benchmark's 60-second limit and contributes no timing evidence; the accepted collection was rerun for 60 seconds. Saves/executable integrity and current source/archive hashes are verified separately in `hitch05-results.json`. No video or saves were written. Earlier sections below describe their own historical builds and defaults.

## Original shadow footprint and material response (light08)

The previous native-diffuse adapter calculated source light energy, then multiplied both ambient and direct terms by texture-derived cavity. Inferred normals also changed the original diffuse calculation, and inferred metallic/specular finishes changed the UE response used to reproduce it. These additions could darken or brighten surfaces independently of the original light state. The matching path now uses source normals for native irradiance, omits the extra cavity multiplier and inferred metallic/specular BRDF for that path, and retains authored glow/gloss/environment stages. Inferred normal relief remains in the UE receiver/compensation path; the older non-native material paths remain available.

The original real-time shadow setting controls actor shadows. The private game's read-only shadow level was 6. Our previous policy also let lit scenery cast: 447 world caster components competed with 182 actor components in the interior fixture, and 1,702 with 282 outdoors. The new optional catalog Boolean `shading.native_actor` comes from captured reference-owned ancestry, covering rigid heads/equipment and skinned bodies. Known scenery is a receiver; known actors retain caster eligibility. Older definitions without that metadata keep their previous behavior. Shadow maps remain enabled, with the existing four interior/two exterior local-light budget and sun cascades. Native hiding/removal still disables casters immediately; tests cover recovery and policy changes without stale eligibility returning.

These two corrections must be assessed together. Material matching alone made some patches darker under the extra scenery shadows. No blanket shadow disable or warm-tint workaround was adopted. The original fixed-function shadow stencil, filter, exact actor/light selection and shadow slider/count behavior are not emulated by this UE policy.

The comparisons use independent original-window captures, original albedo (`upgraded_textures == 0`), identical actual 1024x768 viewports, and console-paused camera/light values. HUD, console and tooltip regions were excluded. The prior policy is reproduced with diagnostic switches on the same final renderer binary; it agrees with the preserved previous build's first-room measurements within rounding. Mean absolute RGB errors use 0..255 byte values; smaller is closer to the same original frame.

| Measured patch | Previous response and scenery shadows | Matching response and actor shadows |
|---|---:|---:|
| First room, left plaster | 2.857 | 1.112 |
| First room, right plaster | 6.680 | 1.023 |
| First room, lower door | 2.645 | 0.924 |
| First room, floor | 5.278 | 4.298 |
| Merchant, left plaster | 2.863 | 2.307 |
| Merchant, right plaster | 4.899 | 3.255 |
| Merchant, counter | 4.473 | 2.608 |
| Merchant, robe | 4.577 | 3.720 |
| Daylight, stone | 14.530 | 13.007 |
| Daylight, door | 11.147 | 6.361 |
| Daylight, ground | 15.425 | 2.171 |

This is a visible, measured improvement across these patches, not whole-game pixel parity. Residual errors also appear in the unshadowed original-vertex reference: first-room floor 4.289, merchant robe 3.602, daylight stone/door 12.791/6.069. Their causes remain unresolved. The remaining work includes original diffuse/texture filtering, actor shadow projection/filtering, bounded/shared UE light compensation and enhanced foliage/effect response. Two interior cameras and one exterior camera do not cover arbitrary weather, materials or locations.

The owned GPU test now compares **actual deferred direct lighting** against independently CPU-prelit native colours, with deliberate cavity/metal data. Previous mean linear RGB error was 0.012917; matching response reaches 0.000245 on both D3D11 and threaded D3D12. Existing static upload, Gouraud clamp and base-texture colour calculations still pass. All **411 source tests, 37 packaged renderer tests and eight GPU runs** pass, including actual moving point-light shadow pixels, native skin palettes, terrain, reflection membership and alpha boundaries.

The live checks exposed an integration regression: adding actor ownership to the full-catalog shading dictionary changed the independent foreground reuse key. The raw converter lacked that irrelevant shadow annotation, so reuse failed; after equipping the sword an independent native graph had 18 sections while the near layout still had 12. The owned cache-rebinding test fails before correcting the key. It now canonicalizes that foreground-irrelevant metadata while still rejecting changed geometry or lighting. Source freshness, native transforms and hide checks were not relaxed. The final normal-launch test matched all 18 sections across 40 exact observations and two draws (485.6/443.1 ms including native animation and polling).

The final **12-second normal-launch** exterior walk restored normal optional texture enhancement and disabled screenshot/trace/presentation-stat flags. CPU interval median/p95/max was **16.667/20.071/96.389 ms**, GPU time **2.172/3.381/8.595 ms**, with zero compatible-resource rebind hides. There is no measured overall pacing improvement or locked-60 claim. The 96.39 ms interval remains an open hitch. The prior unarmed-fixture walk reached 85.773 ms and is preserved; another pre-correction walk reached 39.817 ms. These are sequential, different allocation/streaming histories, not isolated performance comparisons. DXGI statistics were disabled.

Excluded observations remain available: one source-frame copy was busy during the initial comparison, and the first cold normal-launch witness timed out before settling. Initial weapon checks also encountered an unarmed checkpoint and then the reproduced metadata regression. The completed test uses the existing native iron longsword, equipped through the original console; no item was added and no save was written. Misplaced provisional second-camera views outside the room were not used in metrics. The accepted merchant view was inside beside verified actor positions.

The final package refresh includes the foreground Python fix; renderer executable/material inputs are unchanged from the accepted lighting captures, and the refreshed package has its own tests and manifest. The private game is paused with normal unified presentation. All 32 protected saves and original/private executables remain unchanged, with pinned graphics DLLs intact. No video recording or Steam-installation change was made. Source-only packaging and publication audit are refreshed separately from local game-derived evidence.

Local evidence: `light08-results.json`, `light08-before-cases.json`, `light08-material-cases.json`, `light08-actor-cases.json`, `light08-{merchant,daylight}-cases.json` and their metrics/captures, `light08-native-shadow-config.json`, `light08-native-sword-topology.json`, `light08-near-metadata-rejected.log`, `light08-source-tests.log`, `light08-headless.log`, `light08-*-d3d*.log`, `light08-final-live.json`, `light08-final-walk-benchmark.json` and retained rejected observation logs. Captures, native data, logs and binaries remain local and excluded from source publication.

## Native lighting and neutral SDR output (light07)

The build fixes four confirmed differences while retaining original light authority:

- Static upload preserves native display-RGB bytes. UE's runtime `BuildFromMeshDescriptions` encodes linear input with `ToFColor(true)`; passing already encoded values encoded them again. The mutable path already preserved the bytes.
- MODULATE saturates combined vertex colour/light. The optional Gouraud reference combines them before interpolation; production retains pixel lighting. REPLACE/DECAL retain their prior path.
- Base-only texture/vertex multiplication uses display RGB in the native-lighting path, matching the secondary-stage path. Absence of a secondary stage previously selected linear-space multiplication.
- The camera disables UE's default vignette, which darkened identical source colours as they moved toward screen edges despite neutral exposure/tone-curve settings.

An owned eight-colour strip in the **actual scene/backbuffer** isolated the last issue. Before the vignette fix, grey 128 became 124, warm (32,16,8) became (29,14,6), and (64,32,16) became (55,27,13) near the right edge, while central greys were correct. Afterward all eight RGB samples match exactly. The strip binds the real native environment texture and expires after five seconds. Earlier white-strip captures used an invalid placeholder environment and are excluded.

A read-only original Direct3D draw-state probe matched source positions/counts/transforms for 149 world draws. All 2,001 sampled vertex colours and all 149 enabled-light lists matched. Replaying captured material/light/transform states through Direct3D's software vertex pipeline agreed with the supported normalized-direction calculation within half an RGB byte on all samples. An owned depth-varying triangle confirmed perspective-correct colour interpolation. Affine interpolation and raw sun-direction hypotheses were rejected. These are sampled input/calculation checks, not verification of every original effect.

Console pause held camera and native lights fixed for the image comparison. The independent original window used the restored normal pinned graphics wrapper, cropped to its 1024x768 client. UE matched that viewport/camera. `UEMW_TEXTURE_UPGRADES=0` and a zero-upgrade witness excluded enhanced albedo. Console, HUD and tooltip regions were excluded. Mean absolute RGB errors use byte values; lower is closer to this one original frame.

| Fixed patch | Default enhanced, before vignette fix | Default enhanced, after | Unshadowed native vertex reference, after |
|---|---:|---:|---:|
| Left plaster | 8.160 | 4.221 | 1.138 |
| Right plaster | 12.793 | 8.065 | 0.622 |
| Lower door | 2.230 | 2.430 | 0.821 |
| Floor | 7.673 | 5.390 | 4.249 |

Most measured default patches improve, but this is **not full lighting parity**. The native reference disables UE direct lighting/material enhancement while preserving tone curve and native membership. The remaining floor difference includes unresolved texture/filtering/material effects. Default UE PBR and shadows remain separate approximations. No global warm tint, disabled production shadows or gamma-only output workaround was adopted.

All **409 source tests, 37 packaged renderer tests and eight GPU runs** pass on this package. The cooked Gouraud path matches independent CPU-prelit owned colours over 4,096 pixels on D3D11/threaded D3D12 (maximum linear-channel error 0.000122). Before static-upload correction, all 4,096 mismatched, maximum error 0.534668. The dark base-only texture test failed before its colour-space fix (0.002598) and passes afterward (0.000198, within a 0.0005 quantization allowance). Mutable attributes, skin poses, rigid placement, terrain blending, reflection membership and alpha GPU regressions also pass.

A **12-second normal-launch** warm exterior walk at actual 1024x768, with default optional texture enhancement restored and screenshot/trace/presentation-stat flags disabled, measured CPU interval median/p95/max **16.667/17.334/56.810 ms**. GPU time was 3.225/4.866/5.371 ms; resource-rebind hides were zero. Forty-one exact weapon pose/placement witnesses and two draws (520.4/439.6 ms, including native animation and observer polling) passed after disposable checkpoint restoration. DXGI statistics were disabled. These CPU/GPU observations are not displayed FPS or an isolated speedup; the 56.81 ms spike remains open.

All 32 protected saves and original/private executable hashes are unchanged. The temporary private draw-probe DLL was removed and exact pinned graphics DLLs restored; probe runs are excluded from performance. No save writes, executable patches or video recording occurred. The final normal unified renderer is paused in original Options with diagnostics off.

Retained exclusions/failures: the initial enhanced-albedo comparison could not isolate original lighting; repeating with original albedo did not eliminate the discrepancy. A paused candle toggle changed no measured pixels and proves no isolated contribution. Gamma-only output was too bright and rejected. An off-view stale light-cache record and authored mip averages did not explain the broad output mismatch; no runtime heap scan or new mip infrastructure was integrated.

Remaining approximations include enhanced specular/roughness/cavity/normals, shared UE shadow compensation/filtering/softness, 32-light/four-interior/two-exterior local-shadow budgets, effects/transparency and broader interior/exterior parity. Full fixed-function/material-combination coverage and sustained frame pacing are unproven.

Local evidence: `light07-results.json`, `light07-ramp-valid.json`, `light07-ramp-neutral.json`, `light07-original-draw-state.jsonl`, `light07-original-colour-bytes.json`, `light07-original-light-membership.json`, `light07-d3d-math-comparison.json`, `light07-neutral-sdr-cases.json` and metrics, `light07-native-albedo-compare.stdout.log` (pre-vignette baseline), `light07-release-*.log`, `light07-release-live.json` and `light07-release-walk-benchmark.json`. Earlier candidate images/results remain investigation evidence, not final acceptance.

Previous update: allocator trims and first-person resource ownership (2026-11-04), below. Older sections retain their original measurements and failures; they are not current scanout guarantees.

## Allocator trims and first-person resource ownership

The hitch04 baseline captured a 101.233 ms CPU frame interval during settled walking. In its engine trace, one game-thread frame took 109.833 ms, including 91.142 ms inside `FMemory::Trim` called by incremental garbage purging; the actor's work in that frame was 7.941 ms. The scoped geometry timings alone had missed this engine-level stall. Startup and cold distant-resource preparation are separate costs.

The Development client launcher now selects the installed engine's built-in **Binned3** allocator with `-binnedmalloc3`. Garbage collection, visual settings, native capture rates and freshness limits are unchanged. This is a per-process launch argument, not an engine patch or installation change. `UEMW_ALLOCATOR=binned2` selects the retained `-binnedmalloc2` reference. A healthy renderer is restarted when its allocator argument differs. Invalid values fail before launch. The witness reports the actual allocator, and headless/GPU tools select and verify that same allocator. Directly launching the executable without the supplied launcher does not select this default; other engine versions and Shipping configurations are unverified.

The Binned2 baseline trace's four trims peaked at 91.142 ms. A Binned3 trace had three trims peaking at 3.230 ms; its 12-second walk measured CPU median/p95/max 16.667/16.746/29.853 ms. These runs retained the same native session/epoch, rendering backend and settings but occurred in sequence, with different allocation histories and tracing enabled. They identify a concrete costly path and a useful allocator alternative, not a controlled guarantee that every trim improves by 88 ms. On the final package, a separate matched paused-scene diagnostic explicitly trimmed memory three times: Binned2 took 3.380/1.840/1.387 ms and Binned3 took 2.746/1.269/1.186 ms. That smaller result makes the history dependence explicit. `witness(..., memory_trim=True)` requires `-UEMWDiagnosticScreenshots`; it deliberately calls `FMemory::Trim`, reports that CPU scope and is excluded from ordinary-play timing.

Weapon investigation also exposed a deterministic resource-ownership error. With a fresh native near pose, an older world catalog could contain the same object id with a different asset binding. World pose application respected the near lane, but earlier resource preparation still hid the component and queued a competing allocation. A job queued before a newer near discovery could then replace its current component. An owned reproduction failed all four relevant assertions before the fix: visibility, absence of competing work, component identity and current asset identity.

Resource preparation now respects a validated fresh near binding for the same first-person id. Unready visible near resources remain counted as pending; it does not claim completeness or replay a pose. Native-hidden parts do not demand drawable capacity, and an authoritative empty near update suppresses older first-person world bindings too. Instance allocation jobs are discarded when their id/asset no longer matches current resource demand. Jobs build capacity only; the original near payload still supplies current poses and visibility. The regression now passes, including expired ownership, fresh recovery and an older world pose/resource pass following native removal. The existing 150 ms near / 500 ms world freshness limits, incompatible-asset checks and native gameplay authority remain intact. The original stream03 failed witness was not captured, so its individual cause cannot be established retrospectively; this repair closes the reproduced race rather than claiming to have recovered that missing evidence.

The final **30-second normal-launch** original walking check at **1024x768** measured CPU frame intervals median/p95/max **16.667/17.313/38.838 ms**, with zero compatible-resource rebind hides. Native geometry CPU work reached 29.222 ms and catalog staging 6.012 ms. Tracing, diagnostic screenshots and swapchain statistics were all disabled. An earlier candidate's 30-second run, before the empty-near removal extension, measured 16.667/17.331/32.199 ms; its enabled DXGI observations measured 59.51 submitted presents/sec, a 57.09/sec display-change polling lower bound and consecutive observed display intervals p95/max 16.667/33.334 ms. Those are separate CPU and DXGI observations, not photon timing or a locked-60 guarantee. The longer untraced runs are not isolated before/after comparisons against the traced 12-second baseline.

All 409 source tests and 37 packaged renderer tests pass. Six actual GPU runs on Binned3 cover mutable attributes, rigid lighting/shadows, skin palettes, reflection membership and terrain on threaded D3D12 plus the D3D11 fallback. The final normal-launch live check matched 66 exact native weapon pose/placement witnesses, eight draws (368–673 ms including native animation and polling) and 106 post-draw visibility observations. A genuine checkpoint reload on that same final renderer then passed 53 more exact witnesses and two draws. Diagnostic witnesses additionally retain the expected resource and near assets. Earlier original door/load recovery checks are recorded separately with their candidate package identity in the local results ledger. Protected saves and the original executable are unchanged; no video recording was made.

Cold resource creation, distant-scene preparation, driver/GPU scheduling and other locations/weapons still require broader coverage. Earlier traces included roughly 20–34 ms distant update calls during preparation. Choosing Binned3 does not bound every allocation, collection or whole frame, and the short checks do not establish long-session memory stability. The preceding diagnostic candidate's resident/private memory was about 1,255/2,093 MiB after its walking/draw test; large reserved virtual address space is not committed physical memory. One normal-launch collection incorrectly expected a 1920x1080 viewport while the overlay controller fitted the original's actual 1024x768 client. Its context validation failed; the retained sample still contains a 42.898 ms CPU maximum. It is preserved as `hitch04-default-viewport-rejected.json`, not silently discarded or relabelled as a 1080p measurement.

Local evidence: `logs/hitch04-results.json`, `hitch04-baseline.utrace`, `hitch04-baseline-trim-events.csv`, `hitch04-{baseline,binned3}-timers.csv`, retained runtime logs, `hitch04-weapon-ordering-rejected.log`, `hitch04-fix-headless.log`, `hitch04-final-trim-binned{2,3}.json`, `hitch04-final-walk-benchmark.json`, `hitch04-final-weapon.json`, `hitch04-reload-weapon.json` and `hitch04-transition-*.json`. Traces, captures, saves and licensed derivatives remain excluded from publication.

## Terrain preparation and native affine continuity

The packaged client now prepares terrain mip allocations/copies on the catalog worker and transfers single-use platform data into ordinary UE texture arrays. Colour space, layer order, mip chain, sampler and GPU upload path are preserved. A polled render fence gates promotion. Existing terrain materials rebind in batches of at most 128 entries or a soft 2 ms CPU budget. Each material receives its matching textures/layout together; the completed signature stays invalid until all rebinding finishes, including when a newer load supersedes it. Older valid neighbour blending can remain briefly during that handoff. `UEMW_TERRAIN_PREPARED_DATA=0` before a fresh renderer retains the earlier copying path for comparison.

On the final package, a matched paused native scene used the same source session, epoch, catalog, terrain signature, 1,792 tiles, 19 layers, ten mips and 53,127,800 pool bytes. Reference colour/detail array creation took 10.707/15.027 ms; prepared creation took 0.077/0.013 ms. Peak terrain CPU setup scope fell from **17.703 to 0.096 ms**. All 1,792 terrain materials had matching active bindings. These are CPU scopes, not whole-frame, GPU-upload or scanout timings. An earlier matched candidate with 1,024 tiles measured 9.917 to 0.075 ms; do not mix its measurements with the final grid.

Actual original collision-controlled walking crossed from exterior cell [-2,-9] to [-1,-9] and returned, travelling about 208 native units outward. The same renderer and epoch survived; the changed return terrain grid reached 2.806 ms including bounded material work. An intermediate candidate had reached 14.949 ms while rebinding existing materials without batching. That observation identified another stall; it is not a controlled whole-frame before/after comparison. The budget cannot cap the duration of one individual UE operation.

A real cold NPC failure was reproduced before the fix: a 47-vertex shoe section disappeared despite unchanged native visibility, catalog and asset, with 2,005 other shapes pending. Its native affine matrix alternated between shear and an exactly decomposable rigid transform. Returning to rigid instancing queued unavailable resources and hid a section that already had a valid CPU representation. Ready CPU sections now keep that representation for the same asset. An already displayed rigid node receiving its first sheared pose allocates CPU capacity before replacing the rigid draw, then submits that current native pose. Matrix tolerance is unchanged; no old pose is replayed. This one-time allocation can still cost CPU time. A separate owned regression covers a late-ready skin component supplying its missing compatible shared-mesh alias after strict geometry/material/cell checks.

The final cold check retained 26 NPC sections across 36 exact source/UE observations, five catalogs and 23 partial-scene observations, with about five native units of NPC movement. A preceding candidate also passed while that NPC moved about 1,081 units. Transform/palette hashes match the immutable native bodies actually accepted; this is sampled submission evidence, not uninterrupted scanout proof. Native hides/removals, session/cell changes and incompatible replacements remain authoritative. Newly discovered or genuinely changed assets can still await resources.

All 409 source tests and 37 packaged renderer tests pass. Expanded owned fixtures verify every terrain mip/layer byte, cancellation and one-time adoption; paired texture/layout rebinding and supersession; exact current affine vertices, stable representation and native hiding; and the late-ready skin alias. Actual GPU terrain comparisons on D3D11 and threaded D3D12 have **zero mismatched pixels and zero RGB difference** at three scales (1,024/2,048/4,096). Threaded D3D12 mutable attributes, rigid lighting/shadows, skin palettes and reflection membership also pass. A staged original interior load, genuine native door exit and disposable checkpoint reload recovered with the same final renderer/controller. Protected saves and installed executable remain unchanged; no video was recorded.

**Remaining limits:** the final 12-second settled walking measurement still reached CPU frame intervals median/p95/max **16.924/27.877/67.154 ms**, with zero compatible-resource rebind hides. DXGI observations were 52.34 submitted presents/sec, a 39.50/sec display-change polling lower bound, and 33.334/50.001 ms p95/max consecutive observed display intervals. Native geometry work reached 46.006 ms. Other candidate walks reached 82.307 and 103.241 ms; warm/streaming workloads differ and there is no demonstrated general pacing improvement. This update removes the measured terrain allocation/rebinding problem; it does not make the renderer hitch-free.

One final-build weapon check failed during post-draw walking after 51 exact initial walking witnesses and two successful draws. The retained camera observations contain a 154 ms gap near that failure, but the failing UE witness was not captured, so its cause is **unresolved**. The diagnostic now retains that witness and current camera packet on recurrence. Four- and eight-draw repeats passed with 52/53 exact walking witnesses; they do not erase the failure or prove continuous visibility. Another candidate's weapon observer could not match a retained near payload; that is failed observation coverage, not proof of a renderer disappearance. Freshness limits were not extended to hide these issues.

Local evidence: `logs/stream03-results.json`, `stream03-final3-terrain-{reference,enabled}.json` and retained runtime logs, `stream03-final3-npc-cold.json`, `stream03-final3-boundary.json`, `stream03-final3-{interior,door-exit}.json`, `stream03-final3-walk-benchmark.json`, `stream03-final3-weapon-{rejected,diagnostic,repeat}.json`, `stream03-python-tests.log`, `stream03-final3-headless.log` and the current `client-*-gpu*.log` files. Initial compile/type failures, obsolete rigid-route test expectations, diagnostic argument/type failures, differing-grid collections and the reproduced NPC failure remain retained and excluded from acceptance. Logs, captures and licensed derivatives remain local and are excluded from the source archive.



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

## UI latency and frame pacing follow-up (active, 2026-11-03)

The current build meets the bounded checkpoint CPU/UI targets. The broader goal remains active for render-thread/GPU/display pacing in more expensive views. CPU intervals, Canvas submission, GPU timestamps and DXGI observations are separate measurements; none establishes input-to-photon latency or whole-game 60 FPS.

UI capture now uses exact compiled structural fences, fresh owned pages on every sample, mode-specific address plans, immutable projected-geometry/wire reuse and exact current-pixel conversion reuse. Exact variants of the same menu retain its baseline graph when a native tooltip appears/disappears. The structural cache stays bounded at eight entries / 16 MiB of expected bytes. All overlapping requested fields, model revisions, visibility, ownership and final camera/menu checks remain. Plans never substitute old memory values. Selective image retirement preserves still-used fonts. Menus are capped at 60 Hz and the HUD at 30 Hz; actual rates depend on workload.

UE has a dedicated latest-only UI reader and bounded image allocation. The carrier records capture/encode/publication/maintenance; Canvas records exact session/body MD5/sequence and an ordered render-thread probe. Image-resource rows measure CPU construction/copy and UpdateResource enqueue, not GPU upload completion. Original capture timestamps are never renewed; UI leases expire after 500 ms. Cold menu resources could exceed the former 750 ms transition grace, so the bounded menu-resource allowance is 1.25 seconds. Actual leases and source/renderer expiry remain 500 ms. Visible-overlay checks also caught a stale heartbeat while Canvas drew newer frames: publication now has a dedicated latest-only worker, with preceding-publication queue/I/O timings. Genuine faults still latch fallback; a hidden/latched overlay cannot pass the live latency tool.

The world path validates only required materials and limits unchanged incomplete distant-table retries to 10 Hz while preserving per-tick resource creation and immediate source pose/residency/epoch changes. Lighting-only changes preserve actor components/palettes and reuse identical GPU skin weights. Worker retirement selection reuses already-owned resource sets; plain retired CPU mesh/binding data and snapshots are released off the game thread, with UObject ownership retained on it. The new mutable-mesh proxy uploads only changed position, tangent/normal, UV or colour channels. It preserves native bounds, shadows, custom depth, sorting and hide/retirement; no gameplay/collision or animation clock was added.

### Current measurements

The controlled legacy/optimized diagnostic pair used the same executable, settings, 1024x768 unified viewport and disposable checkpoint, reloading between runs and waiting for both owners. Legacy traversal/game-thread-paced UI adoption were enabled only in the first run; other new safeguards/caches stayed enabled. This isolates those paths, not an exact UI09 release replay.

| Input dispatch to matching Canvas submission, p95 | Legacy diagnostic | Current checkpoint |
| --- | ---: | ---: |
| Native cursor | 140.89 ms | 95.40 ms |
| Inventory open/close | 163.43 ms | 91.73 ms |

Current cursor median/max was 79.05/106.93 ms; inventory 76.79/93.13 ms. All 24 cursor events and twelve transitions matched exact drawn source bodies with zero missing observations. Sixteen genuine dialogue-topic glyph-colour changes, excluding the cursor, measured median/p95/max 57.71/71.71/80.80 ms; native-change-to-render-thread-probe p95 was 85.15 ms. These warm fixtures do not bound every surface, cold content or the hybrid portrait's OS-window-region handoff.

| Final matched checkpoint walk | CPU interval median/p95/max | GPU duration median/p95/max |
| --- | --- | --- |
| First | 16.67 / 17.25 / 22.77 ms | 16.80 / 22.67 / 25.74 ms |
| Repeat 1 | 16.67 / 19.31 / 28.48 ms | 17.16 / 23.43 / 39.72 ms |
| Repeat 2 | 16.67 / 16.67 / 27.93 ms | 17.07 / 22.67 / 29.72 ms |

Repeat 1 included 74 compatible retargets, zero rebind hides and a 12.28 ms maximum catalog stage. These three short untraced runs meet the checkpoint CPU target. Own DXGI observations still show p95 33.33 ms consecutive-observation intervals, one 66.67 ms maximum, display-change lower bounds 53.3–54.7/sec and ambiguous skipped present IDs. These are scheduler/polling observations, not exact scanout/photon timestamps. A renderer-only VSync check also retained 33.33 ms p95 observations and did not establish the display target; the VSync-off default was restored.

The post-NPC view had a different camera/location, not a matched checkpoint: CPU median 20.14–24.29 ms, p95 30.30–31.66 ms, maximum 48.17 ms. That view still misses the target. Cold shaders/resources/UI structures, other weather/populations and sustained performance remain limits. No visual quality or reflection settings were reduced to pass a gate.

### Verification and reproduction

385 Python tests, 33 packaged UE tests and current D3D11 NativeUI/NativeVertexAttributes comparisons pass. The latter compares real GPU pixels with UE's general path after position/normal, UV and colour changes, retaining the proxy and skipping identical uploads. The private game passed eight native menu phases, visually inspected full journal pages, weapon walking/two draws, ten exact NPC submissions over 148.68 original units, dialogue/topic/Goodbye, text entry/Cancel, checkpoint reload and source disconnect/new-session recovery. All 32 protected save hashes are unchanged. The original is paused at its restored disposable checkpoint. No video or save writes were made.

Reproduce with `python dev/run.py check_ui_latency --pid <private-PID> --label repeat --events 24 --transitions 12` in unified mode with PresentationStats/DiagnosticScreenshots. It verifies compiled/package hashes, waits for both owners, requires visible presentation, matches exact native cursor/menu bodies, runs a short walk and leaves gameplay paused. Restore the same checkpoint/camera for comparisons; the post-NPC view differs. `check_ui_hover --pid <private-PID> --topic Background --label repeat --events 16` requires genuine NPC dialogue and matches glyph RGBA independently of the cursor. Coverage `passed` fields do not mean all performance thresholds passed.

Failed candidates remain recorded. Early final2/final3 observers evicted source identities and cannot establish earliest response. An initial wrapper continued after a compile failure; stale-binary results were excluded and later tools/builds have exit/hash guards. Empty-versus-missing cell tests caught a retarget regression before live use. Redundant retirement key snapshots increased startup to 22–24 ms before owned sets were reused. First tooltip changes caused 138–148 ms transitions before same-menu variants were retained; unseen structures can still be cold. A reload recovery assertion was too early; the final check waits within the existing load allowance and requires current identity/visible UI. Complete log records are parsed without accepting partial EOF data or silently dropping malformed complete records. Detailed named-event tracing added overhead/large exports; acceptance has tracing off and exports restrict timer/time/thread ranges.

Local evidence includes `ui10-ab-before-ui.json`, `ui10-ab-after-ui.json`, `ui10-checkpoint-*.json`, `ui10-release-hover.json`, `ui10-final-core-weapon.stdout.log`, `ui10-final-live.stdout.log`, `ui10-core-acceptance.json`, `ui10-weapon-regression.json`, `ui10-npc-visual.json`, `ui10-disconnect.json`, `ui10-recovery.json`, `ui10-save-integrity.json`, `ui10-python-tests.log`, `client-headless-tests.log`, `client-mutable-gpu.log` and `client-ui-gpu.log`. Historical UI09 heartbeat ages are not draw latency. Generated assets/captures/logs/saves stay outside the audited source archive.

## Display pacing and UI capture update (active, 2026-11-03)

Managed unified D3D11 now uses display-paced presentation on a 59/60 Hz output when the requested client cap is 60. It retains queue depth 3 and removes the independent CPU sleep cap only while its own overlay is visibly presented over the focused original, with a fresh controller lease. Hidden/unfocused/lost-owner states retain the CPU cap. Other output rates, lower explicit caps and separate-window/other RHI modes retain the existing behavior. No driver, original-engine, display or visual-quality setting changes. `UEMW_DISPLAY_PACING=0` restores the earlier comparison path for a new renderer.

An isolated 3/1/1/3 queue-depth test with VSync off did not fix display pacing. A separate capped/display-paced/display-paced/capped comparison at fixed depth 3 changed observed display-interval p95 from 33.33 ms to 16.67 ms in both paced runs; observed display-change lower bounds rose from 52.3–53.8 to 57.3–58.9/sec. CPU p95 was worse in those initial paced runs, about 21 ms, and is reported separately. Repeating depth 3 versus 1 with display pacing held fixed favored retaining depth 3. These own-swapchain polling observations are not photon timing or a universal 60 FPS guarantee.

UI capture skips transform decoding only for an exact current-byte hit on previously validated geometry. Current transforms, vertices, colours, UVs, material fields and structural/ownership fences remain mandatory. Page addresses now index immutable owned snapshot slabs, avoiding per-page copies; failed spans still require fresh readable neighbours and reject unreadable consumed fields. Repeated texture type checks reuse only the current sample's already resolved/fenced texture entry. Resolved native clipping remains unchanged. An overdue capture yields without adding a further 2 ms sleep; publication caps stay 60 Hz menus / 30 Hz HUD, with the existing menu-mode wakeup.

The controlled 30-capture inventory profile fell from 1.050 seconds to 0.810 seconds after the transform/slab changes, at the same 639 geometry calls per capture. This includes profiler overhead. After the final source restart, actual checkpoint capture median/p95 was 16.70/19.60 ms; the preceding normal-launch build measured 22.41/26.23 ms. Cold graphs, native revisions and scheduling can still produce longer captures. No lease or fence was relaxed to reduce latency.

| Final live view | Cursor input-to-Canvas p95 | Inventory input-to-Canvas p95 | CPU interval median/p95/max | GPU timestamp median/p95/max |
| --- | --- | --- | --- | --- |
| Disposable checkpoint | 75.19 ms | 81.08 ms | 16.65 / 19.88 / 22.22 ms | 16.67 / 16.78 / 17.06 ms |
| Post-NPC crowded view | 80.40 ms | 98.12 ms | 22.96 / 31.21 / 46.91 ms | 23.48 / 32.20 / 46.90 ms |

The checkpoint walk observed 59.95 display changes/sec with zero repeated/skipped present IDs and 16.67 ms p95/maximum consecutive-observation intervals during its short sample. The crowded view observed 41.68/sec, p95 33.33 ms and maximum 50.00 ms. Both kept full visuals and original rendering. The views have different cameras/locations; this table does not isolate a view-cost improvement. Matched policy tests in the expensive view still missed the goal under either policy. **The broader frame-pacing goal remains active.** The UI checkpoint pass does not complete it.

389 Python tests, 33 packaged UE tests and actual D3D11 NativeUI/NativeVertexAttributes comparisons pass. The mutable fixture now separately changes normals under native illumination and compares real GPU pixels with UE's general mesh path. Dynamic-buffer and cached-draw candidates were rejected and removed: the former did not improve the matched walks, and the latter failed actual image comparisons. An initial default-lit normal fixture was ineffective; the final test uses the project's real native-lighting shader and owned light-table data.

The final source passed the native menu/journal cycle, weapon walking/two draws, exact moving-NPC submissions, dialogue/topic/Goodbye, hover and text-entry/Cancel. Dialogue-highlight input-to-Canvas p95 was 67.22 ms. Focus-away/refocus checks restored the cap and resumed automatic pacing. A fresh source session recovered after disconnect, the disposable checkpoint was reloaded, and all 32 protected save hashes remain unchanged. The ordinary untraced session is paused with automatic pacing enabled; the original remains running. No video was recorded. Cold-load/UI-structure delays, other refresh rates, expensive views and longer-session behavior remain limits.

A fresh bounded crowded-view trace isolates the remaining work. In a ten-second warm walking interval, native-geometry preparation averaged 6.26 ms per accepted update (about 3.90 ms excluding the other exported UEMW scopes); reflection preparation averaged 1.34 ms per tick. Nested GPU scopes recorded about 1.63 seconds of shadow depth work, 1.34 seconds of base passes and 0.78 seconds of translucency across main/reflection views. The `Unaccounted` parent encloses named passes; summing its inclusive duration again would double-count them. These traced scopes are diagnostic, include scheduling effects and are not ordinary-play acceptance. The trace and bounded exports are `ui11-crowded-render.utrace`, `ui11-crowded-gpu-summary.json` and `ui11-crowded-cpu-summary.json`. Source/renderer batching and repeated scene preparation remain investigation targets; quality reductions were not used to pass the gate.

Local evidence: `ui11-paced-queue-comparison.json`, `ui11-synced-queue-comparison.json`, `ui11-heavy-paced-queue-comparison.json`, `ui11-*-comparison.json`, `ui10-ui11-release-ui.json`, `ui10-ui11-release-walk.json`, `ui10-ui11-release-crowded-*.json`, `ui10-ui11-release-auto-hover.json`, `ui11-release-core-acceptance.json`, `ui11-release-weapon-regression.json`, `ui11-release-npc-visual.json`, `ui11-release-dialogue-acceptance.json`, `ui11-auto-unfocused.json`, `ui11-auto-refocused.json`, `ui11-release-disconnect.json`, `ui11-recovery.json`, `ui11-save-integrity.json`, `ui11-final-python-tests.log` and `ui11-auto-*-gpu.log`. The remaining crowded-view renderer work must use these limits rather than treating a static import or the checkpoint alone as completion.


## Incremental reflection membership (2026-11-03)

The renderer now retains reflection component membership and patches native visibility and resource-identity changes instead of scanning the loaded scene for every water capture. Source transforms, skin palettes, materials, camera, capture cadence/resolution, transparency and image-ownership fences remain current. Definition retirement, inclusion/blend classification changes and scene reset reconcile the complete list. The opt-out described in DEVELOPMENT.md runs the original scan without repeatedly constructing the new reverse maps, so it does not inflate the comparison baseline.

Four ten-second walking samples used the same disposable checkpoint and native heading, warmed main/distant owners, visible unified D3D11 presentation, measured 60 Hz pacing/depth 3 and unchanged full visual settings. Original AI and resource churn still run; these are short samples, not a deterministic replay or sustained-play claim.

| Order | Membership mode | List CPU total (ms) | Full scans | UE update median (ms) | Frame interval median / p95 / max (ms) |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | Original scan | 633.53 | 249 | 9.668 | 27.574 / 34.384 / 63.167 |
| 2 | Incremental | 7.68 | 2 | 8.302 | 25.350 / 34.552 / 39.371 |
| 3 | Incremental | 20.00 | 5 | 8.915 | 28.512 / 35.949 / 54.633 |
| 4 | Original scan | 593.63 | 236 | 10.176 | 28.772 / 36.953 / 58.504 |

List preparation fell by 96.6–98.8%, and median UE update work fell about 1.3 ms in both pairs. Overall frame-time tails did not reliably improve and remain above the goal. The second incremental sample still contains a 51.06 ms UE-update maximum. These CPU intervals and own-swapchain counters do not establish input-to-photon latency or universal 60 FPS. No visual quality was reduced.

The initial whole-list cache still rebuilt 179 times in its walking sample and did not improve frame pacing; it was replaced by the incremental path. An opaque rigid shadow-cache experiment was also removed after limited benefit. UE 5.2's ID-based instance updater ignored subsequent transforms on stationary batches; the ordinary reuse regression caught it before live use. A promotion fallback passed actual shadow pixels, but the matched comparison did not justify adopting that approach. Two console-fixture attempts and a hidden-overlay timing run were excluded from acceptance; final comparisons require actual visible display-paced presentation.

The new `ReflectionMembership` test checks native hide/restoration, same-count asset/component replacement, creation/removal, classification and reset cleanup. Its D3D11 run compares actual HDR pixels with a separate freshly scanned list after movement, hiding, removal and recreation. The initial fixture incorrectly counted capture-background pixels as its green object; the final criterion distinguishes the object colour and verifies actual movement/absence/reappearance. All 34 packaged tests and the final real-GPU comparison pass.

The existing crowded trace also records 40,629 `FStaticMeshInstanceBuffer::InitRHI` calls in its ten-second warm interval (0.804 seconds aggregate scoped CPU time). This is a next investigation target, not a demonstrated fix or pure GPU-cost estimate. Renderer stalls and crowded-view pacing remain active work.

Local evidence: `ui12-incremental-comparison-summary.json`, `ui12-incremental-*-comparison.json`, `ui12-incremental-headless.log`, `ui12-incremental-gpu.log`, `ui12-shadow-comparison-summary.json`, `ui12-warm-timers.csv` and `ui12-final-python-tests.log`. Tracing was off for all four acceptance timing samples; the aggregate timer export uses the previous bounded crowded trace. No video or save writes were used.


The final live check exposed a separate menu-read race: closing native text entry changed the loading-menu vector during inspection. It was published as an unavailable scene and permanently latched the overlay, despite the next sample recovering 17 ms later. That incoherent read now raises the existing `SceneReadChanged` retry classification. No partial pose or fresh timestamp is published; the last committed frame retains its original 500 ms expiry. Malformed visibility/read failures still fault normally. Two regression tests cover rejection/recovery without advancing a torn loading generation and rejection of malformed flags. All 391 source tests pass. Six actual text-entry/cancel cycles then retained visible mirrored presentation with no save writes. Fresh-source cursor/inventory input-to-Canvas p95 is 80.44/84.94 ms; dialogue highlight p95 on the corrected source was 73.44 ms. These are separate UI/CPU observations, not photons. The crowded-view frame-pacing target remains unresolved.


The corrected source also passed native menus/journal, weapon walking/two draws, exact moving-NPC submissions, genuine dialogue/hover/topic/Goodbye and native text-entry cancellation after a checkpoint reload. Local current-source evidence includes `ui10-ui12-fixed-ui.json`, `ui10-ui12-fixed-auto-hover.json`, `ui12-fixed-core-acceptance.json`, `ui12-fixed-weapon-regression.json`, `ui12-fixed-npc-visual.json`, `ui12-fixed-dialogue-acceptance.json` and `ui12-fixed-text-cancel-regression.json`. The earlier failed text-cancel run is retained in `ui12-text-cancel-latch-failure.json` and is not counted as a pass.


Final native reload, fail-closed source disconnect and visible new-session recovery passed. All 32 protected private-save hashes and the file set remain unchanged. The first disconnect observer used an ordinary file read that collided with atomic heartbeat replacement; its failure was retained, and the final check uses the existing shared-delete reader. This was a diagnostic-harness sharing error, not evidence of a game crash. Logs: `ui12-final-reload.json`, `ui12-final-disconnect.json`, `ui12-final-recovery.json`, `ui12-save-integrity.json`.


## Native single-instance component placement (2026-11-03)

UE 5.2's ID-based instance update rebuilds render-side instance buffers when instance matrices change. For an ordinary world batch with one nonzero-scale object, the renderer now retains an identity instance and applies that same native world matrix to the component. Native IDs, visibility, transforms and animation timing remain authoritative. Shared batches, zero scale and camera-relative/foreground/water/rain geometry retain the original representation. Membership/representation changes submit fresh data, and reset/retirement release the placement identities. UE collision and simulation remain disabled.

Four short matched walks restored the same disposable checkpoint, native heading and full visual settings with visible display-paced unified D3D11 at measured 60 Hz/depth 3. Tracing was off. Original AI/resource churn still runs, so these are not deterministic replays or sustained-play evidence.

| Case | Instance-buffer submissions | CPU frame interval median / p95 / max (ms) | Observed display changes/sec (lower bound) |
| --- | ---: | --- | ---: |
| ui13-components-off | 51,184 | 25.115 / 32.225 / 45.561 | 39.81 |
| ui13-components-on | 3,819 | 20.703 / 27.922 / 32.596 | 46.82 |
| ui13-components-on-b | 3,755 | 21.428 / 28.731 / 50.138 | 46.19 |
| ui13-components-off-b | 54,153 | 24.058 / 30.778 / 35.454 | 42.12 |

Submissions fell about 93%. Median intervals improved by 2.6–4.4 ms and p95 by 2.0–4.3 ms in the two pairs. The 20 ms p95 goal remains unmet, and the second enabled sample still contains a 50.14 ms frame. Buffer-submission counters are CPU work evidence; DXGI observations are a polling lower bound, not photons. The previous reflection tests used a different source/view residency and should not be treated as directly matched with these new pairs.

The new `RigidComponentTransforms` regression checks composed native world matrices, stable IDs, no additional instance uploads for movement/rotation/scale, transitions to shared/zero-scale/empty batches, same-count replacement, recreation, multiple submissions in one frame and reset. Actual native-lit GPU pixels match the original representation through all twelve phases. A separate point-light pass replays the representations independently so a reference caster cannot conceal a stale shadow, and leaves the active caster intact between moves. Its baseline detects 576 real shadow pixels; the native and original paths match the shadow images across motion, scale and membership changes.

The shadow fixture initially failed its presence assertion: its native visibility submission re-enabled casting before the intended no-shadow image. The corrected baseline submits the pose first, then disables casting for that control image. Closed owned geometry, persistent capture state and fixed exposure make the check measurable. Failed fixture runs remain archived and are not accepted as passes. This test uses owned geometry and generated material data, not installed-game assets.

Local evidence: `ui13-comparison-summary.json`, `ui13-components-*-comparison.json`, `ui13-final-headless.log`, `ui13-rigid-gpu.log`, `ui13-shadow-gpu.log`. `UEMW_RIGID_COMPONENT_TRANSFORMS=0` before a new renderer launch selects the prior path for comparison. No visual quality reduction, game memory write, save write or video recording was used.


A fresh bounded trace of the enabled path records 2,073 `FStaticMeshInstanceBuffer::InitRHI` calls and 56.62 ms aggregate CPU scope time in a seven-second warm walking section. The older trace used a different residency/view, so this is confirmation of the remaining profile rather than a matched speedup claim. Largest scopes still include render-thread RDG execution, shadow depth work, native scene preparation and the game-thread wait for render work. Background tasks include a 417.75 ms maximum; their aggregate duration is not a demonstrated game-thread stall. Tracing is diagnostic and excluded from the four acceptance timing samples. Evidence: `ui13-render.utrace`, `ui13-profile-window.json`, `ui13-profile-summary.json` and `ui13-warm-timers.csv`.


The default-on build passes 391 source tests, 35 packaged UE tests and actual GPU UI, native-attribute, water-image, reflection-membership and rigid-placement/shadow comparisons. Live native menus/journal, drawn-weapon walking/two draws, ten exact moving-NPC submissions, genuine dialogue/topic/Goodbye, native text entry/cancel and hover pass. Current input-to-Canvas cursor/inventory/dialogue-hover p95 is 80.78/89.98/67.29 ms; these are not photon measurements. Evidence: `ui10-ui13-release-ui.json`, `ui10-ui13-release-auto-hover.json`, `ui13-release-core-acceptance.json`, `ui13-release-weapon-regression.json`, `ui13-release-npc-visual.json`, `ui13-release-dialogue-acceptance.json`, `ui13-release-text-entry-acceptance.json`, `ui13-python-tests.log` and `ui13-*-gpu.stdout.log`.


Native checkpoint reload, fail-closed source disconnect and visible new-session recovery also pass with the component path enabled. All 32 protected private-save hashes and the file set are unchanged. The final session is paused at the restored disposable checkpoint. Evidence: `ui13-reload.json`, `ui13-final-disconnect.json`, `ui13-recovery.json`, `ui13-save-integrity.json`. Remaining frame-time work is active; these checks do not establish the 20 ms p95 target.


## Stall diagnostics and command-submission comparison (2026-11-03)

The client now publishes UE's actual opened log path in its heartbeat and diagnostic witness. Unreal can select a suffixed filename when the requested file is locked. Benchmark and UI observers require the exact fresh renderer PID/heartbeat and an existing log inside this checkout; they reject missing, stale, future, unrelated or escaping paths instead of guessing the newest log. Three regression tests cover this selection. Native scene preparation also exports bounded per-update CPU phase samples within the existing performance windows. These describe main-owner apply attempts, including rejected attempts; phases are nested within total and are not frame-aligned GPU or display timestamps.

A diagnostic `r.RHICmdBypass=1` trial passed actual owned NativeVertexAttributes GPU comparisons but did not improve the crowded checkpoint. With unchanged visuals, the initial default walk recorded CPU median/p95/max 24.485/33.847/53.472 ms; the valid direct-submission trial recorded 27.336/34.479/44.887 ms. The earlier trial observer read the previous process's requested log rather than UE's actual suffixed file and obtained no renderer samples. That rejected run is retained in `ui14-bypass-on-benchmark.json`; only `ui14-bypass-on-valid-benchmark.json` has timing evidence. The direct-submission setting is rejected and absent from the normal launcher and final process. These short native-AI runs are not deterministic replays.

The final default diagnostic build recorded CPU median/p95/max 22.206/29.324/47.638 ms. Main scene preparation total was 6.125/8.308/21.814 ms, including catalog/material 0.663/2.267/16.386, compare/resources 1.831/2.293/6.032, changed submissions 3.126/4.201/6.244, reconciliation 0.106/0.151/1.820 and rigid flush 0.299/0.402/0.788 ms. These are independently summarized distributions, so their maxima must not be summed into a synthetic stall. Existing catalog-stage samples reached 10.507 ms. The earlier bounded trace separately shows catalog binding and resource retarget work. Catalog handoff and repeated changed-geometry work remain investigation targets; this update does not claim a frame-time fix or achievement of the 20 ms p95 goal.

All 394 source tests and 35 packaged UE tests pass. The fresh default client passed 24 actual cursor events and twelve inventory transitions with input-to-Canvas p95 84.78/101.56 ms; the cursor maximum was 121.89 ms. These are CPU submission timings, not photons. The disposable checkpoint was reloaded without saving. Local evidence includes `ui14-python-tests.log`, `ui14-headless.log`, `ui14-bypass-mutable-gpu.log`, `ui14-default-phases-benchmark.json`, `ui10-ui14-default-ui.json` and `ui14-final-reload.stdout.log`. The previous UI13 weapon/NPC/dialogue/shadow/disconnect acceptance remains separate evidence; those whole suites were not repeated for these diagnostic-only C++ changes.


The twelve-transition inventory p95 of 101.56 ms misses the 100 ms target in this repeat; coverage passing does not imply latency acceptance. The final private game is paused at its reloaded disposable checkpoint with live visible mirrored presentation. All 32 protected save hashes and the exact save-file set remain unchanged (`ui14-save-integrity.json`). The performance goal remains active. `ui14-results.json` records the final build, process/session identities and unresolved thresholds.


## Catalog handoff work (2026-11-03)

The catalog worker now prepares first-person, rain and controlled-material classification in exact binding order, plus the sun membership list, including resident mesh definitions. The game thread moves these arrays at the existing atomic catalog commit. An owned classification snapshot fences resident identities: a changed classification under an existing resident asset name is rejected. No UObject or reusable source pose crosses into this worker plan. Empty newly prepared rigid batches also skip scanning unrelated native slots. Populated reconstruction still invalidates its native slots and keeps placeholders hidden until a fresh source pose arrives.

`UEMW_CATALOG_HANDOFF_PLANS=0` before a new renderer selects the old binding loop and full membership scan for comparison. Both paths in the comparison binary still prepare worker metadata and apply its safety fence; this isolates commit and scan work rather than exactly replaying the previous release. The normal default enables the optimization.

Four short untraced walks reloaded the same disposable checkpoint and native heading, with full visual settings, actual visible unified D3D11, 60 Hz pacing and queue depth 3:

| Case | CPU interval median / p95 / max (ms) | UE update median / p95 / max (ms) |
| --- | --- | --- |
| ui15-plans-off | 22.468 / 28.217 / 36.401 | 7.513 / 9.538 / 34.805 |
| ui15-plans-on | 21.023 / 27.789 / 31.096 | 7.032 / 9.052 / 11.986 |
| ui15-plans-on-b | 21.060 / 28.799 / 34.800 | 6.938 / 9.025 / 10.931 |
| ui15-plans-off-b | 22.503 / 28.186 / 41.295 | 7.346 / 9.823 / 39.112 |

The observed all-run catalog binding scopes fell from median 3.582/3.855 ms in the reference runs to 0.002/0.021 ms in the prepared runs (3/6 versus 1/4 commits). These samples include startup and reload outside the timed walk. Neither prepared walk happened to commit a catalog inside its ten-second timed interval, so its empty timed-bind array is unknown, not a zero-cost event. Timed membership scans fell from median 0.107–0.124 ms to 0.001 ms. The enabled walks skipped 37/38 such scans during their before/after witness interval, in addition to cold-start work.

Median frame intervals were about 1.4 ms lower in both enabled samples. Frame p95 did not consistently improve: original AI, resource churn and handoff events differ between short runs. This is a measured removal of handoff work, not proof that it explains the whole frame-time change. Current reflection membership is about 2,690–2,730, versus about 2,090–2,130 in the preceding diagnostic release; do not compare those views as a matched speedup. Runtime logs were retained per case and matched by their final health epoch; a fresh client can initially observe the preceding epoch. Evidence: `ui15-comparison-summary.json`, `ui15-plans-*-comparison.json`, `ui15-plans-*-benchmark.json` and corresponding retained runtime logs.

The final build adds an independent diagnostic witness that compares committed classification and sun membership against the loaded mesh definitions. Its own corruption regressions detect wrong flags and missing suns. The final default walk confirms that parity before and after walking, with CPU median/p95/max 19.879/26.595/31.837 ms. The 20 ms p95 goal remains unmet. The four comparison runs used the earlier binary without this additional diagnostic probe; the production handoff paths are unchanged. No shader, resolution, geometry, shadow or reflection-quality settings were reduced.

394 source and 36 packaged UE tests pass. The new `CatalogHandoffPlans` test covers cached/cold classification, repeated/reordered bindings, native near-camera/rain/material/stage flags, sun membership, resident identity mutation, runtime reference/prepared parity and populated batch reconstruction. Its initial run caught Unreal's permissive string-to-boolean conversion; classification now requires actual JSON booleans. That rejected run is retained in `ui15-classification-type-rejected.log`. Actual D3D11 rigid surface/shadow, reflection membership, native UI and mutable-vertex comparisons all pass on the final package.

The final live build passed native menus, a visually inspected full journal, drawn-weapon walking/two draws, four original first/third-person changes, ten exact native NPC submissions, genuine dialogue/topic/Goodbye, sixteen hover changes and cancelled text entry. Cursor/inventory/dialogue-hover input-to-Canvas p95 was 88.43/78.20/74.92 ms. These are CPU submission timings, not GPU completion or photon latency. The disposable checkpoint reload, fresh non-live heartbeat on source disconnect, new-session recovery, portability and prerequisite checks pass. All 32 protected save hashes and the exact file set remain unchanged. The original is paused at the restored private checkpoint with visible mirrored presentation. No video or save writes were made.

Local final evidence includes `ui15-final-python-tests.log`, `ui15-final-headless.log`, `ui15-*-gpu.stdout.log`, `ui15-release-default-comparison.json`, `ui10-ui15-default-ui.json`, `ui10-ui15-release-auto-hover.json`, `ui15-view-modes.json`, `ui15-release-*-acceptance.json`, `ui15-release-npc-visual.json`, `ui15-reload.json`, `ui15-final-disconnect.json`, `ui15-recovery.json` and `ui15-save-integrity.json`. Broader frame pacing, render-thread submission cost, cold content/UI structures and sustained behavior remain open work. The overall performance goal remains active.

## D3D12 submission and catalog ownership (UI16)

The client now defaults to D3D12/SM5 with a real separate RHI submission thread. Managed unified presentation on a measured 59/60 Hz output combines VSync with the requested 60 FPS CPU cap; hidden/unfocused/stale-owner presentation falls back to VSync-off CPU pacing. D3D11 remains an explicit cooked fallback (`Start-UEMW-Unified.cmd -RHI d3d11`), with its previous no-RHI-thread policy. No visual settings, geometry, reflection resolution/cadence, shadows, original rendering or gameplay authority were reduced.

Initial short comparisons on this RTX 5080/UE 5.2.1 system restored the same private Seyda Neen checkpoint and native heading, with a drawn first-person weapon and warm main/distant resource owners. The requested 1920x1080 overlay follows the actual 1024x768 native viewport; measurements use that actual size. Original AI/resource churn continues, so these are policy-bundle comparisons, not deterministic replays or an isolated queue-depth experiment.

| Case | CPU interval median / p95 / max, ms | Submitted presents/sec | Observed consecutive display interval p95, ms |
|---|---|---|---|
| D3D11, output-only VSync, no RHI thread | 20.265 / 26.317 / 29.323 | 50.08 | 33.334 |
| D3D12, output-only VSync, RHI thread | 15.004 / 22.399 / 34.742 | 60.01 | 16.667 |
| Normal D3D12 automatic capped VSync | 16.667 / 17.206 / 27.258 | 59.82 | 16.667 |

DXGI observations come from this client's own swap chain. Display changes are a polling lower bound; repeated/skipped IDs cannot by themselves identify dropped frames. These are not photon timings. Actual queried D3D12 maximum latency is unavailable on this system, recorded as an empty value set; the existing latency cvar's value of 3 does not configure D3D12. UE 5.2's D3D11 and D3D12 GPU timestamp scopes differ, so their GPU numbers are not a matched GPU-work speedup. Read-only whole-adapter sampling during the D3D11 reference averaged 23.8% utilization; that includes desktop workloads and is not per-process shader efficiency.

The first 55-second D3D12 walk reached 17.037 ms CPU interval p95 but retained six frames above 33 ms (36.384 ms maximum). Closer catalog measurements located 18-26 ms handoff snapshots. Retaining the decoder's own immutable binding table fixed a source-overtake ownership gap but did not remove those stalls by itself. UE 5.2 `TFuture::Get()` also retains a shared result pointer. It kept supposedly retired catalogs alive until the next game-thread future assignment. Adopted futures now reset while the loader still owns the DTO; superseded DTOs and completed futures retire off-thread. Only plain data is released there. Original poses, visibility and animation clocks remain fresh and authoritative. Regression coverage includes source overtaking, immutable-table independence, reordered native pose reuse, unconsumed future results and abandoned staging.

GPU validation now runs in an isolated owned-data source root on both backends. The previous normal fixture relied on a running game's light; it failed independently on both backends. The repaired test owns separate native-light-table and UE-directional-light references. A new skin fixture compares actual native GPU poses against independently CPU-deformed static geometry through six movement/scale/hide/restore phases. Its initial procedural reference used a different vertex-colour conversion; the final static reference matches the production vertex format without relaxing pixel tolerances. Rejected logs remain local. These fixture failures are not counted as passing validation or proof of a gameplay regression.

### UI transport and final bounded acceptance

The remaining UI delay was measured before changing transport. Across 568 distinct menu captures, the manifest fetch cost 4.345/6.137 ms median/p95 and body IO/hash cost 3.246/4.586 ms. Header parsing was 0.665/1.217 ms, texture checks 0.206/0.342 ms, geometry decoding 0.249/0.387 ms and copying the known-texture lookup 0.025/0.041 ms. `ui_pipeline.read_parts_ms` reports those six phases in header-parse, textures, body, decode, manifest-fetch, lookup-copy order. The single-handle file-read candidate did not materially improve body timings and was removed. A reversible normal-priority UI-worker comparison did not improve capture cost; the original below-normal priority was restored and remains the default.

The UI lane now uses the existing eight-slot shared-memory channel with typed UI/v2 metadata and unchanged UUI1 geometry. Both file UI/v1 and shared UI/v2 are decoded and compared in the owned tests; the actual GPU Canvas check draws from the shared carrier. Shared acknowledgments retain the exact original stamp, and nonce/body-identity/file-only downgrade cases fail closed. UI image files and independent diagnostic body files remain local. An initial live correlation failed because a busy publication reused an already-written immutable filename. Reserving one sequence per attempt fixes that identity bug; a real-IPC owned regression forces the busy case and compares the exact advertised body against its file. The failed six-of-24 timing result is retained and excluded from acceptance.

The corrected UI channel reduced actual UE worker read time from roughly 8 ms to 1 ms median (2 ms p95). Two complete runs each matched all 24 native cursor events and all 24 inventory transitions to verified source bodies actually submitted through Canvas, with zero unarchived draw sequences:

| Run | Cursor input-to-Canvas p95 / max, ms | Inventory input-to-Canvas p95 / max, ms |
|---|---|---|
| Shared UI, corrected identities | 80.039 / 82.662 | 91.705 / 99.830 |
| Shared UI repeat | 79.052 / 79.917 | 84.021 / 85.716 |

Sixteen genuine dialogue glyph-colour hover changes matched independently retained original RGBA with 56.938 ms input-to-Canvas p95 (64.341 ms max). These measure CPU submission, not GPU completion, scanout or photons; an ordered render-thread probe and separate own-swap-chain observations remain available.

The final 55-second warm walk observed 3,294 CPU frame intervals: median 16.667 ms, p95 16.954 ms, max 33.028 ms. One isolated frame exceeded 33 ms by 0.028 ms; none reached 50 ms. There were 13 catalog commits during the case, and no recurring 50-80 ms stalls in this bounded run. Actual DXGI submitted presents were 59.68/sec; observed display changes were a 57.62/sec polling lower bound, with 16.667 ms consecutive-interval p95 and 33.334 ms maximum. Repeated/skipped IDs were 114/113, with no counter resets. These cannot establish exact dropped-frame counts or a universal locked-60 guarantee. Resource residency and reflection-member counts changed after a source restart; the final sustained case is not a same-membership attribution test against earlier 2,700-member views.

Current acceptance includes 398 source tests, 37 packaged UE tests, shared UI GPU pixels on D3D11 and threaded D3D12, and current D3D12 mutable attributes, rigid lighting/shadows, reflection membership, skin poses, water-image ownership and alpha comparisons. The live package passed eight native menu phases, visually inspected journal pages, 54 exact weapon-walk samples/two draws, four first/third-person transitions, ten exact moving-NPC submissions over 490.43 original units, dialogue/topic/Goodbye and native text-entry/Cancel. Source disconnect exposed the original safely with a fresh nonlive renderer heartbeat, and a new source session recovered with the same native game. Presentation-owner loss switched to VSync-off cap 60; rearming restored visible capped VSync without diagnostic overrides. No video or save writes were made.

Cold catalog definition adoption still reached about 58 ms, and terrain-array startup about 10-11 ms. Cold assets, first-use structures, other cells, longer sessions, other GPUs/drivers and input-to-photon latency remain outside this bounded warm acceptance. Original rendering, all visual settings, native authority and source/epoch/visibility/expiry rules are retained. Local evidence includes `ui16-final-*-gpu.stdout.log`, `ui16-final-python-tests.log`, `ui16-ui-shared-headless.log`, `ui16-ui-shared-*-gpu.stdout.log`, `ui10-ui16-ui-shared-fixed-ui.json`, `ui10-ui16-shared-repeat-ui.json`, `ui10-ui16-release-auto-hover.json`, `ui16-shared-release-sustained-benchmark.json`, `ui16-release-*-acceptance.json`, `ui16-release-npc-visual.json` and `ui16-pacing-owner-expiry.json`. Python was restarted after the compile; its actual current source hashes/session are recorded separately in the results ledger, rather than rewriting the compile-time manifest.

## Automatic recovery after native transitions (transition01)

The reported permanent loss after travel/doors/rest had a presentation cause in the available user-session logs: UE kept publishing live frames, but `fallback_latched_restart_overlay` left the overlay hidden until a launcher rearm. The corresponding sessions ended with normal native-process exits, rather than recorded watchdog hangs. A transient source/render/UI fault after the first visible frame could enter that permanent state even after the new scene was ready.

The presentation controller now uncovers faults immediately and automatically returns after 500 ms of verified stable readiness for the same ownership/session/epoch/native-menu identity. Recovery requires complete current geometry, no pending native instances and matching fresh original UI. Bad observations, unknown menus, exceptions, identity changes and polling gaps over 250 ms restart qualification. Existing 500 ms freshness leases, loading allowances, native rendering/input, and independent cutoff deadlines are unchanged. This is a Python presentation repair; the UI16 packaged UE executable and its compile-time manifest were not rebuilt or rewritten.

All 402 source tests pass. Added cases cover travel, interior and same-epoch rest recovery; wrong PID/session/epoch, stale scene/UI, partial/pending geometry; repeated faults, polling gaps, unknown menus and UI-resource grace. Live acceptance activated the original tradehouse exterior and interior doors, bought an actual 15-gold silt-strider trip from Seyda Neen to Balmora, waited one native hour, and activated the installed bed in Caius Cosades' house for one native hour of rest. UE returned with the same renderer and controller in all cases, without a generation change or manual rearm. Eight automatic recoveries were observed across the session. Console positioning was used only to stage access to the original doors/NPC/bed; native activation, travel and rest logic remained in Morrowind. Initial console timing, door selection and an observer that did not retry a busy shared-memory copy caused test-setup failures; those attempts are not passing acceptance evidence.

The disposable checkpoint was reloaded through the original menu and left paused with UE visible. Native waiting/resting wrote the private automatic-save file; its prior bytes were restored from a hash-verified existing backup after the tests. All 32 protected save hashes and the file set match the baseline afterward. No explicit save commands or video recording were made, and the installed game was untouched. This is bounded transition verification, not proof of every destination, long-loading scene or renderer-crash recovery, and no new frame-time speedup is claimed. Local evidence is `transition01-*-hour.json`, `transition01-door-*.json`, `transition01-travel-balmora.json`, `transition01-final-view.json`, `transition01-python-tests.log`, `transition01-save-integrity.json` and `transition01-results.json`.

## Sun billboard and native glare repair (sun01)

The live installed sun uses rigid-camera `NiBillboardNode` mode 2. Its geometry can be read with an identity world rotation outside the native draw; blindly deforming its XY model quad with that temporary matrix produces the wrong plane and movement-related visibility. The producer now resolves only the identified solar billboards against the captured original camera, keeping native placement, scale, model vertices, UVs, colours and alpha. Background mutable proxies also stop issuing hardware occlusion queries against their near bounds, which do not describe the shader-displaced background depth. Ordinary mutable geometry keeps its queries, and world depth still occludes the rendered sky.

The original sunglare was additionally classified as a hand/weapon: it inherited equipment/view-mode suppression, lighting, fog and weapon camera correction. Its weather-controller slot now owns it independently of the borrowed near-pass parent. Celestial kind 7 uses the original translucent blend in an unlit, depth-disabled overlay; native fade/occlusion values control it. It is excluded from water reflections and replaces the additional UE light-shaft bloom. Native root hiding still wins: the tested third-person state had root flags 91 instead of 90 and legitimately hid glare while retaining the sun disc.

409 source tests and all 37 packaged UE tests pass. Actual D3D11 and threaded D3D12 mutable/flare comparisons pass: an owned closer green occluder produced 211 green pixels, the flare affected 80 of them, and native zero alpha restored the reference with zero total RGB difference. The real-proxy checks retain ordinary world occlusion queries while disabling only the displaced background query. The threaded D3D12 reflection-membership regression also passes.

The final live Seyda Neen check retained the exact JSON camera metadata for each accepted binary frame. It matched 48 snapshots, including 40 while walking, drawn/sheathed states, a first/third-person cycle, off-axis looking and returning toward the sun. All 95 visible solar payloads matched the UE-submitted vertex, colour and UV hashes. Maximum vertex-plane error against the captured original camera was 0.001247 native units. Sixteen observations occurred while unrelated world shapes were streaming; this is targeted solar verification, not full-world completeness. The original finished paused and responsive, with the UE native menu visible. All 32 protected save hashes and the file set are unchanged; no save commands or video recording were made. No new FPS or performance improvement is claimed.

Two exact auto-aim attempts also exposed a native failure. The original main thread remained at `0x45321F` in a loop adding/subtracting a full turn, reached through its environment-lighting/weather update at `0x4100D0`. An x86 register snapshot showed x87 NaN in that loop; UE's cutoff correctly stopped its own renderer and left the original untouched. The native process remained hung after UE exited. This is a reproduced limitation, not passing acceptance or a renderer crash. The original executable was not patched. The successful repeat aimed about 3.4 degrees below the exact sun direction, avoiding deliberate exact alignment. Fixing that original-engine numerical edge case would require a separately reviewed native correction and executable-layout validation. Earlier observer failures (missing retained JSON camera metadata, ordinary shared-copy contention and an unnecessarily global readiness requirement) are retained and excluded from acceptance.

Fresh-session verification additionally found that the UI worker could exit when its unavailable-state publication encountered a busy channel during startup. That error publication now retries through the ordinary capture loop, consumes a new sequence and leaves previous timestamps unchanged. The owned regression forces the busy fault publication and verifies survival and fresh identities. The exited UI lane was replaced under the verified current source owner, and the paused menu returned to visible UE without restarting the game or renderer. This final Python-only repair occurred after the UE compile; actual runtime source hashes are recorded separately rather than changing the compile-time manifest.

Local evidence includes `sun01-final-source-tests.log`, `sun01-headless.stdout.log`, `sun01-mutable*-gpu.stdout.log`, `sun01-mutable-d3d11.stdout.log`, `sun01-reflection-gpu.stdout.log`, `sun01-live.json`, `sun01-off-axis-live.stdout.log`, `sun01-native-fpu-stacks.txt`, `sun01-*-native-hang-cutoff.json`, `sun01-ui-recovery.json`, `sun01-save-integrity.json` and `sun01-results.json`. Diagnostic images are private. General billboard modes, exact overall sky/material parity, all weather/time combinations and long-session stability remain outside this bounded repair.

## Cold catalog ordering and definition adoption (cold01)

Historical cold catalog phases reached about 58 ms. A fresh private checkpoint reproduced a 29.195 ms `definitions` call, but its new adoption-only scope was just 7.345 ms. Most of that call was actually job-key sorting in the preceding ready block; the enclosing log label changed before it reported the combined duration. Batching only metadata adoption would therefore have left the larger stall in place. That initial candidate/reference is retained separately and is not the final matched comparison.

The final worker prepares mesh/texture/alias job order, retaining first-person priority and exact native identities. The game thread moves the prepared key arrays and adopts validated CPU definitions in batches yielding after 2 ms or 128 entries per call. Existing bindings remain active until textures/materials and other resources are staged. Selection indices are patched between batches rather than rebuilt because the mesh count increased. Moved-from maps and superseded plain metadata retire with the existing off-thread DTO cleanup. No UObjects, native pose simulation, relaxed expiry or original-game writes move into the worker.

The final package was compared using its retained `UEMW_CATALOG_DEFINITION_BATCHES=0` reference path and two enabled fresh-renderer starts. The private game remained paused at the same checkpoint, with the same source session, epoch and exact catalog, 3,371 cold definitions, D3D12/RHI-thread mode and capped VSync. No visual quality settings changed.

| Case | Definition batches | Adoption total / largest batch, ms | Largest complete catalog-loading call, ms |
|---|---|---|---|
| Retained reference | 1 | 7.554 / 7.554 | 30.204 |
| Enabled A | 27 | 10.184 / 0.761 | 5.633 |
| Enabled B | 27 | 10.393 / 0.853 | 5.705 |

The largest catalog-loading call fell about 81% in this fixture. This reduces blocking work; it does not claim less aggregate CPU work or faster end-to-end loading. The adoption budget is per call, and individual allocations/other catalog phases can exceed it. These are game-thread catalog scopes, not whole-frame, GPU or displayed-frame timings. The previous worst 58 ms case was not reproduced as an exact matched baseline.

A subsequent 12-second warm walk with both resource owners ready measured CPU frame-interval median/p95/max 16.667/17.136/32.503 ms, zero resource-rebind hides, and 59.70 submitted presents/sec. Observed display changes were a 58.03/sec polling lower bound; consecutive display interval p95/max was 16.667/33.334 ms. This is a separate bounded observation, not a matched warm-play speedup or locked-60 guarantee. Native terrain-array upload scopes still reached 15.679 and 10.886 ms during newly exposed terrain preparation. Those allocations, other cold assets, render-thread/GPU costs and sustained display pacing remain follow-up work.

All 409 source tests and 37 packaged renderer tests pass. Expanded owned catalog tests force one-entry batches, preserve previous bindings/materials through partial adoption, supersede that partial load and check exact final classification against the unbatched reference. Threaded D3D12 actual-GPU rigid lighting/shadows, reflection membership and mutable attributes pass. Live weapon verification matched 53 walking witnesses and two draws (441/461 ms). A staged original tradehouse load and genuine native door exit both recovered with the same renderer/controller; the exterior adopted 3,392 definitions in 27 batches with a 0.789 ms maximum adoption batch.

An initial NPC check failed during a frame explicitly reporting 330 pending native shapes. The failure is preserved; a successful ready-resource repeat does not establish uninterrupted NPC visibility during cold staging. Ready-resource repeats matched ten exact native transform/palette observations while the NPC moved. The disposable checkpoint was restored afterward. No explicit saves or video recordings were made. Local evidence includes `cold01-final-reference.json`, `cold01-enabled-a.json`, `cold01-enabled-b.json`, their retained runtime logs, `cold01-final-renderer-tests.stdout.log`, `cold01-walk-benchmark.json`, `cold01-live.json`, `cold01-weapon.json`, `cold01-transition-*.json`, `cold01-npc-streaming-rejected.json`, `cold01-npc-visual.json` and `cold01-final-live.stdout.log`. Temporary-directory permissions caused the sandboxed source-suite attempt to fail; the native Windows repeat passed all 409 tests. The first collection attempt incorrectly required distant scenery while the native pause menu intentionally disabled it; corrected paused-scene collections are the accepted cold comparison.
