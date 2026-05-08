#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

root = Path(__file__).resolve().parents[1]
main = root / "app" / "main.py"
text = main.read_text(encoding="utf-8")
if "from app.api.strategy2568 import router as strategy2568_router" not in text:
    text = text.replace(
        "from app.api.strategy2560 import router as strategy_router",
        "from app.api.strategy2560 import router as strategy_router\nfrom app.api.strategy2568 import router as strategy2568_router",
    )
if "app.include_router(strategy2568_router)" not in text:
    text = text.replace(
        "app.include_router(strategy_router)",
        "app.include_router(strategy_router)\napp.include_router(strategy2568_router)",
    )
main.write_text(text, encoding="utf-8")
print("OK: strategy2568 router registered")
