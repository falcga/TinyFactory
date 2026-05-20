"""
Global configuration constants for TinyCore MultiBoot Factory.
"""

import os
import sys
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

APP_NAME = "TinyCore MultiBoot Factory"
APP_VERSION = "1.1.0"
TINY_CORE_VERSION = "17.x"

# Repository URLs
REPO_BASE = f"http://tinycorelinux.net/{TINY_CORE_VERSION}"

ARCHES = {
    "x86": {
        "repo": f"{REPO_BASE}/x86/tcz/",
        "kernel": "vmlinuz",
        "initrd": "core.gz",
        "iso": f"{REPO_BASE}/x86/release/TinyCore-current.iso",
        "arch_grub": "i386-pc",
    },
    "x86_64": {
        "repo": f"{REPO_BASE}/x86_64/tcz/",
        "kernel": "vmlinuz64",
        "initrd": "corepure64.gz",
        "iso": f"{REPO_BASE}/x86_64/release/TinyCorePure64-current.iso",
        "arch_grub": "x86_64-efi",
    },
    "aarch64": {
        "repo": f"{REPO_BASE}/aarch64/tcz/",
        "kernel": "vmlinuz64",
        "initrd": "corearm64.gz",
        "iso": f"{REPO_BASE}/aarch64/release/CorePure64-17.0.iso",
        "arch_grub": "arm64-efi",
    },
}

# Package categories for UI
PACKAGE_CATEGORIES = {
    "Network & Wi-Fi": {
        "icon": "💡",
        "packages": [
            "wifi",
            "wireless_tools",
            "wpa_supplicant",
            "firmware-iwlwifi",
            "firmware-rtlwifi",
            "dhcpcd",
            "iptables",
            "openssh",
            "nfs-utils",
        ],
    },
    "Browsers": {
        "icon": "🌐",
        "packages": [
            "browsh",
            "firefox",
            "firefox-esr",
            "palemoon",
            "chromium",
            "links",
            "lynx",
        ],
    },
    "Terminals & Utils": {
        "icon": "🖥️",
        "packages": [
            "lxterminal",
            "vt-color-test",
            "mc",
            "vim",
            "nano",
            "tmux",
            "screen",
            "bash",
            "git",
            "rsync",
            "htop",
            "jq",
            "curl",
            "wget",
        ],
    },
    "Drivers": {
        "icon": "🔧",
        "packages": [
            "filesystems-KERNEL",
            "wireless-KERNEL",
            "sata-6G-KERNEL",
            "usb-storage-KERNEL",
            "audio-KERNEL",
            "video-KERNEL",
            "squashfs-tools",
            "ntfs-3g",
            "fuse",
        ],
    },
    "Desktop & X11": {
        "icon": "🖼️",
        "packages": [
            "Xorg-7.7",
            "flwm",
            "jwm",
            "icewm",
            "openbox",
            "fluxbox",
            "xterm",
            "xorg-server",
            "graphics-KERNEL",
            "dri-KERNEL",
        ],
    },
    "Development": {
        "icon": "⚙️",
        "packages": [
            "python3.11",
            "python3.11-dev",
            "gcc",
            "make",
            "perl5",
            "ruby",
            "lua",
            "node",
        ],
    },
}

ARCH_UNAVAILABLE_PACKAGES = {
    "aarch64": [
        "firefox",
        "firefox-esr",
        "palemoon",
        "chromium",
        "Xorg-7.7",
        "flwm",
        "jwm",
        "icewm",
        "openbox",
        "fluxbox",
        "xorg-server",
    ],
    "x86": [
        "node",
        "ruby",
    ],
}

# Default GRUB settings
DEFAULT_GRUB_TIMEOUT = 10
DEFAULT_KERNEL_PARAMS = "quiet norestore loglevel=3"

# Partition settings
DEFAULT_BOOT_PARTITION_SIZE_MB = 500
MIN_BOOT_PARTITION_SIZE_MB = 200
MAX_BOOT_PARTITION_SIZE_MB = 4000


@dataclass
class Profile:
    """Application profile for save/load functionality."""

    selected_usb: str = ""
    selected_packages: Dict[str, List[str]] = field(default_factory=lambda: {
        "x86": [],
        "x86_64": [],
        "aarch64": [],
    })
    grub_timeout: int = DEFAULT_GRUB_TIMEOUT
    kernel_params: str = DEFAULT_KERNEL_PARAMS
    add_custom_tcz: List[str] = field(default_factory=list)
    boot_mode: str = "direct"  # "direct" or "iso"
    boot_partition_size_mb: int = DEFAULT_BOOT_PARTITION_SIZE_MB

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "Profile":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


def get_data_dir() -> str:
    """Get application data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    
    data_dir = os.path.join(base, APP_NAME.replace(" ", ""))
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_cache_dir() -> str:
    """Get cache directory for packages."""
    cache_dir = os.path.join(get_data_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_log_path() -> str:
    """Get log file path."""
    return os.path.join(get_data_dir(), "build.log")


def get_logs_dir() -> str:
    """Get local logs directory (next to the app, in project root)."""
    import datetime
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    logs_dir = os.path.abspath(logs_dir)
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def get_session_log_path() -> str:
    """Get a date-time-stamped log file path for the current session."""
    import datetime
    logs_dir = get_logs_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(logs_dir, f"build_{timestamp}.log")
