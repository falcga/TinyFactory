#!/usr/bin/env python3
"""
TinyCore MultiBoot Factory - Main Entry Point
Creates multi-boot Tiny Core Linux USB drives with package selection.
"""

import sys
import os

# Ensure the project root is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.main_window import run_app


if __name__ == "__main__":
    run_app()