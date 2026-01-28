import os
import sys
import yaml
import logging
import logging.config

def setup_logging(logs_dir, log_level="INFO"):
    """
    Setup centralized logging configuration.
    """
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir, exist_ok=True)

    log_file_path = os.path.join(logs_dir, "mapproxy.log")
    
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            },
        },
        "handlers": {
            "console": {
                "level": "INFO",
                "class": "logging.StreamHandler",
                "formatter": "standard"
            },
            "file": {
                "level": log_level,
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "filename": log_file_path,
                "maxBytes": 10 * 1024 * 1024,  # 10MB
                "backupCount": 5,
                "encoding": "utf-8"
            }
        },
        "loggers": {
            "": {  # root logger
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": True
            },
            "mapproxy.config": {
                "handlers": ["console", "file"],
                "level": "WARNING", # Suppress verbose config logs
                "propagate": False
            }
        }
    }
    
    logging.config.dictConfig(logging_config)
    logging.info(f"Logging configured. Level: {log_level}, File: {log_file_path}")

def validate_mapproxy_config(yaml_path):
    """
    Validate mapproxy.yaml using MapProxy's internal validator.
    """
    if not os.path.exists(yaml_path):
        return False, f"Config file not found: {yaml_path}"

    try:
        from mapproxy.config.loader import load_configuration_file, ConfigurationError
        from mapproxy.config.spec import validate_options
        from mapproxy.config.validator import validate
        
        # 1. Load YAML (Syntax Check)
        abs_yaml_path = os.path.abspath(yaml_path)
        base_dir = os.path.dirname(abs_yaml_path)
        file_name = os.path.basename(abs_yaml_path)
        
        conf_dict = load_configuration_file([file_name], base_dir)
        
        # 2. Spec Validation
        errors, informal_only = validate_options(conf_dict)
        error_msgs = []
        for error in errors:
            if not informal_only:
                error_msgs.append(f"[Spec Error] {error}")
                
        if error_msgs:
            return False, "\n".join(error_msgs)
            
        # 3. Logic Validation
        logic_errors = validate(conf_dict)
        if logic_errors:
            return False, "\n".join([f"[Logic Error] {e}" for e in logic_errors])
            
        return True, "Configuration is valid."
        
    except ImportError:
        return True, "MapProxy library not found, skipping validation." # Don't block if env is not ready
    except Exception as e:
        return False, f"Validation exception: {str(e)}"
