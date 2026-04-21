# setup.py — Universal Python Desktop App Builder

A single-file build script for packaging Python desktop applications into distributable executables. It supports **py2app** (macOS `.app` bundles) and **PyInstaller** (cross-platform), with optional code signing, notarization, and DMG packaging.

## Features

- **AST-based dependency analysis** — scans your source code to auto-detect third-party imports and exclude heavy unused packages, minimizing build size.
- **Dynamic import detection** — captures `__import__("pkg")` and `importlib.import_module("pkg")` string literals; warns on non-literal dynamic imports.
- **Cross-platform** — PyInstaller builds on macOS, Windows, and Linux; py2app for macOS-only `.app` bundles.
- **macOS distribution pipeline** — code signing (hardened runtime), Apple notarization via `notarytool`, and DMG packaging in a single command.
- **Auto icon discovery** — searches `./`, `resources/`, and `assets/` for `.icns`, `.ico`, or `.png` icons with platform-appropriate priority.
- **requirements.txt support** — reads dependencies automatically, correctly stripping inline comments, VCS URLs, and pip directives.

## Requirements

- Python 3.10+
- `setuptools`
- `py2app` (macOS builds only) — `pip install py2app`
- `pyinstaller` (cross-platform builds) — `pip install pyinstaller`

## Usage

```
python setup.py [OPTIONS]
```

Run without arguments to print the full help message.

## Options

### Required (for building)

| Flag | Description |
|------|-------------|
| `--app-name NAME` | Display name of the application |
| `--main-script FILE` | Entry point script (e.g. `run.py`) |
| `--source-dir DIR` | Directory containing your `.py` source files |

### Optional Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--app-version VER` | `1.0.0` | Application version string |
| `--author NAME` | `Unknown` | Author name (used by setuptools) |
| `--bundle-prefix PREFIX` | `com.example.` | Prefix for macOS bundle ID |
| `--min-macos VER` | `10.15` | Minimum macOS version (`LSMinimumSystemVersion`) |
| `--extra-includes PKG...` | _(none)_ | Force-include packages (overrides auto-excludes) |
| `--extra-excludes PKG...` | _(none)_ | Force-exclude packages (wins over `--extra-includes`) |

### Build Actions

| Flag | Description |
|------|-------------|
| `--pyinstaller` | Build with PyInstaller (cross-platform) |
| `--py2app` | Build with py2app (macOS only) |
| `--clean` | Remove `build/`, `dist/`, `__pycache__`, `.egg-info`, and `.spec` files before building (or alone for a clean-only run) |
| `--dmg` | Package the `.app` into a DMG after building (macOS only) |

> `--py2app` and `--pyinstaller` are mutually exclusive.

### Code Signing & Notarization (macOS only)

| Flag | Description |
|------|-------------|
| `--codesign-identity ID` | Signing identity, e.g. `"Developer ID Application: Name (TEAMID)"`. Use `"-"` for ad-hoc signing — bypasses macOS App Translocation and Gatekeeper quarantine on your own machine without requiring a paid Developer ID. Not distributable to other Macs and cannot be notarized. |
| `--notarize-profile NAME` | Keychain profile for `xcrun notarytool`. Requires a real Developer ID (not ad-hoc). |
| `--entitlements FILE` | Path to a custom `.plist` entitlements file. If omitted, a default file for Python/Qt apps is generated automatically. |

## Examples

**1. Basic PyInstaller build (cross-platform):**
```bash
python setup.py --app-name "My App" --main-script run.py \
    --source-dir my_src --pyinstaller
```

**2. Ad-hoc signing — bypass Gatekeeper on your own Mac (no Developer ID needed):**
```bash
python setup.py --app-name "My App" --main-script run.py \
    --source-dir my_src --pyinstaller \
    --codesign-identity "-"
```

**3. py2app build with full signing, notarization, and DMG (macOS distribution):**
```bash
python setup.py --app-name "My App" --main-script run.py \
    --source-dir my_src --py2app --dmg \
    --codesign-identity "Developer ID Application: Jane Doe (ABCD1234EF)" \
    --notarize-profile "my-notarytool-profile"
```

**4. Clean then build with a custom version:**
```bash
python setup.py --clean --app-name "Dashboard" \
    --main-script app.py --source-dir src \
    --app-version 2.1.0 --pyinstaller
```

**5. Clean only:**
```bash
python setup.py --clean
```

**6. Force-include a package missed by auto-detection:**
```bash
python setup.py --app-name "My App" --main-script run.py \
    --source-dir src --pyinstaller \
    --extra-includes plugin_loader my_dynamic_dep
```

## Build Pipeline (macOS)

When all flags are provided, the script runs these steps in order:

```
Dependency Analysis
      ↓
Build (.app via py2app or PyInstaller)
      ↓
Code Signing (codesign --deep, hardened runtime)
      ↓
Notarization (xcrun notarytool submit --wait → xcrun stapler staple)
      ↓
DMG Packaging (hdiutil + Applications symlink)
```

Each step only runs if the previous one succeeded.

## Dependency Resolution

The script scans all `.py` files in `--source-dir` (and `--main-script` if it lives outside that directory) using Python's `ast` module. It then:

1. Identifies all imported top-level packages.
2. Filters out stdlib modules and the local project package.
3. Auto-excludes heavy packages (`numpy`, `pandas`, `torch`, `PyQt5`, etc.) when they are not imported.
4. Passes the result as `--hidden-import` (PyInstaller) or `includes`/`packages` (py2app).

You can override this logic with `--extra-includes` and `--extra-excludes`.

## Icon Discovery

The script searches the following paths in priority order:

| Platform | Priority |
|----------|----------|
| Windows | `.ico` → `.png` → `.icns` |
| macOS (py2app or PyInstaller) | `.icns` → `.ico` → `.png` |
| Linux | `.ico` → `.png` → `.icns` |

Locations searched: `./`, `resources/`, `assets/`.

## Setting Up Notarization

Before using `--notarize-profile`, store your Apple credentials in the keychain:

```bash
xcrun notarytool store-credentials "my-notarytool-profile" \
    --apple-id your@email.com \
    --team-id ABCD1234EF
```

Then pass `--notarize-profile my-notarytool-profile` to the script. The app must be signed with a real Developer ID (not `"-"`).

## Setuptools Fallback

When called without `--pyinstaller` or `--py2app` but with `--app-name`, the script falls back to a standard `setuptools` `setup()` call. This allows it to be used as a conventional `setup.py` for `pip install` workflows.
