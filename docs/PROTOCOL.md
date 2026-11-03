# Local rendering protocol

This is a local single-user protocol between the original-game reader and UE. It contains observed render state, not gameplay commands. Counts, formats and identity/freshness checks are enforced in both implementations; malformed data fails closed. No network listener is used.

## Identity and world transport

Every committed world snapshot is bound to the original PID, bridge session UUID, scene-epoch UUID, monotonically increasing sequence and original capture timestamp. Catalog bindings define immutable ordered `(render id, asset)` entries, with cell generation/ownership metadata. Loading and scene changes invalidate old identities. Newly allocated native addresses do not inherit a retired object's lifetime.

Current `local/bridge/latest.json` is a `uemw.channel` **v1** locator for an inherited-owner Windows named shared-memory channel. The channel carries **`uemw.live` v5**, packed **UFB3** geometry and **UMP1 v1** render metadata. Geometry revision is **6**. The older file-backed live transports remain diagnostic compatibility paths. Only one source writer may own a checkout.

Shared memory uses a validated header and bounded latest slots with owner PID/session/nonce, commit generation, lengths and digests. A reader copies and validates an entire committed slot before adopting it; torn/in-progress/oversized copies do not become partial scene mutations. The current constants and struct layouts are in `bridge/shared_channel.py`; UE's matching reader is in `MWChannel.*`.

## Binary geometry

UFB headers are little endian `<4sHH16s16sQdIIII>`: magic, body version, reserved zero, session GUID, scene GUID, sequence, Unix nanoseconds as binary64, source PID, geometry version, binding count and reserved zero. GUIDs use four little-endian uint32 words corresponding to UE FGuid A/B/C/D. The body must match its enclosing identity and end exactly at the validated payload boundary.

There is one complete typed record per catalog binding. Hidden records carry no old pose. Rigid records carry the original thirteen float32 transform values. Native skins carry transform, original bound and palette matrices of three rows by four floats. Mutable records carry complete observed vertex/color/UV arrays as required by their asset definition. `bridge/live_binary.py` and UE `MWFrame.*` define the record discriminants and exact optional-array layout; `state_metadata.py` / `MWPacked.*` define UMP1's complete environment/material tables. Readers reject unknown kinds, trailing data, nonfinite values, invalid radii and mismatched array counts.

Current budgets include 16,384 bindings, 65,535 vertices per mutable shape, 257 palette matrices including fallback matrix zero, and a 4 MiB geometry-body budget. Native sparse weights use local `USK1` sidecars: `<4sIII>`, vertex/influence/palette counts, uint32 `(start,count)` ranges per vertex, then float32 `(palette_index,weight)` entries. Native influences are retained rather than truncated or normalized.

Local immutable meshes use UEM1/2/3. UEM3 is `<4sII>` followed by XYZ float32 positions, XYZ normals, UV float32 pairs, RGBA8 colors and uint16 triangle indices. Assets/catalogs are generated solely from the user's files/live geometry and are excluded from Git.

## Camera and foreground pass

`local/bridge/camera.json` supports `uemw.camera` **v1** and **v2**, bounded to 256 KiB. V2 adds a `view` object using **`uemw.view` v1**: catalog identity, independent original timestamp, original camera basis/position/frustum, read time and up to 128 states. Visible states carry a native transform and, for skins, the exact palette/bound. Asset bone counts and all numerical bounds must match.

The reader accepts only a committed live world base with the same PID/session/scene and age under 400 ms. UE retains its full-world 500 ms watchdog. Near poses expire after 150 ms; their timestamp must be within 150 ms of the enclosing camera sample and cannot rewind a newer pose. A camera/near update does not renew the world capture timestamp.

The near reader requires two matching owned captures of the native arms camera, nodes and bones, with bounded retries. Original hide, switch, parent, model/skin, equipment and first-person/items state still apply. `view-<SHA256>.json` uses `uemw.view.layout` v1, at most 256 KiB, verified against its filename. Optional reuse signatures describe converted geometry/material and skin-weight content. Rebinding re-reads those bytes; matching old pointers alone is insufficient. UE foreground asset retention is bounded to 128 and resets with the scene.

Topology discovery uses `uemw.view.discovery` v1 in `view-refresh.json`, with PID/session/epoch, SHA256 topology signature and timestamp. Requests older than 400 ms or outside the current identity reject. They request native render discovery, never game actions. Worker-only inherited preparation pipes retain private protocol v1 and support full/layout/identity/lighting/auxiliary deltas against the exact accepted fingerprint; public files never contain pickle data.

## Native helper and controls

The x64 read helper ABI is **1**. It accepts bounded uint32 x86 address ranges and copies into owned external buffers. It has no process-write API and is not loaded into Morrowind. Read plans may be reused; sampled bytes may not be relabeled with a newer timestamp. Node ownership, model identity and exact requested-byte fallbacks remain mandatory.

Cell render roots use ownership checks against the live TES cell root slots in the same captured read. Land roots also require the cell's land pointer to match. Traversal stops at the owned root; a temporary parent above it is not an object-lifetime dependency. Root type, root-slot replacement, native hide flags, child identities, switches and actor-reference fences still apply. These are internal read-layout changes, not a wire-version change.

Presentation, witness and stop controls are local, versioned and process/scene scoped. A stop request must match its recorded run token/owner; stale PID files cannot authorize stopping another process. Normal play does not generate input or recording requests. Developer input probes require the exact private game in the foreground.

Presentation file reads/writes run in a bounded background task. Controller and renderer timestamps retain their original sample times; delayed I/O does not renew a lease. The existing 500 ms source/controller expiry rules remain in force. A disjoint side-by-side view retains its existing physical-window safety check.

With `-UEMWDiagnosticScreenshots` only, a witness request may include integer `record_seconds` from 1 through 10 to trigger the existing backbuffer recorder after startup. Its response includes `capture_folder`. Requests are not queued or extended while a capture is active. PNG capture can stall rendering and skip requests; keep it separate from timing measurements.
