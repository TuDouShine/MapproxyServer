import os
import json
import logging
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta, tzinfo
from utils import load_json

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
        self.map_config_path = os.path.join(self.mapproxy_config_dir, "map_config.json")
        self.audit_log_path = os.path.join(self.work_dir, "logs", "config_audit.log")
        
        # Locate schema
        self.config_schema_path = self._locate_schema()
        if self.config_schema_path:
            self.logger.info(f"Found config schema at: {self.config_schema_path}")
        else:
            self.logger.warning("Config schema not found.")

    def _ensure_dirs(self) -> None:
        try:
            os.makedirs(self.mapproxy_config_dir, exist_ok=True)
        except Exception:
            self.logger.exception("Failed to create mapproxy_config directory in work_dir")
        try:
            os.makedirs(os.path.dirname(self.audit_log_path), exist_ok=True)
        except Exception:
            self.logger.exception("Failed to create logs directory in work_dir")
        try:
            legacy_seed_status = os.path.join(self.work_dir, "seed_status.json")
            migrated_seed_status = os.path.join(self.mapproxy_config_dir, "seed_status.json")
            if os.path.exists(legacy_seed_status):
                if not os.path.exists(migrated_seed_status):
                    os.replace(legacy_seed_status, migrated_seed_status)
                else:
                    legacy_mtime = os.path.getmtime(legacy_seed_status)
                    migrated_mtime = os.path.getmtime(migrated_seed_status)
                    if legacy_mtime > migrated_mtime:
                        os.replace(legacy_seed_status, migrated_seed_status)
                    else:
                        os.remove(legacy_seed_status)
        except Exception:
            self.logger.exception("Failed to migrate seed_status.json into mapproxy_config")
        try:
            legacy_deps_status = os.path.join(self.work_dir, "deps_status.json")
            migrated_deps_status = os.path.join(self.mapproxy_config_dir, "deps_status.json")
            if os.path.exists(legacy_deps_status):
                if not os.path.exists(migrated_deps_status):
                    os.replace(legacy_deps_status, migrated_deps_status)
                else:
                    legacy_mtime = os.path.getmtime(legacy_deps_status)
                    migrated_mtime = os.path.getmtime(migrated_deps_status)
                    if legacy_mtime > migrated_mtime:
                        os.replace(legacy_deps_status, migrated_deps_status)
                    else:
                        os.remove(legacy_deps_status)
        except Exception:
            self.logger.exception("Failed to migrate deps_status.json into mapproxy_config")

    def _now_iso(self, tz: tzinfo | None = None) -> str:
        if tz is None:
            dt = datetime.now()
        else:
            dt = datetime.now(timezone.utc).astimezone(tz).replace(tzinfo=None)
        return dt.isoformat(timespec="seconds")

    def _atomic_write_json(self, path: str, data: dict) -> None:
        self._ensure_dirs()
        target_dir = os.path.dirname(os.path.abspath(path))
        os.makedirs(target_dir, exist_ok=True)

        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=target_dir)
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                tmp_fd = None
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            self.logger.exception(f"Atomic write failed: {path}")
            raise
        finally:
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except Exception:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def _diff_values(self, old, new, prefix: str = "") -> list[dict]:
        changes: list[dict] = []
        if isinstance(old, dict) and isinstance(new, dict):
            keys = set(old.keys()) | set(new.keys())
            for k in sorted(keys, key=lambda x: str(x)):
                path = f"{prefix}.{k}" if prefix else str(k)
                if k not in old:
                    changes.append({"path": path, "from": None, "to": new.get(k)})
                    continue
                if k not in new:
                    changes.append({"path": path, "from": old.get(k), "to": None})
                    continue
                changes.extend(self._diff_values(old.get(k), new.get(k), path))
            return changes

        if old != new:
            changes.append({"path": prefix, "from": old, "to": new})
        return changes

    def _write_audit_log(self, entry: dict) -> None:
        self._ensure_dirs()
        try:
            line = json.dumps(entry, ensure_ascii=False)
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            self.logger.exception("Failed to write config audit log")

    def _normalize_advanced_config(self, config: dict) -> dict:
        defaults = self.get_default_advanced_config()
        merged = defaults
        if isinstance(config, dict):
            merged = {
                "concurrency": config.get("concurrency", defaults["concurrency"]),
                "retry": dict(defaults["retry"]),
                "alert": dict(defaults["alert"]),
            }
            retry_cfg = config.get("retry")
            if isinstance(retry_cfg, dict):
                for k, v in defaults["retry"].items():
                    merged["retry"][k] = retry_cfg.get(k, v)
            alert_cfg = config.get("alert")
            if isinstance(alert_cfg, dict):
                for k, v in defaults["alert"].items():
                    merged["alert"][k] = alert_cfg.get(k, v)

        try:
            merged["concurrency"] = int(merged.get("concurrency", defaults["concurrency"]))
        except Exception:
            merged["concurrency"] = defaults["concurrency"]

        retry = merged.get("retry", {})
        if isinstance(retry, dict):
            retry["enabled"] = bool(retry.get("enabled", defaults["retry"]["enabled"]))
            try:
                retry["max_retries"] = int(retry.get("max_retries", defaults["retry"]["max_retries"]))
            except Exception:
                retry["max_retries"] = defaults["retry"]["max_retries"]
            try:
                retry["interval"] = int(retry.get("interval", defaults["retry"]["interval"]))
            except Exception:
                retry["interval"] = defaults["retry"]["interval"]
            merged["retry"] = retry
        else:
            merged["retry"] = dict(defaults["retry"])

        alert = merged.get("alert", {})
        if isinstance(alert, dict):
            alert["enabled"] = bool(alert.get("enabled", defaults["alert"]["enabled"]))
            alert.pop("alert_email", None)
            alert.pop("alert_threshold", None)
            alert.pop("email", None)
            alert.pop("threshold", None)
            merged["alert"] = alert
        else:
            merged["alert"] = dict(defaults["alert"])

        return merged

    def validate_advanced_config(self, config: dict) -> None:
        normalized = self._normalize_advanced_config(config)
        conc = normalized.get("concurrency")
        if not isinstance(conc, int) or not (1 <= conc <= 16):
            raise ValueError("并发数必须在 1-16 之间")
        retry = normalized.get("retry", {})
        if not isinstance(retry, dict):
            raise ValueError("retry 配置结构无效")
        if not isinstance(retry.get("enabled"), bool):
            raise ValueError("retry.enabled 必须为布尔值")
        if not isinstance(retry.get("max_retries"), int) or retry.get("max_retries") < 0:
            raise ValueError("最大重试次数不能为负数")
        if not isinstance(retry.get("interval"), int) or retry.get("interval") < 0:
            raise ValueError("重试间隔不能为负数")
        alert = normalized.get("alert", {})
        if not isinstance(alert, dict):
            raise ValueError("alert 配置结构无效")
        if not isinstance(alert.get("enabled"), bool):
            raise ValueError("alert.enabled 必须为布尔值")

    def _load_legacy_launcher_config_raw(self) -> dict:
        raw = load_json(self.config_json_path)
        return raw if isinstance(raw, dict) else {}

    def _load_legacy_advanced_config_raw(self) -> dict:
        if not os.path.exists(self.advanced_config_path):
            return self.get_default_advanced_config()
        raw = load_json(self.advanced_config_path)
        return self._normalize_advanced_config(raw if isinstance(raw, dict) else {})

    def _filter_launcher_config_for_map_config(self, config: dict) -> dict:
        if not isinstance(config, dict):
            return {}
        banned = {"python_path", "selection_label", "host"}
        return {k: v for k, v in config.items() if k not in banned}

    def _build_map_config_from_legacy(self) -> dict:
        launcher = self._filter_launcher_config_for_map_config(self._load_legacy_launcher_config_raw())
        adv = self._load_legacy_advanced_config_raw()
        return {
            "version": 1,
            "updated_at": self._now_iso(),
            "launcher_config": launcher,
            "advanced_settings": adv,
        }

    def validate_launcher_config_for_map_config(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise ValueError("launcher_config 必须为对象")
        if "python_path" in config:
            raise ValueError("launcher_config 不允许包含 python_path")
        if "selection_label" in config:
            raise ValueError("launcher_config 不允许包含 selection_label")
        if "host" in config:
            raise ValueError("launcher_config 不允许包含 host")

        if "port" in config:
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

    def validate_map_config(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise ValueError("map_config.json 必须为 JSON 对象")
        ver = config.get("version")
        if not isinstance(ver, int) or ver < 1:
            raise ValueError("version 必须为 >= 1 的整数")
        updated_at = config.get("updated_at")
        if not isinstance(updated_at, str) or not updated_at:
            raise ValueError("updated_at 必须为非空字符串")

        launcher = config.get("launcher_config")
        if launcher is not None:
            if not isinstance(launcher, dict):
                raise ValueError("launcher_config 必须为对象")
            self.validate_launcher_config_for_map_config(launcher)

        adv = config.get("advanced_settings")
        if adv is not None:
            if not isinstance(adv, dict):
                raise ValueError("advanced_settings 必须为对象")
            self.validate_advanced_config(adv)

    def load_map_config(self) -> dict:
        if not os.path.exists(self.map_config_path):
            return self._build_map_config_from_legacy()

        raw = load_json(self.map_config_path)
        if not isinstance(raw, dict):
            return self._build_map_config_from_legacy()

        raw_launcher = raw.get("launcher_config") if isinstance(raw.get("launcher_config"), dict) else self._load_legacy_launcher_config_raw()
        merged = {
            "version": raw.get("version") if isinstance(raw.get("version"), int) else 1,
            "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else self._now_iso(),
            "launcher_config": self._filter_launcher_config_for_map_config(raw_launcher),
            "advanced_settings": self._normalize_advanced_config(raw.get("advanced_settings") if isinstance(raw.get("advanced_settings"), dict) else self._load_legacy_advanced_config_raw()),
        }
        try:
            self.validate_map_config(merged)
        except Exception:
            self.logger.exception("map_config.json 校验失败，回退为 legacy 配置")
            return self._build_map_config_from_legacy()
        return merged

    def ensure_map_config_exists(self, source: str = "init") -> dict:
        self._ensure_dirs()
        if os.path.exists(self.map_config_path):
            return self.load_map_config()

        cfg = self._build_map_config_from_legacy()
        self.validate_map_config(cfg)
        self._atomic_write_json(self.map_config_path, cfg)
        try:
            self._write_audit_log(
                {
                    "timestamp": cfg.get("updated_at", self._now_iso()),
                    "source": str(source or "init"),
                    "version": cfg.get("version", 1),
                    "changes": self._diff_values({}, cfg),
                }
            )
        except Exception:
            pass
        self._apply_hot_reload(cfg)
        return cfg

    def _apply_hot_reload(self, map_config: dict) -> None:
        try:
            adv = map_config.get("advanced_settings") if isinstance(map_config, dict) else None
            if not isinstance(adv, dict):
                return
            adv = self._normalize_advanced_config(adv)
            os.environ["MAPPROXY_SEED_CONCURRENCY"] = str(adv.get("concurrency", 2))
            retry = adv.get("retry", {})
            if isinstance(retry, dict) and bool(retry.get("enabled", False)):
                os.environ["MAPPROXY_SEED_MAX_RETRIES"] = str(int(retry.get("max_retries", 2)))
                os.environ["MAPPROXY_SEED_RETRY_BACKOFF"] = str(int(retry.get("interval", 5)))
            else:
                os.environ["MAPPROXY_SEED_MAX_RETRIES"] = "0"
            alert = adv.get("alert", {})
            os.environ["MAPPROXY_SEED_ALERT_ENABLED"] = "true" if isinstance(alert, dict) and bool(alert.get("enabled", False)) else "false"
        except Exception:
            self.logger.exception("Failed to apply hot reload for config")

    def update_map_config(self, launcher_update: dict | None = None, advanced_update: dict | None = None, source: str = "unknown") -> dict:
        self._ensure_dirs()
        old_cfg = self.load_map_config()
        new_cfg = dict(old_cfg)
        new_cfg["launcher_config"] = dict(old_cfg.get("launcher_config") or {}) if isinstance(old_cfg.get("launcher_config"), dict) else {}
        new_cfg["advanced_settings"] = self._normalize_advanced_config(old_cfg.get("advanced_settings") if isinstance(old_cfg.get("advanced_settings"), dict) else {})

        if launcher_update is not None:
            if not isinstance(launcher_update, dict):
                raise ValueError("launcher_update 必须为对象")
            self.validate_launcher_config(launcher_update)
            new_cfg["launcher_config"] = self._filter_launcher_config_for_map_config(launcher_update)
            self.validate_launcher_config_for_map_config(new_cfg["launcher_config"])

        if advanced_update is not None:
            if not isinstance(advanced_update, dict):
                raise ValueError("advanced_update 必须为对象")
            self.validate_advanced_config(advanced_update)
            new_cfg["advanced_settings"] = self._normalize_advanced_config(advanced_update)

        old_version = old_cfg.get("version") if isinstance(old_cfg.get("version"), int) else 1
        new_cfg["version"] = int(old_version) + 1
        new_cfg["updated_at"] = self._now_iso()

        self.validate_map_config(new_cfg)
        self._atomic_write_json(self.map_config_path, new_cfg)

        changes = self._diff_values(old_cfg, new_cfg)
        self._write_audit_log(
            {
                "timestamp": new_cfg["updated_at"],
                "source": str(source or "unknown"),
                "version": new_cfg["version"],
                "changes": changes,
            }
        )
        self._apply_hot_reload(new_cfg)
        return new_cfg

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

        try:
            self.ensure_map_config_exists(source="config_manager.init_configs")
        except Exception:
            self.logger.exception("Failed to initialize map_config.json")

    def load_launcher_config(self):
        """Load GUI launcher config"""
        try:
            map_cfg = self.load_map_config()
            raw = map_cfg.get("launcher_config")
        except Exception:
            self.logger.exception("读取 map_config.json 失败，回退为 legacy 配置")
            raw = None
        if raw is None:
            raw = self._load_legacy_launcher_config_raw()
        config = raw if isinstance(raw, dict) else {}
        try:
            legacy = self._load_legacy_launcher_config_raw()
            if isinstance(legacy, dict):
                if "python_path" in legacy and "python_path" not in config:
                    config["python_path"] = legacy.get("python_path")
                if "selection_label" in legacy and "selection_label" not in config:
                    config["selection_label"] = legacy.get("selection_label")
        except Exception:
            pass

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
        try:
            map_cfg = self.load_map_config()
            adv = map_cfg.get("advanced_settings")
            if isinstance(adv, dict):
                return self._normalize_advanced_config(adv)
        except Exception:
            self.logger.exception("读取 map_config.json 中的高级设置失败，回退为 legacy 文件")
        return self._load_legacy_advanced_config_raw()

    def save_advanced_config(self, config_data, source: str = "advanced_settings"):
        """Save advanced settings"""
        self.validate_advanced_config(config_data)
        self.update_map_config(advanced_update=config_data, source=source)

    def save_launcher_config(self, config_data, source: str = "launcher"):
        """Save GUI launcher config"""
        self.validate_launcher_config(config_data)
        self.update_map_config(launcher_update=config_data, source=source)

    def validate_launcher_config(self, config):
        """Validate launcher configuration"""
        required_fields = ["python_path", "port"]
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
        allow_external_access = bool(launcher_conf.get("allow_external_access", False))
        host = "0.0.0.0" if allow_external_access else "127.0.0.1"
        port_raw = launcher_conf.get("port", 8080)
        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            port = 8080
        return {
            "port": port,
            "host": host,
            "python_path": launcher_conf.get("python_path"),
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
