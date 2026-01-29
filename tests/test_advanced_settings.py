import unittest
import os
import json
import tempfile
import shutil
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_manager import ConfigManager
from seed_manager import SeedManager

class TestAdvancedSettings(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_root = self.test_dir
        
        # Mock necessary files for SeedManager
        os.makedirs(os.path.join(self.test_dir, ".venv", "Scripts"), exist_ok=True)
        with open(os.path.join(self.test_dir, ".venv", "Scripts", "mapproxy-seed.exe"), 'w') as f:
            f.write("mock")
            
        self.config_mgr = ConfigManager(self.test_dir, self.project_root)
        
        # Create dummy config.json
        with open(os.path.join(self.test_dir, "config.json"), 'w') as f:
            json.dump({"python_path": "python", "port": 8080, "host": "127.0.0.1"}, f)
            
    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass
        
    def test_config_manager_defaults(self):
        config = self.config_mgr.load_launcher_config()
        self.assertIn("seed_settings", config)
        self.assertEqual(config["seed_settings"]["concurrency"], 2)
        self.assertFalse(config["seed_settings"]["retry"]["enabled"])
        
    def test_config_manager_save(self):
        config = self.config_mgr.load_launcher_config()
        config["seed_settings"]["concurrency"] = 8
        config["seed_settings"]["retry"]["enabled"] = True
        self.config_mgr.save_launcher_config(config)
        
        new_config = self.config_mgr.load_launcher_config()
        self.assertEqual(new_config["seed_settings"]["concurrency"], 8)
        self.assertTrue(new_config["seed_settings"]["retry"]["enabled"])
        
    def test_seed_manager_env_vars(self):
        # Mock env vars
        os.environ["MAPPROXY_SEED_CONCURRENCY"] = "4"
        os.environ["MAPPROXY_SEED_MAX_RETRIES"] = "5"
        os.environ["MAPPROXY_SEED_RETRY_BACKOFF"] = "10"
        os.environ["MAPPROXY_SEED_ALERT_ENABLED"] = "true"
        os.environ["MAPPROXY_SEED_ALERT_THRESHOLD"] = "2"
        os.environ["MAPPROXY_SEED_ALERT_EMAIL"] = "test@example.com"
        
        mgr = SeedManager(self.project_root)
        self.assertEqual(mgr.seed_concurrency, 4)
        self.assertEqual(mgr.seed_max_retries, 5)
        self.assertEqual(mgr.seed_retry_backoff, 10)
        self.assertTrue(mgr.alert_enabled)
        self.assertEqual(mgr.alert_threshold, 2)
        self.assertEqual(mgr.alert_email, "test@example.com")
        
        # Cleanup env
        os.environ.pop("MAPPROXY_SEED_CONCURRENCY", None)
        os.environ.pop("MAPPROXY_SEED_MAX_RETRIES", None)
        os.environ.pop("MAPPROXY_SEED_RETRY_BACKOFF", None)
        os.environ.pop("MAPPROXY_SEED_ALERT_ENABLED", None)
        os.environ.pop("MAPPROXY_SEED_ALERT_THRESHOLD", None)
        os.environ.pop("MAPPROXY_SEED_ALERT_EMAIL", None)

if __name__ == "__main__":
    unittest.main()