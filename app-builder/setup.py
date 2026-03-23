#!/usr/bin/env python3

"""
Universal Setup Script for Python Desktop Apps.
Features dynamic AST-based dependency analysis to minimize build size.
Supports py2app (macOS) and PyInstaller (Cross-platform)
via command line parameters.
"""

import os
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
def analyze_actual_imports(source_dir):
    """Scan source code via AST to find explicitly imported modules."""
    print(
        f"Analyzing source code in '{source_dir}'"
        " to optimize dependencies..."
    )
    imported_modules = set()

    source_path = Path(source_dir)
    if not source_path.exists():
        print(
            f"Warning: Source directory '{source_dir}' not found."
            " Skipping AST analysis."
        )
        return imported_modules

    for filepath in source_path.rglob("*.py"):
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
        except SyntaxError:
            print(f"  Warning: Syntax error in {filepath}, skipping.")
        except Exception as e:
            print(f"  Warning: Could not parse {filepath}: {e}")

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


# ==============================================================================
# 2. UTILITY FUNCTIONS
# ==============================================================================
def get_bundle_id(args):
    """Generate a macOS bundle identifier."""
    return args.bundle_prefix + args.app_name.lower().replace(" ", "-")


def get_package_name(args):
    """Generate a normalized package name."""
    return args.app_name.lower().replace(" ", "-")


def read_requirements():
    """Read requirements.txt, skipping pip directives and URLs."""
    req_path = Path("requirements.txt")
    if req_path.exists():
        lines = req_path.read_text(encoding="utf-8").splitlines()
        return [
            line.strip() for line in lines
            if line.strip()
            and not line.strip().startswith("#")
            and not line.strip().startswith("-")   # -r, -c, -e, etc.
            and not line.strip().startswith("git+")  # VCS URLs
            and not line.strip().startswith("http")  # direct URLs
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

    # Reject path-traversal characters to prevent unexpected file creation
    if any(c in args.app_name for c in (os.sep, "/", "..")):
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
            shutil.rmtree(dir_path, ignore_errors=True)
            print(f"  Removed: {dir_name}/")

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
        return True

    except subprocess.CalledProcessError as e:
        print(f"DMG creation failed: {e.stderr}")
        return False

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 3. BUILDERS
# ==============================================================================
def build_with_py2app(args, includes, excludes):
    """Build a macOS .app bundle using py2app."""
    if sys.platform != "darwin":
        print("Error: py2app is only supported on macOS.")
        return False

    print(f"Building {args.app_name} v{args.app_version} with py2app...")

    # py2app 'packages' expects Python package names, not filesystem paths
    source_pkg = Path(args.source_dir).name

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
        "packages": [source_pkg],
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

    # Add source directory as a package path for proper importing
    cmd.extend(["--paths", args.source_dir])

    # Add data files if a 'resources' or 'assets' directory exists
    sep = ";" if sys.platform == "win32" else ":"
    for data_dir in ["resources", "assets", "data"]:
        if Path(data_dir).is_dir():
            cmd.extend(["--add-data", f"{data_dir}{sep}{data_dir}"])
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
# 4. ARGUMENT PARSER
# ==============================================================================
def create_parser():
    """Creates and configures the argument parser."""
    epilog_text = """
Examples:
  1. Build with PyInstaller (cross-platform):
     python setup.py --app-name "My App" --main-script run.py \\
         --source-dir my_src --pyinstaller

  2. Build with py2app and package into a DMG (macOS only):
     python setup.py --app-name "My App" --main-script run.py \\
         --source-dir my_src --py2app --dmg

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
# 5. TYPED ARGUMENT NAMESPACE
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
    extra_includes: list
    extra_excludes: list
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
    parser.parse_known_args(namespace=args)

    # Strip stray surrounding quotes that some shells/IDEs inject
    for _attr in ("app_name", "main_script", "source_dir"):
        _val = getattr(args, _attr, None)
        if isinstance(_val, str):
            setattr(args, _attr, _val.strip('"\''))

    # Determine if we are running a build command
    is_building = args.py2app or args.pyinstaller

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
        actual_imports = analyze_actual_imports(args.source_dir)
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

        # Step C: Package DMG
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
