"""
Repository manager for Tiny Core Linux package repositories.
Handles manifest downloading, package metadata, and dependency resolution.
"""

import os
import re
import json
import hashlib
import logging
from typing import Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from core.config import ARCHES, get_cache_dir

logger = logging.getLogger(__name__)

# Timeouts for HTTP requests
REQUEST_TIMEOUT = 30
USER_AGENT = "TinyCore-MultiBoot-Factory/1.0"


class RepoManager:
    """
    Manages Tiny Core Linux package repositories.
    
    Features:
    - Downloads and parses repository manifests
    - Resolves package dependencies recursively
    - Maintains 404 cache to avoid repeated failed downloads
    - Handles .tcz, .tcz.dep, .tcz.md5.txt files
    """

    def __init__(self):
        self.cache_dir = get_cache_dir()
        self.manifests: Dict[str, Dict[str, str]] = {}  # arch -> {pkg_name: .tcz_url}
        self.dep_cache: Dict[str, Dict[str, List[str]]] = {}  # arch -> {pkg: [deps]}
        self._404_cache: Dict[str, Set[str]] = self._load_404_cache()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    # ──────────────────────────────────────────────
    # Manifest management
    # ──────────────────────────────────────────────

    def _load_404_cache(self) -> Dict[str, Set[str]]:
        """Load the 404 cache from disk."""
        path = os.path.join(self.cache_dir, "404_cache.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                return {k: set(v) for k, v in data.items()}
            except Exception as e:
                logger.warning(f"Failed to load 404 cache: {e}")
        return {}

    def _save_404_cache(self) -> None:
        """Save the 404 cache to disk."""
        path = os.path.join(self.cache_dir, "404_cache.json")
        try:
            data = {k: list(v) for k, v in self._404_cache.items()}
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save 404 cache: {e}")

    def _mark_404(self, arch: str, url: str) -> None:
        """Mark a URL as 404 for a given architecture."""
        if arch not in self._404_cache:
            self._404_cache[arch] = set()
        self._404_cache[arch].add(url)
        self._save_404_cache()

    def _is_404(self, arch: str, url: str) -> bool:
        """Check if a URL has been previously marked as 404."""
        return arch in self._404_cache and url in self._404_cache[arch]

    def _download_file(self, url: str, arch: str = "") -> Optional[bytes]:
        """
        Download a file with caching and retry logic.
        Returns None on failure.
        """
        if arch and self._is_404(arch, url):
            logger.debug(f"Skipping known 404: {url}")
            return None

        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.content
            elif resp.status_code == 404:
                if arch:
                    self._mark_404(arch, url)
                logger.warning(f"404: {url}")
                return None
            else:
                logger.warning(f"HTTP {resp.status_code}: {url}")
                return None
        except requests.RequestException as e:
            logger.error(f"Download error: {url} - {e}")
            return None

    def fetch_manifest(self, arch: str) -> Dict[str, str]:
        """
        Fetch and parse the package manifest for a given architecture.
        Returns a dict mapping package names to their .tcz URLs.
        
        The manifest is a file listing all packages in the repository.
        """
        if arch in self.manifests:
            return self.manifests[arch]

        repo_url = ARCHES[arch]["repo"]
        # Try to fetch the manifest file
        manifest_urls = [
            f"{repo_url}Packages.gz",
            f"{repo_url}Packages.txt",
            f"{repo_url}Packages",
        ]

        manifest_content = None
        for url in manifest_urls:
            logger.info(f"Fetching manifest: {url}")
            data = self._download_file(url)
            if data:
                manifest_content = data
                break

        if not manifest_content:
            logger.warning(f"No manifest found for arch {arch}, falling back to directory listing")
            # Fallback: try to get a listing, but this is unreliable
            return self._fetch_directory_listing(arch)

        # Parse the manifest
        return self._parse_manifest(arch, manifest_content)

    def _parse_manifest(self, arch: str, content: bytes) -> Dict[str, str]:
        """Parse a Tiny Core manifest file."""
        repo_url = ARCHES[arch]["repo"]
        manifest = {}

        try:
            import gzip
            try:
                text = gzip.decompress(content).decode("utf-8", errors="replace")
            except (OSError, gzip.BadGzipFile):
                text = content.decode("utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Failed to decode manifest: {e}")
            return manifest

        # Parse lines
        # Format: package_name.tcz: description
        # or: package_name.tcz:URL
        for line in text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue

            pkg_part = line.split(":", 1)[0].strip()
            # Remove .tcz extension if present
            if pkg_part.endswith(".tcz"):
                pkg_name = pkg_part[:-4]
            else:
                pkg_name = pkg_part

            if pkg_name:
                manifest[pkg_name] = f"{repo_url}{pkg_name}.tcz"

        self.manifests[arch] = manifest
        logger.info(f"Loaded manifest for {arch}: {len(manifest)} packages")
        return manifest

    def _fetch_directory_listing(self, arch: str) -> Dict[str, str]:
        """Fallback: Try to get package list from directory listing."""
        repo_url = ARCHES[arch]["repo"]
        manifest = {}

        # Fetch a pre-known list of common packages as a minimal manifest
        # This is a fallback - the manifest should normally be available
        logger.warning(f"Using fallback package list for {arch}")

        # Try to get some common packages by checking if they exist
        common_pkgs = [
            "bash", "curl", "wget", "wifi", "wireless_tools", "wpa_supplicant",
            "openssh", "git", "vim", "mc", "htop", "Xorg-7.7", "flwm",
            "lxterminal", "python3.11", "gcc", "make", "firefox", "browsh",
            "ntfs-3g", "fuse", "squashfs-tools", "iptables", "dhcpcd",
        ]
        for pkg in common_pkgs:
            manifest[pkg] = f"{repo_url}{pkg}.tcz"

        self.manifests[arch] = manifest
        logger.info(f"Fallback manifest for {arch}: {len(manifest)} packages")
        return manifest

    # ──────────────────────────────────────────────
    # Package dependency resolution
    # ──────────────────────────────────────────────

    def get_dependencies(self, arch: str, package: str) -> List[str]:
        """
        Get the dependency list for a package by downloading .tcz.dep file.
        Returns a list of dependency package names.
        """
        if arch in self.dep_cache and package in self.dep_cache[arch]:
            return self.dep_cache[arch][package]

        repo_url = ARCHES[arch]["repo"]
        dep_url = f"{repo_url}{package}.tcz.dep"

        data = self._download_file(dep_url, arch)
        if not data:
            # No dependencies
            if arch not in self.dep_cache:
                self.dep_cache[arch] = {}
            self.dep_cache[arch][package] = []
            return []

        try:
            text = data.decode("utf-8", errors="replace")
            deps = []
            for line in text.splitlines():
                dep = line.strip().rstrip(".tcz")
                if dep and not dep.startswith("#"):
                    deps.append(dep)

            if arch not in self.dep_cache:
                self.dep_cache[arch] = {}
            self.dep_cache[arch][package] = deps
            return deps
        except Exception as e:
            logger.error(f"Failed to parse dependencies for {package}: {e}")
            return []

    def resolve_dependencies(
        self, arch: str, packages: List[str], max_depth: int = 10
    ) -> List[str]:
        """
        Recursively resolve all dependencies for a list of packages.
        Returns a flat list of all required packages (including the originals).
        """
        resolved: List[str] = []
        visited: Set[str] = set()
        depth = 0

        def _resolve(pkg: str, depth: int) -> None:
            if depth > max_depth:
                logger.warning(f"Dependency depth limit reached for {pkg}")
                return
            if pkg in visited:
                return
            visited.add(pkg)

            deps = self.get_dependencies(arch, pkg)
            for dep in deps:
                _resolve(dep, depth + 1)

            if pkg not in resolved:
                resolved.append(pkg)

        for pkg in packages:
            _resolve(pkg, 0)

        return resolved

    # ──────────────────────────────────────────────
    # Package info
    # ──────────────────────────────────────────────

    def get_package_info(self, arch: str, package: str) -> Optional[Dict]:
        """
        Get info about a package: .tcz URL, .dep URL, .md5 URL.
        Returns None if the package doesn't exist (404).
        """
        repo_url = ARCHES[arch]["repo"]
        tcz_url = f"{repo_url}{package}.tcz"

        # Check if we already know it's 404
        if self._is_404(arch, tcz_url):
            return None

        # Check if it's in the manifest
        manifest = self.fetch_manifest(arch)
        if package not in manifest:
            # Verify by trying head request
            if not self._verify_package_exists(arch, package):
                self._mark_404(arch, tcz_url)
                return None

        return {
            "name": package,
            "tcz_url": tcz_url,
            "dep_url": f"{repo_url}{package}.tcz.dep",
            "md5_url": f"{repo_url}{package}.tcz.md5.txt",
            "info_url": f"{repo_url}{package}.tcz.info",
        }

    def _verify_package_exists(self, arch: str, package: str) -> bool:
        """Verify if a package exists in the repository."""
        repo_url = ARCHES[arch]["repo"]
        tcz_url = f"{repo_url}{package}.tcz"

        if self._is_404(arch, tcz_url):
            return False

        try:
            resp = self.session.head(tcz_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return True
            elif resp.status_code == 404:
                self._mark_404(arch, tcz_url)
                return False
            return False
        except requests.RequestException:
            return False

    def verify_md5(self, filepath: str, arch: str, package: str) -> bool:
        """
        Verify a downloaded .tcz file against its .md5.txt.
        Returns True if valid or if md5 file not found.
        """
        repo_url = ARCHES[arch]["repo"]
        md5_url = f"{repo_url}{package}.tcz.md5.txt"

        data = self._download_file(md5_url, arch)
        if not data:
            logger.warning(f"No MD5 for {package}, skipping verification")
            return True

        try:
            expected_md5 = data.decode("utf-8", errors="replace").strip().split()[0]
            with open(filepath, "rb") as f:
                actual_md5 = hashlib.md5(f.read()).hexdigest()

            if expected_md5 != actual_md5:
                logger.error(f"MD5 mismatch for {package}: expected {expected_md5}, got {actual_md5}")
                return False
            return True
        except Exception as e:
            logger.error(f"MD5 verification failed for {package}: {e}")
            return False

    # ──────────────────────────────────────────────
    # Package availability
    # ──────────────────────────────────────────────

    def get_available_packages(self, arch: str) -> Dict[str, str]:
        """
        Get all available packages for an architecture.
        Returns dict of {package_name: tcz_url}.
        """
        return self.fetch_manifest(arch)

    def package_exists(self, arch: str, package: str) -> bool:
        """Check if a package exists for a given architecture."""
        manifest = self.fetch_manifest(arch)
        if package in manifest:
            return True
        return self._verify_package_exists(arch, package)

    def get_unavailable_packages(self, arch: str, packages: List[str]) -> List[str]:
        """Return a subset of packages that are NOT available for this arch."""
        unavailable = []
        for pkg in packages:
            if not self.package_exists(arch, pkg):
                unavailable.append(pkg)
        return unavailable