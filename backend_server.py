import os
import time
import json
import threading
import logging
import signal
import sys
import tempfile
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

# Import the controller instead of individual components
import controller

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Backend")

# Create Flask app
app = Flask(__name__)

# Create a temporary directory for uploads
UPLOAD_FOLDER = tempfile.mkdtemp()

# Configure Flask app settings
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# API routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok"})

@app.route('/', methods=['GET'])
def root():
    """Root endpoint for basic health check"""
    return jsonify({"status": "ok", "message": "EyeSpy server is running"})

@app.route('/api/upload_face', methods=['POST'])
def upload_face():
    """
    Endpoint to receive and process face images from the client
    Expects a face image file in the POST request
    """
    if 'face' not in request.files:
        return jsonify({"error": "No face file part in the request"}), 400
    
    face_file = request.files['face']
    
    if face_file.filename == '':
        return jsonify({"error": "No face file selected"}), 400
    
    if face_file:
        # Generate secure filename
        filename = secure_filename(face_file.filename)
        timestamp = int(time.time())
        filename = f"face_{timestamp}_{filename}"
        
        # Save the file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        face_file.save(file_path)
        
        # Extract face_id from filename
        face_id = os.path.splitext(filename)[0]
        
        # Process the face in a background thread using the controller
        thread = threading.Thread(
            target=process_face_thread,
            args=(file_path, face_id),
            daemon=True
        )
        thread.start()
        
        return jsonify({
            "status": "success", 
            "message": "Face uploaded and processing started",
            "file_id": filename
        })

def process_face_thread(face_path, face_id=None):
    """Process a face in a background thread"""
    logger.info(f"Starting processing for: {os.path.basename(face_path)}")
    try:
        # If face_id not provided, extract from path
        if face_id is None:
            face_id = os.path.splitext(os.path.basename(face_path))[0]
            
        # IMPORTANT: Process the face directly with FaceUpload FIRST
        # This prevents the file deletion race condition
        try:
            import FaceUpload
            logger.info(f"Directly processing face with FaceUpload: {os.path.basename(face_path)}")
            success = FaceUpload.process_single_face(face_path)
            
            if success:
                logger.info(f"Successfully processed face with FaceUpload: {os.path.basename(face_path)}")
                
                # Now queue additional processing (bio and records) through the controller
                # Just pass the face_id since we don't need the file anymore
                controller.process_additional_steps(face_id)
            else:
                logger.error(f"Failed to process face with FaceUpload: {os.path.basename(face_path)}")
        except Exception as e:
            logger.error(f"Error processing face with FaceUpload: {str(e)}")
            success = False
            
    except Exception as e:
        logger.error(f"Error in face processing thread: {str(e)}")
        success = False
    finally:
        # Clean up the uploaded file after FaceUpload has processed it
        try:
            if os.path.exists(face_path):
                os.remove(face_path)
                logger.info(f"Removed temporary file: {os.path.basename(face_path)}")
        except Exception as e:
            logger.error(f"Error removing temporary file: {str(e)}")

def main():
    """Main function to start the backend server"""
    # Print banner
    print("""
    ╔═════════════════════════════════════════════╗
    ║          EYE SPY BACKEND SERVER             ║
    ║       Face Processing & Identity Search     ║
    ╚═════════════════════════════════════════════╝
    """)
    
    # First, create the controller instance to load .env file
    # But don't fully initialize components yet
    controller.controller  # This ensures the controller singleton is created
    
    # Parse command line arguments manually for tokens BEFORE full initialization
    print("Parsing command line arguments...")
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--token' and i+1 < len(args):
            os.environ['FACECHECK_API_TOKEN'] = args[i+1]
            print(f"Set FACECHECK_API_TOKEN from command line")
            i += 2
        elif args[i] == '--firecrawl-key' and i+1 < len(args):
            os.environ['FIRECRAWL_API_KEY'] = args[i+1]
            print(f"Set FIRECRAWL_API_KEY from command line")
            i += 2
        elif args[i] == '--port' and i+1 < len(args):
            os.environ['PORT'] = args[i+1]
            print(f"Set PORT from command line to {args[i+1]}")
            i += 2
        else:
            i += 1
    
    # NOW initialize the controller with reloaded config
    if not controller.initialize(reload_config=True):
        print("Failed to initialize controller, exiting")
        return
    
    # Default port
    port = int(os.environ.get('PORT', 8080))
    
    # Set up signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down EyeSpy server...")
        controller.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start the server
    print(f"[BACKEND] Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)


# This ensures app will run whether imported as a module or run directly
if __name__ == "__main__":
    main()
else:
    # When running in a container (like Cloud Run), ensure we listen on the correct port
    port = int(os.environ.get('PORT', 8080))
    print(f"[BACKEND] Module imported. Starting server on port {port}...")
    # Do not call app.run() here - it will be called by the container
    # Instead, we make the Flask app available for gunicorn or other WSGI servers