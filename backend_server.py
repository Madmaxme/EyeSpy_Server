import os
import time
import json
import threading
import logging
import signal
import sys
from db_connector import init_connection_pool, validate_database_connection
from flask import Flask, request, jsonify
import FaceUpload
from bio_integration import integrate_with_controller as integrate_bio
from record_integration import integrate_records_with_controller as integrate_records
from werkzeug.utils import secure_filename


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Backend")

# Create Flask app
app = Flask(__name__)

# Initialize database pool
try:
    init_connection_pool()
    logger.info("Database connection pool initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize database connection: {str(e)}")
    # Don't fail the whole app if DB connection fails - Cloud Run needs the HTTP server to start

# Create directories for data storage
import tempfile
UPLOAD_FOLDER = tempfile.mkdtemp()  # Create a temporary directory for uploads that will be cleaned up
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_search_results")

# Create results directory if it doesn't exist
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)
    print(f"Created results directory: {RESULTS_DIR}")

# Update FaceUpload's results directory
FaceUpload.RESULTS_DIR = RESULTS_DIR

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# Initialize components and integrate functionality
def initialize_components():
    """Initialize all backend components"""
    components_status = {
        "record_checking": True,
        "bio_generation": True
    }
    
    # Initialize record checking FIRST if available
    try:
        # Check if RECORDS_API_KEY is set in environment
        if not os.getenv("RECORDS_API_KEY"):
            print("[BACKEND] Warning: RECORDS_API_KEY not set. Record checking will be disabled.")
        else:
            # Integrate record checking
            components_status["record_checking"] = integrate_records()
            print("[BACKEND] Record checking enabled and integrated.")
    except Exception as e:
        print(f"[BACKEND] Error initializing record checking: {e}")
    
    # Initialize bio generation AFTER record checking
    try:
        # Check if OPENAI_API_KEY is set in environment
        if not os.getenv("OPENAI_API_KEY"):
            print("[BACKEND] Warning: OPENAI_API_KEY not set. Bio generation will be disabled.")
        else:
            # Integrate bio generation
            components_status["bio_generation"] = integrate_bio()
            print("[BACKEND] Bio generation enabled and integrated.")
    except Exception as e:
        print(f"[BACKEND] Error initializing bio generation: {e}")
    
    # Print component status summary
    print("\n[BACKEND] System Components Status:")
    for component, status in components_status.items():
        status_str = "ENABLED" if status else "DISABLED"
        print(f"  - {component}: {status_str}")
    print("")

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
        
        # Process the face in a background thread to avoid blocking the API response
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
            
        success = FaceUpload.process_single_face(face_path)
        if success:
            logger.info(f"Successfully processed: {os.path.basename(face_path)}")
        else:
            logger.error(f"Failed to process: {os.path.basename(face_path)}")
    except Exception as e:
        logger.error(f"Error processing face: {str(e)}")
    finally:
        # Clean up the uploaded file after processing
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

    validate_database_connection()
    
    # Initialize components
    initialize_components()

    validate_database_connection()
    
    # Default port
    port = int(os.environ.get('PORT', 8080))
    
    # Parse command line arguments manually for tokens
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--token' and i+1 < len(args):
            os.environ['FACECHECK_API_TOKEN'] = args[i+1]
            i += 2
        elif args[i] == '--firecrawl-key' and i+1 < len(args):
            os.environ['FIRECRAWL_API_KEY'] = args[i+1]
            i += 2
        elif args[i] == '--port' and i+1 < len(args):
            port = int(args[i+1])
            i += 2
        else:
            i += 1
    
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