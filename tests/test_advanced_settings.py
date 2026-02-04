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
from utils import cleanup_empty_legacy_launcher_dir_in_cwd

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
        """验证 SeedManager 能正确读取并解析环境变量配置。"""
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

    def test_config_manager_reads_layers_from_migrated_path(self):
        """验证迁移后 ConfigManager 仍能从 mapproxy_config/mapproxy.yaml 读取图层。"""
        work_dir = tempfile.mkdtemp()
        project_root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(work_dir, "mapproxy_config"), exist_ok=True)
            yaml_path = os.path.join(work_dir, "mapproxy_config", "mapproxy.yaml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                f.write(
                    "layers:\n"
                    "  - name: demo\n"
                    "    title: Demo\n"
                    "    sources: [demo_cache]\n"
                    "caches:\n"
                    "  demo_cache:\n"
                    "    format: image/png\n"
                )

            mgr = ConfigManager(work_dir, project_root)
            layers = mgr.get_layers()
            self.assertTrue(any(layer.get("name") == "demo" for layer in layers))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            shutil.rmtree(project_root, ignore_errors=True)

    def test_init_configs_copies_migrated_yaml_into_workdir(self):
        """验证 init_configs 会把项目内 mapproxy_config 下的 YAML 初始化到工作目录。"""
        work_dir = tempfile.mkdtemp()
        project_root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(project_root, "mapproxy_config"), exist_ok=True)
            with open(os.path.join(project_root, "mapproxy_config", "mapproxy.yaml"), "w", encoding="utf-8") as f:
                f.write("services:\n  demo:\n")
            with open(os.path.join(project_root, "mapproxy_config", "mapproxy-seed.yaml"), "w", encoding="utf-8") as f:
                f.write("seeds:\n  t1:\n    caches: []\n    grids: []\n")

            mgr = ConfigManager(work_dir, project_root)
            mgr.init_configs()

            self.assertTrue(os.path.exists(os.path.join(work_dir, "mapproxy_config", "mapproxy.yaml")))
            self.assertTrue(os.path.exists(os.path.join(work_dir, "mapproxy_config", "mapproxy-seed.yaml")))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            shutil.rmtree(project_root, ignore_errors=True)

    def test_seed_manager_uses_migrated_yaml_paths(self):
        """验证 SeedManager 会从 mapproxy_config 目录读取配置并可计算 hash。"""
        project_root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(project_root, "mapproxy_config"), exist_ok=True)
            with open(os.path.join(project_root, "mapproxy_config", "mapproxy.yaml"), "w", encoding="utf-8") as f:
                f.write("services:\n  demo:\n")
            with open(os.path.join(project_root, "mapproxy_config", "mapproxy-seed.yaml"), "w", encoding="utf-8") as f:
                f.write("seeds:\n  t1:\n    caches: []\n    grids: []\n")

            os.makedirs(os.path.join(project_root, ".venv", "Scripts"), exist_ok=True)
            with open(os.path.join(project_root, ".venv", "Scripts", "mapproxy-seed.exe"), "w", encoding="utf-8") as f:
                f.write("mock")

            mgr = SeedManager(project_root)
            digest = mgr._compute_seed_hash()
            self.assertIsNotNone(digest)
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

    def test_cleanup_empty_legacy_launcher_dir_in_cwd(self):
        """验证可清理当前目录下遗留的空 MapProxyLauncher 文件夹。"""
        tmp_dir = tempfile.mkdtemp()
        prev_cwd = os.getcwd()
        try:
            os.chdir(tmp_dir)
            legacy = os.path.join(tmp_dir, "MapProxyLauncher")
            os.makedirs(legacy, exist_ok=True)
            cleanup_empty_legacy_launcher_dir_in_cwd("MapProxyLauncher", "Test")
            self.assertFalse(os.path.exists(legacy))

            os.makedirs(legacy, exist_ok=True)
            with open(os.path.join(legacy, "keep.txt"), "w", encoding="utf-8") as f:
                f.write("x")
            cleanup_empty_legacy_launcher_dir_in_cwd("MapProxyLauncher", "Test")
            self.assertTrue(os.path.exists(legacy))
        finally:
            os.chdir(prev_cwd)
            shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
