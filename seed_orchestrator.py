import os
import sys
import logging
import importlib

class SeedOrchestrator:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.logger = logging.getLogger("SeedOrchestrator")
        self.seed_mgr = None

    def start_seeding(self, venv_dir=None):
        """Start the background seeding process"""
        try:
            # Ensure work_dir is in sys.path to import seed_manager from there
            if self.work_dir not in sys.path:
                sys.path.insert(0, self.work_dir)
            
            # Dynamic import to handle cases where file is just deployed
            try:
                import seed_manager
                importlib.reload(seed_manager)
            except ImportError:
                self.logger.warning("seed_manager module not found in work directory.")
                return

            self.seed_mgr = seed_manager.SeedManager(self.work_dir, venv_dir=venv_dir)
            self.seed_mgr.start_background_seed()
            self.logger.info("Seed manager started in background.")
        except Exception:
            self.logger.warning("Warning: Failed to start Seed Manager")
