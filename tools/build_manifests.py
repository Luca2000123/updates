from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hublib import HubError, build_site, dump_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera il sito dei manifest da apps/*.toml e releases/**."
    )
    parser.add_argument("--root", default=".", help="radice del repo hub")
    parser.add_argument("--out", default="site", help="directory di output")
    parser.add_argument("--strict", action="store_true",
                        help="tratta gli avvisi come errori")
    parser.add_argument("--check", action="store_true",
                        help="valida senza scrivere nulla")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    try:
        files, warnings, notes = build_site(root)
    except HubError as err:
        print(f"errore: {err}", file=sys.stderr)
        return 1

    for note in notes:
        print(f"nota: {note}", file=sys.stderr)
    for warning in warnings:
        print(f"avviso: {warning}", file=sys.stderr)
    if warnings and args.strict:
        print(f"errore: {len(warnings)} avvisi con --strict", file=sys.stderr)
        return 1

    if args.check:
        print(f"ok: {len(files)} file generabili")
        return 0

    out = Path(args.out) if Path(args.out).is_absolute() else root / args.out
    if out.exists():
        shutil.rmtree(out)
    for rel, obj in sorted(files.items()):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_json(obj), encoding="utf-8")

    (out / ".nojekyll").write_text("", encoding="utf-8")

    static_dir = root / "static"
    if static_dir.is_dir():
        for item in sorted(static_dir.iterdir()):
            if item.is_file():
                shutil.copyfile(item, out / item.name)

    schema_src = root / "schema" / "manifest-v1.json"
    if schema_src.is_file():
        schema_dst = out / "schema" / "manifest-v1.json"
        schema_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(schema_src, schema_dst)

    for rel in sorted(files):
        print(f"scritto {rel}")
    print(f"ok: {len(files)} file in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
