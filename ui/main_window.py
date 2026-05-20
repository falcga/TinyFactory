"""
Main GUI window for TinyCore MultiBoot Factory.
Built with PyQt6.
"""

import os
import sys
import json
import logging
import threading
from typing import Dict, List, Optional, Set
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QComboBox, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QProgressBar, QTextEdit,
    QGroupBox, QFileDialog, QMessageBox, QSplitter, QSpinBox,
    QLineEdit, QScrollArea, QFrame, QHeaderView, QStatusBar,
    QGridLayout, QToolButton, QMenu, QDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QColor, QAction

from core.config import (
    APP_NAME, APP_VERSION, ARCHES, PACKAGE_CATEGORIES,
    ARCH_UNAVAILABLE_PACKAGES, DEFAULT_GRUB_TIMEOUT,
    DEFAULT_KERNEL_PARAMS, DEFAULT_BOOT_PARTITION_SIZE_MB,
    MIN_BOOT_PARTITION_SIZE_MB, MAX_BOOT_PARTITION_SIZE_MB,
    TINY_CORE_VERSION, TINY_CORE_DEFAULT, AVAILABLE_VERSIONS,
    ARCHES_TEMPLATE, get_arches_for_version,
    Profile, get_data_dir, get_log_path, get_logs_dir,
    get_session_log_path,
)
from core.usb import USBDevice, USBDetector
from core.repo import RepoManager
from core.downloader import PackageDownloader, DownloadProgress
from core.builder import USBBuilder, BuildConfig, BuildProgress
from core.diskops import DiskOperator, DiskError

logger = logging.getLogger(__name__)

# Style constants
STYLE_SHEET = """
QMainWindow {
    background-color: #1e1e2e;
}
QLabel {
    color: #cdd6f4;
    font-size: 13px;
}
QGroupBox {
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 14px;
    padding: 20px 12px 16px 12px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #89b4fa;
}
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    min-height: 32px;
}
QPushButton:hover {
    background-color: #585b70;
    border-color: #89b4fa;
}
QPushButton:pressed {
    background-color: #313244;
}
QPushButton:disabled {
    background-color: #313244;
    color: #6c7086;
}
QPushButton#btnBuild {
    background-color: #a6e3a1;
    color: #1e1e2e;
    font-weight: bold;
    font-size: 15px;
    padding: 12px 24px;
    border: none;
}
QPushButton#btnBuild:hover {
    background-color: #89dceb;
}
QPushButton#btnBuild:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QPushButton#btnDownload {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}
QPushButton#btnDownload:hover {
    background-color: #b4befe;
}
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 36px;
}
QComboBox:hover {
    border-color: #89b4fa;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
}
QTreeWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    font-size: 13px;
}
QTreeWidget::item {
    padding: 4px;
    border-bottom: 1px solid #313244;
}
QTreeWidget::item:hover {
    background-color: #313244;
}
QTreeWidget::item:selected {
    background-color: #45475a;
}
QHeaderView::section {
    background-color: #313244;
    color: #cdd6f4;
    padding: 6px;
    border: 1px solid #45475a;
    font-weight: bold;
}
QCheckBox {
    color: #cdd6f4;
    font-size: 13px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #585b70;
    background-color: #313244;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}
QCheckBox::indicator:hover {
    border-color: #b4befe;
}
QTextEdit, QLineEdit, QSpinBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 36px;
}
QTextEdit:focus, QLineEdit:focus, QSpinBox:focus {
    border-color: #89b4fa;
}
QSpinBox::down-button, QSpinBox::up-button {
    width: 28px;
    border: none;
    background: transparent;
}
QSpinBox::down-button:hover, QSpinBox::up-button:hover {
    background-color: #45475a;
    border-radius: 4px;
}
QSpinBox::up-arrow {
    image: none;
    width: 10px;
    height: 10px;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 8px solid #cdd6f4;
    margin-top: 6px;
}
QSpinBox::down-arrow {
    image: none;
    width: 10px;
    height: 10px;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 8px solid #cdd6f4;
    margin-bottom: 6px;
}
QProgressBar {
    border: 1px solid #45475a;
    border-radius: 6px;
    text-align: center;
    color: #cdd6f4;
    font-size: 12px;
    background-color: #313244;
    min-height: 20px;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 5px;
}
QTabWidget::pane {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px;
}
QTabBar::tab {
    background-color: #313244;
    color: #6c7086;
    border: 1px solid #45475a;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #89b4fa;
    border-color: #45475a;
    border-bottom: 1px solid #1e1e2e;
}
QTabBar::tab:hover:!selected {
    color: #cdd6f4;
}
QScrollBar:vertical {
    background-color: #1e1e2e;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QStatusBar {
    background-color: #181825;
    color: #6c7086;
    font-size: 12px;
    border-top: 1px solid #45475a;
}
QStatusBar::item {
    border: none;
}
"""


class WorkerThread(QThread):
    """Base worker thread for background tasks."""
    progress_updated = pyqtSignal(object)
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True


class DownloadWorker(WorkerThread):
    """Worker thread for downloading packages."""

    def __init__(self, downloader: PackageDownloader, arch: str,
                 packages: List[str]):
        super().__init__()
        self.downloader = downloader
        self.arch = arch
        self.packages = packages
        self.progress = DownloadProgress()

    def run(self):
        try:
            self.progress.register_callback(
                lambda p: self.progress_updated.emit(p)
            )

            # Resolve dependencies
            all_packages = self.downloader.repo.resolve_dependencies(
                self.arch, self.packages
            )
            self.log_message.emit(
                f"Downloading {len(all_packages)} packages for {self.arch}..."
            )

            # Download
            results = self.downloader.download_packages(
                self.arch, all_packages, self.progress
            )

            failed = [p for p, r in results.items() if r is None]
            if failed:
                self.error_occurred.emit(
                    f"Failed to download: {', '.join(failed[:5])}"
                )

            success = len([r for r in results.values() if r is not None])
            self.log_message.emit(
                f"Downloaded {success}/{len(results)} packages for {self.arch}"
            )
            self.finished.emit(len(failed) == 0)

        except Exception as e:
            self.error_occurred.emit(f"Download error: {e}")
            self.finished.emit(False)


class BuildWorker(WorkerThread):
    """Worker thread for building the USB drive."""

    def __init__(self, builder: USBBuilder, config: BuildConfig):
        super().__init__()
        self.builder = builder
        self.config = config

    def run(self):
        try:
            self.builder.progress.register_callback(
                lambda p: self.progress_updated.emit(p)
            )

            # Run build
            result = self.builder.build(self.config)

            if result:
                self.log_message.emit("Build completed successfully!")
            else:
                errors = self.builder.progress.errors
                if errors:
                    self.error_occurred.emit(errors[-1])

            self.finished.emit(result)

        except Exception as e:
            self.error_occurred.emit(f"Build error: {e}")
            self.finished.emit(False)


class USBSelectorWidget(QWidget):
    """Widget for USB device selection."""
    device_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices: List[USBDevice] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QLabel("💽 Select USB Drive")
        header.setStyleSheet("font-size: 15px; font-weight: bold; color: #89b4fa;")
        layout.addWidget(header)

        # Warning
        warning = QLabel(
            "⚠️  All data on the selected drive will be DESTROYED!"
        )
        warning.setStyleSheet(
            "color: #f38ba8; font-weight: bold; padding: 4px; "
            "background-color: #313244; border-radius: 4px;"
        )
        layout.addWidget(warning)

        # Device selection row
        row = QHBoxLayout()

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        row.addWidget(self.device_combo, 1)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        row.addWidget(self.refresh_btn)

        layout.addLayout(row)

        # Device info
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

    def refresh_devices(self):
        """Refresh the list of USB devices."""
        self.device_combo.clear()
        self.devices = USBDetector.detect()

        if not self.devices:
            self.device_combo.addItem("No USB devices found", None)
            self.info_label.setText("")
            self.device_changed.emit(None)
            return

        for dev in self.devices:
            label = f"{dev.label} ({dev.size_str})"
            if dev.mount_points:
                label += f" - {', '.join(dev.mount_points)}"
            self.device_combo.addItem(label, dev)

        self._on_device_changed(0)

    def _on_device_changed(self, index: int):
        """Handle device selection change."""
        if index < 0 or index >= self.device_combo.count():
            self.device_changed.emit(None)
            return

        device = self.device_combo.itemData(index)
        if device:
            info = (
                f"Device: {device.device}\n"
                f"Model: {device.model}\n"
                f"Size: {device.size_str}"
            )
            if device.mount_points:
                info += f"\nMount Points: {', '.join(device.mount_points)}"
            self.info_label.setText(info)
            self.device_changed.emit(device)
        else:
            self.info_label.setText("")
            self.device_changed.emit(None)

    def get_selected_device(self) -> Optional[USBDevice]:
        """Get the currently selected USB device."""
        index = self.device_combo.currentIndex()
        if index >= 0:
            return self.device_combo.itemData(index)
        return None


class PackageTreeWidget(QWidget):
    """Widget displaying packages for a specific architecture."""
    selection_changed = pyqtSignal(str, list)  # arch, selected_packages

    def __init__(self, arch: str, parent=None):
        super().__init__(parent)
        self.arch = arch
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Architecture label
        arch_names = {
            "x86": "x86 (32-bit)",
            "x86_64": "x86_64 (64-bit)",
            "aarch64": "ARM (64-bit)",
        }
        label = QLabel(f"📦 {arch_names.get(self.arch, self.arch)}")
        label.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #cba6f7; padding: 4px 0;"
        )
        layout.addWidget(label)

        # Package tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Package", "Status", "Size", "Info"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 60)
        self.tree.setColumnWidth(2, 60)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(20)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        # Select/Deselect all
        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(deselect_all_btn)

        layout.addLayout(btn_row)

    def populate(self, unavailable: Optional[List[str]] = None):
        """Populate the tree with package categories."""
        self.tree.clear()

        if unavailable is None:
            unavailable = ARCH_UNAVAILABLE_PACKAGES.get(self.arch, [])

        for category, info in PACKAGE_CATEGORIES.items():
            # Create category item
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, f"{info['icon']} {category}")
            cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            cat_item.setExpanded(False)

            # Category font
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)

            for pkg in info["packages"]:
                pkg_item = QTreeWidgetItem(cat_item)
                pkg_item.setText(0, pkg)
                pkg_item.setFlags(
                    pkg_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )

                # Check if unavailable
                if pkg in unavailable:
                    pkg_item.setCheckState(0, Qt.CheckState.Unchecked)
                    pkg_item.setText(1, "❌")
                    pkg_item.setText(3, "Not available")
                    pkg_item.setForeground(1, QColor("#f38ba8"))
                    pkg_item.setFlags(
                        pkg_item.flags() & ~Qt.ItemFlag.ItemIsEnabled
                    )
                else:
                    pkg_item.setCheckState(0, Qt.CheckState.Unchecked)
                    pkg_item.setText(1, "📦")

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handle item check state change."""
        if column == 0:
            # Emit selection change after short delay
            QTimer.singleShot(50, self._emit_selection)

    def _emit_selection(self):
        """Emit the current selection."""
        selected = self.get_selected_packages()
        self.selection_changed.emit(self.arch, selected)

    def get_selected_packages(self) -> List[str]:
        """Get list of selected package names."""
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            for j in range(cat.childCount()):
                item = cat.child(j)
                if item.checkState(0) == Qt.CheckState.Checked:
                    selected.append(item.text(0))
        return selected

    def set_selected_packages(self, packages: List[str]):
        """Set the selected packages."""
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            for j in range(cat.childCount()):
                item = cat.child(j)
                if item.text(0) in packages:
                    item.setCheckState(0, Qt.CheckState.Checked)

    def _select_all(self):
        """Select all available packages."""
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            for j in range(cat.childCount()):
                item = cat.child(j)
                if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                    item.setCheckState(0, Qt.CheckState.Checked)
        self._emit_selection()

    def _deselect_all(self):
        """Deselect all packages."""
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            for j in range(cat.childCount()):
                item = cat.child(j)
                item.setCheckState(0, Qt.CheckState.Unchecked)
        self._emit_selection()


class AdvancedSettingsWidget(QWidget):
    """Widget for advanced settings — simple two-column form, no sections."""
    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        grid = QGridLayout(self)
        grid.setVerticalSpacing(12)
        grid.setHorizontalSpacing(16)
        grid.setContentsMargins(8, 8, 8, 8)

        # ── Partition size ──
        grid.addWidget(QLabel("💾 Boot partition size:"), 0, 0)
        part_row = QHBoxLayout()
        self.partition_size_spin = QSpinBox()
        self.partition_size_spin.setRange(MIN_BOOT_PARTITION_SIZE_MB, MAX_BOOT_PARTITION_SIZE_MB)
        self.partition_size_spin.setValue(DEFAULT_BOOT_PARTITION_SIZE_MB)
        self.partition_size_spin.setSingleStep(50)
        self.partition_size_spin.setSuffix(" MB")
        self.partition_size_spin.valueChanged.connect(self._on_change)
        self.partition_size_spin.valueChanged.connect(self._update_size_note)
        part_row.addWidget(self.partition_size_spin)
        self.size_note = QLabel(self._make_size_note_text(DEFAULT_BOOT_PARTITION_SIZE_MB))
        self.size_note.setStyleSheet("color: #a6adc8; font-size: 11px;")
        part_row.addWidget(self.size_note, 1)
        grid.addLayout(part_row, 0, 1)

        # ── GRUB timeout ──
        grid.addWidget(QLabel("🔧 GRUB timeout (sec):"), 1, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, 120)
        self.timeout_spin.setValue(DEFAULT_GRUB_TIMEOUT)
        self.timeout_spin.valueChanged.connect(self._on_change)
        grid.addWidget(self.timeout_spin, 1, 1)

        # ── Kernel params ──
        grid.addWidget(QLabel("🔧 Kernel parameters:"), 2, 0)
        self.kernel_params = QLineEdit(DEFAULT_KERNEL_PARAMS)
        self.kernel_params.textChanged.connect(self._on_change)
        grid.addWidget(self.kernel_params, 2, 1)

        # ── Boot mode ──
        grid.addWidget(QLabel("💿 Boot mode:"), 3, 0)
        boot_row = QHBoxLayout()
        self.direct_boot_cb = QCheckBox("Direct kernel/initrd boot (recommended)")
        self.direct_boot_cb.setChecked(True)
        self.direct_boot_cb.toggled.connect(self._on_change)
        boot_row.addWidget(self.direct_boot_cb)
        self.iso_boot_cb = QCheckBox("Boot from ISO")
        self.iso_boot_cb.toggled.connect(self._on_change)
        boot_row.addWidget(self.iso_boot_cb)
        boot_row.addStretch()
        grid.addLayout(boot_row, 3, 1)

        # ── Custom TCZ ──
        grid.addWidget(QLabel("📁 Custom packages:"), 4, 0)
        tcz_row = QHBoxLayout()
        self.custom_tcz_list = QTextEdit()
        self.custom_tcz_list.setPlaceholderText(
            "Drag & drop or type paths to custom .tcz files\nOne per line"
        )
        self.custom_tcz_list.setMaximumHeight(64)
        self.custom_tcz_list.textChanged.connect(self._on_change)
        tcz_row.addWidget(self.custom_tcz_list, 1)
        browse_btn = QPushButton("Browse .tcz")
        browse_btn.clicked.connect(self._browse_tcz)
        tcz_row.addWidget(browse_btn)
        grid.addLayout(tcz_row, 4, 1)

        # ── Profile Management (buttons at the bottom, full width) ──
        grid.addWidget(QLabel("💾 Profile:"), 5, 0)
        profile_row = QHBoxLayout()
        save_profile_btn = QPushButton("Save Profile")
        save_profile_btn.clicked.connect(self._save_profile)
        profile_row.addWidget(save_profile_btn)
        load_profile_btn = QPushButton("Load Profile")
        load_profile_btn.clicked.connect(self._load_profile)
        profile_row.addWidget(load_profile_btn)
        profile_row.addStretch()
        grid.addLayout(profile_row, 5, 1)

        # Push everything to the top
        grid.setRowStretch(6, 1)
        # Make column 1 stretch
        grid.setColumnStretch(1, 1)
        # Uniform label width
        grid.setColumnMinimumWidth(0, 180)

    def _make_size_note_text(self, mb: int) -> str:
        """Generate a human-readable note about partition size."""
        gb = mb / 1024
        if gb >= 1.0:
            return f"≈ {gb:.1f} GB. Range: {MIN_BOOT_PARTITION_SIZE_MB}–{MAX_BOOT_PARTITION_SIZE_MB} MB"
        return f"Range: {MIN_BOOT_PARTITION_SIZE_MB}–{MAX_BOOT_PARTITION_SIZE_MB} MB"

    def _update_size_note(self, value: int):
        self.size_note.setText(self._make_size_note_text(value))

    def _on_change(self):
        """Emit settings changed signal."""
        settings = self.get_settings()
        self.settings_changed.emit(settings)

    def _browse_tcz(self):
        """Browse for .tcz files."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select .tcz files", "", "TCZ Packages (*.tcz);;All Files (*.*)"
        )
        if files:
            current = self.custom_tcz_list.toPlainText().strip()
            new_paths = "\n".join(files)
            if current:
                self.custom_tcz_list.setText(current + "\n" + new_paths)
            else:
                self.custom_tcz_list.setText(new_paths)

    def _save_profile(self):
        """Save current settings as profile."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "", "JSON Files (*.json);;All Files (*.*)"
        )
        if path:
            profile = Profile()
            profile.grub_timeout = self.timeout_spin.value()
            profile.kernel_params = self.kernel_params.text()
            profile.boot_mode = "iso" if self.iso_boot_cb.isChecked() else "direct"
            profile.boot_partition_size_mb = self.partition_size_spin.value()
            profile.add_custom_tcz = [
                p.strip() for p in self.custom_tcz_list.toPlainText().split("\n")
                if p.strip()
            ]
            profile.save(path)
            QMessageBox.information(self, "Profile Saved", f"Profile saved to:\n{path}")

    def _load_profile(self):
        """Load settings from profile."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "JSON Files (*.json);;All Files (*.*)"
        )
        if path:
            try:
                profile = Profile.load(path)
                self.timeout_spin.setValue(profile.grub_timeout)
                self.kernel_params.setText(profile.kernel_params)
                self.iso_boot_cb.setChecked(profile.boot_mode == "iso")
                self.direct_boot_cb.setChecked(profile.boot_mode != "iso")
                self.partition_size_spin.setValue(
                    getattr(profile, 'boot_partition_size_mb', DEFAULT_BOOT_PARTITION_SIZE_MB)
                )
                self.custom_tcz_list.setText("\n".join(profile.add_custom_tcz))
                QMessageBox.information(
                    self, "Profile Loaded", "Settings loaded from profile."
                )
                self._on_change()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load profile: {e}")

    def get_settings(self) -> dict:
        """Get current settings as dict."""
        return {
            "grub_timeout": self.timeout_spin.value(),
            "kernel_params": self.kernel_params.text(),
            "boot_mode": "iso" if self.iso_boot_cb.isChecked() else "direct",
            "custom_tcz": [
                p.strip() for p in self.custom_tcz_list.toPlainText().split("\n")
                if p.strip()
            ],
            "boot_partition_size_mb": self.partition_size_spin.value(),
        }


class LogWidget(QTextEdit):
    """Widget for displaying build logs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 10))
        self.setStyleSheet("""
            QTextEdit {
                background-color: #11111b;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
        """)

    def append_log(self, message: str, level: str = "INFO"):
        """Append a log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = {
            "INFO": "#cdd6f4",
            "WARNING": "#f9e2af",
            "ERROR": "#f38ba8",
            "SUCCESS": "#a6e3a1",
            "STEP": "#89b4fa",
        }.get(level, "#cdd6f4")

        prefix = {
            "INFO": "  ",
            "WARNING": "⚠ ",
            "ERROR": "✗ ",
            "SUCCESS": "✓ ",
            "STEP": "▸ ",
        }.get(level, "  ")

        html = (
            f'<span style="color: #6c7086;">[{timestamp}]</span> '
            f'<span style="color: {color};">{prefix}{message}</span><br>'
        )
        self.insertHtml(html)
        # Auto-scroll to bottom
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        # Core components
        self.repo_manager = RepoManager()
        self.downloader = PackageDownloader(self.repo_manager)
        self.builder = USBBuilder(self.repo_manager)

        # State
        self.selected_device: Optional[USBDevice] = None
        self.selected_packages: Dict[str, List[str]] = {
            "x86": [],
            "x86_64": [],
            "aarch64": [],
        }
        self.build_settings = {
            "grub_timeout": DEFAULT_GRUB_TIMEOUT,
            "kernel_params": DEFAULT_KERNEL_PARAMS,
            "boot_mode": "direct",
            "custom_tcz": [],
            "boot_partition_size_mb": DEFAULT_BOOT_PARTITION_SIZE_MB,
        }
        self.current_worker: Optional[WorkerThread] = None

        # Setup UI
        self._setup_ui()
        self._setup_menu()
        self._apply_styles()

        # Populate package trees
        for arch, tree in self.pkg_trees.items():
            tree.populate()

        # Initialize
        self._refresh_devices()

    def _setup_menu(self):
        """Setup menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction("&Save Profile", self._save_profile)
        file_menu.addAction("&Load Profile", self._load_profile)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction("&Refresh USB Devices",
                           lambda: self.usb_selector.refresh_devices())
        tools_menu.addAction("&Clear Package Cache", self._clear_cache)
        tools_menu.addSeparator()
        tools_menu.addAction("&Open Log File", self._open_log)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("&About", self._show_about)

    def _setup_ui(self):
        """Setup the main UI."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QLabel(f"🖥️  {APP_NAME} v{APP_VERSION}")
        header.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #cba6f7; padding: 8px 0;"
        )
        main_layout.addWidget(header)

        # USB Selector
        self.usb_selector = USBSelectorWidget()
        self.usb_selector.device_changed.connect(self._on_device_changed)
        main_layout.addWidget(self.usb_selector)

        # Main content: tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        # Tab 1: Packages
        packages_tab = QWidget()
        packages_layout = QVBoxLayout(packages_tab)

        # Version tabs
        version_bar = QHBoxLayout()
        version_bar.addWidget(QLabel("Tiny Core Version:"))
        self.version_combo = QComboBox()
        for v in AVAILABLE_VERSIONS:
            self.version_combo.addItem(f"v{v.rstrip('.x')}", v)
        self.version_combo.setCurrentText(f"v{TINY_CORE_VERSION.rstrip('.x')}")
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)
        version_bar.addWidget(self.version_combo)

        self.add_version_btn = QPushButton("+ Add Version")
        self.add_version_btn.clicked.connect(self._add_version_tab)
        version_bar.addWidget(self.add_version_btn)

        self.remove_version_btn = QPushButton("− Remove")
        self.remove_version_btn.clicked.connect(self._remove_version_tab)
        version_bar.addWidget(self.remove_version_btn)

        version_bar.addStretch()
        packages_layout.addLayout(version_bar)

        # Version tab widget
        self.version_tabs = QTabWidget()
        packages_layout.addWidget(self.version_tabs, 1)

        # Create default version tab
        self.version_configs: Dict[str, dict] = {}
        self._create_version_tab(TINY_CORE_VERSION)

        # Sync checkbox
        sync_row = QHBoxLayout()
        self.sync_cb = QCheckBox("🔗 Sync selections across all architectures (same packages for x86, x86_64, aarch64)")
        self.sync_cb.toggled.connect(self._on_sync_toggled)
        sync_row.addWidget(self.sync_cb)
        sync_row.addStretch()
        packages_layout.addLayout(sync_row)

        # Download button row
        download_row = QHBoxLayout()
        download_row.addStretch()

        self.download_btn = QPushButton("⬇️  Download Selected Packages")
        self.download_btn.setObjectName("btnDownload")
        self.download_btn.clicked.connect(self._download_packages)
        self.download_btn.setEnabled(False)
        download_row.addWidget(self.download_btn)

        packages_layout.addLayout(download_row)

        self.tabs.addTab(packages_tab, "📦 Packages")

        # Tab 2: Advanced
        self.advanced_settings = AdvancedSettingsWidget()
        self.advanced_settings.settings_changed.connect(self._on_settings_changed)
        self.tabs.addTab(self.advanced_settings, "⚙️ Advanced")

        # Tab 3: Log
        self.log_widget = LogWidget()
        self.tabs.addTab(self.log_widget, "📋 Log")

        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        # Download progress
        self.dl_progress_bar = QProgressBar()
        self.dl_progress_bar.setVisible(False)
        progress_layout.addWidget(self.dl_progress_bar)

        # Build progress
        self.build_progress_bar = QProgressBar()
        self.build_progress_bar.setVisible(False)
        progress_layout.addWidget(self.build_progress_bar)

        # Status label
        self.status_progress = QLabel("")
        self.status_progress.setStyleSheet("color: #a6adc8; font-size: 12px;")
        progress_layout.addWidget(self.status_progress)

        main_layout.addWidget(progress_group)

        # Build button
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.build_btn = QPushButton("🚀  Build USB Drive")
        self.build_btn.setObjectName("btnBuild")
        self.build_btn.clicked.connect(self._start_build)
        self.build_btn.setEnabled(False)
        btn_row.addWidget(self.build_btn)

        self.cancel_btn = QPushButton("✋ Cancel")
        self.cancel_btn.clicked.connect(self._cancel_operation)
        self.cancel_btn.setVisible(False)
        btn_row.addWidget(self.cancel_btn)

        main_layout.addLayout(btn_row)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _apply_styles(self):
        """Apply the stylesheet."""
        self.setStyleSheet(STYLE_SHEET)

    # ──────────────────────────────────────────────
    # Event handlers
    # ──────────────────────────────────────────────

    def _on_device_changed(self, device: Optional[USBDevice]):
        """Handle USB device selection change."""
        self.selected_device = device
        self._update_build_button()

    def _on_package_selection(self, arch: str, packages: List[str]):
        """Handle package selection change for an architecture."""
        self.selected_packages[arch] = packages
        self._update_build_button()

        # Enable download button if any packages selected
        has_packages = any(pkgs for pkgs in self.selected_packages.values())
        self.download_btn.setEnabled(has_packages)

    def _on_settings_changed(self, settings: dict):
        """Handle advanced settings change."""
        self.build_settings.update(settings)

    def _update_build_button(self):
        """Update the build button state."""
        has_device = self.selected_device is not None
        has_packages = any(pkgs for pkgs in self.selected_packages.values())
        self.build_btn.setEnabled(has_device and has_packages)

    # ──────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────

    def _on_version_changed(self, idx: int):
        """Handle version combo box change - switch active version tab."""
        version = self.version_combo.itemData(idx)
        if version and version in self.version_configs:
            # Show existing tab
            for i in range(self.version_tabs.count()):
                if self.version_tabs.tabText(i) == f"v{version.rstrip('.x')}":
                    self.version_tabs.setCurrentIndex(i)
                    break

    def _create_version_tab(self, version: str):
        """Create a version tab with package trees for all architectures."""
        if version in self.version_configs:
            return

        arches = get_arches_for_version(version)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        pkg_trees = {}
        for arch in ["x86", "x86_64", "aarch64"]:
            tree = PackageTreeWidget(arch)
            tree.selection_changed.connect(self._on_package_selection)
            tree.populate()
            splitter.addWidget(tree)
            pkg_trees[arch] = tree

        layout.addWidget(splitter, 1)
        self.version_configs[version] = pkg_trees
        display = f"v{version.rstrip('.x')}"
        self.version_tabs.addTab(tab, display)

        # If first version, set it as current
        if self.version_tabs.count() == 1:
            self.version_tabs.setCurrentIndex(0)

    def _add_version_tab(self):
        """Add a new version tab from the combo selection."""
        idx = self.version_combo.currentIndex()
        version = self.version_combo.itemData(idx)
        if not version:
            return

        if version in self.version_configs:
            QMessageBox.information(self, "Already Open",
                f"Tab for Tiny Core {version} is already open.")
            return

        self._create_version_tab(version)

    def _remove_version_tab(self):
        """Remove the current version tab."""
        idx = self.version_tabs.currentIndex()
        if idx < 0 or self.version_tabs.count() <= 1:
            QMessageBox.information(self, "Cannot Remove",
                "At least one version tab must remain.")
            return

        # Find the version for this tab
        tab_text = self.version_tabs.tabText(idx)
        version_to_remove = None
        for ver, config in self.version_configs.items():
            if f"v{ver.rstrip('.x')}" == tab_text:
                version_to_remove = ver
                break

        if version_to_remove:
            del self.version_configs[version_to_remove]
        self.version_tabs.removeTab(idx)

    def _on_sync_toggled(self, checked: bool):
        """Sync or unsync selections across architectures."""
        if not checked:
            return

        # Get all packages from the current active tree
        current_idx = self.version_tabs.currentIndex()
        if current_idx < 0:
            return

        tab_text = self.version_tabs.tabText(current_idx)
        current_ver = None
        for ver in self.version_configs:
            if f"v{ver.rstrip('.x')}" == tab_text:
                current_ver = ver
                break

        if not current_ver:
            return

        trees = self.version_configs[current_ver]
        # Get union of all selected packages
        all_selected = set()
        for arch, tree in trees.items():
            all_selected.update(tree.get_selected_packages())

        # Apply to all trees
        for arch, tree in trees.items():
            tree.set_selected_packages(list(all_selected))

    def _refresh_devices(self):
        """Refresh USB device list."""
        self.usb_selector.refresh_devices()
        self.log_widget.append_log("USB devices refreshed", "INFO")

    def _download_packages(self):
        """Download selected packages."""
        # Check which architectures have packages
        arches_with_pkgs = {
            arch: pkgs for arch, pkgs in self.selected_packages.items()
            if pkgs
        }

        if not arches_with_pkgs:
            QMessageBox.warning(self, "No Packages", "No packages selected.")
            return

        # Check for unavailable packages
        unavailable_msg = ""
        for arch, pkgs in arches_with_pkgs.items():
            unavailable = self.repo_manager.get_unavailable_packages(arch, pkgs)
            if unavailable:
                unavailable_msg += (
                    f"\n{arch}: {', '.join(unavailable)}"
                )

        if unavailable_msg:
            reply = QMessageBox.question(
                self, "Unavailable Packages",
                f"The following packages are not available:{unavailable_msg}\n\n"
                "Continue with available packages only?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Show progress
        self.dl_progress_bar.setVisible(True)
        self.dl_progress_bar.setValue(0)
        self.download_btn.setEnabled(False)
        self.status_progress.setText("Downloading packages...")

        # Start download thread for each architecture sequentially
        self._download_for_arches(list(arches_with_pkgs.keys()), 0)

    def _download_for_arches(self, arches: List[str], index: int):
        """Download packages for architectures sequentially."""
        if index >= len(arches):
            self.dl_progress_bar.setVisible(False)
            self.download_btn.setEnabled(True)
            self.status_progress.setText("Download complete!")
            self.log_widget.append_log("All packages downloaded successfully", "SUCCESS")
            return

        arch = arches[index]
        pkgs = self.selected_packages[arch]

        self.log_widget.append_log(f"Downloading packages for {arch}...", "STEP")
        self.dl_progress_bar.setValue(0)

        # Fetch manifest first
        try:
            manifest = self.repo_manager.fetch_manifest(arch)
            self.log_widget.append_log(
                f"Loaded manifest for {arch}: {len(manifest)} packages available",
                "INFO"
            )
        except Exception as e:
            self.log_widget.append_log(f"Failed to fetch manifest for {arch}: {e}", "ERROR")
            self._download_for_arches(arches, index + 1)
            return

        # Start worker thread
        self.current_worker = DownloadWorker(self.downloader, arch, pkgs)
        self.current_worker.progress_updated.connect(
            lambda p: self.dl_progress_bar.setValue(int(p.percent))
        )
        self.current_worker.log_message.connect(
            lambda m: self.log_widget.append_log(m, "INFO")
        )
        self.current_worker.error_occurred.connect(
            lambda e: self.log_widget.append_log(e, "ERROR")
        )

        def on_finished(success: bool):
            self.status_progress.setText(
                f"Downloaded packages for {arch}: {'✓' if success else '✗'}"
            )
            self._download_for_arches(arches, index + 1)

        self.current_worker.finished.connect(on_finished)
        self.current_worker.start()

    def _start_build(self):
        """Start the USB build process."""
        if not self.selected_device:
            QMessageBox.warning(self, "No Device", "Please select a USB device.")
            return

        if not any(self.selected_packages.values()):
            QMessageBox.warning(
                self, "No Packages",
                "Please select at least one package."
            )
            return

        # Confirmation dialog
        device = self.selected_device
        reply = QMessageBox.warning(
            self, "⚠️ DESTRUCTIVE OPERATION",
            f"This will ERASE ALL DATA on:\n\n"
            f"  {device.label}\n"
            f"  Device: {device.device}\n"
            f"  Size: {device.size_str}\n\n"
            f"The drive will be partitioned into:\n"
            f"  - 500 MB FAT32 (boot partition)\n"
            f"  - Rest as exFAT (data partition)\n\n"
            f"Packages selected:\n"
            f"  x86: {len(self.selected_packages['x86'])} packages\n"
            f"  x86_64: {len(self.selected_packages['x86_64'])} packages\n"
            f"  aarch64: {len(self.selected_packages['aarch64'])} packages\n\n"
            f"Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Build config
        config = BuildConfig(
            device=self.selected_device,
            selected_packages=self.selected_packages,
            **self.build_settings,
        )

        # Setup UI for build
        self.build_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.build_progress_bar.setVisible(True)
        self.build_progress_bar.setValue(0)
        self.tabs.setCurrentIndex(2)  # Switch to log tab

        self.log_widget.append_log("=" * 60, "INFO")
        self.log_widget.append_log("BUILD STARTED", "STEP")
        self.log_widget.append_log(f"Device: {device.label}", "INFO")
        self.log_widget.append_log(f"Packages: {sum(len(v) for v in self.selected_packages.values())} total", "INFO")
        self.log_widget.append_log("=" * 60, "INFO")

        # Start build worker
        self.current_worker = BuildWorker(self.builder, config)

        def on_progress(progress: BuildProgress):
            self.build_progress_bar.setValue(int(progress.percent))
            if progress.current_step:
                self.status_progress.setText(progress.current_step)
            if progress.current_substep:
                self.status_bar.showMessage(progress.current_substep)
            # Log new steps
            for log in progress.log[-1:]:
                pass  # Already logged via builder

        def on_log(msg: str):
            self.log_widget.append_log(msg, "INFO")

        def on_error(err: str):
            self.log_widget.append_log(err, "ERROR")

        def on_finished(success: bool):
            self.build_btn.setEnabled(True)
            self.cancel_btn.setVisible(False)
            self.build_progress_bar.setVisible(False)
            self.status_progress.setText("")

            if success:
                self.log_widget.append_log("=" * 60, "INFO")
                self.log_widget.append_log("✅ BUILD COMPLETED SUCCESSFULLY!", "SUCCESS")
                self.log_widget.append_log("=" * 60, "INFO")
                self.status_bar.showMessage("Build completed successfully!")
                QMessageBox.information(
                    self, "Build Complete",
                    "USB drive has been created successfully!\n\n"
                    "You can now safely remove the drive and boot from it."
                )
            else:
                self.log_widget.append_log("=" * 60, "ERROR")
                self.log_widget.append_log("❌ BUILD FAILED", "ERROR")
                self.log_widget.append_log("=" * 60, "ERROR")
                self.status_bar.showMessage("Build failed - check log for details")
                QMessageBox.critical(
                    self, "Build Failed",
                    "USB drive creation failed.\n\n"
                    "Check the log tab for details."
                )

        self.current_worker.progress_updated.connect(on_progress)
        self.current_worker.log_message.connect(on_log)
        self.current_worker.error_occurred.connect(on_error)
        self.current_worker.finished.connect(on_finished)
        self.current_worker.start()

    def _cancel_operation(self):
        """Cancel the current operation."""
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.cancel()
            # Can't easily terminate threads in Python, but we can signal
            self.log_widget.append_log("Operation cancelled by user", "WARNING")

    def _clear_cache(self):
        """Clear the package cache."""
        reply = QMessageBox.question(
            self, "Clear Cache",
            "This will remove all downloaded packages and 404 cache.\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            from core.config import get_cache_dir
            cache_dir = get_cache_dir()
            if os.path.exists(cache_dir):
                for item in os.listdir(cache_dir):
                    path = os.path.join(cache_dir, item)
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
            self.log_widget.append_log("Package cache cleared", "INFO")
            QMessageBox.information(self, "Cache Cleared", "Package cache has been cleared.")

    def _open_log(self):
        """Open the log file in the default editor."""
        log_path = get_log_path()
        if os.path.exists(log_path):
            os.startfile(log_path) if sys.platform == "win32" else \
                os.system(f"open {log_path}" if sys.platform == "darwin" else
                         f"xdg-open {log_path}")

    def _save_profile(self):
        """Save current configuration as profile."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "", "JSON Files (*.json);;All Files (*.*)"
        )
        if path:
            try:
                profile = Profile(
                    selected_usb=self.selected_device.device if self.selected_device else "",
                    selected_packages=self.selected_packages,
                    **self.build_settings,
                )
                profile.save(path)
                QMessageBox.information(self, "Profile Saved", f"Profile saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save profile: {e}")

    def _load_profile(self):
        """Load configuration from profile."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "JSON Files (*.json);;All Files (*.*)"
        )
        if path:
            try:
                profile = Profile.load(path)
                self.selected_packages = profile.selected_packages
                for arch, pkgs in profile.selected_packages.items():
                    if arch in self.pkg_trees:
                        self.pkg_trees[arch].set_selected_packages(pkgs)

                self.advanced_settings.timeout_spin.setValue(profile.grub_timeout)
                self.advanced_settings.kernel_params.setText(profile.kernel_params)
                self.advanced_settings.iso_boot_cb.setChecked(profile.boot_mode == "iso")
                self.advanced_settings.direct_boot_cb.setChecked(profile.boot_mode != "iso")
                self.advanced_settings.custom_tcz_list.setText(
                    "\n".join(profile.add_custom_tcz)
                )

                # Try to select the USB device
                if profile.selected_usb:
                    for i in range(self.usb_selector.device_combo.count()):
                        data = self.usb_selector.device_combo.itemData(i)
                        if data and data.device == profile.selected_usb:
                            self.usb_selector.device_combo.setCurrentIndex(i)
                            break

                self.log_widget.append_log(f"Profile loaded from {path}", "INFO")
                QMessageBox.information(self, "Profile Loaded", "Profile loaded successfully.")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load profile: {e}")

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h2>{APP_NAME}</h2>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>A tool for creating multi-boot Tiny Core Linux USB drives.</p>"
            f"<p>Supports x86, x86_64, and aarch64 architectures.</p>"
            f"<p>Built with Python, PyQt6, and ❤️</p>"
        )

    def closeEvent(self, event):
        """Handle window close event."""
        if self.current_worker and self.current_worker.isRunning():
            reply = QMessageBox.question(
                self, "Confirm Exit",
                "A build is in progress. Are you sure you want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()


def run_app():
    """Run the application."""
    # Setup logging - local logs dir + app data dir
    log_path = get_log_path()
    session_log_path = get_session_log_path()

    # Ensure logs directory exists
    logs_dir = get_logs_dir()
    os.makedirs(logs_dir, exist_ok=True)

    handlers = [
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.FileHandler(session_log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    logger.info(f"Session log: {session_log_path}")
    logger.info(f"App data log: {log_path}")
    logger.info(f"Local logs dir: {logs_dir}")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    # Set app icon (if available)
    icon_path = os.path.join(os.path.dirname(__file__), "..", "resources", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())