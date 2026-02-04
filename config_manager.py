import os
import json
import logging
import shutil
import sys
from utils import load_json, save_json

class ConfigManager:
    def __init__(self, work_dir, project_root):
        self.work_dir = work_dir
        self.project_root = project_root
        self.logger = logging.getLogger("ConfigManager")
        
        # Config paths
        self.config_json_path = os.path.join(work_dir, "config.json")
        self.advanced_config_path = os.path.join(work_dir, "advanced_settings.json")
        self.mapproxy_config_dir = os.path.join(work_dir, "mapproxy_config")
        self.mapproxy_yaml_path = os.path.join(self.mapproxy_config_dir, "mapproxy.yaml")
        self.seed_yaml_path = os.path.join(self.mapproxy_config_dir, "mapproxy-seed.yaml")
        
        # Locate schema
        self.config_schema_path = self._locate_schema()
        if self.config_schema_path:
            self.logger.info(f"Found config schema at: {self.config_schema_path}")
        else:
            self.logger.warning("Config schema not found.")

    def _locate_schema(self):
        """Locate the mapproxy config-schema.json file"""
        # 1. Try sys._MEIPASS (Frozen app)
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            # In build.spec, we put it in mapproxy/config
            schema_path = os.path.join(base_path, 'mapproxy', 'config', 'config-schema.json')
            if os.path.exists(schema_path):
                return schema_path
        
        # 2. Try importing mapproxy
        try:
            import mapproxy
            base_path = os.path.dirname(mapproxy.__file__)
            schema_path = os.path.join(base_path, 'config', 'config-schema.json')
            if os.path.exists(schema_path):
                return schema_path
        except ImportError:
            pass
            
        return None

    def init_configs(self):
        """Initialize configuration files in work directory"""
        try:
            os.makedirs(self.mapproxy_config_dir, exist_ok=True)
        except Exception:
            self.logger.exception("Failed to create mapproxy_config directory in work_dir")

        config_src_dir = os.path.join(self.project_root, "mapproxy_config")
        config_files = [
            ("mapproxy.yaml", self.mapproxy_yaml_path),
            ("mapproxy-seed.yaml", self.seed_yaml_path),
        ]
        for filename, dst in config_files:
            src = os.path.join(config_src_dir, filename)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                    self.logger.info(f"Initialized config: {os.path.relpath(dst, self.work_dir)}")
                except Exception:
                    self.logger.exception(f"Failed to copy config: {filename}")

        config_py_src = os.path.join(self.project_root, "config.py")
        config_py_dst = os.path.join(self.work_dir, "config.py")
        if os.path.exists(config_py_src) and not os.path.exists(config_py_dst):
            try:
                shutil.copy2(config_py_src, config_py_dst)
                self.logger.info("Initialized config: config.py")
            except Exception:
                self.logger.exception("Failed to copy config: config.py")

    def load_launcher_config(self):
        """Load GUI launcher config"""
        raw = load_json(self.config_json_path)
        config = raw if isinstance(raw, dict) else {}

        seed_settings = config.get("seed_settings")
        if not isinstance(seed_settings, dict):
            seed_settings = {}
            config["seed_settings"] = seed_settings

        defaults = self.get_default_advanced_config()
        try:
            adv = self.load_advanced_config()
        except Exception:
            self.logger.exception("读取高级设置失败，回退为默认值")
            adv = defaults

        seed_settings.setdefault("concurrency", adv.get("concurrency", defaults["concurrency"]))

        retry_cfg = seed_settings.get("retry")
        if not isinstance(retry_cfg, dict):
            retry_cfg = {}
            seed_settings["retry"] = retry_cfg
        adv_retry = adv.get("retry", {})
        default_retry = defaults["retry"]
        retry_cfg.setdefault("enabled", bool(adv_retry.get("enabled", default_retry["enabled"])))
        retry_cfg.setdefault("max_retries", int(adv_retry.get("max_retries", default_retry["max_retries"])))
        retry_cfg.setdefault("interval", int(adv_retry.get("interval", default_retry["interval"])))

        alert_cfg = seed_settings.get("alert")
        if not isinstance(alert_cfg, dict):
            alert_cfg = {}
            seed_settings["alert"] = alert_cfg
        adv_alert = adv.get("alert", {})
        default_alert = defaults["alert"]
        alert_cfg.setdefault("enabled", bool(adv_alert.get("enabled", default_alert["enabled"])))

        return config

    def get_default_advanced_config(self):
        """Get default advanced settings"""
        return {
            "concurrency": 2,
            "retry": {
                "enabled": False,
                "max_retries": 2,
                "interval": 5
            },
            "alert": {
                "enabled": False
            }
        }

    def load_advanced_config(self):
        """Load advanced settings from independent file"""
        if not os.path.exists(self.advanced_config_path):
            return self.get_default_advanced_config()
            
        config = load_json(self.advanced_config_path)
        defaults = self.get_default_advanced_config()
        
        # Ensure structure matches defaults (merge)
        if "concurrency" not in config:
            config["concurrency"] = defaults["concurrency"]
        
        if "retry" not in config:
            config["retry"] = defaults["retry"]
        else:
            for k, v in defaults["retry"].items():
                if k not in config["retry"]:
                    config["retry"][k] = v
                    
        if "alert" not in config:
            config["alert"] = defaults["alert"]
        else:
             for k, v in defaults["alert"].items():
                if k not in config["alert"]:
                    config["alert"][k] = v
        
        # Sanitize: Remove deprecated keys if they exist in file
        if "alert" in config:
            config["alert"].pop("alert_email", None)
            config["alert"].pop("alert_threshold", None)
            config["alert"].pop("email", None)
            config["alert"].pop("threshold", None)
                    
        return config

    def save_advanced_config(self, config_data):
        """Save advanced settings"""
        save_json(self.advanced_config_path, config_data)

    def save_launcher_config(self, config_data):
        """Save GUI launcher config"""
        self.validate_launcher_config(config_data)
        save_json(self.config_json_path, config_data)

    def validate_launcher_config(self, config):
        """Validate launcher configuration"""
        required_fields = ["python_path", "port", "host"]
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required config field: {field}")
        
        port = config.get("port")
        try:
            port = int(port)
        except (ValueError, TypeError):
             raise ValueError(f"Invalid port: {port}")
             
        if not (1 <= port <= 65535):
            raise ValueError(f"Invalid port: {port}")

        if "waitress_threads" in config:
            threads = config.get("waitress_threads")
            try:
                threads = int(threads)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid threads count: {threads}")
            
            if not (1 <= threads <= 32):
                raise ValueError(f"Threads count must be between 1 and 32: {threads}")

    def validate_mapproxy_config(self):
        """Validate mapproxy.yaml against schema"""
        if not self.config_schema_path or not os.path.exists(self.config_schema_path):
            self.logger.warning("Schema not found, skipping validation.")
            return True
            
        try:
            import yaml
            import jsonschema
            
            with open(self.config_schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            
            with open(self.mapproxy_yaml_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            jsonschema.validate(instance=config, schema=schema)
            self.logger.info("mapproxy.yaml validation successful.")
            return True
            
        except ImportError as e:
            self.logger.warning(f"Validation dependencies missing ({e}). Skipping validation.")
            return True
        except yaml.YAMLError as e:
            self.logger.exception(f"mapproxy.yaml syntax error: {e}")
            raise ValueError(f"YAML Syntax Error: {e}")
        except jsonschema.ValidationError as e:
            self.logger.exception(f"mapproxy.yaml validation error: {e.message}")
            raise ValueError(f"Config Validation Error: {e.message}")
        except Exception:
            self.logger.exception(f"Unexpected validation error")
            raise

    def validate_seed_config(self):
        """
        Diagnostic: Validate mapproxy-seed.yaml structure and log tasks.
        Requested by Step 3 of validation plan.
        """
        if not os.path.exists(self.seed_yaml_path):
            self.logger.warning(f"Seed config not found at {self.seed_yaml_path}")
            return False
            
        try:
            import yaml
            with open(self.seed_yaml_path, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
            
            # Log raw dict keys to verify 'seeds' and task names exist
            self.logger.info(f"Seed Config Loaded. Top-level keys: {list(raw_config.keys())}")
            
            if 'seeds' in raw_config:
                seeds = raw_config['seeds']
                self.logger.info(f"Found {len(seeds)} seed tasks: {list(seeds.keys())}")
                for name, details in seeds.items():
                    # Verify task structure (simple check)
                    self.logger.debug(f"Task '{name}' keys: {list(details.keys())}")
            else:
                self.logger.warning("'seeds' section missing in mapproxy-seed.yaml")
                
            return True
        except Exception as e:
            self.logger.exception(f"Failed to validate seed config: {e}")
            return False

    def get_service_config(self):
        """Get effective service configuration"""
        launcher_conf = self.load_launcher_config()
        return {
            "port": launcher_conf.get("port", 8080),
            "host": launcher_conf.get("host", "127.0.0.1"),
            "python_path": launcher_conf.get("python_path")
        }

    def get_layers(self):
        """Get list of layers with format info from mapproxy.yaml"""
        if not os.path.exists(self.mapproxy_yaml_path):
            return []
            
        try:
            # Lazy import
            import yaml
            with open(self.mapproxy_yaml_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            layers = []
            caches = config.get('caches', {})
            
            if 'layers' in config:
                for layer in config['layers']:
                    name = layer.get('name', 'Unknown')
                    title = layer.get('title', 'No Title')
                    sources = layer.get('sources', [])
                    
                    # Try to find format from sources (assuming source is a cache)
                    fmt = "Unknown"
                    for src in sources:
                        if src in caches:
                            fmt = caches[src].get('format', fmt)
                            break
                            
                    layers.append({
                        'name': name,
                        'title': title,
                        'format': fmt
                    })
            return layers
        except Exception:
            self.logger.exception(f"Failed to read layers:")
            return []
