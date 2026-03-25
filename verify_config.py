import json
import os
import unittest
import shutil

from config_manager import ConfigManager

class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_config_dir"
        os.makedirs(self.test_dir, exist_ok=True)
        self.cm = ConfigManager(self.test_dir, self.test_dir)
        self.config_path = self.cm.map_config_path

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_update_map_config(self):
        # Initial config
        initial_config = self.cm.load_map_config()
        
        # Test update
        sources_update = {
            "global_url": "https://test.global.url",
            "china_url": "https://test.china.url"
        }
        features_update = {
            "smart_switch": True,
            "offline_mode": True,
            "cache_dir": "./test/cache_data"
        }
        
        updated = self.cm.update_map_config(
            sources_update=sources_update,
            features_update=features_update
        )
        
        # Verify returned config
        self.assertEqual(updated["sources"]["global_url"], "https://test.global.url")
        self.assertEqual(updated["sources"]["china_url"], "https://test.china.url")
        
        self.assertTrue(updated["features"]["smart_switch"])
        self.assertTrue(updated["features"]["offline_mode"])
        self.assertEqual(updated["features"]["cache_dir"], "./test/cache_data")
        
        # Verify file content
        with open(self.config_path, "r", encoding="utf-8") as f:
            saved_config = json.load(f)
            
        self.assertEqual(saved_config["sources"]["global_url"], "https://test.global.url")
        self.assertEqual(saved_config["sources"]["china_url"], "https://test.china.url")
        
        self.assertTrue(saved_config["features"]["smart_switch"])
        self.assertTrue(saved_config["features"]["offline_mode"])
        self.assertEqual(saved_config["features"]["cache_dir"], "./test/cache_data")
        
        # Verify other fields are intact
        self.assertIn("version", saved_config)
        self.assertIn("updated_at", saved_config)

if __name__ == "__main__":
    unittest.main()
