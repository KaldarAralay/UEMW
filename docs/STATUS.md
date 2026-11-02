# Status and supported scope

UEMW is an experimental Windows source alpha. It renders actual original-game geometry in a packaged UE 5.2.1 client while unmodified Steam Morrowind remains authoritative. It is not a completed full-game port or a compatibility promise for arbitrary mods/versions.

Implemented paths include original interiors and bounded loaded exterior cells, native terrain textures/blending, sparse bone palettes, player/NPC poses, first-person camera correction, native material/texture state, sampled lighting/fog/weather, shadows, water/underwater appearance, sky/celestial objects, rain and foliage presentation. Rendering parity is incomplete. The original UI remains a separate original-game window by default.

The latest weapon regression repair was tested in live Seyda Neen with an equipped iron longsword, walking, repeated draws, original reloads and view-mode switching. Exterior/reload checks matched 213 exact pose/placement witnesses with all eighteen foreground sections present; eight draws took roughly 0.36–0.51 seconds including native animation and observer polling. These are bounded local tests, not a guarantee for every item or long session. Immutable opaque foreground assets have the independent fast path; other effect/material cases retain older paths.

**General rendering hitches remain the next rendering task.** A short local post-reload check measured about 50.6 UE actor ticks/s, 16.7 ms median frame interval and 34.0 ms p95, with larger outliers. Those are not display/scanout FPS measurements, and a locked 60 FPS target is unproven. Whole-world state rate can be lower than camera/foreground rate. Mod compatibility, full-world coverage, all effects/body-part combinations, exact shadows/material parity and sustained stability remain open.

Source tests use owned synthetic data and Windows allocations, without game/engine files. Packaged UE tests use generated owned fixtures. CI runs the former without licensed dependencies; full packaging and live play remain local checks. Setup verifies the documented toolchain and refuses unsupported executable hashes instead of guessing offsets.

The GitHub preparation work changes layout, build/setup discovery, dependency isolation and launch supervision. It does not add rendering features or claim to solve the remaining frame-time hitches.
