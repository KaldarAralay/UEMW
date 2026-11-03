# Status and supported scope

UEMW is an experimental Windows source alpha. It renders actual original-game geometry in a packaged UE 5.2.1 client while unmodified Steam Morrowind remains authoritative. It is not a completed full-game port or a compatibility promise for arbitrary mods/versions.

Implemented paths include original interiors and bounded loaded exterior cells, native terrain textures/blending, sparse bone palettes, player/NPC poses, first-person camera correction, native material/texture state, sampled lighting/fog/weather, shadows, water/underwater appearance, sky/celestial objects, rain and foliage presentation. Rendering parity is incomplete. The original UI remains a separate original-game window by default.

The latest weapon regression repair was tested in live Seyda Neen with an equipped iron longsword, walking, repeated draws, original reloads and view-mode switching. Exterior/reload checks matched 213 exact pose/placement witnesses with all eighteen foreground sections present; eight draws took roughly 0.36–0.51 seconds including native animation and observer polling. These are bounded local tests, not a guarantee for every item or long session. Immutable opaque foreground assets have the independent fast path; other effect/material cases retain older paths.

**Rendering hitches and transient visibility have received another repair.** Cell-root ownership now follows live TES cell slots, avoiding false cell/NPC removal during temporary reparenting. Binding indices, cache rebasing and presentation I/O move work off the game thread; material selection and invalidation remain incremental. The final short walk measured 16.67 ms median, 16.69 ms p95 and 31.67 ms worst game-thread intervals, with no samples over 33.33 ms. This is not a locked-60 or every-frame visibility guarantee; the paired preserved-client run had a lower maximum under less streaming work. See [performance evidence and limits](PERFORMANCE.md).

Those are not display/scanout FPS measurements, and a locked 60 FPS target is unproven. Whole-world state rate can be lower than camera/foreground rate. Mod compatibility, full-world coverage, all effects/body-part combinations, exact shadows/material parity and sustained stability remain open.

Source tests use owned synthetic data and Windows allocations, without game/engine files. Packaged UE tests use generated owned fixtures. CI runs the former without licensed dependencies; full packaging and live play remain local checks. Setup verifies the documented toolchain and refuses unsupported executable hashes instead of guessing offsets.

The GitHub preparation work covers layout, build/setup discovery, dependency isolation and launch supervision. The subsequent hitch work changes renderer execution/caching; it keeps the same visual settings and original gameplay authority.
