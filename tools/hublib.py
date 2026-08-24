from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote

SCHEMA_VERSION = 1
CHANNELS = ("stable", "beta")
INSTALL_KINDS = {
    "apk",
    "ipk-manual",
    "zip-relay",
    "nsis",
    "msi",
    "dmg",
    "appimage",
    "deb",
    "script",
    "web",
}

RE_APP_ID = re.compile(r"^[a-z0-9]+(\.[a-z0-9][a-z0-9-]*)+$")
RE_PLATFORM = re.compile(r"^[a-z0-9]+-[a-z0-9_]+$")
RE_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(\+(\d+))?$")
RE_SEMVER_PURE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
RE_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RE_EXT = re.compile(r"^[a-z0-9]{2,8}$")
RE_TAG_PREFIX = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RE_FIREBASE_BUCKET = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class HubError(Exception):
    pass


def _require(cond, msg):
    if not cond:
        raise HubError(msg)


def parse_version(version: str) -> tuple[tuple[int, int, int], int | None]:
    match = RE_VERSION.match(version or "")
    _require(match is not None,
             f"version '{version}' non valida: attesa <major>.<minor>.<patch> "
             f"con '+<build>' opzionale e numerico")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    build = int(match.group(5)) if match.group(5) is not None else None
    return (major, minor, patch), build


def safe_version(version: str) -> str:
    (major, minor, patch), build = parse_version(version)
    if build is None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch}-b{build}"


def webos_version(version: str) -> str:
    (major, minor, patch), build = parse_version(version)
    if build is None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{build}"


def load_hub_config(root: Path) -> dict:
    path = root / "hub.toml"
    _require(path.is_file(), f"{path} mancante")
    with path.open("rb") as fh:
        cfg = tomllib.load(fh)

    base_url = cfg.get("base_url")
    _require(isinstance(base_url, str) and base_url.startswith("https://"),
             "hub.toml: base_url deve essere una URL https")
    cfg["base_url"] = base_url.rstrip("/")

    nxt = cfg.get("manifest_url_next")
    if nxt is not None:
        _require(isinstance(nxt, str) and nxt.startswith("https://"),
                 "hub.toml: manifest_url_next deve essere una URL https")
        cfg["manifest_url_next"] = nxt.rstrip("/")
    return cfg


def load_app(path: Path) -> dict:
    with path.open("rb") as fh:
        app = tomllib.load(fh)

    app_id = app.get("id")
    _require(isinstance(app_id, str) and RE_APP_ID.match(app_id),
             f"{path.name}: id '{app_id}' non e' reverse-DNS valido")
    _require(path.stem == app_id,
             f"{path.name}: il nome del file deve essere '{app_id}.toml'")
    for key in ("title", "source_repo"):
        _require(isinstance(app.get(key), str) and app[key],
                 f"{path.name}: campo '{key}' obbligatorio")
    _require(RE_REPO.match(app["source_repo"]),
             f"{path.name}: source_repo deve essere 'owner/nome'")

    app.setdefault("release_repo", app["source_repo"])
    _require(RE_REPO.match(app["release_repo"]),
             f"{path.name}: release_repo deve essere 'owner/nome'")

    prefix = app.get("tag_prefix")
    if prefix is not None:
        _require(isinstance(prefix, str) and RE_TAG_PREFIX.match(prefix),
                 f"{path.name}: tag_prefix '{prefix}' deve essere minuscolo, "
                 f"cifre e '-'")

    firebase = app.get("firebase")
    if firebase is not None:
        _require(isinstance(firebase, dict), f"{path.name}: [firebase] deve essere una tabella")
        bucket = firebase.get("bucket")
        _require(isinstance(bucket, str) and RE_FIREBASE_BUCKET.match(bucket),
                 f"{path.name}: firebase.bucket '{bucket}' non valido")

    targets = app.get("targets")
    _require(isinstance(targets, dict) and targets,
             f"{path.name}: serve almeno un [targets.<platform-key>]")

    for platform, target in targets.items():
        _require(RE_PLATFORM.match(platform),
                 f"{path.name}: platform key '{platform}' non valida (atteso <os>-<arch>)")
        ext = target.get("ext")
        _require(isinstance(ext, str) and RE_EXT.match(ext),
                 f"{path.name}/{platform}: 'ext' mancante o non valida")
        install = target.get("install")
        _require(install in INSTALL_KINDS,
                 f"{path.name}/{platform}: install '{install}' non riconosciuto, "
                 f"attesi {sorted(INSTALL_KINDS)}")
        requires = target.get("requires", {})
        _require(isinstance(requires, dict),
                 f"{path.name}/{platform}: 'requires' deve essere una tabella")
        for rk, rv in requires.items():
            _require(isinstance(rv, str),
                     f"{path.name}/{platform}: requires.{rk} deve essere una stringa")
        legacy = target.get("legacy_name")
        if legacy is not None:
            _require(isinstance(legacy, str) and legacy and "/" not in legacy,
                     f"{path.name}/{platform}: legacy_name deve essere un nome di file")

        unknown = set(target) - {"ext", "install", "requires", "legacy_name"}
        _require(not unknown,
                 f"{path.name}/{platform}: chiavi non riconosciute {sorted(unknown)}")

    if any(p.startswith("webos-") for p in targets):
        webos = app.get("webos")
        _require(isinstance(webos, dict),
                 f"{path.name}: c'e' un target webos, serve la sezione [webos]")
        _require(webos.get("type") in ("web", "native"),
                 f"{path.name}: webos.type deve essere 'web' o 'native'")
        _require(isinstance(webos.get("rootRequired"), bool),
                 f"{path.name}: webos.rootRequired deve essere true o false")

    return app


def load_apps(root: Path) -> dict[str, dict]:
    apps_dir = root / "apps"
    _require(apps_dir.is_dir(), f"{apps_dir} mancante")
    apps = {}
    for path in sorted(apps_dir.glob("*.toml")):
        app = load_app(path)
        _require(app["id"] not in apps, f"app id duplicato: {app['id']}")
        apps[app["id"]] = app

    seen = {}
    for app_id, app in apps.items():
        key = (app["release_repo"], app.get("tag_prefix"))
        other = seen.get(key)
        _require(other is None,
                 f"{app_id} e {other} pubblicano nello stesso repo "
                 f"'{key[0]}' con lo stesso tag_prefix {key[1]!r}: i tag "
                 f"collidono, dai a ognuna il suo prefisso")
        seen[key] = app_id
    return apps


def load_release(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_releases(root: Path, app_id: str) -> dict[str, dict]:
    out = {}
    app_dir = root / "releases" / app_id
    if not app_dir.is_dir():
        return out
    for channel in CHANNELS:
        path = app_dir / f"{channel}.json"
        if path.is_file():
            out[channel] = load_release(path)
    return out


def expected_filename(app_id: str, version: str, platform: str, ext: str) -> str:
    return f"{app_id}-{safe_version(version)}-{platform}.{ext}"


def firebase_storage_url(bucket: str, path: str) -> str:
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{quote(path, safe='')}?alt=media"


def asset_url(app: dict, repo: str, tag: str, filename: str) -> str:
    firebase = app.get("firebase")
    if firebase:
        path = f"releases/{app['id']}/{tag}/{filename}"
        return firebase_storage_url(firebase["bucket"], path)
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def normalize_release(payload: dict, app: dict, previous: dict | None = None) -> dict:
    app_id = payload.get("app_id")
    _require(app_id == app["id"],
             f"payload: app_id '{app_id}' non corrisponde a '{app['id']}'")

    channel = payload.get("channel", "stable")
    _require(channel in CHANNELS,
             f"payload: channel '{channel}' non valido, attesi {list(CHANNELS)}")

    version = payload.get("version", "")
    _, build = parse_version(version)

    version_code = payload.get("version_code", build)
    _require(isinstance(version_code, int) and version_code > 0,
             f"payload: serve un 'version_code' intero positivo "
             f"(deducibile da '+<build>' in version, qui version='{version}')")

    if previous is not None and previous.get("version_code") is not None:
        _require(version_code > previous["version_code"],
                 f"payload: version_code {version_code} non e' maggiore del precedente "
                 f"{previous['version_code']} - l'aggiornamento non sarebbe rilevabile")

    prefix = app.get("tag_prefix")
    default_tag = f"v{safe_version(version)}"
    if prefix:
        default_tag = f"{prefix}-{default_tag}"
    tag = payload.get("tag") or default_tag
    _require(isinstance(tag, str) and tag, "payload: tag non valido")
    if prefix:
        _require(tag.startswith(f"{prefix}-"),
                 f"payload: il tag '{tag}' deve iniziare con '{prefix}-', "
                 f"altrimenti collide con le altre app dello stesso repo")

    repo = payload.get("repo") or app["release_repo"]
    _require(RE_REPO.match(repo), f"payload: repo '{repo}' deve essere 'owner/nome'")

    min_supported_code = payload.get("min_supported_code")
    if min_supported_code is not None:
        _require(isinstance(min_supported_code, int) and 0 < min_supported_code <= version_code,
                 f"payload: min_supported_code deve essere un intero fra 1 e {version_code}")

    raw_assets = payload.get("assets")
    _require(isinstance(raw_assets, list) and raw_assets,
             "payload: 'assets' deve essere una lista non vuota")

    targets = app["targets"]
    assets = {}
    for entry in raw_assets:
        platform = entry.get("platform")
        _require(platform in targets,
                 f"payload: platform '{platform}' non dichiarata in {app['id']}.toml "
                 f"(dichiarate: {sorted(targets)})")
        _require(platform not in assets, f"payload: platform '{platform}' duplicata")

        filename = entry.get("filename", "")
        want = expected_filename(app["id"], version, platform, targets[platform]["ext"])
        _require(filename == want,
                 f"payload: filename '{filename}' non segue la convenzione, atteso '{want}'")

        size = entry.get("size")
        _require(isinstance(size, int) and size > 0,
                 f"payload/{platform}: size deve essere un intero positivo")

        sha256 = (entry.get("sha256") or "").lower()
        _require(RE_SHA256.match(sha256),
                 f"payload/{platform}: sha256 '{sha256}' non e' un digest esadecimale a 64 cifre")

        signature = entry.get("signature")
        _require(signature is None or isinstance(signature, str),
                 f"payload/{platform}: signature deve essere una stringa o null")

        assets[platform] = {
            "filename": filename,
            "size": size,
            "sha256": sha256,
            "signature": signature,
        }

    return {
        "schema": SCHEMA_VERSION,
        "app_id": app["id"],
        "channel": channel,
        "version": version,
        "version_code": version_code,
        "tag": tag,
        "repo": repo,
        "pub_date": payload.get("pub_date"),
        "notes": payload.get("notes"),
        "notes_url": payload.get("notes_url") or f"https://github.com/{repo}/releases/tag/{tag}",
        "min_supported_code": min_supported_code,
        "assets": assets,
    }


def build_manifest(app: dict, release: dict, hub: dict) -> tuple[dict, list[str]]:
    warnings = []
    targets = app["targets"]
    platforms = {}

    for platform, asset in sorted(release["assets"].items()):
        target = targets.get(platform)
        if target is None:
            warnings.append(
                f"{app['id']}/{release['channel']}: asset per '{platform}' "
                f"ma il target non e' piu' dichiarato, ignorato"
            )
            continue
        entry = {
            "url": asset_url(app, release["repo"], release["tag"], asset["filename"]),
            "size": asset["size"],
            "sha256": asset["sha256"],
            "signature": asset.get("signature"),
            "install": target["install"],
        }
        if target.get("requires"):
            entry["requires"] = dict(target["requires"])
        platforms[platform] = entry

    _require(platforms,
             f"{app['id']}/{release['channel']}: nessun asset valido, manifest non generabile")

    for platform in sorted(set(targets) - set(platforms)):
        warnings.append(
            f"{app['id']}/{release['channel']}: target '{platform}' dichiarato "
            f"ma assente dalla release {release['version']}"
        )

    next_base = hub.get("manifest_url_next")
    manifest = {
        "schema": SCHEMA_VERSION,
        "id": app["id"],
        "channel": release["channel"],
        "version": release["version"],
        "version_code": release["version_code"],
        "pub_date": release.get("pub_date"),
        "notes": release.get("notes"),
        "notes_url": release.get("notes_url"),
        "min_supported_code": release.get("min_supported_code"),
        "manifest_url_next": (
            f"{next_base}/v1/apps/{app['id']}/{release['channel']}.json"
            if next_base else None
        ),
        "platforms": platforms,
    }
    return manifest, warnings


def build_webos_manifest(app: dict, manifest: dict) -> dict | None:
    webos_platforms = [p for p in manifest["platforms"] if p.startswith("webos-")]
    if not webos_platforms:
        return None
    entry = manifest["platforms"][sorted(webos_platforms)[0]]
    version = webos_version(manifest["version"])
    _require(RE_SEMVER_PURE.match(version),
             f"{app['id']}: versione webOS '{version}' non e' semver puro")
    out = {
        "id": app["id"],
        "version": version,
        "type": app["webos"]["type"],
        "title": app["title"],
        "iconUri": app.get("icon", ""),
        "sourceUrl": app.get("homepage") or f"https://github.com/{app['source_repo']}",
        "rootRequired": app["webos"]["rootRequired"],
        "ipkUrl": entry["url"],
        "ipkHash": {"sha256": entry["sha256"]},
        "ipkSize": entry["size"],
    }
    if app.get("description"):
        out["appDescription"] = app["description"]
    return out


def build_index(apps: dict, manifests: dict, hub: dict) -> dict:
    base = hub["base_url"]
    entries = []
    for app_id in sorted(manifests):
        app = apps[app_id]
        firebase = app.get("firebase")
        channels = {}
        for channel in CHANNELS:
            manifest = manifests[app_id].get(channel)
            if manifest is None:
                continue
            if firebase:
                manifest_url = firebase_storage_url(
                    firebase["bucket"], f"v1/apps/{app_id}/{channel}.json")
            else:
                manifest_url = f"{base}/v1/apps/{app_id}/{channel}.json"
            channels[channel] = {
                "version": manifest["version"],
                "version_code": manifest["version_code"],
                "manifest_url": manifest_url,
                "platforms": sorted(manifest["platforms"]),
            }
        entry = {
            "id": app_id,
            "title": app["title"],
            "icon": app.get("icon", ""),
            "source_url": f"https://github.com/{app['source_repo']}",
            "channels": channels,
        }
        if app.get("description"):
            entry["description"] = app["description"]
        entries.append(entry)
    return {"schema": SCHEMA_VERSION, "apps": entries}


def build_site(root: Path) -> tuple[dict[str, dict], list[str], list[str]]:
    hub = load_hub_config(root)
    apps = load_apps(root)
    files = {}
    manifests = {}
    warnings = []
    notes = []

    for app_id, app in apps.items():
        legacy = sorted(
            f"{platform} -> {target['legacy_name']}"
            for platform, target in app["targets"].items()
            if target.get("legacy_name")
        )
        if legacy:
            notes.append(
                f"{app_id}: transizione attiva, ogni release deve contenere ancora "
                f"gli asset col nome vecchio ({'; '.join(legacy)})"
            )
        releases = load_releases(root, app_id)
        if not releases:
            notes.append(f"{app_id}: nessuna release registrata, esclusa dal catalogo")
            continue
        manifests[app_id] = {}
        for channel, release in releases.items():
            _require(release.get("app_id") == app_id,
                     f"releases/{app_id}/{channel}.json: app_id incoerente")
            _require(release.get("channel") == channel,
                     f"releases/{app_id}/{channel}.json: channel incoerente")
            manifest, warns = build_manifest(app, release, hub)
            warnings.extend(warns)
            manifests[app_id][channel] = manifest
            files[f"v1/apps/{app_id}/{channel}.json"] = manifest

        stable = manifests[app_id].get("stable")
        if stable is not None:
            webos = build_webos_manifest(app, stable)
            if webos is not None:
                files[f"v1/apps/{app_id}/webos/{app_id}.manifest.json"] = webos

    files["v1/index.json"] = build_index(apps, manifests, hub)
    return files, warnings, notes


def dump_json(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
