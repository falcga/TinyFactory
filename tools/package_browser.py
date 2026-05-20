#!/usr/bin/env python3
"""
TinyCore Package Browser — standalone tool for browsing ALL packages
from any Tiny Core version, with checkboxes to add them to a config file.

Usage:
    python -m tools.package_browser

Output: generates config snippets that can be loaded by the main app.
Also can directly modify the main app's PACKAGE_CATEGORIES in core/config.py.
"""

import os
import sys
import json
import logging
from typing import Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QCheckBox, QTreeWidget,
    QTreeWidgetItem, QProgressBar, QTextEdit, QMessageBox,
    QSplitter, QGroupBox, QFileDialog, QLineEdit, QTabWidget,
    QGridLayout, QHeaderView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor

from core.config import (
    APP_NAME, AVAILABLE_VERSIONS, ARCHES_TEMPLATE,
    PACKAGE_CATEGORIES as DEFAULT_CATEGORIES,
    get_arches_for_version,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("package_browser")

REQUEST_TIMEOUT = 30
USER_AGENT = "TinyCore-PackageBrowser/1.0"


class ManifestFetcher(QThread):
    """Thread for fetching package manifests."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)  # {arch: [pkg_names]}
    error = pyqtSignal(str)

    def __init__(self, version: str, arches: List[str]):
        super().__init__()
        self.version = version
        self.arches = arches
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def run(self):
        results = {}
        for arch in self.arches:
            self.progress.emit(f"Fetching {arch} manifest for Tiny Core {self.version}...")
            try:
                pkgs = self._fetch_manifest(arch)
                results[arch] = pkgs
                self.progress.emit(f"  ✓ {arch}: {len(pkgs)} packages found")
            except Exception as e:
                self.error.emit(f"  ✗ {arch}: {e}")
                results[arch] = []
        self.finished.emit(results)

    def _fetch_manifest(self, arch: str) -> List[str]:
        """Fetch and parse ALL package names from a Tiny Core repo."""
        repo_url = f"http://tinycorelinux.net/{self.version}/{arch}/tcz/"
        manifest_urls = [
            f"{repo_url}Packages.gz",
            f"{repo_url}Packages.txt",
            f"{repo_url}Packages",
        ]

        content = None
        for url in manifest_urls:
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    content = resp.content
                    break
            except requests.RequestException:
                continue

        if not content:
            # Fallback: fetch directory listing
            return self._fetch_from_listing(repo_url)

        # Parse
        try:
            import gzip
            try:
                text = gzip.decompress(content).decode("utf-8", errors="replace")
            except (OSError, gzip.BadGzipFile):
                text = content.decode("utf-8", errors="replace")
        except Exception:
            text = content.decode("utf-8", errors="replace")

        packages = []
        for line in text.splitlines():
            line = line.strip()
            if ":" in line:
                pkg = line.split(":", 1)[0].strip()
                if pkg.endswith(".tcz"):
                    pkg = pkg[:-4]
                if pkg and not pkg.startswith("#"):
                    packages.append(pkg)
        return sorted(set(packages))

    def _fetch_from_listing(self, repo_url: str) -> List[str]:
        """Fallback: try to get package list from HTML directory listing."""
        packages = []
        try:
            resp = self.session.get(repo_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                import re
                for match in re.finditer(r'href="([^"]+\.tcz)"', resp.text):
                    pkg = match.group(1).replace(".tcz", "")
                    packages.append(pkg)
        except Exception:
            pass
        return sorted(set(packages))


class PackageBrowserWindow(QMainWindow):
    """Main window for the package browser tool."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TinyCore Package Browser")
        self.setMinimumSize(900, 600)
        self.resize(1100, 700)

        # State
        self.version = "17.x"
        self.all_packages: Dict[str, List[str]] = {}  # arch -> [pkg_names]
        self.selected: Dict[str, Set[str]] = {a: set() for a in ARCHES_TEMPLATE}
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Header
        header = QLabel("📦 TinyCore Package Browser")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(header)

        # Controls
        top = QHBoxLayout()

        top.addWidget(QLabel("Version:"))
        self.version_combo = QComboBox()
        for v in AVAILABLE_VERSIONS:
            self.version_combo.addItem(f"Tiny Core {v}", v)
        self.version_combo.currentIndexChanged.connect(self._on_version_change)
        top.addWidget(self.version_combo)

        self.fetch_btn = QPushButton("🔄 Fetch All Packages")
        self.fetch_btn.clicked.connect(self._fetch_all)
        top.addWidget(self.fetch_btn)

        top.addStretch()
        layout.addLayout(top)

        # Progress
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #a6adc8;")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Package trees
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.trees: Dict[str, QTreeWidget] = {}

        for arch in ["x86", "x86_64", "aarch64"]:
            tree = QTreeWidget()
            tree.setHeaderLabels(["✓", "Package"])
            tree.setColumnWidth(0, 40)
            tree.setColumnWidth(1, 300)
            tree.itemChanged.connect(self._on_item_changed)
            splitter.addWidget(tree)
            self.trees[arch] = tree

            # Arch label
            label = QLabel(f"  {arch}")
            label.setStyleSheet("font-weight: bold; color: #89b4fa;")
            # We add as first widget in a wrapper
            wrapper = QWidget()
            wl = QVBoxLayout(wrapper)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(label)
            wl.addWidget(tree)

        layout.addWidget(splitter, 1)

        # Bottom controls
        bottom = QHBoxLayout()

        self.select_all_btn = QPushButton("Select All Shown")
        self.select_all_btn.clicked.connect(self._select_all)
        bottom.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        bottom.addWidget(self.deselect_all_btn)

        bottom.addStretch()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Filter packages...")
        self.search_edit.textChanged.connect(self._filter_packages)
        bottom.addWidget(self.search_edit, 1)

        layout.addLayout(bottom)

        # Export buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.export_config_btn = QPushButton("💾 Export to config.json")
        self.export_config_btn.clicked.connect(self._export_config)
        btn_row.addWidget(self.export_config_btn)

        self.update_app_btn = QPushButton("📥 Update App Categories")
        self.update_app_btn.clicked.connect(self._update_app_config)
        btn_row.addWidget(self.update_app_btn)

        layout.addLayout(btn_row)

    def _on_version_change(self, idx: int):
        self.version = self.version_combo.itemData(idx)

    def _fetch_all(self):
        """Fetch all packages for all architectures."""
        self.fetch_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Clear trees
        for arch, tree in self.trees.items():
            tree.clear()

        arches = list(ARCHES_TEMPLATE.keys())
        self.fetcher = ManifestFetcher(self.version, arches)
        self.fetcher.progress.connect(lambda m: self.progress_label.setText(m))
        self.fetcher.finished.connect(self._on_fetch_done)
        self.fetcher.error.connect(lambda e: self.progress_label.setText(e))
        self.fetcher.start()

    def _on_fetch_done(self, results: Dict[str, List[str]]):
        """Populate trees with fetched packages."""
        self.all_packages = results
        self.fetch_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        total = sum(len(v) for v in results.values())
        self.progress_label.setText(f"✅ Loaded {total} packages across {len(results)} architectures")

        for arch, pkgs in results.items():
            tree = self.trees.get(arch)
            if not tree:
                continue
            tree.clear()
            tree.setSortingEnabled(False)

            # Group by first letter for easier navigation
            groups: Dict[str, list] = {}
            for pkg in pkgs:
                prefix = pkg[0].upper() if pkg else "#"
                if prefix not in groups:
                    groups[prefix] = []
                groups[prefix].append(pkg)

            for letter in sorted(groups.keys()):
                group_item = QTreeWidgetItem(tree)
                group_item.setText(0, "")
                group_item.setText(1, f"📁 {letter}  ({len(groups[letter])})")
                group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                group_item.setExpanded(False)
                font = group_item.font(0)
                font.setBold(True)
                group_item.setFont(0, font)

                for pkg in sorted(groups[letter]):
                    item = QTreeWidgetItem(group_item)
                    item.setText(0, "")
                    item.setText(1, pkg)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    item.setToolTip(0, pkg)

            tree.setSortingEnabled(True)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Update selection tracking."""
        if column == 0 and item.childCount() == 0:  # Leaf node
            for arch, tree in self.trees.items():
                if self._find_item(tree, item):
                    pkg = item.text(1)
                    if item.checkState(0) == Qt.CheckState.Checked:
                        self.selected[arch].add(pkg)
                    else:
                        self.selected[arch].discard(pkg)
                    break

    def _find_item(self, tree: QTreeWidget, target: QTreeWidgetItem) -> bool:
        """Check if an item belongs to a specific tree."""
        root = tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat = root.child(i)
            for j in range(cat.childCount()):
                if cat.child(j) == target:
                    return True
        return False

    def _select_all(self):
        """Select all visible (non-filtered) packages."""
        for arch, tree in self.trees.items():
            root = tree.invisibleRootItem()
            for i in range(root.childCount()):
                cat = root.child(i)
                if not cat.isHidden():
                    for j in range(cat.childCount()):
                        item = cat.child(j)
                        if not item.isHidden():
                            item.setCheckState(0, Qt.CheckState.Checked)

    def _deselect_all(self):
        """Deselect all packages."""
        for arch, tree in self.trees.items():
            root = tree.invisibleRootItem()
            for i in range(root.childCount()):
                cat = root.child(i)
                for j in range(cat.childCount()):
                    cat.child(j).setCheckState(0, Qt.CheckState.Unchecked)

    def _filter_packages(self, text: str):
        """Filter packages by search text."""
        text = text.lower()
        for arch, tree in self.trees.items():
            root = tree.invisibleRootItem()
            for i in range(root.childCount()):
                cat = root.child(i)
                visible = False
                for j in range(cat.childCount()):
                    item = cat.child(j)
                    if not text or text in item.text(1).lower():
                        item.setHidden(False)
                        visible = True
                    else:
                        item.setHidden(True)
                cat.setHidden(not visible)

    def _export_config(self):
        """Export selected packages to a JSON config file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Package Config", "packages_config.json",
            "JSON Files (*.json);;All Files (*.*)"
        )
        if not path:
            return

        data = {
            "version": self.version,
            "selected": {arch: sorted(list(pkgs))
                         for arch, pkgs in self.selected.items() if pkgs},
            "total_selected": sum(len(v) for v in self.selected.values()),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        QMessageBox.information(
            self, "Exported",
            f"Saved {data['total_selected']} selected packages to:\n{path}"
        )

    def _update_app_config(self):
        """Update the main app's PACKAGE_CATEGORIES with all fetched packages."""
        # Generate a new PACKAGE_CATEGORIES entry with all packages
        from core import config as cfg

        reply = QMessageBox.question(
            self, "Update App Config",
            "This will add fetched packages to the app's 'All Packages' category.\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        all_pkgs = set()
        for arch_pkgs in self.all_packages.values():
            all_pkgs.update(arch_pkgs)

        # Add to config
        available = sorted(all_pkgs)

        # Show save dialog for modified config
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Extended Config", "packages_full_list.json",
            "JSON Files (*.json);;All Files (*.*)"
        )
        if not path:
            return

        with open(path, "w") as f:
            json.dump({
                "version": self.version,
                "total_packages": len(available),
                "packages": available,
            }, f, indent=2)

        QMessageBox.information(
            self, "Saved",
            f"Full package list ({len(available)} packages) saved to:\n{path}\n\n"
            "To use this in the app, add a new category to PACKAGE_CATEGORIES\n"
            "in core/config.py pointing to this file."
        )


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QMainWindow { background-color: #1e1e2e; }
        QLabel { color: #cdd6f4; font-size: 13px; }
        QPushButton {
            background-color: #45475a; color: #cdd6f4;
            border: 1px solid #585b70; border-radius: 6px;
            padding: 8px 16px; font-size: 13px; min-height: 32px;
        }
        QPushButton:hover { background-color: #585b70; border-color: #89b4fa; }
        QComboBox, QLineEdit {
            background-color: #313244; color: #cdd6f4;
            border: 1px solid #45475a; border-radius: 6px;
            padding: 8px 12px; font-size: 13px; min-height: 36px;
        }
        QTreeWidget {
            background-color: #1e1e2e; color: #cdd6f4;
            border: 1px solid #45475a; border-radius: 6px;
        }
        QTreeWidget::item { padding: 2px; border-bottom: 1px solid #313244; }
        QTreeWidget::item:hover { background-color: #313244; }
        QHeaderView::section {
            background-color: #313244; color: #cdd6f4;
            padding: 4px; border: 1px solid #45475a; font-weight: bold;
        }
        QCheckBox { color: #cdd6f4; font-size: 13px; spacing: 8px; }
        QCheckBox::indicator {
            width: 18px; height: 18px; border-radius: 4px;
            border: 2px solid #585b70; background-color: #313244;
        }
        QCheckBox::indicator:checked { background-color: #89b4fa; border-color: #89b4fa; }
        QProgressBar {
            border: 1px solid #45475a; border-radius: 6px; text-align: center;
            color: #cdd6f4; background-color: #313244; min-height: 20px;
        }
        QProgressBar::chunk { background-color: #89b4fa; border-radius: 5px; }
    """)

    window = PackageBrowserWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()