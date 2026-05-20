"""
Builder module - orchestrates the creation of multi-boot Tiny Core USB drives.
"""

import os
import sys
import re
import logging
import tempfile
import shutil
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field

from core.config import (
    ARCHES, DEFAULT_GRUB_TIMEOUT, DEFAULT_KERNEL_PARAMS,
    DEFAULT_BOOT_PARTITION_SIZE_MB, APP_NAME, get_cache_dir,
)
from core.usb import USBDevice
from core.diskops import DiskOperator, DiskError
from core.repo import RepoManager
from core.downloader import PackageDownloader, DownloadProgress

logger = logging.getLogger(__name__)


@dataclass
class BuildConfig:
    """Configuration for a USB build."""
    device: USBDevice
    selected_packages: Dict[str, List[str]] = field(default_factory=lambda: {
        "x86": [],
        "x86_64": [],
        "aarch64": [],
    })
    grub_timeout: int = DEFAULT_GRUB_TIMEOUT
    kernel_params: str = DEFAULT_KERNEL_PARAMS
    boot_mode: str = "direct"  # "direct" or "iso"
    custom_tcz_paths: List[str] = field(default_factory=list)
    boot_partition_size_mb: int = DEFAULT_BOOT_PARTITION_SIZE_MB
    dry_run: bool = False


class BuildProgress:
    """Tracks build progress with steps."""

    def __init__(self):
        self.steps: List[str] = []
        self.current_step = ""
        self.current_substep = ""
        self.percent = 0.0
        self.log: List[str] = []
        self.errors: List[str] = []
        self._callbacks: List[Callable] = []

    def register_callback(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def _notify(self) -> None:
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception as e:
                logger.warning(f"Build progress callback error: {e}")

    def start_step(self, name: str) -> None:
        self.current_step = name
        self.current_substep = ""
        self.steps.append(name)
        logger.info(f"BUILD STEP: {name}")
        self._notify()

    def set_substep(self, name: str) -> None:
        self.current_substep = name
        logger.info(f"  {name}")
        self._notify()

    def set_percent(self, percent: float) -> None:
        self.percent = percent
        self._notify()

    def add_log(self, message: str) -> None:
        self.log.append(message)
        logger.info(message)
        self._notify()

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.log.append(f"ERROR: {error}")
        logger.error(error)
        self._notify()


class USBBuilder:
    """
    Orchestrates the entire process of creating a multi-boot Tiny Core USB.
    """

    def __init__(self, repo_manager: RepoManager):
        self.repo = repo_manager
        self.downloader = PackageDownloader(repo_manager)
        self.disk_op = DiskOperator()
        self.progress = BuildProgress()

    def build(self, config: BuildConfig, dl_progress: Optional[DownloadProgress] = None) -> bool:
        """
        Execute the full build process.
        Returns True on success.
        """
        self.progress = BuildProgress()

        try:
            # Step 1: Validation
            self.progress.start_step("Validating configuration")
            if not self._validate_config(config):
                return False

            # Step 2: Prepare boot files (download kernels, initrds)
            self.progress.start_step("Preparing boot files")
            if not self._prepare_boot_files(config):
                return False

            # Step 3: Download packages
            self.progress.start_step("Downloading packages")
            if not self._download_packages(config, dl_progress):
                return False

            # Step 4: Partition and format USB
            self.progress.start_step("Partitioning USB drive")
            self.progress.add_log(
                f"Boot partition size: {config.boot_partition_size_mb} MB"
            )
            boot_part, data_part = self.disk_op.create_partitions(
                config.device, config.boot_partition_size_mb
            )

            # Step 5: Install GRUB
            self.progress.start_step("Installing GRUB bootloader")
            if not self._install_grub(config, boot_part):
                return False

            # Step 6: Copy files to boot partition
            self.progress.start_step("Copying boot files")
            if not self._copy_boot_files(config, boot_part):
                return False

            # Step 7: Copy packages to data partition
            self.progress.start_step("Copying packages to data partition")
            if not self._copy_packages_to_usb(config, data_part):
                return False

            # Step 8: Generate configuration files
            self.progress.start_step("Generating configuration")
            if not self._generate_configs(config, boot_part, data_part):
                return False

            # Step 9: Final verification
            self.progress.start_step("Final verification")
            if not self._verify_build(config):
                return False

            self.progress.start_step("Build complete!")
            self.progress.set_percent(100.0)
            return True

        except DiskError as e:
            self.progress.add_error(f"Disk error: {e}")
            return False
        except Exception as e:
            self.progress.add_error(f"Build failed: {e}")
            logger.exception("Build failed with exception")
            return False

    def _validate_config(self, config: BuildConfig) -> bool:
        """Validate build configuration."""
        if not config.device:
            self.progress.add_error("No USB device selected")
            return False

        # Check that at least one package is selected for at least one architecture
        has_packages = any(
            pkgs for pkgs in config.selected_packages.values()
        )
        if not has_packages:
            self.progress.add_error("No packages selected")
            return False

        self.progress.add_log(f"Building for: {config.device.label} ({config.device.size_str})")
        for arch, pkgs in config.selected_packages.items():
            if pkgs:
                self.progress.add_log(f"  {arch}: {len(pkgs)} packages selected")

        return True

    def _prepare_boot_files(self, config: BuildConfig) -> bool:
        """Download kernel and initrd files for selected architectures."""
        temp_dir = os.path.join(get_cache_dir(), "boot_files")
        os.makedirs(temp_dir, exist_ok=True)

        for arch, pkgs in config.selected_packages.items():
            if not pkgs:
                continue  # Skip architectures with no packages

            arch_info = ARCHES[arch]
            kernel_url = f"{arch_info['repo']}{arch_info['kernel']}"
            initrd_url = f"{arch_info['repo']}{arch_info['initrd']}"

            self.progress.set_substep(f"Downloading kernel for {arch}")

            # Download kernel
            kernel_path = os.path.join(temp_dir, f"vmlinuz-{arch}")
            if not os.path.exists(kernel_path):
                success = self._download_file(
                    kernel_url, kernel_path,
                    f"vmlinuz-{arch}"
                )
                if not success:
                    self.progress.add_error(f"Failed to download kernel for {arch}")
                    # Try an alternative URL
                    alt_kernel_url = f"{arch_info['iso']}/boot/{arch_info['kernel']}"
                    success = self._download_file(
                        alt_kernel_url, kernel_path,
                        f"vmlinuz-{arch}"
                    )
                    if not success:
                        self.progress.add_error(f"Failed to download kernel for {arch} from alternative URL")

            # Download initrd
            initrd_path = os.path.join(temp_dir, f"core-{arch}.gz")
            if not os.path.exists(initrd_path):
                success = self._download_file(
                    initrd_url, initrd_path,
                    f"core-{arch}.gz"
                )
                if not success:
                    alt_initrd_url = f"{arch_info['iso']}/boot/{arch_info['initrd']}"
                    success = self._download_file(
                        alt_initrd_url, initrd_path,
                        f"core-{arch}.gz"
                    )
                    if not success:
                        self.progress.add_error(f"Failed to download initrd for {arch}")

        return True

    def _download_file(self, url: str, dest: str, label: str) -> bool:
        """Download a single file with progress."""
        import requests
        try:
            self.progress.add_log(f"Downloading {label}...")
            resp = requests.get(url, stream=True, timeout=60)
            if resp.status_code != 200:
                logger.warning(f"Failed to download {url}: HTTP {resp.status_code}")
                return False

            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            self.progress.add_log(f"Downloaded {label}")
            return True
        except Exception as e:
            logger.error(f"Download failed {label}: {e}")
            return False

    def _download_packages(
        self, config: BuildConfig,
        dl_progress: Optional[DownloadProgress] = None
    ) -> bool:
        """Download all selected packages with dependencies."""
        if not dl_progress:
            dl_progress = DownloadProgress()

        all_success = True
        for arch, pkgs in config.selected_packages.items():
            if not pkgs:
                continue

            self.progress.set_substep(f"Downloading packages for {arch}")

            # First fetch manifest to ensure it's available
            self.progress.add_log(f"Fetching package manifest for {arch}...")
            manifest = self.repo.fetch_manifest(arch)
            self.progress.add_log(f"Found {len(manifest)} packages in repository")

            # Check for unavailable packages
            unavailable = self.repo.get_unavailable_packages(arch, pkgs)
            if unavailable:
                warning = f"Unavailable packages for {arch}: {', '.join(unavailable)}"
                self.progress.add_log(f"WARNING: {warning}")
                # Filter them out
                pkgs = [p for p in pkgs if p not in unavailable]

            if not pkgs:
                continue

            # Resolve dependencies
            self.progress.add_log(f"Resolving dependencies for {arch}...")
            all_packages = self.repo.resolve_dependencies(arch, pkgs)
            self.progress.add_log(
                f"Need to download {len(all_packages)} packages "
                f"(including dependencies)"
            )

            # Download
            results = self.downloader.download_packages(
                arch, all_packages, dl_progress
            )

            failed = [pkg for pkg, path in results.items() if path is None]
            if failed:
                self.progress.add_error(
                    f"Failed to download {len(failed)} packages for {arch}: "
                    f"{', '.join(failed[:5])}"
                )
                all_success = False

            success_count = len([p for p, r in results.items() if r is not None])
            self.progress.add_log(
                f"Downloaded {success_count}/{len(results)} packages for {arch}"
            )

        return all_success

    def _install_grub(self, config: BuildConfig, boot_part: str) -> bool:
        """Install GRUB bootloader."""
        self.progress.set_substep("Installing GRUB (BIOS)...")

        # Get mount point
        boot_mount = self._get_mount_point(config.device, boot_part, is_boot=True)

        # Install for BIOS
        if not self.disk_op.install_grub(boot_part, boot_mount, "i386-pc"):
            self.progress.add_error("Failed to install GRUB for BIOS")
            return False

        # Install for UEFI
        self.progress.set_substep("Installing GRUB (UEFI)...")
        if not self.disk_op.install_grub(boot_part, boot_mount, "x86_64-efi"):
            self.progress.add_log("WARNING: Failed to install GRUB for UEFI (non-fatal)")
            # Non-fatal - UEFI might work with bundled files

        # Create GRUB directory if it doesn't exist
        grub_dir = os.path.join(boot_mount, "boot", "grub")
        os.makedirs(grub_dir, exist_ok=True)

        # Copy GRUB fonts and themes if available
        self._copy_grub_assets(grub_dir)

        return True

    def _copy_grub_assets(self, grub_dir: str) -> None:
        """Copy GRUB assets (fonts, themes)."""
        # Create minimal GRUB assets
        fonts_dir = os.path.join(grub_dir, "fonts")
        os.makedirs(fonts_dir, exist_ok=True)

        # Try to find and copy unicode font
        font_sources = [
            "/usr/share/grub/unicode.pf2",
            "/boot/grub/fonts/unicode.pf2",
        ]
        for src in font_sources:
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(fonts_dir, "unicode.pf2"))
                break

    def _copy_boot_files(self, config: BuildConfig, boot_part: str) -> bool:
        """Copy kernel and initrd files to the boot partition."""
        boot_mount = self._get_mount_point(config.device, boot_part, is_boot=True)
        boot_dir = os.path.join(boot_mount, "boot")
        os.makedirs(boot_dir, exist_ok=True)

        cache_boot = os.path.join(get_cache_dir(), "boot_files")

        # Copy kernel and initrd for each selected architecture
        for arch in config.selected_packages:
            if not config.selected_packages[arch]:
                continue

            kernel_src = os.path.join(cache_boot, f"vmlinuz-{arch}")
            initrd_src = os.path.join(cache_boot, f"core-{arch}.gz")

            kernel_dst = os.path.join(boot_dir, f"vmlinuz-{arch}")
            initrd_dst = os.path.join(boot_dir, f"core-{arch}.gz")

            if os.path.exists(kernel_src):
                shutil.copy2(kernel_src, kernel_dst)
                self.progress.add_log(f"Copied kernel for {arch}")
            else:
                self.progress.add_error(f"Kernel not found for {arch}")

            if os.path.exists(initrd_src):
                shutil.copy2(initrd_src, initrd_dst)
                self.progress.add_log(f"Copied initrd for {arch}")
            else:
                self.progress.add_error(f"Initrd not found for {arch}")

        # If boot mode is ISO, download and copy ISOs
        if config.boot_mode == "iso":
            self.progress.set_substep("Downloading ISO images...")
            self._download_isos(config, boot_dir)

        return True

    def _download_isos(self, config: BuildConfig, boot_dir: str) -> None:
        """Download ISO images for ISO boot mode."""
        for arch in config.selected_packages:
            if not config.selected_packages[arch]:
                continue

            iso_url = ARCHES[arch]["iso"]
            iso_path = os.path.join(boot_dir, f"tinycore-{arch}.iso")

            if not os.path.exists(iso_path):
                self._download_file(iso_url, iso_path, f"tinycore-{arch}.iso")

    def _copy_packages_to_usb(
        self, config: BuildConfig, data_part: str
    ) -> bool:
        """Copy downloaded packages to the USB data partition."""
        data_mount = self._get_mount_point(config.device, data_part, is_boot=False)

        for arch, pkgs in config.selected_packages.items():
            if not pkgs:
                continue

            # Create tce directory structure
            tce_dir = os.path.join(data_mount, "tce", arch)
            optional_dir = os.path.join(tce_dir, "optional")
            os.makedirs(optional_dir, exist_ok=True)

            # Resolve dependencies to get full package list
            all_packages = self.repo.resolve_dependencies(arch, pkgs)

            self.progress.set_substep(f"Copying {arch} packages...")
            copied = 0

            for pkg in all_packages:
                cache_path = self.downloader.get_cache_path(arch, pkg)
                if os.path.exists(cache_path):
                    dst = os.path.join(optional_dir, f"{pkg}.tcz")
                    shutil.copy2(cache_path, dst)
                    copied += 1

            self.progress.add_log(f"Copied {copied} packages for {arch}")

            # Generate onboot.lst
            onboot_path = os.path.join(tce_dir, "onboot.lst")
            with open(onboot_path, "w") as f:
                for pkg in all_packages:
                    f.write(f"{pkg}.tcz\n")

            self.progress.add_log(f"Generated onboot.lst for {arch}")

        # Create home and opt directories
        os.makedirs(os.path.join(data_mount, "home"), exist_ok=True)
        os.makedirs(os.path.join(data_mount, "opt"), exist_ok=True)

        # Copy custom TCZ files if any
        if config.custom_tcz_paths:
            self.progress.set_substep("Copying custom TCZ files...")
            for arch in config.selected_packages:
                if not config.selected_packages[arch]:
                    continue
                optional_dir = os.path.join(data_mount, "tce", arch, "optional")
                for tcz_path in config.custom_tcz_paths:
                    if os.path.exists(tcz_path):
                        shutil.copy2(tcz_path, optional_dir)
                        self.progress.add_log(f"Copied custom: {os.path.basename(tcz_path)}")

        return True

    def _generate_configs(
        self, config: BuildConfig, boot_part: str, data_part: str
    ) -> bool:
        """Generate GRUB configuration and other config files."""
        boot_mount = self._get_mount_point(config.device, boot_part, is_boot=True)
        grub_cfg_path = os.path.join(boot_mount, "boot", "grub", "grub.cfg")

        # Get UUID of data partition for persistence
        data_uuid = self._get_uuid(data_part)

        # Generate grub.cfg
        grub_cfg = self._generate_grub_cfg(config, data_uuid)

        with open(grub_cfg_path, "w") as f:
            f.write(grub_cfg)

        self.progress.add_log("Generated grub.cfg")
        return True

    def _generate_grub_cfg(self, config: BuildConfig, data_uuid: str) -> str:
        """Generate the GRUB configuration file content."""
        lines = []
        lines.append("#")
        lines.append(f"# GRUB configuration generated by {APP_NAME}")
        lines.append("#")
        lines.append("")
        lines.append("set default=0")
        lines.append(f"set timeout={config.grub_timeout}")
        lines.append("")
        lines.append("# Load video backend")
        lines.append("if loadfont unicode ; then")
        lines.append("  set gfxmode=auto")
        lines.append("  set gfxpayload=keep")
        lines.append("  terminal_output gfxterm")
        lines.append("fi")
        lines.append("")
        lines.append("# Menu entries")
        lines.append("")

        # Create entries for each architecture with packages
        entry_num = 0
        for arch in ["x86", "x86_64", "aarch64"]:
            pkgs = config.selected_packages.get(arch, [])
            if not pkgs:
                continue

            arch_names = {
                "x86": "32-bit",
                "x86_64": "64-bit",
                "aarch64": "ARM 64-bit",
            }

            kernel = f"/boot/vmlinuz-{arch}"
            initrd = f"/boot/core-{arch}.gz"

            lines.append(f'menuentry "Tiny Core Linux {arch_names[arch]}" {{')
            lines.append(f'  linux {kernel} {config.kernel_params} '
                         f'tce=UUID="{data_uuid}"/tce/{arch} '
                         f'home=UUID="{data_uuid}"/home '
                         f'opt=UUID="{data_uuid}"/opt')

            if config.boot_mode == "iso":
                iso_path = f"/tinycore-{arch}.iso"
                lines.append(f'  initrd {initrd}')
                lines.append(f'  loopback loop {iso_path}')
                lines.append(f'  linux (loop)/boot/{ARCHES[arch]["kernel"]} '
                             f'{config.kernel_params} iso=UUID="{data_uuid}"{iso_path}')
            else:
                lines.append(f'  initrd {initrd}')

            lines.append("}")
            lines.append("")
            entry_num += 1

        # Add utility entries
        lines.append('menuentry "System restart" {')
        lines.append("  reboot")
        lines.append("}")
        lines.append("")
        lines.append('menuentry "System shutdown" {')
        lines.append("  halt")
        lines.append("}")

        return "\n".join(lines)

    def _get_mount_point(
        self, device: USBDevice, partition: str, is_boot: bool
    ) -> str:
        """Get the mount point for a partition."""
        import tempfile

        if self.disk_op.system == "Windows":
            # On Windows, partitions get drive letters automatically
            # Try to find the assigned letter
            import subprocess
            try:
                result = subprocess.run(
                    ["wmic", "path", "Win32_LogicalDisk", "get",
                     "DeviceID,VolumeName", "/format:csv"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.splitlines():
                    if is_boot and "TINYCORE" in line.upper():
                        drive = line.split(",")[0].strip()
                        return drive + "\\"
                    elif not is_boot and "TCDATA" in line.upper():
                        drive = line.split(",")[0].strip()
                        return drive + "\\"
            except Exception:
                pass
            # Fallback: assume T: and U:
            return "T:\\" if is_boot else "U:\\"

        # On Linux, create a temp mount point
        mount_point = f"/mnt/tinycore_{'boot' if is_boot else 'data'}"
        os.makedirs(mount_point, exist_ok=True)
        return mount_point

    def _get_uuid(self, partition_path: str) -> str:
        """Get the UUID of a partition."""
        if self.disk_op.system == "Linux":
            try:
                import subprocess
                # Use blkid to get UUID
                result = subprocess.run(
                    ["blkid", "-s", "UUID", "-o", "value", partition_path],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    uuid = result.stdout.strip()
                    if uuid:
                        return uuid
            except Exception:
                pass

        return partition_path

    def _verify_build(self, config: BuildConfig) -> bool:
        """Verify the built USB drive."""
        self.progress.set_substep("Verifying build...")

        boot_mount = self._get_mount_point(config.device, "", is_boot=True)
        data_mount = self._get_mount_point(config.device, "", is_boot=False)

        # Check boot partition
        boot_files = [
            "boot/grub/grub.cfg",
        ]
        for arch in config.selected_packages:
            if config.selected_packages[arch]:
                boot_files.append(f"boot/vmlinuz-{arch}")
                boot_files.append(f"boot/core-{arch}.gz")

        for file in boot_files:
            path = os.path.join(boot_mount, file)
            if os.path.exists(path):
                self.progress.add_log(f"  ✓ {file}")
            else:
                self.progress.add_error(f"  ✗ {file} missing")

        # Check data partition
        data_dirs = ["home", "opt"]
        for d in data_dirs:
            path = os.path.join(data_mount, d)
            if os.path.isdir(path):
                self.progress.add_log(f"  ✓ {d}/")

        for arch in config.selected_packages:
            if config.selected_packages[arch]:
                tce_dir = os.path.join(data_mount, "tce", arch)
                if os.path.isdir(tce_dir):
                    self.progress.add_log(f"  ✓ tce/{arch}/")
                    onboot = os.path.join(tce_dir, "onboot.lst")
                    if os.path.exists(onboot):
                        self.progress.add_log(f"    ✓ onboot.lst")
                else:
                    self.progress.add_error(f"  ✗ tce/{arch}/ missing")

        return True

    def cleanup(self) -> None:
        """Clean up temporary files."""
        cache_dir = get_cache_dir()
        temp_dirs = [
            os.path.join(cache_dir, "boot_files"),
        ]
        for d in temp_dirs:
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
                logger.info(f"Cleaned up: {d}")