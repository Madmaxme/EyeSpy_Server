#!/usr/bin/env python3
"""
controller.py - Centralized controller for the EyeSpy system

This module replaces the monkey patching approach with a clean, centralized
controller that manages all components and their interactions.
"""

import os
import threading
import logging
import time
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Controller")

class ConfigManager:
    """Centralized configuration management for the EyeSpy system"""
    
    def __init__(self):
        """Initialize configuration by loading environment variables"""
        # Load environment variables from .env file with absolute path and override
        dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        load_dotenv(dotenv_path=dotenv_path, override=True)
        logger.info(f"Loaded environment from {dotenv_path}")
        
        # Store configuration
        self.config = {}
        self._load_config()
    
    def reload_config(self):
        """Reload configuration from environment variables"""
        logger.info("Reloading configuration from environment variables")
        self._load_config()
        return self
        
    def _load_config(self):
        """Load configuration from environment variables"""
        # API Keys
        self.config["FACECHECK_API_TOKEN"] = os.getenv("FACECHECK_API_TOKEN", "")
        self.config["FIRECRAWL_API_KEY"] = os.getenv("FIRECRAWL_API_KEY", "")
        self.config["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")
        self.config["RECORDS_API_KEY"] = os.getenv("RECORDS_API_KEY", "")
        self.config["ZYTE_API_KEY"] = os.getenv("ZYTE_API_KEY", "")
        
        # Database config
        self.config["DATABASE_URL"] = os.getenv("DATABASE_URL", "")
        self.config["DB_USER"] = os.getenv("DB_USER", "")
        self.config["DB_PASS"] = os.getenv("DB_PASS", "")
        self.config["DB_NAME"] = os.getenv("DB_NAME", "")
        self.config["DB_HOST"] = os.getenv("DB_HOST", "")
        self.config["DB_PORT"] = os.getenv("DB_PORT", "")
        self.config["INSTANCE_CONNECTION_NAME"] = os.getenv("INSTANCE_CONNECTION_NAME", "")
        
        # Server config
        self.config["PORT"] = int(os.getenv("PORT", "8080"))
        self.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "")
        self.config["RESULTS_DIR"] = os.getenv("RESULTS_DIR", "")
        
        # Log the configuration (without sensitive values)
        self._log_config()
    
    def _log_config(self):
        """Log the loaded configuration without sensitive values"""
        safe_config = self.config.copy()
        
        # Mask sensitive values
        for key in ["FACECHECK_API_TOKEN", "FIRECRAWL_API_KEY", "OPENAI_API_KEY", 
                   "RECORDS_API_KEY", "ZYTE_API_KEY", "DB_PASS"]:
            if safe_config.get(key):
                safe_config[key] = "********"
        
        logger.info(f"Loaded configuration: {safe_config}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            The configuration value or default
        """
        return self.config.get(key, default)
    
    def validate_required_keys(self, keys: list) -> bool:
        """
        Validate that all required keys are present
        
        Args:
            keys: List of required configuration keys
            
        Returns:
            True if all keys are present, False otherwise
        """
        missing_keys = []
        for key in keys:
            if not self.config.get(key):
                missing_keys.append(key)
        
        if missing_keys:
            logger.warning(f"Missing required configuration keys: {missing_keys}")
            return False
        
        return True


class EyeSpyController:
    """
    Central controller for the EyeSpy system
    
    This class coordinates all components, manages configuration, and defines
    the processing flow between components.
    """
    
    def __init__(self):
        """Initialize the controller and its components"""
        self.config = ConfigManager()
        self.components = {}
        self.db_connector = None
        self.face_uploader = None
        self.bio_generator = None
        self.record_checker = None
        self.name_resolver = None
        self.initialized = False
        
        # Processing queue for background tasks
        self.processing_queue = []
        self.queue_lock = threading.Lock()
        self.shutdown_requested = False
    
    def initialize(self, reload_config=False) -> bool:
        """
        Initialize all components
        
        Args:
            reload_config: Whether to reload configuration from environment variables
            
        Returns:
            True if initialization was successful, False otherwise
        """
        if self.initialized and not reload_config:
            logger.info("Controller already initialized, skipping")
            return True
            
        # Reload configuration if requested
        if reload_config:
            # Reload configuration
            self.config = self.config.reload_config()
            logger.info("Configuration reloaded from environment variables")
            
        try:
            logger.info("Initializing EyeSpy controller")
            
            # Initialize database connector
            try:
                import db_connector
                self.db_connector = db_connector
                db_connector.init_connection_pool()
                db_connector.validate_database_connection()
                logger.info("Database connector initialized")
            except Exception as e:
                logger.error(f"Failed to initialize database connector: {e}")
                return False
            
            # Initialize name resolver
            try:
                from NameResolver import NameResolver
                self.name_resolver = NameResolver
                logger.info("Name resolver initialized")
            except Exception as e:
                logger.error(f"Failed to initialize name resolver: {e}")
                return False
            
            # Initialize FaceUpload with config
            try:
                import FaceUpload
                # Inject configuration
                if self.config.get("FACECHECK_API_TOKEN"):
                    FaceUpload.APITOKEN = self.config.get("FACECHECK_API_TOKEN")
                if self.config.get("FIRECRAWL_API_KEY"):
                    FaceUpload.FIRECRAWL_API_KEY = self.config.get("FIRECRAWL_API_KEY")
                if self.config.get("ZYTE_API_KEY"):
                    FaceUpload.ZYTE_API_KEY = self.config.get("ZYTE_API_KEY")
                    FaceUpload.ZYTE_AVAILABLE = True
                if self.config.get("OPENAI_API_KEY"):
                    FaceUpload.OPENAI_API_KEY = self.config.get("OPENAI_API_KEY")
                
                self.face_uploader = FaceUpload
                logger.info("FaceUpload initialized")
            except Exception as e:
                logger.error(f"Failed to initialize FaceUpload: {e}")
                return False
            
            # Initialize RecordChecker if API key is available
            records_enabled = False
            if self.config.get("RECORDS_API_KEY"):
                try:
                    from RecordChecker import RecordChecker
                    self.record_checker = RecordChecker(api_key=self.config.get("RECORDS_API_KEY"))
                    records_enabled = True
                    logger.info("RecordChecker initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize RecordChecker: {e}")
            else:
                logger.warning("RECORDS_API_KEY not set, record checking disabled")
            
            # Initialize BioGenerator if API key is available
            bio_enabled = False
            if self.config.get("OPENAI_API_KEY"):
                try:
                    from BioGenerator import BioGenerator
                    self.bio_generator = BioGenerator(api_key=self.config.get("OPENAI_API_KEY"))
                    bio_enabled = True
                    logger.info("BioGenerator initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize BioGenerator: {e}")
            else:
                logger.warning("OPENAI_API_KEY not set, bio generation disabled")
            
            # Start background processing thread
            processing_thread = threading.Thread(
                target=self._background_processor,
                daemon=True
            )
            processing_thread.start()
            logger.info("Background processor started")
            
            # Store component status
            self.components["db_connector"] = True
            self.components["face_uploader"] = True
            self.components["name_resolver"] = True
            self.components["record_checker"] = records_enabled
            self.components["bio_generator"] = bio_enabled
            
            self.initialized = True
            logger.info("EyeSpy controller initialized successfully")
            
            # Print component status summary
            self._log_component_status()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize controller: {e}")
            return False
    
    def _log_component_status(self):
        """Log the status of all components"""
        logger.info("System Components Status:")
        for component, status in self.components.items():
            status_str = "ENABLED" if status else "DISABLED"
            logger.info(f"  - {component}: {status_str}")
    
    def process_face(self, image_path: str) -> bool:
        """
        Process a face image through the complete pipeline
        
        This method replaces the monkey-patched approach with a clean,
        centralized processing flow.
        
        Args:
            image_path: Path to the face image file
            
        Returns:
            True if the face was queued for processing, False otherwise
        """
        if not self.initialized:
            logger.error("Controller not initialized, cannot process face")
            return False
        
        if not os.path.exists(image_path):
            logger.error(f"Face image not found: {image_path}")
            return False
        
        # Extract face_id from the image path
        face_id = os.path.splitext(os.path.basename(image_path))[0]
        
        try:
            # Queue the face for processing
            with self.queue_lock:
                self.processing_queue.append({
                    "image_path": image_path,
                    "face_id": face_id,
                    "timestamp": time.time()
                })
            
            logger.info(f"Face queued for processing: {face_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error queueing face for processing: {e}")
            return False
    
    def process_additional_steps(self, face_id: str) -> bool:
        """
        Process additional steps for a face (bio and records) after FaceUpload has already run
        
        Args:
            face_id: Face ID to process
            
        Returns:
            True if processing was queued, False otherwise
        """
        if not self.initialized:
            logger.error("Controller not initialized, cannot process additional steps")
            return False
        
        try:
            # Trigger record checking and bio generation if enabled
            logger.info(f"Processing additional steps for face: {face_id}")
            
            # Step 1: Process records if record checker is available
            if self.components.get("record_checker") and self.record_checker:
                try:
                    logger.info(f"Processing records for face: {face_id}")
                    
                    # Do this in a separate thread to avoid blocking
                    threading.Thread(
                        target=self._process_records,
                        args=(face_id,),
                        daemon=True
                    ).start()
                    
                except Exception as e:
                    logger.error(f"Error starting record processing: {e}")
            
            # Step 2: Generate bio if bio generator is available
            if self.components.get("bio_generator") and self.bio_generator:
                try:
                    logger.info(f"Queueing bio generation for face: {face_id}")
                    
                    # Do this in a separate thread to avoid blocking
                    threading.Thread(
                        target=self._generate_bio,
                        args=(face_id,),
                        daemon=True
                    ).start()
                    
                except Exception as e:
                    logger.error(f"Error starting bio generation: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing additional steps for face {face_id}: {e}")
            return False
    
    def _process_records(self, face_id: str):
        """Process records for a face in a separate thread"""
        try:
            logger.info(f"Starting record processing for face: {face_id}")
            record_success = self.record_checker.process_face_record(face_id)
            
            if record_success:
                logger.info(f"Records successfully processed for face: {face_id}")
            else:
                logger.warning(f"No records found for face: {face_id}")
                
        except Exception as e:
            logger.error(f"Error processing records: {e}")
    
    def _generate_bio(self, face_id: str):
        """Generate bio for a face in a separate thread"""
        try:
            # Wait a bit to ensure records processing has a chance to complete
            time.sleep(2)
            
            logger.info(f"Starting bio generation for face: {face_id}")
            bio = self.bio_generator.process_result_directory(face_id)
            
            if bio:
                logger.info(f"Bio successfully generated for face: {face_id}")
            else:
                logger.warning(f"Failed to generate bio for face: {face_id}")
                
        except Exception as e:
            logger.error(f"Error generating bio: {e}")
    
    def _background_processor(self):
        """Background thread that processes queued faces"""
        logger.info("Background processor started")
        
        while not self.shutdown_requested:
            # Check if there are any faces to process
            with self.queue_lock:
                if self.processing_queue:
                    # Get the next face to process
                    face_item = self.processing_queue.pop(0)
                else:
                    # No faces to process, sleep for a bit
                    face_item = None
            
            if face_item:
                # Process the face
                self._process_face_item(face_item)
            else:
                # Sleep for a bit before checking again
                time.sleep(1)
    
    def _process_face_item(self, face_item: Dict[str, Any]):
        """
        Process a single face item through the complete pipeline
        
        Args:
            face_item: Dictionary containing face processing information
        """
        image_path = face_item["image_path"]
        face_id = face_item["face_id"]
        
        logger.info(f"Processing face: {face_id}")
        
        try:
            # Step 1: Process face with FaceUpload
            success = self.face_uploader.process_single_face(image_path)
            
            if not success:
                logger.error(f"Failed to process face with FaceUpload: {face_id}")
                return
            
            logger.info(f"Face successfully processed with FaceUpload: {face_id}")
            
            # Step 2: Process records if record checker is available
            if self.components.get("record_checker") and self.record_checker:
                try:
                    logger.info(f"Processing records for face: {face_id}")
                    record_success = self.record_checker.process_face_record(face_id)
                    
                    if record_success:
                        logger.info(f"Records successfully processed for face: {face_id}")
                    else:
                        logger.warning(f"No records found for face: {face_id}")
                        
                except Exception as e:
                    logger.error(f"Error processing records: {e}")
            
            # Step 3: Generate bio if bio generator is available
            if self.components.get("bio_generator") and self.bio_generator:
                try:
                    logger.info(f"Generating bio for face: {face_id}")
                    bio = self.bio_generator.process_result_directory(face_id)
                    
                    if bio:
                        logger.info(f"Bio successfully generated for face: {face_id}")
                    else:
                        logger.warning(f"Failed to generate bio for face: {face_id}")
                        
                except Exception as e:
                    logger.error(f"Error generating bio: {e}")
            
            logger.info(f"Face processing complete: {face_id}")
            
        except Exception as e:
            logger.error(f"Error processing face {face_id}: {e}")
    
    def shutdown(self):
        """Shut down the controller and all components"""
        logger.info("Shutting down controller")
        self.shutdown_requested = True
        
        # Wait for background processor to finish
        logger.info("Waiting for background processor to finish")
        for _ in range(5):  # Wait up to 5 seconds
            if not self.processing_queue:
                break
            time.sleep(1)
        
        # Shut down database connection
        if self.db_connector and hasattr(self.db_connector, "stop_cloud_sql_proxy"):
            try:
                self.db_connector.stop_cloud_sql_proxy()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")
        
        logger.info("Controller shutdown complete")


# Singleton instance for global access
controller = EyeSpyController()

def initialize(reload_config=False):
    """Initialize the controller and all components"""
    return controller.initialize(reload_config=reload_config)

def process_face(image_path: str) -> bool:
    """Process a face image through the complete pipeline"""
    return controller.process_face(image_path)

def process_additional_steps(face_id: str) -> bool:
    """Process additional steps for a face (bio and records)"""
    return controller.process_additional_steps(face_id)

def shutdown():
    """Shut down the controller and all components"""
    controller.shutdown()


def get_config(key, default=None):
    """Get a configuration value from the controller"""
    return controller.config.get(key, default)


# Direct initialization when run as a script
if __name__ == "__main__":
    initialize()