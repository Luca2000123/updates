from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hublib
from hublib import HubError

APP_ID = "dev.local.testapp"

APP_TOML = """
id = "dev.local.testapp"
title = "Test App"
description = "App finta usata dai test."
icon = "https://example.com/icon.png"
source_repo = "acme/testapp"
release_repo = "acme/testapp-releases"

[targets.android-all]
ext = "apk"
install = "apk"

[targets.windows-x86_64]
ext = "zip"
install = "zip-relay"

[targets.webos-all]
ext = "ipk"
install = "ipk-manual"
requires = { webosRelease = ">=5.0" }

[webos]
type = "web"
rootRequired = false
"""

ANDROID_TARGET = """[targets.android-all]
ext = "apk"
install = "apk"
"""

ANDROID_TARGET_LEGACY = """[targets.android-all]
ext = "apk"
install = "apk"
legacy_name = "vecchio.apk"
"""

ANDROID_TARGET_LEGACY_BAD = """[targets.android-all]
ext = "apk"
install = "apk"
legacy_name = "sotto/vecchio.apk"
"""

SHA = {
    "android-all": "1" * 64,
    "windows-x86_64": "2" * 64,
    "webos-all": "3" * 64,
}
EXT = {"android-all": "apk", "windows-x86_64": "zip", "webos-all": "ipk"}


def payload(version="1.0.0+66", platforms=("android-all", "windows-x86_64", "webos-all"), **over):
    assets = []
    for platform in platforms:
        assets.append({
            "platform": platform,
            "filename": hublib.expected_filename(APP_ID, version, platform, EXT[platform]),
            "size": 1000 + len(platform),
            "sha256": SHA[platform],
            "signature": None,
        })
    out = {
        "app_id": APP_ID,
        "channel": "stable",
        "version": version,
        "pub_date": "2026-08-24T10:00:00Z",
        "assets": assets,
    }
    out.update(over)
    return out


class HubFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "apps").mkdir()
        (self.root / "apps" / f"{APP_ID}.toml").write_text(APP_TOML, encoding="utf-8")
        self.set_hub()

    def set_hub(self, base="https://example.github.io/updates", next_url=None):
        text = f'base_url = "{base}"\n'
        if next_url:
            text += f'manifest_url_next = "{next_url}"\n'
        (self.root / "hub.toml").write_text(text, encoding="utf-8")

    def app(self):
        return hublib.load_app(self.root / "apps" / f"{APP_ID}.toml")

    def record(self, data, previous=None):
        release = hublib.normalize_release(data, self.app(), previous)
        out = self.root / "releases" / APP_ID / f"{release['channel']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(hublib.dump_json(release), encoding="utf-8")
        return release

    def build(self):
        return hublib.build_site(self.root)


class TestVersioning(unittest.TestCase):
    def test_build_number_is_the_discriminant(self):
        self.assertEqual(hublib.parse_version("1.0.0+66"), ((1, 0, 0), 66))
        self.assertEqual(hublib.parse_version("1.0.0"), ((1, 0, 0), None))

    def test_safe_version_removes_plus(self):
        self.assertEqual(hublib.safe_version("1.0.0+66"), "1.0.0-b66")
        self.assertEqual(hublib.safe_version("2.3.4"), "2.3.4")

    def test_webos_version_is_monotonic_pure_semver(self):
        self.assertEqual(hublib.webos_version("1.0.0+66"), "1.0.66")
        self.assertEqual(hublib.webos_version("1.0.0+67"), "1.0.67")
        self.assertEqual(hublib.webos_version("1.1.0+70"), "1.1.70")
        self.assertEqual(hublib.webos_version("1.0.3"), "1.0.3")

    def test_rejects_non_numeric_build(self):
        with self.assertRaises(HubError):
            hublib.parse_version("1.0.0+beta1")
        with self.assertRaises(HubError):
            hublib.parse_version("v1.0.0")

    def test_filename_has_no_plus(self):
        name = hublib.expected_filename(APP_ID, "1.0.0+66", "android-all", "apk")
        self.assertEqual(name, "dev.local.testapp-1.0.0-b66-android-all.apk")
        self.assertNotIn("+", name)


class TestAppDescriptor(HubFixture):
    def test_release_repo_distinct_from_source_repo(self):
        app = self.app()
        self.assertEqual(app["source_repo"], "acme/testapp")
        self.assertEqual(app["release_repo"], "acme/testapp-releases")

    def test_release_repo_defaults_to_source_repo(self):
        path = self.root / "apps" / f"{APP_ID}.toml"
        path.write_text(APP_TOML.replace('release_repo = "acme/testapp-releases"\n', ""),
                        encoding="utf-8")
        self.assertEqual(self.app()["release_repo"], "acme/testapp")

    def test_filename_must_match_app_id(self):
        wrong = self.root / "apps" / "altro.toml"
        wrong.write_text(APP_TOML, encoding="utf-8")
        with self.assertRaises(HubError):
            hublib.load_app(wrong)

    def test_webos_target_requires_webos_section(self):
        path = self.root / "apps" / f"{APP_ID}.toml"
        path.write_text(APP_TOML.split("[webos]")[0], encoding="utf-8")
        with self.assertRaises(HubError):
            self.app()

    def test_unknown_install_kind_rejected(self):
        path = self.root / "apps" / f"{APP_ID}.toml"
        path.write_text(APP_TOML.replace('install = "apk"', 'install = "chocolatey"'),
                        encoding="utf-8")
        with self.assertRaises(HubError):
            self.app()


class TestNormalizeRelease(HubFixture):
    def test_version_code_derived_from_build(self):
        release = hublib.normalize_release(payload(), self.app())
        self.assertEqual(release["version_code"], 66)
        self.assertEqual(release["version"], "1.0.0+66")

    def test_version_code_required_when_no_build(self):
        with self.assertRaises(HubError):
            hublib.normalize_release(payload(version="1.2.3"), self.app())
        release = hublib.normalize_release(payload(version="1.2.3", version_code=7), self.app())
        self.assertEqual(release["version_code"], 7)

    def test_default_tag_and_repo(self):
        release = hublib.normalize_release(payload(), self.app())
        self.assertEqual(release["tag"], "v1.0.0-b66")
        self.assertEqual(release["repo"], "acme/testapp-releases")

    def test_regression_blocked(self):
        first = hublib.normalize_release(payload(version="1.0.0+66"), self.app())
        with self.assertRaises(HubError):
            hublib.normalize_release(payload(version="1.0.0+66"), self.app(), first)
        with self.assertRaises(HubError):
            hublib.normalize_release(payload(version="1.0.0+65"), self.app(), first)
        later = hublib.normalize_release(payload(version="1.0.1+67"), self.app(), first)
        self.assertEqual(later["version_code"], 67)

    def test_filename_convention_enforced(self):
        data = payload()
        data["assets"][0]["filename"] = "my_streaming.apk"
        with self.assertRaises(HubError) as ctx:
            hublib.normalize_release(data, self.app())
        self.assertIn("dev.local.testapp-1.0.0-b66-android-all.apk", str(ctx.exception))

    def test_undeclared_platform_rejected(self):
        data = payload()
        data["assets"][0]["platform"] = "darwin-aarch64"
        with self.assertRaises(HubError):
            hublib.normalize_release(data, self.app())

    def test_bad_sha256_rejected(self):
        data = payload()
        data["assets"][0]["sha256"] = "deadbeef"
        with self.assertRaises(HubError):
            hublib.normalize_release(data, self.app())

    def test_sha256_lowercased(self):
        data = payload()
        data["assets"][0]["sha256"] = "A" * 64
        release = hublib.normalize_release(data, self.app())
        self.assertEqual(release["assets"]["android-all"]["sha256"], "a" * 64)

    def test_zero_size_rejected(self):
        data = payload()
        data["assets"][0]["size"] = 0
        with self.assertRaises(HubError):
            hublib.normalize_release(data, self.app())

    def test_min_supported_code_bounds(self):
        with self.assertRaises(HubError):
            hublib.normalize_release(payload(min_supported_code=99), self.app())
        release = hublib.normalize_release(payload(min_supported_code=40), self.app())
        self.assertEqual(release["min_supported_code"], 40)


class TestBuildSite(HubFixture):
    def test_manifest_shape_and_urls(self):
        self.record(payload())
        files, warnings, notes = self.build()
        self.assertEqual(warnings, [])
        manifest = files[f"v1/apps/{APP_ID}/stable.json"]
        self.assertEqual(manifest["schema"], 1)
        self.assertEqual(manifest["id"], APP_ID)
        self.assertEqual(manifest["version"], "1.0.0+66")
        self.assertEqual(manifest["version_code"], 66)
        self.assertIsNone(manifest["manifest_url_next"])
        self.assertEqual(sorted(manifest["platforms"]),
                         ["android-all", "webos-all", "windows-x86_64"])
        android = manifest["platforms"]["android-all"]
        self.assertEqual(
            android["url"],
            "https://github.com/acme/testapp-releases/releases/download/"
            "v1.0.0-b66/dev.local.testapp-1.0.0-b66-android-all.apk",
        )
        self.assertNotIn("+", android["url"])
        self.assertEqual(android["install"], "apk")
        self.assertIsNone(android["signature"])
        self.assertEqual(manifest["platforms"]["windows-x86_64"]["install"], "zip-relay")
        self.assertEqual(manifest["platforms"]["webos-all"]["requires"],
                         {"webosRelease": ">=5.0"})
        self.assertNotIn("requires", android)

    def test_platform_absent_means_no_update(self):
        self.record(payload(platforms=("android-all",)))
        files, warnings, notes = self.build()
        manifest = files[f"v1/apps/{APP_ID}/stable.json"]
        self.assertNotIn("webos-all", manifest["platforms"])
        self.assertNotIn(f"v1/apps/{APP_ID}/webos/{APP_ID}.manifest.json", files)
        self.assertEqual(len(warnings), 2)

    def test_asset_for_removed_target_is_dropped(self):
        self.record(payload())
        path = self.root / "apps" / f"{APP_ID}.toml"
        text = path.read_text(encoding="utf-8")
        head, rest = text.split("[targets.windows-x86_64]", 1)
        path.write_text(head + rest.split('install = "zip-relay"', 1)[1], encoding="utf-8")
        files, warnings, notes = self.build()
        manifest = files[f"v1/apps/{APP_ID}/stable.json"]
        self.assertNotIn("windows-x86_64", manifest["platforms"])
        self.assertTrue(any("windows-x86_64" in w for w in warnings))

    def test_webos_view(self):
        self.record(payload())
        files, _, _ = self.build()
        webos = files[f"v1/apps/{APP_ID}/webos/{APP_ID}.manifest.json"]
        self.assertEqual(webos["id"], APP_ID)
        self.assertEqual(webos["version"], "1.0.66")
        self.assertEqual(webos["type"], "web")
        self.assertEqual(webos["title"], "Test App")
        self.assertEqual(webos["iconUri"], "https://example.com/icon.png")
        self.assertEqual(webos["sourceUrl"], "https://github.com/acme/testapp")
        self.assertIs(webos["rootRequired"], False)
        self.assertEqual(webos["ipkHash"], {"sha256": SHA["webos-all"]})
        self.assertIsInstance(webos["ipkHash"], dict)
        self.assertEqual(webos["ipkSize"], 1009)
        self.assertTrue(webos["ipkUrl"].endswith("-webos-all.ipk"))
        self.assertNotIn("icon", webos)
        self.assertEqual(webos["appDescription"], "App finta usata dai test.")

    def test_webos_view_only_from_stable(self):
        self.record(payload())
        release = hublib.normalize_release(payload(version="1.1.0+70", channel="beta"), self.app())
        out = self.root / "releases" / APP_ID / "beta.json"
        out.write_text(hublib.dump_json(release), encoding="utf-8")
        files, _, _ = self.build()
        webos = files[f"v1/apps/{APP_ID}/webos/{APP_ID}.manifest.json"]
        self.assertEqual(webos["version"], "1.0.66")
        self.assertEqual(files[f"v1/apps/{APP_ID}/beta.json"]["version_code"], 70)

    def test_index(self):
        self.record(payload())
        files, _, _ = self.build()
        index = files["v1/index.json"]
        self.assertEqual(index["schema"], 1)
        self.assertEqual(len(index["apps"]), 1)
        entry = index["apps"][0]
        self.assertEqual(entry["id"], APP_ID)
        self.assertEqual(entry["source_url"], "https://github.com/acme/testapp")
        self.assertEqual(entry["channels"]["stable"]["version_code"], 66)
        self.assertEqual(
            entry["channels"]["stable"]["manifest_url"],
            f"https://example.github.io/updates/v1/apps/{APP_ID}/stable.json",
        )
        self.assertNotIn("beta", entry["channels"])

    def test_app_without_release_is_skipped(self):
        files, warnings, notes = self.build()
        self.assertEqual(files["v1/index.json"]["apps"], [])
        self.assertEqual(warnings, [])
        self.assertTrue(any("nessuna release" in n for n in notes))

    def test_manifest_url_next_propagated(self):
        self.set_hub(next_url="https://updates.example.com/")
        self.record(payload())
        files, _, _ = self.build()
        manifest = files[f"v1/apps/{APP_ID}/stable.json"]
        self.assertEqual(
            manifest["manifest_url_next"],
            f"https://updates.example.com/v1/apps/{APP_ID}/stable.json",
        )

    def test_notes_propagated(self):
        self.record(payload(notes="- fix scroll TV\n- fix crash avvio"))
        files, _, _ = self.build()
        manifest = files[f"v1/apps/{APP_ID}/stable.json"]
        self.assertEqual(manifest["notes"], "- fix scroll TV\n- fix crash avvio")

    def test_output_is_deterministic(self):
        self.record(payload())
        first, _, _ = self.build()
        second, _, _ = self.build()
        self.assertEqual(hublib.dump_json(first["v1/index.json"]),
                         hublib.dump_json(second["v1/index.json"]))
        self.assertEqual(sorted(first), sorted(second))

    def test_base_url_must_be_https(self):
        self.set_hub(base="http://example.github.io/updates")
        with self.assertRaises(HubError):
            self.build()


class TestSchemaConformance(HubFixture):
    def test_manifests_validate_against_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema non installato")
        schema_path = Path(__file__).resolve().parent.parent / "schema" / "manifest-v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.record(payload())
        files, _, _ = self.build()
        for rel, obj in files.items():
            if rel.endswith("/stable.json") or rel.endswith("/beta.json"):
                jsonschema.validate(obj, schema)


class TestMakePayload(HubFixture):
    def run_tool(self, *extra_args, files=None):
        import subprocess
        assets = self.root / "assets"
        assets.mkdir(exist_ok=True)
        for name, blob in (files or {}).items():
            (assets / name).write_bytes(blob)
        tool = Path(__file__).resolve().parent / "make_payload.py"
        proc = subprocess.run(
            [sys.executable, str(tool), "--app-id", APP_ID, "--dir", str(assets),
             "--pub-date", "2026-08-24T12:00:00Z", *extra_args],
            capture_output=True, text=True,
        )
        return proc

    def test_payload_matches_what_record_release_expects(self):
        names = {
            hublib.expected_filename(APP_ID, "1.0.0+66", platform, ext): b"x" * (10 + i)
            for i, (platform, ext) in enumerate(sorted(EXT.items()))
        }
        proc = self.run_tool("--version", "1.0.0+66", files=names)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["version"], "1.0.0+66")
        self.assertEqual(len(data["assets"]), 3)
        release = hublib.normalize_release(data, self.app())
        self.assertEqual(release["version_code"], 66)
        self.assertEqual(release["tag"], "v1.0.0-b66")
        digest = hashlib.sha256(names[hublib.expected_filename(
            APP_ID, "1.0.0+66", "android-all", "apk")]).hexdigest()
        self.assertEqual(release["assets"]["android-all"]["sha256"], digest)

    def test_ignores_files_outside_the_convention(self):
        names = {
            hublib.expected_filename(APP_ID, "1.0.0+66", "android-all", "apk"): b"x",
            "my_streaming.apk": b"y",
            "note.txt": b"z",
        }
        proc = self.run_tool("--version", "1.0.0+66", files=names)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual([a["platform"] for a in data["assets"]], ["android-all"])
        self.assertIn("my_streaming.apk", proc.stderr)

    def test_legacy_non_e_rumore_e_se_manca_avvisa(self):
        names = {
            hublib.expected_filename(APP_ID, "1.0.0+66", "android-all", "apk"): b"x",
            "my_streaming.apk": b"y",
        }
        proc = self.run_tool("--version", "1.0.0+66", "--legacy", "my_streaming.apk",
                             "--legacy", "my_streaming-windows-x64.zip", files=names)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("ignorato 'my_streaming.apk'", proc.stderr)
        self.assertIn("my_streaming-windows-x64.zip", proc.stderr)
        self.assertIn("non si aggiorneranno", proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual([a["platform"] for a in data["assets"]], ["android-all"])

    def test_fails_when_nothing_matches(self):
        proc = self.run_tool("--version", "9.9.9+99", files={"altro.apk": b"x"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("nessun asset", proc.stderr)


class TestTransizioneLegacy(HubFixture):
    def scrivi_toml(self, blocco):
        assert ANDROID_TARGET in APP_TOML
        path = self.root / "apps" / f"{APP_ID}.toml"
        path.write_text(APP_TOML.replace(ANDROID_TARGET, blocco), encoding="utf-8")

    def test_legacy_name_invalido_rifiutato(self):
        self.scrivi_toml(ANDROID_TARGET_LEGACY_BAD)
        with self.assertRaises(HubError):
            self.app()

    def test_nota_di_transizione(self):
        self.scrivi_toml(ANDROID_TARGET_LEGACY)
        self.record(payload())
        files, warnings, notes = self.build()
        self.assertEqual(warnings, [])
        self.assertTrue(any("vecchio.apk" in n for n in notes))

    def test_manifest_ignora_il_legacy(self):
        self.scrivi_toml(ANDROID_TARGET_LEGACY)
        self.record(payload())
        files, _, _ = self.build()
        android = files[f"v1/apps/{APP_ID}/stable.json"]["platforms"]["android-all"]
        self.assertNotIn("legacy_name", android)
        self.assertTrue(android["url"].endswith("dev.local.testapp-1.0.0-b66-android-all.apk"))

    def test_tag_legacy_col_piu_resta_nel_url(self):
        self.record(payload(tag="v1.0.0+66"))
        files, _, _ = self.build()
        url = files[f"v1/apps/{APP_ID}/stable.json"]["platforms"]["android-all"]["url"]
        self.assertIn("/download/v1.0.0+66/", url)
        self.assertTrue(url.endswith("-1.0.0-b66-android-all.apk"))


class TestTagPrefix(HubFixture):
    def con_prefix(self):
        path = self.root / "apps" / f"{APP_ID}.toml"
        path.write_text(
            APP_TOML.replace(
                'release_repo = "acme/testapp-releases"',
                'release_repo = "acme/updates"\ntag_prefix = "testapp"',
            ),
            encoding="utf-8",
        )

    def test_prefix_invalido_rifiutato(self):
        path = self.root / "apps" / f"{APP_ID}.toml"
        path.write_text(
            APP_TOML.replace(
                'release_repo = "acme/testapp-releases"',
                'tag_prefix = "Test App"',
            ),
            encoding="utf-8",
        )
        with self.assertRaises(HubError):
            self.app()

    def test_tag_default_prefissato(self):
        self.con_prefix()
        release = hublib.normalize_release(payload(), self.app())
        self.assertEqual(release["tag"], "testapp-v1.0.0-b66")
        self.assertEqual(release["repo"], "acme/updates")

    def test_tag_esplicito_senza_prefisso_rifiutato(self):
        self.con_prefix()
        with self.assertRaises(HubError) as ctx:
            hublib.normalize_release(payload(tag="v1.0.0-b66"), self.app())
        self.assertIn("collide", str(ctx.exception))

    def test_url_usa_il_tag_prefissato(self):
        self.con_prefix()
        self.record(payload())
        files, _, _ = self.build()
        url = files[f"v1/apps/{APP_ID}/stable.json"]["platforms"]["android-all"]["url"]
        self.assertIn("/acme/updates/releases/download/testapp-v1.0.0-b66/", url)

    def test_due_app_nello_stesso_repo_senza_prefisso_distinto(self):
        altra = self.root / "apps" / "dev.local.altra.toml"
        altra.write_text(
            APP_TOML.replace('id = "dev.local.testapp"', 'id = "dev.local.altra"'),
            encoding="utf-8",
        )
        with self.assertRaises(HubError) as ctx:
            hublib.load_apps(self.root)
        self.assertIn("collidono", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
