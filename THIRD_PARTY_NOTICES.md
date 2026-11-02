# Third-party notices

The MIT license covers original UEMW source. It does not grant rights to Morrowind, Steam, Unreal Engine or third-party dependencies.

| Component | Use and distribution |
|---|---|
| Bethesda Morrowind | Required user-owned Steam installation. No executable, master/archive, save, model, texture, audio or converted game asset is included in this repository. |
| Epic Unreal Engine 5.2.1 | Separately installed under Epic's license. Engine source/content is not vendored. Project materials are generated locally using the installed engine. |
| Steam | Separately installed by the user. A private bootstrap is added through Steam's own non-Steam-game UI. No Steam files are published here. |
| [DxWrapper](https://github.com/elishacloud/dxwrapper/releases/tag/v1.9.8700.25) | Downloaded during setup, pinned to ZIP SHA256 `5584b75342c04dc53c1a8e6bf15b1b0bd044398e86959f7d2e1973fcfa2431f4`. Its supplied `License.txt` is kept beside the private DLLs. No wrapper binary is vendored. |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN/tree/a4abfb2979a7bbff3f69f58f58ae324608821e27) | Optional inference architecture adapted in `tools/texture_upscale.py`, copyright 2021 Xintao Wang, BSD-3-Clause. The full [notice and license](docs/third-party-licenses/Real-ESRGAN.txt) are included. Model weights and generated textures remain local. |
| NumPy / Pillow | Pinned Python runtime dependencies, installed into `local/venv`. Their own licenses apply. |
| [MWSE](https://github.com/MWSE/MWSE/tree/4bdb158457fbe15943119b90a916bc2f54a752dd) | Reference for the pinned original engine's memory layouts. MWSE is not installed, injected or linked. |
| [NifTools PyFFI](https://pyffi.readthedocs.io/en/develop/_modules/pyffi/formats/nif.html) | Skin-transform equation reference; no PyFFI runtime dependency. |

UEMW is an independent project and is not affiliated with Bethesda, Valve or Epic. Converted assets and the prepared private installation must stay out of source releases. See [development](docs/DEVELOPMENT.md) for the repository audit and source-only packaging commands.
