import unittest
import os
import json
import tempfile
import shutil
import sys
import time
from datetime import datetime

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
        
        with open(os.path.join(self.test_dir, "config.json"), 'w', encoding="utf-8") as f:
            json.dump(
                {
                    "python_path": "python",
                    "selection_label": "Python 3.x - python",
                    "port": 8080,
                    "host": "127.0.0.1",
                    "waitress_threads": 16,
                },
                f,
                ensure_ascii=False,
            )

        with open(os.path.join(self.test_dir, "advanced_settings.json"), 'w', encoding="utf-8") as f:
            json.dump(
                {
                    "concurrency": 4,
                    "retry": {"enabled": True, "max_retries": 3, "interval": 7},
                    "alert": {"enabled": True},
                },
                f,
                ensure_ascii=False,
            )
            
    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass
        
    def test_config_manager_defaults(self):
        config = self.config_mgr.load_launcher_config()
        self.assertIn("seed_settings", config)
        self.assertEqual(config["seed_settings"]["concurrency"], 4)
        self.assertTrue(config["seed_settings"]["retry"]["enabled"])
        
    def test_config_manager_save(self):
        legacy_launcher_path = os.path.join(self.test_dir, "config.json")
        legacy_adv_path = os.path.join(self.test_dir, "advanced_settings.json")
        with open(legacy_launcher_path, "r", encoding="utf-8") as f:
            legacy_launcher_before = f.read()
        with open(legacy_adv_path, "r", encoding="utf-8") as f:
            legacy_adv_before = f.read()
        launcher_mtime_before = os.path.getmtime(legacy_launcher_path)
        adv_mtime_before = os.path.getmtime(legacy_adv_path)

        config = self.config_mgr.load_launcher_config()
        config["seed_settings"]["concurrency"] = 8
        config["seed_settings"]["retry"]["enabled"] = True
        self.config_mgr.save_launcher_config(config)
        
        new_config = self.config_mgr.load_launcher_config()
        self.assertEqual(new_config["seed_settings"]["concurrency"], 8)
        self.assertTrue(new_config["seed_settings"]["retry"]["enabled"])

        map_cfg_path = os.path.join(self.test_dir, "mapproxy_config", "map_config.json")
        self.assertTrue(os.path.exists(map_cfg_path))
        with open(map_cfg_path, "r", encoding="utf-8") as f:
            map_cfg = json.load(f)
        self.assertIn("version", map_cfg)
        self.assertGreaterEqual(int(map_cfg.get("version", 0)), 2)
        self.assertIn("launcher_config", map_cfg)
        self.assertNotIn("python_path", map_cfg.get("launcher_config", {}))
        self.assertNotIn("selection_label", map_cfg.get("launcher_config", {}))
        self.assertNotIn("host", map_cfg.get("launcher_config", {}))

        with open(legacy_launcher_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), legacy_launcher_before)
        with open(legacy_adv_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), legacy_adv_before)
        self.assertEqual(os.path.getmtime(legacy_launcher_path), launcher_mtime_before)
        self.assertEqual(os.path.getmtime(legacy_adv_path), adv_mtime_before)
        
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
            self.assertTrue(os.path.exists(os.path.join(work_dir, "mapproxy_config", "map_config.json")))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            shutil.rmtree(project_root, ignore_errors=True)

    def test_map_config_version_increments_on_saves(self):
        self.config_mgr.ensure_map_config_exists(source="test")
        map_cfg_path = os.path.join(self.test_dir, "mapproxy_config", "map_config.json")
        with open(map_cfg_path, "r", encoding="utf-8") as f:
            map_cfg1 = json.load(f)
        v1 = int(map_cfg1.get("version", 0))

        launcher = self.config_mgr.load_launcher_config()
        launcher["port"] = 8081
        self.config_mgr.save_launcher_config(launcher, source="test_launcher_save")

        with open(map_cfg_path, "r", encoding="utf-8") as f:
            map_cfg2 = json.load(f)
        v2 = int(map_cfg2.get("version", 0))
        self.assertEqual(v2, v1 + 1)

        adv = self.config_mgr.load_advanced_config()
        adv["concurrency"] = 3
        self.config_mgr.save_advanced_config(adv, source="test_adv_save")
        with open(map_cfg_path, "r", encoding="utf-8") as f:
            map_cfg3 = json.load(f)
        v3 = int(map_cfg3.get("version", 0))
        self.assertEqual(v3, v2 + 1)

    def test_save_does_not_create_legacy_files(self):
        legacy_launcher_path = os.path.join(self.test_dir, "config.json")
        legacy_adv_path = os.path.join(self.test_dir, "advanced_settings.json")
        os.remove(legacy_launcher_path)
        os.remove(legacy_adv_path)

        launcher_payload = {
            "python_path": "python",
            "selection_label": "Python 3.x - python",
            "port": 7001,
            "host": "127.0.0.1",
            "allow_external_access": False,
            "waitress_threads": 16,
            "seed_settings": {
                "concurrency": 2,
                "retry": {"enabled": False, "max_retries": 2, "interval": 5},
                "alert": {"enabled": False},
            },
        }
        self.config_mgr.save_launcher_config(launcher_payload, source="test_save_launcher")
        self.config_mgr.save_advanced_config(self.config_mgr.get_default_advanced_config(), source="test_save_adv")

        self.assertFalse(os.path.exists(legacy_launcher_path))
        self.assertFalse(os.path.exists(legacy_adv_path))

        map_cfg_path = os.path.join(self.test_dir, "mapproxy_config", "map_config.json")
        self.assertTrue(os.path.exists(map_cfg_path))
        with open(map_cfg_path, "r", encoding="utf-8") as f:
            map_cfg = json.load(f)
        self.assertNotIn("python_path", map_cfg.get("launcher_config", {}))
        self.assertNotIn("selection_label", map_cfg.get("launcher_config", {}))
        self.assertNotIn("host", map_cfg.get("launcher_config", {}))

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

    def test_updated_at_is_local_timezone_iso_seconds(self):
        """验证 updated_at 为 ISO-8601 秒级精度格式（无时区偏移）。"""
        cfg = self.config_mgr.ensure_map_config_exists(source="test_updated_at")
        updated_at = cfg.get("updated_at")
        self.assertIsInstance(updated_at, str)
        dt = datetime.fromisoformat(updated_at)
        self.assertIsNone(dt.tzinfo)
        self.assertEqual(dt.microsecond, 0)

        local_now = datetime.now().replace(microsecond=0)
        self.assertLessEqual(abs((local_now - dt).total_seconds()), 10)

    def test_get_service_config_host_derived_from_allow_external_access(self):
        """验证服务 host 仅由 allow_external_access 推导，不依赖持久化 host 字段。"""
        launcher_payload = {
            "python_path": "python",
            "selection_label": "Python 3.x - python",
            "port": 7001,
            "host": "127.0.0.1",
            "allow_external_access": True,
            "waitress_threads": 16,
            "seed_settings": {
                "concurrency": 2,
                "retry": {"enabled": False, "max_retries": 2, "interval": 5},
                "alert": {"enabled": False},
            },
        }
        self.config_mgr.save_launcher_config(launcher_payload, source="test_service_cfg")
        svc = self.config_mgr.get_service_config()
        self.assertEqual(svc.get("host"), "0.0.0.0")
        self.assertEqual(svc.get("port"), 7001)

        time.sleep(1.1)
        launcher_payload["allow_external_access"] = False
        self.config_mgr.save_launcher_config(launcher_payload, source="test_service_cfg_2")
        svc2 = self.config_mgr.get_service_config()
        self.assertEqual(svc2.get("host"), "127.0.0.1")

if __name__ == "__main__":
    unittest.main()
