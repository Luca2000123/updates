from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida i manifest generati contro schema/manifest-v1.json."
    )
    parser.add_argument("--root", default=".", help="radice del repo hub")
    parser.add_argument("--site", default="site", help="directory generata")
    args = parser.parse_args()

    try:
        import jsonschema
    except ImportError:
        print("errore: serve jsonschema (pip install jsonschema)", file=sys.stderr)
        return 1

    root = Path(args.root).resolve()
    site = Path(args.site)
    site = site if site.is_absolute() else root / site
    schema = json.loads((root / "schema" / "manifest-v1.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    checked = 0
    failed = 0
    for path in sorted(site.glob("v1/apps/*/*.json")):
        if path.parent.name == "webos":
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        rel = path.relative_to(site).as_posix()
        errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
        if errors:
            failed += 1
            for err in errors:
                where = "/".join(str(x) for x in err.path) or "(radice)"
                print(f"errore: {rel}: {where}: {err.message}", file=sys.stderr)
        checked += 1

    if checked == 0:
        index = site / "v1" / "index.json"
        if not index.is_file():
            print(f"errore: manca {index.name}, il sito non e' stato generato", file=sys.stderr)
            return 1
        apps = json.loads(index.read_text(encoding="utf-8")).get("apps")
        if apps:
            print("errore: il catalogo elenca app ma non c'e' nessun manifest", file=sys.stderr)
            return 1
        print("nota: catalogo vuoto, nessuna release ancora pubblicata")
        return 0
    if failed:
        print(f"errore: {failed} manifest su {checked} non validi", file=sys.stderr)
        return 1
    print(f"ok: {checked} manifest validi contro manifest-v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
