#!/usr/bin/env python3
"""Build a deterministic HA-Fitness Bridge ZIP for manual/HACS validation."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "fitness_bridge"
TOP_LEVEL = (ROOT / "hacs.json", ROOT / "README.md", ROOT / "LICENSE")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def _files() -> list[Path]:
    rows = [
        path
        for path in INTEGRATION.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]
    rows.extend(path for path in TOP_LEVEL if path.is_file())
    return sorted(rows, key=lambda path: path.relative_to(ROOT).as_posix())


def build(output: Path) -> None:
    if not INTEGRATION.is_dir():
        raise SystemExit(f"Missing integration directory: {INTEGRATION}")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in _files():
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())

    print(f"Built {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "HA-Fitness-Bridge.zip")
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
