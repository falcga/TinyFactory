"""
Disk operations module.
Handles partitioning, formatting, and GRUB installation.
Cross-platform: Windows (diskpart) and Linux (parted).
"""

import os
import sys
import re
import time
import platform
import subprocess
import logging
import tempfile
import shutil
from typing import List, Optional, Tuple
from pathlib import Path

from core.config import DEFAULT_BOOT_PARTITION_SIZE_MB
from core.usb import USBDevice

logger = logging.getLogger(__name__)


class DiskError(Exception):
    """Custom exception for disk operations."""
    pass


class DiskOperator:
    """
    Handles low-level disk operations: partitioning, formatting, GRUB installation.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.system = platform.system()

    # ──────────────────────────────────────────────
    # Partitioning
    # ──────────────────────────────────────────────

    def create_partitions(
        self, device: USBDevice, fat32_size_mb: int = DEFAULT_BOOT_PARTITION_SIZE_MB
    ) -> Tuple[str, str]:
        """
        Create two partitions on the USB device:
        1. FAT32 (500 MB) - boot partition
        2. exFAT (rest) - data partition
        
        Returns tuple of (boot_partition, data_partition) device paths.
        """
        logger.warning(f"Creating partitions on {device.device}")
        logger.warning(f"ALL DATA ON {device.device} WILL BE DESTROYED!")

        if self.dry_run:
            logger.info(f"DRY RUN: Would partition {device.device}")
            return self._get_partition_paths(device, 1), self._get_partition_paths(device, 2)

        if self.system == "Windows":
            return self._create_partitions_windows(device, fat32_size_mb)
        elif self.system == "Linux":
            return self._create_partitions_linux(device, fat32_size_mb)
        else:
            raise DiskError(f"Unsupported OS: {self.system}")

    def _create_partitions_windows(
        self, device: USBDevice, fat32_size_mb: int
    ) -> Tuple[str, str]:
        """Create partitions on Windows using diskpart."""
        # Extract disk number from device path
        disk_match = re.search(r"PHYSICALDRIVE(\d+)", device.device.upper())
        if not disk_match:
            raise DiskError(f"Cannot parse disk number from {device.device}")
        disk_num = disk_match.group(1)

        # Create diskpart script
        script = f"""
        select disk {disk_num}
        clean
        convert mbr
        create partition primary size={fat32_size_mb}
        format fs=fat32 quick label="TINYCORE"
        active
        assign letter=T
        create partition primary
        format fs=exfat quick label="TCDATA"
        assign letter=U
        exit
        """

        script_path = os.path.join(tempfile.gettempdir(), "diskpart_script.txt")
        try:
            with open(script_path, "w") as f:
                f.write(script)

            logger.info("Running diskpart script...")
            result = subprocess.run(
                ["diskpart", "/s", script_path],
                capture_output=True, text=True, timeout=120,
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                logger.error(f"diskpart failed: {error_msg}")
                raise DiskError(f"diskpart failed: {error_msg}")

            logger.info(f"diskpart output: {result.stdout}")

        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

        # Return partition paths
        return (r"\\.\PHYSICALDRIVE" + disk_num + r",partition=1",
                r"\\.\PHYSICALDRIVE" + disk_num + r",partition=2")

    def _create_partitions_linux(
        self, device: USBDevice, fat32_size_mb: int
    ) -> Tuple[str, str]:
        """Create partitions on Linux using parted."""
        dev_path = device.device
        boot_part = f"{dev_path}1"
        data_part = f"{dev_path}2"

        try:
            # First, unmount any existing partitions
            subprocess.run(
                ["umount", "-f", f"{dev_path}*"],
                capture_output=True, text=True, timeout=30,
                shell=True
            )

            # Create partition table and partitions
            commands = [
                ["parted", "-s", dev_path, "mklabel", "msdos"],
                ["parted", "-s", dev_path, "mkpart", "primary", "fat32",
                 "0%", f"{fat32_size_mb}MiB"],
                ["parted", "-s", dev_path, "set", "1", "boot", "on"],
                ["parted", "-s", dev_path, "mkpart", "primary",
                 f"{fat32_size_mb}MiB", "100%"],
            ]

            for cmd in commands:
                logger.info(f"Running: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode != 0:
                    logger.warning(f"Command warning: {result.stderr}")

            # Wait for kernel to recognize partitions
            time.sleep(2)

            # Format partitions
            logger.info(f"Formatting {boot_part} as FAT32...")
            subprocess.run(
                ["mkfs.vfat", "-F", "32", "-n", "TINYCORE", boot_part],
                capture_output=True, text=True, timeout=30, check=True
            )

            logger.info(f"Formatting {data_part} as exFAT...")
            # Try exfat first, fall back to ext4
            try:
                subprocess.run(
                    ["mkfs.exfat", "-n", "TCDATA", data_part],
                    capture_output=True, text=True, timeout=30, check=True
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("mkfs.exfat not available, using ext4 instead")
                subprocess.run(
                    ["mkfs.ext4", "-L", "TCDATA", data_part],
                    capture_output=True, text=True, timeout=30, check=True
                )

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr or str(e)
            logger.error(f"Partitioning failed: {error_msg}")
            raise DiskError(f"Partitioning failed: {error_msg}")
        except subprocess.TimeoutExpired:
            raise DiskError("Partitioning timed out")

        return boot_part, data_part

    def _get_partition_paths(
        self, device: USBDevice, partition_num: int
    ) -> str:
        """Get partition device path."""
        if self.system == "Windows":
            disk_match = re.search(r"PHYSICALDRIVE(\d+)", device.device.upper())
            if disk_match:
                return f"\\\\.\\PHYSICALDRIVE{disk_match.group(1)},partition={partition_num}"
            return f"{device.device}\\partition={partition_num}"
        else:
            return f"{device.device}{partition_num}"

    # ──────────────────────────────────────────────
    # Mounting
    # ──────────────────────────────────────────────

    def mount_partition(
        self, partition_path: str, mount_point: str
    ) -> bool:
        """Mount a partition. Returns True on success."""
        if self.system == "Windows":
            return True  # Windows assigns letters automatically

        os.makedirs(mount_point, exist_ok=True)
        try:
            result = subprocess.run(
                ["mount", partition_path, mount_point],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error(f"Mount failed: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.error(f"Mount error: {e}")
            return False

    def unmount_all(self, device: USBDevice) -> None:
        """Unmount all partitions of a device."""
        if self.system == "Linux":
            try:
                subprocess.run(
                    ["umount", "-f", f"{device.device}*"],
                    capture_output=True, text=True, timeout=30,
                    shell=True
                )
            except Exception as e:
                logger.warning(f"Unmount warning: {e}")

    # ──────────────────────────────────────────────
    # GRUB Installation
    # ──────────────────────────────────────────────

    def install_grub(
        self, boot_partition: str, boot_mount: str,
        target: str = "i386-pc"
    ) -> bool:
        """
        Install GRUB to the boot partition.
        Supports i386-pc (BIOS) and x86_64-efi (UEFI).
        """
        logger.info(f"Installing GRUB ({target}) to {boot_partition}")

        if self.dry_run:
            logger.info(f"DRY RUN: Would install GRUB to {boot_mount}")
            return True

        if self.system == "Linux":
            return self._install_grub_linux(boot_partition, boot_mount, target)
        elif self.system == "Windows":
            return self._install_grub_windows(boot_mount, target)
        else:
            logger.error(f"GRUB installation not supported on {self.system}")
            return False

    def _install_grub_linux(
        self, boot_partition: str, boot_mount: str, target: str
    ) -> bool:
        """Install GRUB on Linux."""
        try:
            # Determine the device from partition
            dev_path = re.sub(r"\d+$", "", boot_partition)

            if target == "i386-pc":
                # BIOS installation
                result = subprocess.run(
                    ["grub-install", "--target=i386-pc",
                     "--boot-directory", os.path.join(boot_mount, "boot"),
                     dev_path],
                    capture_output=True, text=True, timeout=60,
                )
            elif target == "x86_64-efi":
                # UEFI installation
                result = subprocess.run(
                    ["grub-install", "--target=x86_64-efi",
                     "--efi-directory", boot_mount,
                     "--boot-directory", os.path.join(boot_mount, "boot"),
                     "--removable"],
                    capture_output=True, text=True, timeout=60,
                )
            else:
                result = subprocess.run(
                    ["grub-install", f"--target={target}",
                     "--boot-directory", os.path.join(boot_mount, "boot"),
                     dev_path],
                    capture_output=True, text=True, timeout=60,
                )

            if result.returncode != 0:
                logger.error(f"GRUB install failed: {result.stderr}")
                return False

            logger.info(f"GRUB installed successfully: {result.stdout}")
            return True

        except FileNotFoundError:
            logger.error("grub-install not found on this system")
            return False
        except Exception as e:
            logger.error(f"GRUB installation error: {e}")
            return False

    def _install_grub_windows(self, boot_mount: str, target: str) -> bool:
        """
        Install GRUB on Windows by copying pre-compiled GRUB files.
        Since Windows doesn't have native grub-install, we bundle GRUB files.
        """
        logger.info("Installing GRUB from bundled files (Windows)...")

        # GRUB files should be bundled with the application
        grub_dir = self._get_bundled_grub_path(target)
        if not grub_dir:
            logger.error(f"Bundled GRUB files not found for target {target}")
            return False

        target_boot_grub = os.path.join(boot_mount, "boot", "grub")
        os.makedirs(target_boot_grub, exist_ok=True)

        try:
            # Copy GRUB files
            if os.path.isdir(grub_dir):
                for item in os.listdir(grub_dir):
                    src = os.path.join(grub_dir, item)
                    dst = os.path.join(target_boot_grub, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)

            logger.info(f"GRUB files copied to {target_boot_grub}")
            return True

        except Exception as e:
            logger.error(f"Failed to copy GRUB files: {e}")
            return False

    def _get_bundled_grub_path(self, target: str) -> Optional[str]:
        """Get path to bundled GRUB files."""
        # Check multiple locations for bundled GRUB
        search_paths = [
            os.path.join(os.path.dirname(__file__), "..", "resources", "grub", target),
            os.path.join(os.path.dirname(__file__), "..", "grub", target),
            os.path.join(os.path.dirname(__file__), "..", "resources", "grub"),
        ]

        for path in search_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                return abs_path

        return None

    # ──────────────────────────────────────────────
    # File copy helpers
    # ──────────────────────────────────────────────

    def copy_to_partition(
        self, source: str, dest_root: str, relative_path: str = ""
    ) -> bool:
        """Copy file or directory to a partition."""
        dest = os.path.join(dest_root, relative_path)

        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            if os.path.isdir(source):
                shutil.copytree(source, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(source, dest)

            logger.info(f"Copied {source} -> {dest}")
            return True
        except Exception as e:
            logger.error(f"Copy failed {source} -> {dest}: {e}")
            return False

    def write_file(self, path: str, content: str) -> bool:
        """Write text content to a file."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Wrote file: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to write {path}: {e}")
            return False

    # ──────────────────────────────────────────────
    # Eject/Safely remove
    # ──────────────────────────────────────────────

    def eject(self, device: USBDevice) -> bool:
        """Safely eject the USB device."""
        logger.info(f"Ejecting {device.device}")

        if self.dry_run:
            return True

        try:
            if self.system == "Windows":
                # Use diskpart to offline the disk
                disk_match = re.search(r"PHYSICALDRIVE(\d+)", device.device.upper())
                if disk_match:
                    disk_num = disk_match.group(1)
                    script = f"select disk {disk_num}\noffline\nexit\n"
                    result = subprocess.run(
                        ["diskpart"],
                        input=script, capture_output=True, text=True, timeout=15,
                    )
                    return result.returncode == 0

            elif self.system == "Linux":
                result = subprocess.run(
                    ["eject", device.device],
                    capture_output=True, text=True, timeout=15,
                )
                return result.returncode == 0

            elif self.system == "Darwin":
                disk_name = os.path.basename(device.device)
                result = subprocess.run(
                    ["diskutil", "eject", disk_name],
                    capture_output=True, text=True, timeout=15,
                )
                return result.returncode == 0

        except Exception as e:
            logger.error(f"Eject error: {e}")

        return False