"""
Setup script for Zendesk DC Manager.
Supports both py2app and PyInstaller for building Mac apps.
"""

import os
import sys
import shutil
import subprocess
import re
from setuptools import setup, find_packages

# Application metadata - single source of truth
APP_NAME = "Zendesk DC Manager"


def get_version():
    """Extract version from config.py."""
    version_file = os.path.join("zendesk_dc_manager", "config.py")
    if os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
    return "1.0.0"


def get_bundle_id():
    """Generate bundle ID from app name."""
    return "com.zendesk." + APP_NAME.lower().replace(" ", "-")


def get_package_name():
    """Generate package name from app name."""
    return APP_NAME.lower().replace(" ", "-")


def check_available_builders():
    """Check which build tools are available."""
    builders = {
        'py2app': False,
        'pyinstaller': False,
    }

    try:
        from py2app.build_app import py2app as py2app_cmd
        builders['py2app'] = True
    except ImportError:
        pass

    try:
        import PyInstaller
        builders['pyinstaller'] = True
    except ImportError:
        pass

    return builders


# Read requirements
requirements = []
if os.path.exists("requirements.txt"):
    with open("requirements.txt", "r", encoding="utf-8") as f:
        requirements = [
            line.strip() for line in f
            if line.strip() and not line.startswith("#")
        ]

# Read README if it exists
long_description = ""
if os.path.exists("README.md"):
    with open("README.md", "r", encoding="utf-8") as f:
        long_description = f.read()


def clean_build():
    """Clean build artifacts."""
    dirs_to_remove = [
        "build",
        "dist",
    ]

    print("Cleaning build artifacts...")

    for dir_name in dirs_to_remove:
        if os.path.isdir(dir_name):
            print(f"  Removing directory: {dir_name}")
            shutil.rmtree(dir_name, ignore_errors=True)

    for root, dirs, files in os.walk("."):
        if "/." in root or root.startswith("."):
            continue

        for d in list(dirs):
            if d in ("__pycache__", ".eggs") or d.endswith(".egg-info"):
                path = os.path.join(root, d)
                print(f"  Removing directory: {path}")
                shutil.rmtree(path, ignore_errors=True)
                dirs.remove(d)

        for f in files:
            if f.endswith((".pyc", ".pyo", ".spec")) or f == ".DS_Store":
                path = os.path.join(root, f)
                print(f"  Removing file: {path}")
                try:
                    os.remove(path)
                except OSError:
                    pass

    print("Clean complete.")


def create_dmg(version):
    """Create a DMG file for Mac distribution."""
    if sys.platform != "darwin":
        print("DMG creation is only supported on macOS.")
        return False

    app_path = f"dist/{APP_NAME}.app"
    dmg_path = f"dist/{APP_NAME}-{version}.dmg"

    if not os.path.exists(app_path):
        print(f"Error: {app_path} not found.")
        return False

    if os.path.exists(dmg_path):
        print(f"Removing existing DMG: {dmg_path}")
        os.remove(dmg_path)

    print(f"Creating DMG: {dmg_path}")

    try:
        temp_dir = "dist/dmg_temp"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)

        shutil.copytree(app_path, os.path.join(temp_dir, f"{APP_NAME}.app"))

        os.symlink(
            "/Applications",
            os.path.join(temp_dir, "Applications")
        )

        subprocess.run([
            "hdiutil", "create",
            "-volname", APP_NAME,
            "-srcfolder", temp_dir,
            "-ov",
            "-format", "UDZO",
            dmg_path
        ], check=True)

        shutil.rmtree(temp_dir)

        print(f"DMG created successfully: {dmg_path}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"Error creating DMG: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def find_icon():
    """Find application icon file."""
    icon_paths = [
        'icon.icns',
        'resources/icon.icns',
        'assets/icon.icns',
        'icon.ico',
        'resources/icon.ico',
        'assets/icon.ico',
    ]
    for path in icon_paths:
        if os.path.exists(path):
            return path
    return None


def build_with_py2app(version):
    """Build app using py2app."""
    print(f"Building {APP_NAME} v{version} with py2app...")

    py2app_options = {
        'argv_emulation': False,
        'plist': {
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': APP_NAME,
            'CFBundleIdentifier': get_bundle_id(),
            'CFBundleVersion': version,
            'CFBundleShortVersionString': version,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.15',
            'NSRequiresAquaSystemAppearance': False,
        },
        'packages': [
            'PyQt6',
            'zendesk_dc_manager',
            'requests',
            'urllib3',
            'certifi',
            'charset_normalizer',
            'idna',
        ],
        'includes': [
            'PyQt6.QtCore',
            'PyQt6.QtWidgets',
            'PyQt6.QtGui',
            'sqlite3',
            'hashlib',
            'threading',
            'json',
            'html',
            'unicodedata',
            'pathlib',
            'atexit',
            'weakref',
            'queue',
            'contextlib',
            'dataclasses',
            'enum',
            'typing',
            'datetime',
            'time',
            'random',
            're',
            'logging',
            'zendesk_dc_manager.config',
            'zendesk_dc_manager.api',
            'zendesk_dc_manager.cache',
            'zendesk_dc_manager.controller',
            'zendesk_dc_manager.translator',
            'zendesk_dc_manager.types',
            'zendesk_dc_manager.utils',
            'zendesk_dc_manager.ui_main',
            'zendesk_dc_manager.ui_styles',
            'zendesk_dc_manager.ui_widgets',
            'zendesk_dc_manager.main',
        ],
        'excludes': [
            'tkinter',
            'matplotlib',
            'numpy',
            'scipy',
            'pandas',
            'PIL',
            'IPython',
            'jupyter',
            'pytest',
            'sphinx',
            'cv2',
            'tensorflow',
            'torch',
            'sklearn',
        ],
        'resources': [],
    }

    icon_path = find_icon()
    if icon_path and icon_path.endswith('.icns'):
        py2app_options['iconfile'] = icon_path

    # Temporarily modify sys.argv for setuptools
    original_argv = sys.argv.copy()
    sys.argv = [sys.argv[0], 'py2app']

    try:
        setup(
            name=get_package_name(),
            version=version,
            app=['run.py'],
            data_files=[],
            options={'py2app': py2app_options},
            setup_requires=['py2app'],
            install_requires=requirements,
        )
        print(f"Build complete: dist/{APP_NAME}.app")
        return True
    except Exception as e:
        print(f"py2app build failed: {e}")
        return False
    finally:
        sys.argv = original_argv


def build_with_pyinstaller(version):
    """Build app using PyInstaller."""
    print(f"Building {APP_NAME} v{version} with PyInstaller...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
    ]

    # Add data files
    if sys.platform == "win32":
        cmd.extend(["--add-data", "zendesk_dc_manager;zendesk_dc_manager"])
    else:
        cmd.extend(["--add-data", "zendesk_dc_manager:zendesk_dc_manager"])

    # Add icon
    icon_path = find_icon()
    if icon_path:
        cmd.extend(["--icon", icon_path])

    # macOS specific options
    if sys.platform == "darwin":
        cmd.extend([
            "--osx-bundle-identifier", get_bundle_id(),
        ])

    # Hidden imports for PyQt6 and application modules
    hidden_imports = [
        # PyQt6
        "PyQt6.QtCore",
        "PyQt6.QtWidgets",
        "PyQt6.QtGui",
        "PyQt6.sip",
        # Requests and dependencies
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
        # Standard library modules used
        "sqlite3",
        "hashlib",
        "threading",
        "json",
        "html",
        "unicodedata",
        "pathlib",
        "atexit",
        "weakref",
        "queue",
        "contextlib",
        "dataclasses",
        "enum",
        "typing",
        "datetime",
        "time",
        "random",
        "re",
        "logging",
        # Application modules
        "zendesk_dc_manager",
        "zendesk_dc_manager.config",
        "zendesk_dc_manager.api",
        "zendesk_dc_manager.cache",
        "zendesk_dc_manager.controller",
        "zendesk_dc_manager.translator",
        "zendesk_dc_manager.types",
        "zendesk_dc_manager.utils",
        "zendesk_dc_manager.ui_main",
        "zendesk_dc_manager.ui_styles",
        "zendesk_dc_manager.ui_widgets",
        "zendesk_dc_manager.main",
    ]
    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])

    # Excludes to reduce size
    excludes = [
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "PIL",
        "IPython",
        "jupyter",
        "pytest",
        "sphinx",
        "cv2",
        "tensorflow",
        "torch",
        "sklearn",
    ]
    for exc in excludes:
        cmd.extend(["--exclude-module", exc])

    # Entry point
    cmd.append("run.py")

    print(f"Running: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        print(f"Build complete: dist/{APP_NAME}.app")
        return True
    except subprocess.CalledProcessError as e:
        print(f"PyInstaller build failed: {e}")
        return False


def print_help():
    """Print custom help message."""
    version = get_version()
    builders = check_available_builders()

    print(f"""
{APP_NAME} Setup Script v{version}

Usage:
  python setup.py [options]

Options:
  --clean           Clean build artifacts before building
  --dmg             Create DMG file after building (macOS only)
  --py2app          Force use of py2app (macOS only)
  --pyinstaller     Force use of PyInstaller
  --help-custom     Show this help message

Examples:
  python setup.py                      Build app (auto-detect builder)
  python setup.py --clean              Clean and build
  python setup.py --clean --dmg        Clean, build, and create DMG
  python setup.py --pyinstaller        Build using PyInstaller
  python setup.py --py2app             Build using py2app
  python setup.py --clean --py2app --dmg   Full build with py2app

Available Builders:
  py2app:      {"✓ Installed" if builders['py2app'] else "✗ Not installed (pip install py2app)"}
  PyInstaller: {"✓ Installed" if builders['pyinstaller'] else "✗ Not installed (pip install pyinstaller)"}

Current Configuration:
  App Name:    {APP_NAME}
  Version:     {version}
  Bundle ID:   {get_bundle_id()}
  Package:     {get_package_name()}
""")


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================


if __name__ == "__main__":

    version = get_version()
    builders = check_available_builders()

    # Check for custom flags
    do_clean = "--clean" in sys.argv
    do_dmg = "--dmg" in sys.argv
    force_py2app = "--py2app" in sys.argv
    force_pyinstaller = "--pyinstaller" in sys.argv
    show_help = "--help-custom" in sys.argv

    # Remove custom flags from sys.argv
    custom_flags = (
        "--clean", "--dmg", "--py2app", "--pyinstaller", "--help-custom"
    )
    sys.argv = [arg for arg in sys.argv if arg not in custom_flags]

    # Show help
    if show_help:
        print_help()
        sys.exit(0)

    # Clean if requested
    if do_clean:
        clean_build()

    # On macOS (or with explicit flag), build the app
    if sys.platform == "darwin" or force_pyinstaller:

        # If no command specified (or just custom flags), build the app
        if len(sys.argv) == 1:

            # Determine which builder to use
            use_py2app = False
            use_pyinstaller = False

            if force_py2app:
                if builders['py2app']:
                    use_py2app = True
                else:
                    print("Error: py2app requested but not installed.")
                    print("Install with: pip install py2app")
                    sys.exit(1)
            elif force_pyinstaller:
                if builders['pyinstaller']:
                    use_pyinstaller = True
                else:
                    print("Error: PyInstaller requested but not installed.")
                    print("Install with: pip install pyinstaller")
                    sys.exit(1)
            else:
                # Auto-detect: prefer py2app on macOS, PyInstaller elsewhere
                if sys.platform == "darwin" and builders['py2app']:
                    use_py2app = True
                elif builders['pyinstaller']:
                    use_pyinstaller = True
                elif builders['py2app']:
                    use_py2app = True
                else:
                    print("Error: No build tool available.")
                    print("Install one of the following:")
                    print("  pip install py2app      (macOS only)")
                    print("  pip install pyinstaller (cross-platform)")
                    sys.exit(1)

            # Build
            success = False
            if use_py2app:
                success = build_with_py2app(version)
            elif use_pyinstaller:
                success = build_with_pyinstaller(version)

            # Create DMG if requested and build succeeded
            if success and do_dmg:
                create_dmg(version)

            sys.exit(0 if success else 1)

    # Standard setuptools setup (for pip install, etc.)
    setup(
        name=get_package_name(),
        version=version,
        author="Your Name",
        author_email="your@email.com",
        description=f"{APP_NAME} with Translation Support",
        long_description=long_description,
        long_description_content_type="text/markdown",
        url=f"https://github.com/yourusername/{get_package_name()}",
        packages=find_packages(),
        include_package_data=True,
        python_requires=">=3.9",
        install_requires=requirements,
        entry_points={
            "console_scripts": [
                f"{get_package_name()}=zendesk_dc_manager.main:main",
            ],
            "gui_scripts": [
                f"{get_package_name()}-gui=zendesk_dc_manager.main:main",
            ],
        },
        classifiers=[
            "Development Status :: 4 - Beta",
            "Environment :: MacOS X",
            "Environment :: Win32 (MS Windows)",
            "Intended Audience :: System Administrators",
            "License :: OSI Approved :: MIT License",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft :: Windows",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "Topic :: Office/Business",
        ],
    )