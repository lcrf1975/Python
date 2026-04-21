#!/usr/bin/env python3

"""
Universal Setup Script for Python Desktop Apps.
Features dynamic AST-based dependency analysis to minimize build size.
Supports py2app (macOS) and PyInstaller (Cross-platform)
via command line parameters.
"""

import sys
import shutil
import subprocess
import ast
import argparse
from pathlib import Path
from setuptools import setup, find_packages

# Packages to aggressively exclude when not explicitly imported
HEAVY_PACKAGES = {
    "numpy", "pandas", "scipy", "matplotlib", "PIL", "cv2",
    "tensorflow", "torch", "sklearn", "PyQt5", "PyQt6", "PySide6",
    "tkinter", "IPython", "jupyter", "pytest", "sphinx"
}

# Use the authoritative stdlib list (Python 3.10+),
# fall back to a broad manual set for older versions.
try:
    STDLIB_MODULES = sys.stdlib_module_names  # frozenset, since 3.10
except AttributeError:
    STDLIB_MODULES = {
        "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
        "asyncore", "atexit", "audioop", "base64", "bdb", "binascii",
        "binhex", "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb",
        "chunk", "cmath", "cmd", "code", "codecs", "codeop", "colorsys",
        "compileall", "concurrent", "configparser", "contextlib",
        "contextvars", "copy", "copyreg", "cProfile", "csv", "ctypes",
        "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
        "dis", "doctest", "email", "encodings", "enum", "errno",
        "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
        "fractions", "ftplib", "functools", "gc", "getopt", "getpass",
        "gettext", "glob", "grp", "gzip", "hashlib", "heapq", "hmac",
        "html", "http", "idlelib", "imaplib", "imghdr", "imp",
        "importlib", "inspect", "io", "ipaddress", "itertools", "json",
        "keyword", "lib2to3", "linecache", "locale", "logging", "lzma",
        "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
        "modulefinder", "multiprocessing", "netrc", "nis", "nntplib",
        "numbers", "operator", "optparse", "os", "ossaudiodev",
        "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
        "platform", "plistlib", "poplib", "posix", "posixpath",
        "pprint", "profile", "pstats", "pty", "pwd", "py_compile",
        "pyclbr", "pydoc", "queue", "quopri", "random", "re",
        "readline", "reprlib", "resource", "rlcompleter", "runpy",
        "sched", "secrets", "select", "selectors", "shelve", "shlex",
        "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
        "socket", "socketserver", "spwd", "sqlite3", "sre_compile",
        "sre_constants", "sre_parse", "ssl", "stat", "statistics",
        "string", "stringprep", "struct", "subprocess", "sunau",
        "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
        "telnetlib", "tempfile", "termios", "test", "textwrap",
        "threading", "time", "timeit", "tkinter", "token", "tokenize",
        "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
        "turtledemo", "types", "typing", "unicodedata", "unittest",
        "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
        "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
        "zipfile", "zipimport", "zlib", "zoneinfo", "_thread",
        "__future__",
    }


# ==============================================================================
# 1. ADVANCED DEPENDENCY ANALYZER
# ==============================================================================
def analyze_actual_imports(source_dir, main_script=None):
    """Scan source code via AST to find explicitly imported modules.

    Also scans main_script if it lives outside source_dir, and captures
    string-literal dynamic imports (__import__("pkg") and
    importlib.import_module("pkg")).  Non-literal dynamic imports trigger
    a warning so the user can add them via --extra-includes.
    """
    print(
        f"Analyzing source code in '{source_dir}'"
        " to optimize dependencies..."
    )
    imported_modules = set()
    dynamic_import_files = []

    source_path = Path(source_dir)
    if not source_path.exists():
        print(
            f"Warning: Source directory '{source_dir}' not found."
            " Skipping AST analysis."
        )
        return imported_modules

    files_to_scan = list(source_path.rglob("*.py"))

    # Fix #7: also scan main_script when it lives outside source_dir
    if main_script:
        main_path = Path(main_script).resolve()
        try:
            main_path.relative_to(source_path.resolve())
        except ValueError:
            if main_path.is_file():
                files_to_scan.append(main_path)

    for filepath in files_to_scan:
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(filepath))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_modules.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    # Skip relative imports (node.level > 0):
                    # they reference local modules, not third-party.
                    if node.module and node.level == 0:
                        imported_modules.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call):
                    # Fix #1: capture string-literal dynamic imports:
                    # __import__("pkg") and importlib.import_module("pkg")
                    func = node.func
                    is_builtin_import = (
                        isinstance(func, ast.Name)
                        and func.id == "__import__"
                    )
                    is_importlib = (
                        isinstance(func, ast.Attribute)
                        and func.attr == "import_module"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "importlib"
                    )
                    if is_builtin_import or is_importlib:
                        if node.args and isinstance(
                            node.args[0], ast.Constant
                        ):
                            imported_modules.add(
                                str(node.args[0].value).split(".")[0]
                            )
                        else:
                            dynamic_import_files.append(str(filepath))
        except SyntaxError:
            print(f"  Warning: Syntax error in {filepath}, skipping.")
        except Exception as e:
            print(f"  Warning: Could not parse {filepath}: {e}")

    if dynamic_import_files:
        unique_files = sorted(set(dynamic_import_files))
        print(
            "  Warning: Non-literal dynamic imports detected in "
            f"{len(unique_files)} file(s) — these cannot be auto-detected.\n"
            "  Use --extra-includes to add any missing packages manually:\n"
            + "\n".join(f"    {f}" for f in unique_files)
        )

    print(
        "Detected explicit imports: "
        f"{', '.join(sorted(imported_modules))}"
    )
    return imported_modules


def get_optimized_excludes(actual_imports):
    """Return heavy packages to exclude based on what isn't imported."""
    excludes = []
    for heavy_pkg in HEAVY_PACKAGES:
        if heavy_pkg not in actual_imports:
            excludes.append(heavy_pkg)

    if excludes:
        print(
            "Aggressively excluding unused heavy packages: "
            f"{', '.join(excludes)}"
        )
    return excludes


def get_third_party_includes(actual_imports, source_dir=None):
    """
    Filter imports to return only third-party packages.
    Excludes stdlib modules and the local project package itself.
    """
    local_pkg = Path(source_dir).name if source_dir else None
    third_party = set()
    for module in actual_imports:
        if module in STDLIB_MODULES:
            continue
        if local_pkg and module == local_pkg:
            continue
        third_party.add(module)
    return list(third_party)


def find_source_packages(source_dir):
    """Fix #2: find actual importable package names within source_dir.

    A package is a directory containing __init__.py.  Falls back to the
    directory name if no packages are found (with a warning).
    """
    source_path = Path(source_dir).resolve()
    packages = []

    # source_dir itself may be the package
    if (source_path / "__init__.py").exists():
        packages.append(source_path.name)
    else:
        # Look one level deep for sub-packages
        for child in sorted(source_path.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                packages.append(child.name)

    if not packages:
        packages = [source_path.name]
        print(
            f"  Warning: No __init__.py found in '{source_dir}'."
            f" Assuming package name is '{source_path.name}'."
        )

    return packages


# ==============================================================================
# 2. UTILITY FUNCTIONS
# ==============================================================================
def get_bundle_id(args):
    """Generate a macOS bundle identifier."""
    prefix = args.bundle_prefix
    if not prefix.endswith("."):
        prefix += "."
    return prefix + args.app_name.lower().replace(" ", "-")


def get_package_name(args):
    """Generate a normalized package name."""
    return args.app_name.lower().replace(" ", "-")


def read_requirements():
    """Read requirements.txt, skipping pip directives and URLs.

    Fix #5: searches CWD first, then the directory containing this script,
    so the script works correctly regardless of the invocation directory.
    """
    for base in (Path("."), Path(__file__).parent):
        req_path = base / "requirements.txt"
        if req_path.exists():
            lines = req_path.read_text(encoding="utf-8").splitlines()
            return [
                line.strip() for line in lines
                if line.strip()
                and not line.strip().startswith("#")
                and not line.strip().startswith("-")   # -r, -c, -e, etc.
                and not line.strip().startswith("git+")  # VCS URLs
                and not line.strip().startswith("http://")   # direct URLs
                and not line.strip().startswith("https://")  # direct URLs
            ]
    return []


def find_icon(prefer_icns=False):
    """
    Search for an application icon in common locations.

    Args:
        prefer_icns: If True, prioritize .icns (for macOS py2app builds).
                     On Windows, .ico is always preferred.
    """
    icns_paths = ["icon.icns", "resources/icon.icns", "assets/icon.icns"]
    ico_paths = ["icon.ico", "resources/icon.ico", "assets/icon.ico"]
    png_paths = ["icon.png", "resources/icon.png", "assets/icon.png"]

    if sys.platform == "win32":
        search_order = ico_paths + png_paths + icns_paths
    elif prefer_icns:
        search_order = icns_paths + ico_paths + png_paths
    else:
        search_order = ico_paths + png_paths + icns_paths

    for path in search_order:
        if Path(path).exists():
            return path
    return None


def validate_build_inputs(args):
    """Validate that required files and directories exist."""
    errors = []

    # Fix #6: reject path-traversal patterns using Path decomposition.
    # len(parts) != 1 catches any embedded separator; ".." / "." catch
    # the remaining traversal and self-referential edge cases.
    _parts = Path(args.app_name).parts
    if len(_parts) != 1 or _parts[0] in ("..", "."):
        errors.append(
            f"App name contains invalid path characters: '{args.app_name}'"
        )

    if not Path(args.main_script).is_file():
        errors.append(f"Main script not found: '{args.main_script}'")

    if not Path(args.source_dir).is_dir():
        errors.append(f"Source directory not found: '{args.source_dir}'")

    if errors:
        print("\n[Validation Error]")
        for error in errors:
            print(f"  - {error}")
        print()
        return False
    return True


def clean_build():
    """Remove all build artifacts and caches."""
    print("Cleaning build artifacts...")
    for dir_name in ["build", "dist"]:
        dir_path = Path(dir_name)
        if dir_path.is_dir():
            try:
                shutil.rmtree(dir_path)
                print(f"  Removed: {dir_name}/")
            except OSError as e:
                print(f"  Warning: Could not fully remove {dir_name}/: {e}")

    # Recursively remove __pycache__ and egg-info
    removed_count = 0
    for pattern in ["**/__pycache__", "**/*.egg-info", "**/.eggs"]:
        for path in Path(".").glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed_count += 1

    if removed_count:
        print(f"  Removed {removed_count} cache/egg directories.")

    # Remove PyInstaller spec file if present
    for spec_file in Path(".").glob("*.spec"):
        spec_file.unlink(missing_ok=True)
        print(f"  Removed: {spec_file}")


def create_dmg(args):
    """Create a macOS DMG installer package."""
    if sys.platform != "darwin":
        print("DMG creation is only supported on macOS.")
        return False

    app_path = Path(f"dist/{args.app_name}.app")
    dmg_path = Path(f"dist/{args.app_name}-{args.app_version}.dmg")

    if not app_path.exists():
        print(f"Error: {app_path} not found. Cannot create DMG.")
        return False

    if dmg_path.exists():
        dmg_path.unlink()

    print(f"Creating DMG: {dmg_path}")
    temp_dir = Path("dist/dmg_temp")

    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        temp_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(app_path, temp_dir / f"{args.app_name}.app")

        # Create Applications symlink (handle existing)
        apps_link = temp_dir / "Applications"
        if apps_link.exists() or apps_link.is_symlink():
            apps_link.unlink()
        apps_link.symlink_to("/Applications")

        subprocess.run(
            [
                "hdiutil", "create",
                "-volname", args.app_name,
                "-srcfolder", str(temp_dir),
                "-ov",
                "-format", "UDZO",
                str(dmg_path)
            ],
            check=True,
            capture_output=True,
            text=True
        )
        print("DMG created successfully.")

        identity = args.codesign_identity
        if identity:
            print(f"  Signing DMG with identity: {identity}")
            try:
                subprocess.run(
                    ["codesign", "--force", "--sign", identity, str(dmg_path)],
                    check=True, capture_output=True, text=True
                )
                print("  DMG signed successfully.")
            except subprocess.CalledProcessError as sign_err:
                print(f"  DMG signing failed: {sign_err.stderr}")

        return True

    except subprocess.CalledProcessError as e:
        print(f"DMG creation failed: {e.stderr}")
        return False

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 3. CODE SIGNING & NOTARIZATION
# ==============================================================================
def generate_entitlements(custom_path=None):
    """
    Return the path to an entitlements plist.
    If no custom path is given, generate a default one for Python/Qt apps.
    """
    if custom_path:
        return custom_path

    target = Path("entitlements.plist")
    if not target.exists():
        target.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
            '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            '<dict>\n'
            '    <!-- Required for Python dynamic code execution -->\n'
            '    <key>com.apple.security.cs.allow-jit</key>\n'
            '    <true/>\n'
            '    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>\n'
            '    <true/>\n'
            '    <!-- Required to load bundled .so/.dylib files -->\n'
            '    <key>com.apple.security.cs.disable-library-validation</key>\n'
            '    <true/>\n'
            '</dict>\n'
            '</plist>\n',
            encoding="utf-8"
        )
        print(f"  Generated entitlements: {target}")
    return str(target)


def codesign_app(app_path, identity, entitlements_path):
    """
    Sign a .app bundle with hardened runtime enabled.
    Uses --deep so all bundled frameworks and .so files are signed recursively.
    Hardened runtime + a real Developer ID is required for notarization.

    Note: Apple recommends signing inner binaries individually before the
    outer bundle.  --deep is a pragmatic shortcut for Python apps but may
    miss nested bundles or apply incorrect entitlements to inner frameworks.
    """
    app = Path(app_path)
    if not app.exists():
        print(f"Error: app bundle not found: {app}")
        return False

    print(f"Code-signing {app.name} with identity: {identity}")
    cmd = [
        "codesign",
        "--deep", "--force", "--verify", "--verbose",
        "--sign", identity,
        "--options", "runtime",
        "--entitlements", entitlements_path,
        str(app),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("  Signed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Code signing failed:\n{e.stderr}")
        return False


def notarize_app(app_path, profile):
    """
    Submit a .app to Apple's notarization service and staple the ticket.

    Requires a keychain profile created beforehand with:
      xcrun notarytool store-credentials <profile-name> \\
          --apple-id your@email.com --team-id TEAMID
    """
    app = Path(app_path)
    zip_path = app.parent / f"{app.stem}-notarize.zip"
    print(f"Notarizing {app.name} (this may take a few minutes)...")

    try:
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", str(app), str(zip_path)],
            check=True, capture_output=True, text=True
        )
        result = subprocess.run(
            [
                "xcrun", "notarytool", "submit", str(zip_path),
                "--keychain-profile", profile,
                "--wait",
            ],
            check=True, capture_output=True, text=True
        )
        print(result.stdout)
        subprocess.run(
            ["xcrun", "stapler", "staple", str(app)],
            check=True, capture_output=True, text=True
        )
        print("  Notarized and stapled successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Notarization failed:\n{e.stdout}\n{e.stderr}")
        return False
    finally:
        zip_path.unlink(missing_ok=True)


# ==============================================================================
# 4. BUILDERS
# ==============================================================================
def build_with_py2app(args, includes, excludes):
    """Build a macOS .app bundle using py2app."""
    if sys.platform != "darwin":
        print("Error: py2app is only supported on macOS.")
        return False

    print(f"Building {args.app_name} v{args.app_version} with py2app...")

    # Fix #2: resolve actual package names instead of assuming folder name
    source_pkgs = find_source_packages(args.source_dir)

    options = {
        "argv_emulation": False,
        "plist": {
            "CFBundleName": args.app_name,
            "CFBundleDisplayName": args.app_name,
            "CFBundleIdentifier": get_bundle_id(args),
            "CFBundleVersion": args.app_version,
            "CFBundleShortVersionString": args.app_version,
            "LSMinimumSystemVersion": args.min_macos,
            "NSHighResolutionCapable": True,
        },
        "includes": includes,
        "excludes": excludes,
        "packages": source_pkgs,
    }

    icon_path = find_icon(prefer_icns=True)
    if icon_path and icon_path.endswith(".icns"):
        options["iconfile"] = icon_path
        print(f"  Using icon: {icon_path}")

    # Temporarily modify sys.argv for setuptools (canonical py2app pattern)
    original_argv = sys.argv.copy()
    sys.argv = [sys.argv[0], "py2app"]

    try:
        setup(
            name=get_package_name(args),
            app=[args.main_script],
            options={"py2app": options},
            setup_requires=["py2app"],
            install_requires=read_requirements(),
        )
        print(f"\npy2app build complete: dist/{args.app_name}.app")
        return True

    except Exception as e:
        print(f"\npy2app build failed: {e}")
        return False

    finally:
        sys.argv = original_argv


def build_with_pyinstaller(args, includes, excludes):
    """Build an executable using PyInstaller."""
    print(
        f"Building {args.app_name} v{args.app_version}"
        " with PyInstaller..."
    )

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", args.app_name,
        "--windowed",
        "--noconfirm",
        "--clean",
    ]

    # Add data files if a 'resources' or 'assets' directory exists
    # Fix #4: use resolved absolute path as source so this works regardless
    # of the working directory from which the script is invoked.
    sep = ";" if sys.platform == "win32" else ":"
    for data_dir in ["resources", "assets", "data"]:
        data_path = Path(data_dir).resolve()
        if data_path.is_dir():
            cmd.extend(["--add-data", f"{data_path}{sep}{data_dir}"])
            print(f"  Including data directory: {data_dir}/")

    # Add icon
    icon_path = find_icon()
    if icon_path:
        cmd.extend(["--icon", icon_path])
        print(f"  Using icon: {icon_path}")

    # macOS-specific options
    if sys.platform == "darwin":
        cmd.extend(["--osx-bundle-identifier", get_bundle_id(args)])

    # Add hidden imports (third-party only)
    for inc in includes:
        cmd.extend(["--hidden-import", inc])

    # Add exclusions
    for exc in excludes:
        cmd.extend(["--exclude-module", exc])

    cmd.append(args.main_script)

    print(f"  Running: {' '.join(cmd[:6])}...")

    try:
        subprocess.run(cmd, check=True, text=True)
        ext = ".app" if sys.platform == "darwin" else ""
        output_name = f"{args.app_name}{ext}"
        print(f"\nPyInstaller build complete: dist/{output_name}")
        return True

    except subprocess.CalledProcessError as e:
        print(
            f"\nPyInstaller build failed with exit code {e.returncode}"
        )
        return False

    except FileNotFoundError:
        print(
            "\nError: PyInstaller not found. "
            "Install it with: pip install pyinstaller"
        )
        return False


# ==============================================================================
# 5. ARGUMENT PARSER
# ==============================================================================
def create_parser():
    """Creates and configures the argument parser."""
    epilog_text = """
Examples:
  1. Build with PyInstaller (cross-platform):
     python setup.py --app-name "My App" --main-script run.py \\
         --source-dir my_src --pyinstaller

  2. Build with py2app, sign, notarize, and package into a DMG (macOS only):
     python setup.py --app-name "My App" --main-script run.py \\
         --source-dir my_src --py2app --dmg \\
         --codesign-identity "Developer ID Application: Name (TEAMID)" \\
         --notarize-profile "my-notarytool-profile"

  3. Clean previous builds and compile with a custom version:
     python setup.py --clean --app-name "Dashboard" \\
         --main-script app.py --source-dir src \\
         --app-version 2.1.0 --pyinstaller

  4. Just clean build artifacts:
     python setup.py --clean
    """

    parser = argparse.ArgumentParser(
        description=(
            "Universal Setup Script for Python Desktop Apps.\n"
            "Dynamically analyzes your imports to minimize build size."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=epilog_text
    )

    group_req = parser.add_argument_group("Required Parameters (for building)")
    group_req.add_argument(
        "--app-name",
        type=str,
        help="The display name of your app (e.g., 'My App')"
    )
    group_req.add_argument(
        "--main-script",
        type=str,
        help="The entry point script (e.g., 'run.py')"
    )
    group_req.add_argument(
        "--source-dir",
        type=str,
        help="The main folder containing your .py source files"
    )

    group_opt = parser.add_argument_group("Optional Configuration")
    group_opt.add_argument(
        "--app-version",
        type=str,
        default="1.0.0",
        help="App version (default: 1.0.0)"
    )
    group_opt.add_argument(
        "--author",
        type=str,
        default="Unknown",
        help="Author name"
    )
    group_opt.add_argument(
        "--bundle-prefix",
        type=str,
        default="com.example.",
        help="Prefix for macOS bundle ID (default: com.example.)"
    )
    group_opt.add_argument(
        "--min-macos",
        type=str,
        default="10.15",
        help="Minimum macOS version required (default: 10.15)"
    )
    group_opt.add_argument(
        "--extra-includes",
        type=str,
        nargs="*",
        default=[],
        help="Modules to include (overrides auto-excludes)"
    )
    group_opt.add_argument(
        "--extra-excludes",
        type=str,
        nargs="*",
        default=[],
        help="Modules to exclude (wins over --extra-includes)"
    )

    group_sign = parser.add_argument_group(
        "Code Signing & Notarization (macOS only)"
    )
    group_sign.add_argument(
        "--codesign-identity",
        type=str,
        default=None,
        help=(
            'Code-signing identity, e.g. "Developer ID Application: Name (TEAMID)". '
            'Use "-" for ad-hoc signing (prevents App Translocation on the same machine '
            'but cannot be notarized and will still be blocked on other Macs).'
        )
    )
    group_sign.add_argument(
        "--notarize-profile",
        type=str,
        default=None,
        help=(
            "Keychain profile name for Apple notarization. "
            "Create one with: xcrun notarytool store-credentials <profile-name>. "
            "Requires --codesign-identity with a real Developer ID (not ad-hoc)."
        )
    )
    group_sign.add_argument(
        "--entitlements",
        type=str,
        default=None,
        help=(
            "Path to a custom entitlements .plist file. "
            "If omitted, a default Python/Qt entitlements file is generated automatically."
        )
    )

    group_build = parser.add_argument_group("Build Actions")
    group_build.add_argument(
        "--clean",
        action="store_true",
        help="Clean build artifacts before building"
    )
    group_build.add_argument(
        "--dmg",
        action="store_true",
        help="Create DMG file after building (macOS only)"
    )
    group_build.add_argument(
        "--py2app",
        action="store_true",
        help="Build using py2app (macOS only)"
    )
    group_build.add_argument(
        "--pyinstaller",
        action="store_true",
        help="Build using PyInstaller (cross-platform)"
    )

    return parser


# ==============================================================================
# 6. TYPED ARGUMENT NAMESPACE
# ==============================================================================
class Args(argparse.Namespace):
    """Typed namespace for parsed CLI arguments."""

    app_name: str
    main_script: str
    source_dir: str
    app_version: str
    author: str
    bundle_prefix: str
    min_macos: str
    extra_includes: list[str]
    extra_excludes: list[str]
    codesign_identity: str | None
    notarize_profile: str | None
    entitlements: str | None
    clean: bool
    dmg: bool
    py2app: bool
    pyinstaller: bool


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
def main():
    """Main entry point for the setup script."""
    parser = create_parser()

    # If no arguments provided, print help and exit
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    # Parse arguments (ignoring unknown ones for setuptools compatibility)
    args = Args()
    _, unknown = parser.parse_known_args(namespace=args)
    if unknown:
        print(f"[Warning] Ignoring unknown arguments: {' '.join(unknown)}")

    # Strip stray surrounding quotes that some shells/IDEs inject
    for _attr in ("app_name", "main_script", "source_dir"):
        _val = getattr(args, _attr, None)
        if isinstance(_val, str):
            setattr(args, _attr, _val.strip('"\''))

    # Validate flag combinations
    # Fix #3: --py2app and --pyinstaller are mutually exclusive
    if args.py2app and args.pyinstaller:
        print("[Error] --py2app and --pyinstaller are mutually exclusive.")
        sys.exit(1)

    if args.notarize_profile and not args.codesign_identity:
        print(
            "[Error] --notarize-profile requires --codesign-identity.\n"
            "        Notarization needs a signed app bundle."
        )
        sys.exit(1)

    # Determine if we are running a build command
    is_building = args.py2app or args.pyinstaller

    if args.dmg and not is_building:
        print(
            "[Warning] --dmg has no effect without"
            " --py2app or --pyinstaller."
        )

    # Handle clean-only operation
    if args.clean:
        clean_build()
        if not is_building:
            print("\nClean complete.")
            sys.exit(0)

    # Validate required arguments if building
    if is_building:
        if not (args.app_name and args.main_script and args.source_dir):
            print(
                "\n[Error] The following parameters are"
                " REQUIRED for building:"
            )
            print("  --app-name, --main-script, --source-dir\n")
            parser.print_help()
            sys.exit(1)

        # Resolve main_script relative to source_dir when not found cwd
        if (
            args.main_script
            and not Path(args.main_script).is_file()
        ):
            candidate = Path(args.source_dir) / args.main_script
            if candidate.is_file():
                args.main_script = str(candidate)

        if not validate_build_inputs(args):
            sys.exit(1)

        # Step A: Analyze Dependencies
        print("\n" + "=" * 60)
        print("DEPENDENCY ANALYSIS")
        print("=" * 60)
        # Fix #7: pass main_script so imports outside source_dir are captured
        actual_imports = analyze_actual_imports(
            args.source_dir, main_script=args.main_script
        )
        auto_excludes = get_optimized_excludes(actual_imports)
        auto_includes = get_third_party_includes(
            actual_imports, args.source_dir
        )

        # Resolve auto conflicts first (exclude wins among auto-detected)
        auto_includes = [i for i in auto_includes if i not in auto_excludes]

        # --extra-includes can lift an auto-exclude
        excludes = [e for e in auto_excludes if e not in args.extra_includes]
        includes = list(auto_includes)
        for pkg in args.extra_includes:
            if pkg not in includes:
                includes.append(pkg)

        # --extra-excludes win over everything, including --extra-includes
        excludes.extend(e for e in args.extra_excludes if e not in excludes)
        includes = [i for i in includes if i not in args.extra_excludes]

        # Deduplicate, preserving order
        includes = list(dict.fromkeys(includes))
        excludes = list(dict.fromkeys(excludes))

        inc_str = ', '.join(includes) if includes else '(none)'
        exc_str = ', '.join(excludes) if excludes else '(none)'
        print(f"\nFinal includes: {inc_str}")
        print(f"Final excludes: {exc_str}")

        # Step B: Execute Build
        print("\n" + "=" * 60)
        print("BUILD PHASE")
        print("=" * 60)

        success = False
        if args.py2app:
            success = build_with_py2app(args, includes, excludes)
        elif args.pyinstaller:
            success = build_with_pyinstaller(args, includes, excludes)

        # Step C: Code Signing
        if success and sys.platform == "darwin" and args.codesign_identity:
            print("\n" + "=" * 60)
            print("CODE SIGNING")
            print("=" * 60)
            app_path = f"dist/{args.app_name}.app"
            entitlements_path = generate_entitlements(args.entitlements)
            success = codesign_app(app_path, args.codesign_identity, entitlements_path)

            # Step D: Notarization (only if signing succeeded and profile given)
            if success and args.notarize_profile:
                print("\n" + "=" * 60)
                print("NOTARIZATION")
                print("=" * 60)
                success = notarize_app(app_path, args.notarize_profile)
        elif success and sys.platform == "darwin" and not args.codesign_identity:
            print(
                "\n[Warning] No --codesign-identity provided. "
                "The app will not be signed or notarized.\n"
                "         macOS Gatekeeper may block or translocate it on other machines.\n"
                "         Pass --codesign-identity to fix this."
            )

        # Step E: Package DMG
        if success and args.dmg:
            print("\n" + "=" * 60)
            print("PACKAGING PHASE")
            print("=" * 60)
            if sys.platform == "darwin":
                create_dmg(args)
            else:
                print("Skipping DMG creation (not on macOS)")

        sys.exit(0 if success else 1)

    # Fallback to standard setuptools (for pip install, etc.)
    elif args.app_name:
        setup(
            name=get_package_name(args),
            version=args.app_version,
            author=args.author,
            packages=find_packages(),
            install_requires=read_requirements(),
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
