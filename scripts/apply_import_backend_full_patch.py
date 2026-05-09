#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

p = Path("app/main.py")
s = p.read_text(encoding="utf-8")
if "from app.api.import_data import router as import_router" not in s:
    lines = s.splitlines()
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from app.api."):
            insert_at = i + 1
    lines.insert(insert_at, "from app.api.import_data import router as import_router")
    s = "\n".join(lines) + "\n"
if "app.include_router(import_router)" not in s:
    lines = s.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if "app.include_router" in line:
            idx = i
    if idx is None:
        lines.append("app.include_router(import_router)")
    else:
        lines.insert(idx + 1, "app.include_router(import_router)")
    s = "\n".join(lines) + "\n"
p.write_text(s, encoding="utf-8")
print("OK: registered import_router in app/main.py")
