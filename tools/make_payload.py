from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hublib import HubError, RE_PLATFORM, safe_version


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Costruisce il payload di release scandendo gli asset gia' presenti su disco."
    )
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--version", required=True,
                        help="versione completa, es. 1.0.0+66")
    parser.add_argument("--version-code", type=int,
                        help="obbligatorio solo se la versione non ha +<build>")
    parser.add_argument("--dir", required=True, help="directory con gli asset")
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--tag", help="default: v<versione normalizzata>")
    parser.add_argument("--repo", help="owner/nome del repo delle release")
    parser.add_argument("--min-supported-code", type=int)
    parser.add_argument("--pub-date", help="default: adesso in UTC")
    parser.add_argument("--out", default="-", help="file di output, - per stdout")
    args = parser.parse_args()

    try:
        prefix = f"{args.app_id}-{safe_version(args.version)}-"
    except HubError as err:
        print(f"errore: {err}", file=sys.stderr)
        return 1

    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"errore: {directory} non e' una directory", file=sys.stderr)
        return 1

    assets = []
    ignored = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if not name.startswith(prefix) or "." not in name[len(prefix):]:
            ignored.append(name)
            continue
        rest = name[len(prefix):]
        platform, _, ext = rest.rpartition(".")
        if not RE_PLATFORM.match(platform) or not ext:
            ignored.append(name)
            continue
        assets.append({
            "platform": platform,
            "filename": name,
            "size": path.stat().st_size,
            "sha256": sha256_of(path),
            "signature": None,
        })

    for name in ignored:
        print(f"avviso: ignorato '{name}': non segue '{prefix}<platform>.<ext>'", file=sys.stderr)

    if not assets:
        print(f"errore: nessun asset con prefisso '{prefix}' in {directory}", file=sys.stderr)
        return 1

    payload = {
        "app_id": args.app_id,
        "channel": args.channel,
        "version": args.version,
        "pub_date": args.pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assets": assets,
    }
    if args.version_code is not None:
        payload["version_code"] = args.version_code
    if args.tag:
        payload["tag"] = args.tag
    if args.repo:
        payload["repo"] = args.repo
    if args.min_supported_code is not None:
        payload["min_supported_code"] = args.min_supported_code

    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        sys.stdout.write(text)
    else:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"scritto {args.out}: {len(assets)} asset", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
