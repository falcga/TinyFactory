"""
USB device detection and management module.
Cross-platform support for Windows, Linux, and macOS.
"""

import os
import re
import sys
import platform
import subprocess
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class USBDevice:
    """Represents a detected USB storage device."""
    device: str          # e.g., /dev/sdb, \\.\PhysicalDrive1
    label: str           # Human-readable name
    size_gb: float       # Size in GB
    mount_points: List[str] = field(default_factory=list)
    is_usb: bool = True
    model: str = ""
    vendor: str = ""

    @property
    def size_str(self) -> str:
        """Format size for display."""
        if self.size_gb >= 100:
            return f"{self.size_gb:.0f} GB"
        return f"{self.size_gb:.1f} GB"


class USBDetector:
    """
    Detects USB storage devices on the system.
    Supports Windows (wmic/diskpart), Linux (lsblk), and macOS (diskutil).
    """

    @staticmethod
    def detect() -> List[USBDevice]:
        """
        Detect all USB storage devices.
        Returns a list of USBDevice objects.
        """
        system = platform.system()
        logger.info(f"Detecting USB devices on {system}")

        try:
            if system == "Windows":
                return USBDetector._detect_windows()
            elif system == "Linux":
                return USBDetector._detect_linux()
            elif system == "Darwin":
                return USBDetector._detect_macos()
            else:
                logger.warning(f"Unsupported OS: {system}")
                return []
        except Exception as e:
            logger.error(f"Error detecting USB devices: {e}")
            return []

    @staticmethod
    def _detect_windows() -> List[USBDevice]:
        """Detect USB devices on Windows using wmic."""
        devices = []

        try:
            # Use wmic to get physical disk info
            cmd = (
                'wmic diskdrive get '
                'DeviceID,Model,Size,InterfaceType,MediaType /format:csv'
            )
            result = subprocess.run(
                cmd, capture_output=True, text=True, shell=True, timeout=15
            )

            if result.returncode != 0:
                logger.warning(f"wmic failed: {result.stderr}")
                return USBDetector._detect_windows_fallback()

            lines = result.stdout.strip().splitlines()
            if len(lines) < 2:
                return []

            # Parse CSV header
            headers = [h.strip() for h in lines[0].split(",")]

            for line in lines[1:]:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) != len(headers):
                    continue

                info = dict(zip(headers, parts))

                # Filter for USB or removable
                interface = info.get("InterfaceType", "").lower()
                media_type = info.get("MediaType", "").lower()

                is_usb = (
                    "usb" in interface or
                    "removable" in media_type or
                    "usb" in media_type or
                    info.get("Model", "").lower().startswith("usb")
                )

                if not is_usb:
                    continue

                device_id = info.get("DeviceID", "")
                model = info.get("Model", "Unknown USB Device")

                # Parse size
                size_str = info.get("Size", "0")
                try:
                    size_bytes = int(size_str)
                except (ValueError, TypeError):
                    size_bytes = 0
                size_gb = size_bytes / (1024 ** 3)

                if size_gb < 0.5:
                    continue  # Skip small devices

                # Get mount points
                mount_points = USBDetector._get_windows_mount_points(device_id)

                devices.append(USBDevice(
                    device=device_id,
                    label=model.strip(),
                    size_gb=size_gb,
                    mount_points=mount_points,
                    is_usb=True,
                    model=model.strip(),
                ))

        except subprocess.TimeoutExpired:
            logger.error("wmic timed out")
        except Exception as e:
            logger.error(f"Windows USB detection error: {e}")

        return devices

    @staticmethod
    def _detect_windows_fallback() -> List[USBDevice]:
        """Fallback: use diskpart to list disks."""
        devices = []
        try:
            script = "list disk\nexit\n"
            result = subprocess.run(
                ["diskpart"],
                input=script,
                capture_output=True,
                text=True,
                timeout=15,
            )

            for line in result.stdout.splitlines():
                # Parse: Disk 1    Online    7643 MB    0 B    USB
                if "USB" in line or "Removable" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            disk_num = parts[1]
                            size_str = parts[2]
                            # Convert size
                            size = float(size_str) / 1024  # MB to GB
                            devices.append(USBDevice(
                                device=f"\\\\.\\PhysicalDrive{disk_num}",
                                label=f"USB Disk ({size:.1f} GB)",
                                size_gb=size,
                                is_usb=True,
                                model=f"USB Disk Drive {disk_num}",
                            ))
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            logger.error(f"diskpart fallback error: {e}")

        return devices

    @staticmethod
    def _get_windows_mount_points(device_id: str) -> List[str]:
        """Get mount points for a Windows disk."""
        mount_points = []
        try:
            # Get the disk number from device ID
            # DeviceID format: \\.\PHYSICALDRIVE0
            disk_match = re.search(r"PHYSICALDRIVE(\d+)", device_id.upper())
            if not disk_match:
                return mount_points

            disk_num = disk_match.group(1)

            # Use wmic to get logical disk associations
            cmd = (
                f'wmic path Win32_LogicalDiskToPartition '
                f'get Antecedent,Dependent /format:csv'
            )
            result = subprocess.run(
                cmd, capture_output=True, text=True, shell=True, timeout=10
            )

            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if f'Disk #{disk_num}' in line or f'Disk {disk_num}' in line:
                        # Extract drive letter
                        drive_match = re.search(r"DeviceID=\"([A-Z]:)", line)
                        if drive_match:
                            mount_points.append(drive_match.group(1))

        except Exception as e:
            logger.error(f"Error getting mount points: {e}")

        return mount_points

    @staticmethod
    def _detect_linux() -> List[USBDevice]:
        """Detect USB devices on Linux using lsblk."""
        devices = []

        try:
            # Use lsblk with JSON output for easy parsing
            result = subprocess.run(
                [
                    "lsblk", "-o",
                    "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,TRAN,VENDOR",
                    "-J", "-d"
                ],
                capture_output=True, text=True, timeout=10,
            )

            if result.returncode != 0:
                logger.warning(f"lsblk failed: {result.stderr}")
                return []

            import json
            data = json.loads(result.stdout)

            for device in data.get("blockdevices", []):
                tran = device.get("tran", "").lower()
                if tran != "usb":
                    continue

                name = device.get("name", "")
                if not name:
                    continue

                # Parse size
                size_str = device.get("size", "0")
                size_gb = USBDetector._parse_size(size_str)
                if size_gb < 0.5:
                    continue

                model = device.get("model", "").strip()
                vendor = device.get("vendor", "").strip()
                label = f"{vendor} {model}".strip() or f"/dev/{name}"

                # Get mount point
                mount = device.get("mountpoint", "")

                devices.append(USBDevice(
                    device=f"/dev/{name}",
                    label=label,
                    size_gb=size_gb,
                    mount_points=[mount] if mount else [],
                    is_usb=True,
                    model=model,
                    vendor=vendor,
                ))

        except FileNotFoundError:
            logger.warning("lsblk not found, trying fallback")
            return USBDetector._detect_linux_fallback()
        except Exception as e:
            logger.error(f"Linux USB detection error: {e}")

        return devices

    @staticmethod
    def _detect_linux_fallback() -> List[USBDevice]:
        """Fallback: read /sys/block and /proc/partitions."""
        devices = []
        try:
            with open("/proc/partitions", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 4:
                        name = parts[3]
                        blocks = int(parts[2])
                        size_gb = blocks * 1024 / (1024 ** 3)
                        if size_gb < 0.5:
                            continue

                        # Check if removable
                        removable_path = f"/sys/block/{name}/removable"
                        if os.path.exists(removable_path):
                            with open(removable_path, "r") as rf:
                                if rf.read().strip() == "1":
                                    devices.append(USBDevice(
                                        device=f"/dev/{name}",
                                        label=f"/dev/{name}",
                                        size_gb=size_gb,
                                        is_usb=True,
                                        model=name,
                                    ))
        except Exception as e:
            logger.error(f"Linux fallback detection error: {e}")

        return devices

    @staticmethod
    def _detect_macos() -> List[USBDevice]:
        """Detect USB devices on macOS using diskutil."""
        devices = []

        try:
            result = subprocess.run(
                ["diskutil", "list", "-external", "-plist"],
                capture_output=True, text=True, timeout=15,
            )

            if result.returncode != 0:
                return []

            # Parse plist output
            import plistlib
            try:
                data = plistlib.loads(result.stdout.encode("utf-8"))
            except Exception:
                # Fallback to text parsing
                return USBDetector._detect_macos_text()

            for disk in data.get("AllDisks", []):
                info_result = subprocess.run(
                    ["diskutil", "info", "-plist", disk],
                    capture_output=True, text=True, timeout=10,
                )
                if info_result.returncode != 0:
                    continue

                try:
                    info = plistlib.loads(info_result.stdout.encode("utf-8"))
                except Exception:
                    continue

                if not info.get("RemovableMedia", False):
                    continue

                size_str = info.get("TotalSize", 0)
                size_gb = size_str / (1000 ** 3)

                if size_gb < 0.5:
                    continue

                media_name = info.get("MediaName", disk)
                device_node = info.get("DeviceNode", f"/dev/{disk}")

                devices.append(USBDevice(
                    device=device_node,
                    label=media_name,
                    size_gb=size_gb,
                    mount_points=[info.get("MountPoint", "")],
                    is_usb=True,
                    model=media_name,
                ))

        except Exception as e:
            logger.error(f"macOS USB detection error: {e}")

        return devices

    @staticmethod
    def _detect_macos_text() -> List[USBDevice]:
        """Fallback: parse diskutil text output."""
        devices = []
        try:
            result = subprocess.run(
                ["diskutil", "list", "-external"],
                capture_output=True, text=True, timeout=15,
            )

            current_device = None
            for line in result.stdout.splitlines():
                # Match device lines like: /dev/disk2 (external, physical):
                dev_match = re.match(r"/(dev/disk\d+)", line)
                if dev_match:
                    current_device = dev_match.group(1)
                    continue

                # Match size info
                if current_device and "GB" in line:
                    size_match = re.search(r"([\d.]+)\s*GB", line)
                    if size_match:
                        size_gb = float(size_match.group(1))
                        if size_gb >= 0.5:
                            devices.append(USBDevice(
                                device=current_device,
                                label=f"USB Disk ({size_gb:.1f} GB)",
                                size_gb=size_gb,
                                is_usb=True,
                                model=current_device,
                            ))
                    current_device = None

        except Exception as e:
            logger.error(f"macOS text detection error: {e}")

        return devices

    @staticmethod
    def _parse_size(size_str: str) -> float:
        """Parse size string like '7.2G', '500M' to GB."""
        size_str = size_str.upper().strip()
        try:
            if size_str.endswith("T"):
                return float(size_str[:-1]) * 1024
            elif size_str.endswith("G"):
                return float(size_str[:-1])
            elif size_str.endswith("M"):
                return float(size_str[:-1]) / 1024
            elif size_str.endswith("K"):
                return float(size_str[:-1]) / (1024 ** 2)
            else:
                return float(size_str) / (1024 ** 3)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def refresh() -> List[USBDevice]:
        """Force a fresh detection of USB devices."""
        return USBDetector.detect()