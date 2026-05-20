"""
Package downloader module.
Handles downloading, caching, and verifying Tiny Core packages.
Supports parallel downloads and progress tracking.
"""

import os
import json
import hashlib
import logging
import threading
from typing import Dict, List, Optional, Set, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from core.config import ARCHES, get_cache_dir
from core.repo import RepoManager

logger = logging.getLogger(__name__)

# Download settings
MAX_WORKERS = 4
CHUNK_SIZE = 8192


class DownloadProgress:
    """Tracks download progress across multiple files."""

    def __init__(self):
        self.total_files = 0
        self.completed_files = 0
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.current_file = ""
        self.errors: List[str] = []
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []

    def register_callback(self, callback: Callable) -> None:
        """Register a progress callback."""
        self._callbacks.append(callback)

    def _notify(self) -> None:
        """Notify all callbacks of progress change."""
        for callback in self._callbacks:
            try:
                callback(self)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    def start_file(self, filename: str, size: int = 0) -> None:
        with self._lock:
            self.current_file = filename
            self.total_files += 1
            self.total_bytes += size
        self._notify()

    def add_bytes(self, count: int) -> None:
        with self._lock:
            self.downloaded_bytes += count
        self._notify()

    def complete_file(self) -> None:
        with self._lock:
            self.completed_files += 1
        self._notify()

    def add_error(self, error: str) -> None:
        with self._lock:
            self.errors.append(error)
        self._notify()

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return min(100.0, (self.downloaded_bytes / self.total_bytes) * 100.0)

    @property
    def is_complete(self) -> bool:
        return self.completed_files >= self.total_files and self.total_files > 0


class PackageDownloader:
    """
    Downloads and caches Tiny Core packages.
    
    Features:
    - Parallel downloads with ThreadPoolExecutor
    - Smart caching (skips already-downloaded packages)
    - MD5 verification
    - 404 tracking
    - Progress reporting
    """

    def __init__(self, repo_manager: RepoManager):
        self.repo = repo_manager
        self.cache_dir = get_cache_dir()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TinyCore-MultiBoot-Factory/1.0",
        })

        # Ensure cache directories exist
        self._ensure_cache_dirs()

    def _ensure_cache_dirs(self) -> None:
        """Create cache directory structure."""
        for arch in ARCHES:
            arch_cache = os.path.join(self.cache_dir, arch)
            os.makedirs(arch_cache, exist_ok=True)

    def get_cache_path(self, arch: str, package: str) -> str:
        """Get the cache file path for a package."""
        return os.path.join(self.cache_dir, arch, f"{package}.tcz")

    def is_cached(self, arch: str, package: str) -> bool:
        """Check if a package is already cached."""
        cache_path = self.get_cache_path(arch, package)
        return os.path.exists(cache_path) and os.path.getsize(cache_path) > 0

    def get_cached_packages(self, arch: str) -> Set[str]:
        """Get the set of cached packages for an architecture."""
        arch_cache = os.path.join(self.cache_dir, arch)
        if not os.path.exists(arch_cache):
            return set()

        cached = set()
        for f in os.listdir(arch_cache):
            if f.endswith(".tcz"):
                cached.add(f[:-4])
        return cached

    def download_package(
        self, arch: str, package: str,
        progress: Optional[DownloadProgress] = None,
        verify: bool = True
    ) -> Optional[str]:
        """
        Download a single package.
        Returns the file path on success, None on failure.
        """
        cache_path = self.get_cache_path(arch, package)

        # Check cache first
        if self.is_cached(arch, package):
            logger.info(f"Using cached package: {package}")
            if progress:
                progress.start_file(f"{package}.tcz", 0)
                progress.complete_file()
            return cache_path

        # Get package info
        pkg_info = self.repo.get_package_info(arch, package)
        if not pkg_info:
            logger.warning(f"Package not found: {package} (arch: {arch})")
            if progress:
                progress.add_error(f"Package not found: {package}")
            return None

        tcz_url = pkg_info["tcz_url"]

        # Get file size for progress tracking
        try:
            head = self.session.head(tcz_url, timeout=10)
            file_size = int(head.headers.get("Content-Length", 0))
        except Exception:
            file_size = 0

        if progress:
            progress.start_file(f"{package}.tcz", file_size)

        try:
            # Download with streaming
            resp = self.session.get(tcz_url, stream=True, timeout=60)
            if resp.status_code != 200:
                if resp.status_code == 404:
                    self.repo._mark_404(arch, tcz_url)
                logger.error(f"Download failed: {tcz_url} (HTTP {resp.status_code})")
                if progress:
                    progress.add_error(f"HTTP {resp.status_code}: {package}")
                return None

            # Write to temporary file first
            temp_path = cache_path + ".tmp"
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)

            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        if progress:
                            progress.add_bytes(len(chunk))

            # Verify MD5 if requested
            if verify:
                if not self.repo.verify_md5(temp_path, arch, package):
                    os.remove(temp_path)
                    logger.error(f"MD5 verification failed for {package}")
                    if progress:
                        progress.add_error(f"MD5 verification failed: {package}")
                    return None

            # Move temp file to cache
            os.replace(temp_path, cache_path)

            if progress:
                progress.complete_file()

            logger.info(f"Downloaded: {package}.tcz ({file_size / 1024:.0f} KB)")
            return cache_path

        except requests.RequestException as e:
            logger.error(f"Download error for {package}: {e}")
            if progress:
                progress.add_error(f"Download error: {package} - {e}")
            # Clean up temp file
            temp_path = cache_path + ".tmp"
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None

    def download_packages(
        self, arch: str, packages: List[str],
        progress: Optional[DownloadProgress] = None,
        verify: bool = True
    ) -> Dict[str, Optional[str]]:
        """
        Download multiple packages in parallel.
        Returns dict of {package_name: file_path_or_None}.
        """
        results: Dict[str, Optional[str]] = {}
        already_cached = [p for p in packages if self.is_cached(arch, p)]
        to_download = [p for p in packages if not self.is_cached(arch, p)]

        # Mark cached packages
        for pkg in already_cached:
            results[pkg] = self.get_cache_path(arch, pkg)
            if progress:
                progress.start_file(f"{pkg}.tcz", 0)
                progress.complete_file()

        if not to_download:
            return results

        logger.info(f"Downloading {len(to_download)} packages for {arch} "
                     f"({len(already_cached)} already cached)")

        # Download packages in parallel
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_pkg = {
                executor.submit(
                    self.download_package, arch, pkg, progress, verify
                ): pkg for pkg in to_download
            }

            for future in as_completed(future_to_pkg):
                pkg = future_to_pkg[future]
                try:
                    result = future.result()
                    results[pkg] = result
                except Exception as e:
                    logger.error(f"Unexpected error downloading {pkg}: {e}")
                    results[pkg] = None
                    if progress:
                        progress.add_error(f"Unexpected error: {pkg}")

        return results

    def download_package_tree(
        self, arch: str, packages: List[str],
        progress: Optional[DownloadProgress] = None,
        verify: bool = True
    ) -> Dict[str, Optional[str]]:
        """
        Resolve dependencies and download the full package tree.
        Returns dict of {package_name: file_path_or_None}.
        """
        # Resolve all dependencies
        all_packages = self.repo.resolve_dependencies(arch, packages)
        logger.info(f"Package tree for {arch}: {len(packages)} selected, "
                     f"{len(all_packages)} total with dependencies")

        # Download everything
        return self.download_packages(arch, all_packages, progress, verify)

    def get_download_size(
        self, arch: str, packages: List[str]
    ) -> int:
        """
        Estimate total download size for a set of packages.
        Returns size in bytes.
        """
        all_packages = self.repo.resolve_dependencies(arch, packages)
        total_size = 0

        for pkg in all_packages:
            if self.is_cached(arch, pkg):
                continue

            pkg_info = self.repo.get_package_info(arch, pkg)
            if not pkg_info:
                continue

            try:
                head = self.session.head(pkg_info["tcz_url"], timeout=10)
                total_size += int(head.headers.get("Content-Length", 0))
            except Exception:
                pass

        return total_size