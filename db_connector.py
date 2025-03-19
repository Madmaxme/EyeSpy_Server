import os
import psycopg2
import subprocess
import atexit
import time
import platform
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from urllib.parse import urlparse
import json
import datetime
import logging
import tempfile

_pool_initialized = False


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Connection pool
pool = None
proxy_process = None
proxy_binary_path = None

def download_proxy_if_needed():
    """Download the Cloud SQL proxy if it doesn't exist"""
    global proxy_binary_path
    
    # Create temp directory for proxy if it doesn't exist
    temp_dir = os.path.join(tempfile.gettempdir(), 'cloud_sql_proxy')
    os.makedirs(temp_dir, exist_ok=True)
    
    # Determine the right binary for this platform
    system = platform.system().lower()
    if system == 'darwin':
        binary_name = 'cloud-sql-proxy.darwin.amd64'
        download_url = 'https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.10.0/cloud-sql-proxy.darwin.amd64'
    elif system == 'linux':
        binary_name = 'cloud-sql-proxy.linux.amd64'
        download_url = 'https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.10.0/cloud-sql-proxy.linux.amd64'
    elif system == 'windows':
        binary_name = 'cloud-sql-proxy.windows.amd64.exe'
        download_url = 'https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.10.0/cloud-sql-proxy.windows.amd64.exe'
    else:
        logger.error(f"Unsupported platform: {system}")
        return None
    
    proxy_binary_path = os.path.join(temp_dir, binary_name)
    
    # Check if proxy already exists
    if os.path.exists(proxy_binary_path):
        logger.info(f"Cloud SQL Proxy already exists at {proxy_binary_path}")
        return proxy_binary_path
    
    # Download the proxy
    logger.info(f"Downloading Cloud SQL Proxy from {download_url}")
    try:
        import requests
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        with open(proxy_binary_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Make executable
        os.chmod(proxy_binary_path, 0o755)
        logger.info(f"Cloud SQL Proxy downloaded successfully to {proxy_binary_path}")
        return proxy_binary_path
    except Exception as e:
        logger.error(f"Failed to download Cloud SQL Proxy: {str(e)}")
        return None

def start_cloud_sql_proxy(instance_connection_name):
    """
    Start the Cloud SQL Auth Proxy as a subprocess.
    Returns the local port number the proxy is listening on.
    """
    global proxy_process
    
    # Make sure we have the proxy binary
    if not proxy_binary_path:
        proxy_path = download_proxy_if_needed()
        if not proxy_path:
            logger.error("Could not obtain Cloud SQL Proxy.")
            return None
    else:
        proxy_path = proxy_binary_path
    
    # Set up local TCP port for the proxy (e.g., 5433 to avoid conflicts with local PostgreSQL)
    local_port = 5433
    
    try:
        # Start the proxy process - updated command format for v2.x
        cmd = [proxy_path, instance_connection_name, f"--port={local_port}"]
        logger.info(f"Starting Cloud SQL Proxy with command: {' '.join(cmd)}")
        
        # Start the proxy and redirect output
        proxy_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Register cleanup function to terminate proxy when the program exits
        atexit.register(stop_cloud_sql_proxy)
        
        # Wait a moment for the proxy to start
        time.sleep(2)
        
        # Check if the process is still running
        if proxy_process.poll() is not None:
            # Process terminated already
            stdout, stderr = proxy_process.communicate()
            logger.error(f"Cloud SQL Proxy failed to start: {stderr}")
            return None
        
        logger.info(f"Cloud SQL Proxy started. Listening on localhost:{local_port}")
        return local_port
        
    except Exception as e:
        logger.error(f"Error starting Cloud SQL Proxy: {e}")
        return None

def stop_cloud_sql_proxy():
    """Stop the Cloud SQL Auth Proxy process if it's running."""
    global proxy_process
    if proxy_process:
        logger.info("Stopping Cloud SQL Proxy...")
        try:
            # Try graceful termination first
            proxy_process.terminate()
            try:
                proxy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't terminate
                proxy_process.kill()
            
            logger.info("Cloud SQL Proxy stopped.")
        except Exception as e:
            logger.error(f"Error stopping Cloud SQL Proxy: {e}")
        finally:
            proxy_process = None

def is_running_in_cloud():
    """Detect if running in Cloud Run or similar cloud environment"""
    # In Cloud Run, this directory exists and contains the socket
    return os.path.exists('/cloudsql')

def init_connection_pool():
    """Initialize the connection pool."""
    global pool, _pool_initialized

    if pool is not None and _pool_initialized:
        logger.info("Database connection pool already initialized, reusing existing pool")
        return pool
    
    
    # Check for DATABASE_URL first (new format)
    database_url = os.environ.get("DATABASE_URL")
    
    if database_url:
        # Parse the DATABASE_URL
        parsed = urlparse(database_url)
        
        # Extract components from the URL
        db_user = parsed.username
        db_pass = parsed.password
        db_name = parsed.path.lstrip('/')
        
        # Parse query parameters
        query_params = {}
        if parsed.query:
            query_params = dict(q.split('=') for q in parsed.query.split('&'))
        
        # Check if Cloud SQL Unix socket is specified
        if 'host' in query_params and query_params['host'].startswith('/cloudsql/'):
            instance_connection_name = query_params['host'].replace('/cloudsql/', '')
            
            # Check if we're running in Cloud Run or similar
            if is_running_in_cloud():
                # Use Unix socket in cloud environment
                db_host = query_params['host']
                conn_string = f"host={db_host} dbname={db_name} user={db_user} password={db_pass}"
                logger.info(f"Connecting to Cloud SQL via socket: {db_host}")
            else:
                # We're running locally - start the proxy
                local_port = start_cloud_sql_proxy(instance_connection_name)
                if local_port:
                    db_host = 'localhost'
                    conn_string = f"host={db_host} port={local_port} dbname={db_name} user={db_user} password={db_pass}"
                    logger.info(f"Connecting to Cloud SQL via proxy on localhost:{local_port}")
                else:
                    # Fallback to direct connection if proxy fails
                    logger.error("Cloud SQL Proxy failed to start. Cannot connect to Google Cloud SQL database.")
                    raise Exception("Failed to connect to Google Cloud SQL database. Proxy initialization failed.")
        else:
            # Regular TCP connection
            db_host = parsed.hostname or 'localhost'
            db_port = parsed.port or 5432
            conn_string = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_pass}"
    else:
        # Fall back to individual environment variables (old format)
        db_user = os.environ.get("DB_USER")
        db_pass = os.environ.get("DB_PASS")
        db_name = os.environ.get("DB_NAME")
        instance_connection_name = os.environ.get("INSTANCE_CONNECTION_NAME")
        
        if instance_connection_name:
            if is_running_in_cloud():
                # Use Unix socket in cloud environment
                db_host = f"/cloudsql/{instance_connection_name}"
                conn_string = f"host={db_host} dbname={db_name} user={db_user} password={db_pass}"
                logger.info(f"Connecting to Cloud SQL via socket: {db_host}")
            else:
                # We're running locally - start the proxy
                local_port = start_cloud_sql_proxy(instance_connection_name)
                if local_port:
                    db_host = 'localhost'
                    conn_string = f"host={db_host} port={local_port} dbname={db_name} user={db_user} password={db_pass}"
                    logger.info(f"Connecting to Cloud SQL via proxy on localhost:{local_port}")
                else:
                    logger.error("Cloud SQL Proxy failed to start. Cannot connect to Google Cloud SQL database.")
                    raise Exception("Failed to connect to Google Cloud SQL database. Proxy initialization failed.")
        else:
            # Regular local connection
            db_host = os.environ.get("DB_HOST", "localhost")
            db_port = os.environ.get("DB_PORT", 5432)
            conn_string = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_pass}"
    
    # Log connection info (without password)
    safe_conn_info = conn_string.replace(db_pass, "******") if db_pass else conn_string
    logger.info(f"Connecting to database: {safe_conn_info}")
    
    # Create connection pool with min/max connections
    try:
        pool = ThreadedConnectionPool(1, 10, conn_string)
        logger.info("Database connection pool initialized successfully")
        
        # Create the database schema if it doesn't exist
        create_schema()


        _pool_initialized = True
        return pool
    except psycopg2.OperationalError as e:
        logger.error(f"Failed to initialize connection pool: {e}")
        raise

# Rest of your code remains unchanged
@contextmanager
def get_db_connection():
    """Get a connection from the pool."""
    if pool is None:
        init_connection_pool()
    
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

@contextmanager
def get_db_cursor():
    """Get a cursor from a connection from the pool."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

def create_schema():
    """Create the database schema if it doesn't exist."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Check if tables exist
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'faces'
                );
            """)
            tables_exist = cursor.fetchone()[0]
            
            if not tables_exist:
                logger.info("Creating database schema...")
                
                # Create faces table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS faces (
                        id SERIAL PRIMARY KEY,
                        face_id TEXT UNIQUE,
                        image_base64 TEXT,
                        upload_timestamp TIMESTAMP,
                        processing_status TEXT,
                        search_timestamp TIMESTAMP
                    );
                """)
                
                # Create identity_matches table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS identity_matches (
                        id SERIAL PRIMARY KEY,
                        face_id TEXT REFERENCES faces(face_id),
                        url TEXT,
                        score FLOAT,
                        source_type TEXT,
                        thumbnail_base64 TEXT,
                        scraped_data JSONB
                    );
                """)
                
                # Create person_profiles table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS person_profiles (
                        id SERIAL PRIMARY KEY,
                        face_id TEXT REFERENCES faces(face_id),
                        full_name TEXT,
                        bio_text TEXT,
                        bio_timestamp TIMESTAMP,
                        record_data JSONB,
                        record_timestamp TIMESTAMP,
                        record_search_names TEXT[]
                    );
                """)
                
                # Create raw_results table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS raw_results (
                        id SERIAL PRIMARY KEY,
                        face_id TEXT REFERENCES faces(face_id),
                        result_type TEXT,
                        raw_data JSONB,
                        timestamp TIMESTAMP
                    );
                """)
                
                conn.commit()
                logger.info("Database schema created successfully.")
            else:
                logger.info("Database schema already exists.")

# Helper functions for database operations
def load_processed_faces():
    """Load the list of face IDs that have been processed."""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT face_id FROM faces")
        results = cursor.fetchall()
        return [row[0] for row in results]

def save_face_result(face_id, result_data):
    """Save face search results to the database."""
    # Convert non-serializable objects to strings
    if isinstance(result_data.get('search_timestamp'), datetime.datetime):
        result_data['search_timestamp'] = result_data['search_timestamp'].strftime("%Y%m%d_%H%M%S")
    
    with get_db_cursor() as cursor:
        # Insert face record
        cursor.execute(
            "INSERT INTO faces (face_id, image_base64, upload_timestamp, processing_status, search_timestamp) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (face_id) DO UPDATE "
            "SET processing_status = %s, search_timestamp = %s RETURNING id",
            (
                face_id, 
                result_data.get('source_image_base64'), 
                datetime.datetime.now(), 
                'processed', 
                result_data.get('search_timestamp'), 
                'processed', 
                result_data.get('search_timestamp')
            )
        )
        
        # Store original results
        cursor.execute(
            "INSERT INTO raw_results (face_id, result_type, raw_data, timestamp) "
            "VALUES (%s, %s, %s, %s)",
            (
                face_id, 
                'face_search', 
                json.dumps(result_data.get('original_results', [])), 
                datetime.datetime.now()
            )
        )
        
        # Store identity matches
        for match in result_data.get('identity_analyses', []):
            cursor.execute(
                "INSERT INTO identity_matches (face_id, url, score, source_type, thumbnail_base64, scraped_data) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    face_id, 
                    match.get('url'), 
                    match.get('score'), 
                    match.get('source_type'), 
                    match.get('thumbnail_base64'), 
                    json.dumps(match.get('scraped_data', {}))
                )
            )

def save_bio(face_id, bio_text, record_data=None, search_names=None):
    """Save generated bio and record data to the database."""
    with get_db_cursor() as cursor:
        # Check if a profile exists for this face
        cursor.execute("SELECT id FROM person_profiles WHERE face_id = %s", (face_id,))
        profile_exists = cursor.fetchone()
        
        # Convert search_names to proper PostgreSQL array format
        if search_names:
            if isinstance(search_names, list):
                search_names_array = search_names
            else:
                search_names_array = [search_names]
        else:
            search_names_array = None
            
        # Get the full name from record data or first search name
        full_name = None
        if search_names_array and len(search_names_array) > 0:
            full_name = search_names_array[0]
        
        if profile_exists:
            # Build update SQL parts conditionally to avoid empty parameters
            sql_parts = ["UPDATE person_profiles SET bio_text = %s, bio_timestamp = %s"]
            params = [bio_text, datetime.datetime.now()]
            
            if record_data:
                sql_parts.append(", record_data = %s, record_timestamp = %s")
                params.extend([json.dumps(record_data), datetime.datetime.now()])
                
            if search_names_array:
                sql_parts.append(", record_search_names = %s")
                params.append(search_names_array)
                
            if full_name:
                sql_parts.append(", full_name = %s")
                params.append(full_name)
                
            # Add WHERE clause
            sql_parts.append(" WHERE face_id = %s")
            params.append(face_id)
            
            # Execute the constructed query
            cursor.execute(" ".join(sql_parts), params)
        else:
            # For new profiles, only include non-null fields
            fields = ["face_id", "bio_text", "bio_timestamp"]
            values = ["%s", "%s", "%s"]
            params = [face_id, bio_text, datetime.datetime.now()]
            
            if record_data:
                fields.extend(["record_data", "record_timestamp"])
                values.extend(["%s", "%s"])
                params.extend([json.dumps(record_data), datetime.datetime.now()])
                
            if search_names_array:
                fields.append("record_search_names")
                values.append("%s")
                params.append(search_names_array)
                
            if full_name:
                fields.append("full_name")
                values.append("%s")
                params.append(full_name)
                
            # Construct the INSERT query
            query = f"INSERT INTO person_profiles ({', '.join(fields)}) VALUES ({', '.join(values)})"
            cursor.execute(query, params)

def get_face_result(face_id):
    """Get face search results from the database."""
    with get_db_cursor() as cursor:
        # Get face record
        cursor.execute("SELECT * FROM faces WHERE face_id = %s", (face_id,))
        face = cursor.fetchone()
        if not face:
            return None
        
        # Get identity matches
        cursor.execute("SELECT * FROM identity_matches WHERE face_id = %s", (face_id,))
        identity_matches = cursor.fetchall()
        
        # Get raw results
        cursor.execute("SELECT * FROM raw_results WHERE face_id = %s AND result_type = 'face_search'", (face_id,))
        raw_results = cursor.fetchone()
        
        # Get bio and record data
        cursor.execute("SELECT * FROM person_profiles WHERE face_id = %s", (face_id,))
        profile = cursor.fetchone()
        
        # Build result object in the same format as the original JSON
        result = {
            "face_id": face_id,
            "source_image_base64": face[2],
            "search_timestamp": face[5].strftime("%Y%m%d_%H%M%S") if face[5] else None,
            "identity_analyses": [],
            "original_results": raw_results[3] if raw_results else []
        }
        
        # Add identity analyses
        for match in identity_matches:
            result["identity_analyses"].append({
                "url": match[2],
                "score": match[3],
                "source_type": match[4],
                "thumbnail_base64": match[5],
                "scraped_data": match[6]
            })
        
        # Add bio and record data if available
        if profile:
            result["bio_text"] = profile[3]
            result["bio_timestamp"] = profile[4].strftime("%Y%m%d_%H%M%S") if profile[4] else None
            result["record_analyses"] = profile[5]
            result["record_search_names"] = profile[7]
        
        return result
    
def get_identity_analyses(face_id):
    """Get properly formatted identity analyses for NameResolver"""
    with get_db_cursor() as cursor:
        # Get identity matches
        cursor.execute("SELECT * FROM identity_matches WHERE face_id = %s", (face_id,))
        identity_matches = cursor.fetchall()
        
        analyses = []
        for match in identity_matches:
            # The scraped_data is already a Python dict from the JSONB field
            # Don't try to parse it again with json.loads()
            if match[6] is not None:
                if isinstance(match[6], dict):
                    # Already a dict, use directly
                    scraped_data = match[6]
                elif isinstance(match[6], str):
                    # String that needs to be parsed
                    scraped_data = json.loads(match[6])
                else:
                    # Fallback
                    scraped_data = {}
            else:
                scraped_data = {}
            
            analyses.append({
                "url": match[2],
                "score": match[3],
                "source_type": match[4],
                "thumbnail_base64": match[5],
                "scraped_data": scraped_data  # Now correctly handled
            })
        
        return analyses

def get_bio_text(face_id):
    """Get bio text for a face ID"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT bio_text FROM person_profiles WHERE face_id = %s", (face_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def get_record_analyses(face_id):
    """Get record analyses for a face ID"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT record_data FROM person_profiles WHERE face_id = %s", (face_id,))
        result = cursor.fetchone()
        if result and result[0]:
            # Check if already a dict (JSONB auto-conversion)
            if isinstance(result[0], dict):
                return result[0]
            # Otherwise, try to parse as JSON string
            else:
                return json.loads(result[0])
        return None

def save_record_data(face_id, record_data, search_names=None):
    """Save record data to the database"""
    with get_db_cursor() as cursor:
        # Convert search_names to a proper PostgreSQL array format
        if search_names:
            # If it's already a list, convert to PostgreSQL array format
            if isinstance(search_names, list):
                # PostgreSQL expects array literals as: '{item1,item2,...}'
                search_names_array = search_names
            else:
                # Convert single string to single-item array
                search_names_array = [search_names]
        else:
            search_names_array = None
            
        # Check if a profile exists for this face
        cursor.execute("SELECT id FROM person_profiles WHERE face_id = %s", (face_id,))
        profile_exists = cursor.fetchone()
        
        if profile_exists:
            # Update existing profile
            cursor.execute(
                "UPDATE person_profiles SET record_data = %s, record_timestamp = %s, record_search_names = %s WHERE face_id = %s",
                (json.dumps(record_data), datetime.datetime.now(), search_names_array, face_id)
            )
        else:
            # Create new profile
            cursor.execute(
                "INSERT INTO person_profiles (face_id, record_data, record_timestamp, record_search_names) VALUES (%s, %s, %s, %s)",
                (face_id, json.dumps(record_data), datetime.datetime.now(), search_names_array)
            )

class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.strftime("%Y%m%d_%H%M%S")
        return json.JSONEncoder.default(self, obj)
    

def validate_database_connection():
    """Test the database connection with a simple query"""
    try:
        with get_db_cursor() as cursor:
            # Try a simple query
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            
            if result and result[0] == 1:
                print("DATABASE CONNECTION TEST: SUCCESS")
                
                # Try to count rows in critical tables
                tables = ["faces", "identity_matches", "person_profiles", "raw_results"]
                for table in tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        print(f"Table '{table}' exists and has {count} rows")
                    except Exception as e:
                        print(f"Error accessing table '{table}': {e}")
                
                return True
            else:
                print("DATABASE CONNECTION TEST: FAILED - Query returned unexpected result")
                return False
    except Exception as e:
        print(f"DATABASE CONNECTION TEST: FAILED - {e}")
        return False