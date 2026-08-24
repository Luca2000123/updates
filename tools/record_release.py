from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hublib import CHANNELS, HubError, dump_json, load_app, load_release, normalize_release


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida il payload di una release e lo registra in releases/<app-id>/<channel>.json."
    )
    parser.add_argument("--root", default=".", help="radice del repo hub")
    parser.add_argument("--payload", required=True,
                        help="file JSON col payload, oppure - per stdin")
    parser.add_argument("--allow-rollback", action="store_true",
                        help="permette un version_code non crescente rispetto alla release corrente")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    try:
        raw = sys.stdin.read() if args.payload == "-" else Path(args.payload).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as err:
        print(f"errore: payload illeggibile: {err}", file=sys.stderr)
        return 1

    app_id = payload.get("app_id")
    app_path = root / "apps" / f"{app_id}.toml"
    if not app_path.is_file():
        print(f"errore: app '{app_id}' sconosciuta, manca apps/{app_id}.toml "
              f"(va creato a mano prima della prima release)", file=sys.stderr)
        return 1

    channel = payload.get("channel", "stable")
    if channel not in CHANNELS:
        print(f"errore: channel '{channel}' non valido, attesi {list(CHANNELS)}", file=sys.stderr)
        return 1

    out = root / "releases" / app_id / f"{channel}.json"
    previous = None
    if out.is_file() and not args.allow_rollback:
        try:
            previous = load_release(out)
        except (OSError, json.JSONDecodeError) as err:
            print(f"errore: {out.name} corrotto: {err}", file=sys.stderr)
            return 1

    try:
        app = load_app(app_path)
        release = normalize_release(payload, app, previous)
    except HubError as err:
        print(f"errore: {err}", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_json(release), encoding="utf-8")
    print(f"registrata {app_id} {release['version']} (code {release['version_code']}, "
          f"{release['channel']}) -> {out.relative_to(root).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
