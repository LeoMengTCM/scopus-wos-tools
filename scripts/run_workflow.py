#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI runner for the bibliometric workflow."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bibliometrics.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
