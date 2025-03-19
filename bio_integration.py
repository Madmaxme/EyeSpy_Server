#!/usr/bin/env python3
"""
Integration module for adding bio generation to the FaceUpload pipeline
This should be imported in FaceUpload.py
"""
import os
import threading
import traceback
from BioGenerator import BioGenerator
from RecordChecker import RecordChecker
from NameResolver import NameResolver
from db_connector import get_identity_analyses

def add_bio_generator_to_faceupload():
    """
    This function patches the FaceUpload.py module to add bio generation
    It should be called once during system initialization
    """
    try:
        import FaceUpload
        
        # Store the original process_single_face function
        original_process_single_face = FaceUpload.process_single_face
        
        # Create a wrapped version that adds bio generation
        def process_single_face_with_bio(image_file, timeout=300):
            """Wrapper around the original process_single_face that adds bio generation"""
            # Call the original function
            success = original_process_single_face(image_file, timeout)
            
            # If successful, generate bio in a separate thread
            if success:
                try:
                    # Extract the face_id from the image_file path
                    face_id = os.path.basename(image_file)
                    face_id = os.path.splitext(face_id)[0]  # Remove extension
                    
                    # Run bio generation in a separate thread to not block
                    threading.Thread(
                        target=process_face_with_records_then_bio,
                        args=(face_id,),
                        daemon=True
                    ).start()
                except Exception as e:
                    print(f"[BIO_INTEGRATION] Error setting up bio generation: {e}")
            
            return success
        
        # Replace the original function with our wrapped version
        FaceUpload.process_single_face = process_single_face_with_bio
        
        print("[BIO_INTEGRATION] Successfully integrated bio generation into FaceUpload")
        return True
    
    except Exception as e:
        print(f"[BIO_INTEGRATION] Failed to integrate bio generation: {e}")
        return False


def process_face_with_records_then_bio(face_id):
    """
    Process a face with records search first, then bio generation
    This function is called in a separate thread after face search completes
    
    Args:
        face_id: Face ID to process
    """
    try:
        print(f"[BIO_INTEGRATION] Starting processing for face ID: {face_id}")
        
        # Step 0: Get identity_analyses from database
        identity_analyses = get_identity_analyses(face_id)
        if not identity_analyses:
            print(f"[BIO_INTEGRATION] No identity analyses found for face ID: {face_id}")
            return

        # Getting canonical name first ensures it's determined consistently
        if identity_analyses:
            canonical_name = NameResolver.resolve_canonical_name(identity_analyses)
            print(f"[BIO_INTEGRATION] Canonical name resolved: '{canonical_name}'")
        else:
            print(f"[BIO_INTEGRATION] No identity analyses found for face ID: {face_id}")
            canonical_name = "Unknown Person"
        
        # Step 1: Check records first
        print(f"[BIO_INTEGRATION] Starting record checking for face ID: {face_id}")
        record_checker = RecordChecker()
        record_success = record_checker.process_face_record(face_id)
        
        if record_success:
            print(f"[BIO_INTEGRATION] Record checking complete for face ID: {face_id}")
        else:
            print(f"[BIO_INTEGRATION] Record checking failed or no records found for face ID: {face_id}")
        
        # Step 2: Generate bio after record checking
        print(f"[BIO_INTEGRATION] Starting bio generation for face ID: {face_id}")
        generator = BioGenerator()
        bio = generator.process_result_directory(face_id)
        
        if bio:
            print(f"[BIO_INTEGRATION] Bio generation complete for face ID: {face_id}")
        else:
            print(f"[BIO_INTEGRATION] Bio generation failed for face ID: {face_id}")
    
    except Exception as e:
        print(f"[BIO_INTEGRATION] Error in combined processing: {e}")
        traceback.print_exc()


# Patch to enable direct integration into the controller
def integrate_with_controller():
    """Add this to controller.py to activate bio generation"""
    # Import and patch FaceUpload
    add_bio_generator_to_faceupload()


if __name__ == "__main__":
    # For testing the integration
    add_bio_generator_to_faceupload()