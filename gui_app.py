#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""向后兼容的 GUI 入口。"""

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bibliometrics.presentation.gui import main


if __name__ == "__main__":
    raise SystemExit(main())
