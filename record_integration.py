#!/usr/bin/env python3
"""
record_integration.py - Integration module for adding record checking to the EyeSpy system
This should be imported in controller.py
"""

import os
from RecordChecker import RecordChecker
from db_connector import init_connection_pool

def integrate_records_with_controller():
    """
    Integrate record checking into the EyeSpy system
    This should be called from controller.py during initialization
    """
    try:
        # Initialize database connection pool 
        init_connection_pool()
        
        # Check if RECORDS_API_KEY is set in environment
        if not os.getenv("RECORDS_API_KEY"):
            print("[RECORDS_INTEGRATION] Warning: RECORDS_API_KEY not set. Record checking will be disabled.")
            return False
            
        # Get optional provider setting
        provider = os.getenv("RECORDS_PROVIDER")
        if provider:
            print(f"[RECORDS_INTEGRATION] Using {provider} as records provider")
        
        # Validate record checker can be initialized
        try:
            checker = RecordChecker()
            print("[RECORDS_INTEGRATION] Record checker initialized successfully")
        except Exception as e:
            print(f"[RECORDS_INTEGRATION] Error initializing RecordChecker: {e}")
            return False
        
        print("[RECORDS_INTEGRATION] Record checking successfully integrated with the system")
        return True
            
    except Exception as e:
        print(f"[RECORDS_INTEGRATION] Error initializing record checking: {e}")
        return False

def direct_process_face(face_id):
    """
    Process a face with record checking directly (not through integration)
    This is useful for manual processing or backfilling records
    
    Args:
        face_id: Face ID to process
    
    Returns:
        Boolean indicating if record checking was successful
    """
    try:
        checker = RecordChecker()
        return checker.process_face_record(face_id)
    except Exception as e:
        print(f"[RECORDS_INTEGRATION] Error processing face ID {face_id}: {e}")
        return False

if __name__ == "__main__":
    # For testing the integration
    integrate_records_with_controller()