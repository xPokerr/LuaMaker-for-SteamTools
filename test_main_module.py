import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

import luamaker_app as LUA_MAKER


class LuaMakerTests(unittest.TestCase):
    def test_parse_appinfo_extracts_matching_app(self):
        raw_text = """
noise before output
"480"
{
    "common"
    {
        "name" "Spacewar"
    }
    "depots"
    {
        "111"
        {
            "manifests"
            {
                "public"
                {
                    "gid" "999"
                }
            }
        }
    }
}
"""
        parsed = LUA_MAKER.parse_appinfo(raw_text, "480")
        self.assertEqual(parsed["common"]["name"], "Spacewar")
        self.assertEqual(parsed["depots"]["111"]["manifests"]["public"]["gid"], "999")

    def test_fetch_app_info_uses_steamcmd_output(self):
        raw_text = """
"480"
{
    "common"
    {
        "name" "Spacewar"
    }
}
"""
        with patch.object(LUA_MAKER, "find_steamcmd_exe", return_value="steamcmd.exe"):
            with patch.object(
                LUA_MAKER.subprocess,
                "run",
                return_value=SimpleNamespace(stdout=raw_text.encode("utf-8"), stderr=b""),
            ):
                with patch.object(LUA_MAKER, "save_appinfo_log") as save_log:
                    parsed = LUA_MAKER.fetch_app_info("480")

        self.assertEqual(parsed["common"]["name"], "Spacewar")
        save_log.assert_called_once()

    def test_collect_decryption_keys_keeps_only_supported_depots(self):
        depots = {"111": "999", "222": "555"}
        config_text = """
"111"
{
    "DecryptionKey" "KEY111"
}
"""
        usable_depots, keys = LUA_MAKER.collect_decryption_keys(config_text, depots)
        self.assertEqual(usable_depots, {"111": "999"})
        self.assertEqual(keys, {"111": "KEY111"})

    def test_extract_dlc_appids_reads_extended_listofdlc(self):
        app_info = {
            "extended": {
                "listofdlc": "3990800, 3990820,invalid,3990800"
            }
        }
        self.assertEqual(LUA_MAKER.extract_dlc_appids(app_info), ["3990800", "3990820"])

    def test_copy_manifests_copies_only_matching_depots(self):
        with tempfile.TemporaryDirectory() as depotcache, tempfile.TemporaryDirectory() as out_dir:
            Path(depotcache, "111_1.manifest").write_text("a", encoding="utf-8")
            Path(depotcache, "222_1.manifest").write_text("b", encoding="utf-8")
            Path(depotcache, "readme.txt").write_text("c", encoding="utf-8")

            copied = LUA_MAKER.copy_manifests({"111": "999"}, depotcache, out_dir)

            self.assertEqual(copied, 1)
            self.assertTrue(Path(out_dir, "111_1.manifest").exists())
            self.assertFalse(Path(out_dir, "222_1.manifest").exists())

    def test_write_lua_writes_expected_lines(self):
        with tempfile.TemporaryDirectory() as out_dir:
            file_path = LUA_MAKER.write_lua(
                "480",
                {"111": "999"},
                {"111": "KEY111"},
                out_dir,
                dlc_appids=["222", "333"],
            )

            content = Path(file_path).read_text(encoding="utf-8")

        self.assertIn("addappid(480)", content)
        self.assertIn("addappid(222)", content)
        self.assertIn("addappid(333)", content)
        self.assertIn('addappid(111,1,"KEY111")', content)
        self.assertIn('setManifestid(111,"999")', content)


if __name__ == "__main__":
    unittest.main()
