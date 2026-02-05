import logging

class SeedOrchestrator:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.logger = logging.getLogger("SeedOrchestrator")
        self.seed_mgr = None

    def start_seeding(self, venv_dir=None):
        """Start the background seeding process"""
        try:
            import seed_manager
            self.seed_mgr = seed_manager.SeedManager(self.work_dir, venv_dir=venv_dir)
            self.seed_mgr.start_background_seed()
            self.logger.info("Seed manager started in background.")
        except Exception:
            self.logger.warning("Warning: Failed to start Seed Manager")
