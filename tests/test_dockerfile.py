"""Every local module the server imports is copied into the image.   python3 -m pytest -q tests/test_dockerfile.py

A module missing from the Dockerfile is not an error at start-up: sentinel.py
imports its optional parts inside try/except, so the feature silently goes
missing on the server (this happened to contract_book.py on 8 Oct 2026)."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def copied() -> set[str]:
    out = set()
    for line in open(os.path.join(ROOT, "Dockerfile")):
        if line.startswith("COPY "):
            out.update(p for p in line.split()[1:-1] if p.endswith(".py"))
    return out


def local_imports(fname: str) -> set[str]:
    src = open(os.path.join(ROOT, fname)).read()
    mods = set(re.findall(r"^\s*import ([a-zA-Z_][\w]*)", src, re.M)) | set(re.findall(r"^\s*from ([a-zA-Z_][\w]*) import", src, re.M))
    return {m + ".py" for m in mods if os.path.exists(os.path.join(ROOT, m + ".py"))}


def test_every_imported_local_module_is_in_the_image():
    have = copied()
    todo, seen = sorted(have), set()
    while todo:
        f = todo.pop()
        if f in seen or not os.path.exists(os.path.join(ROOT, f)):
            continue
        seen.add(f)
        todo += sorted(local_imports(f))
    missing = sorted(seen - have)
    assert not missing, f"imported by the server but not copied in the Dockerfile: {missing}"
    assert "contract_book.py" in have and "paper_monitor.py" in have and "joel_twin.py" in have
