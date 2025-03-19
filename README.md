# EyeSpy Server

Backend server component of the EyeSpy system. This server receives face images from clients, processes them to find online identity matches, generates biographical information, checks public records, and stores all results in a PostgreSQL database.

## Features

- **Face Identity Search**: Uses FaceCheckID API to find identity matches online
- **Web Scraping**: Extracts additional information from matching websites using Firecrawl
- **Bio Generation**: Creates AI-generated biographical summaries using OpenAI
- **Records Integration**: Optional records search capabilities
- **Database Storage**: Stores all results in a PostgreSQL database
- **REST API**: Simple HTTP endpoints for client communication
- **Docker Support**: Easy deployment with containerization
- **Background Processing**: Multi-threaded architecture for efficient operation

## Prerequisites

1. Python 3.9+
2. API Keys:
   - FaceCheckID API key (required)
   - OpenAI API key (optional, for bio generation)
   - Firecrawl API key (optional, for enhanced web scraping)
   - Records API key (optional, for public records search)
3. PostgreSQL database (or use the included Cloud SQL Proxy)

## Installation

### Local Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file with your API keys and database configuration:
```
FACECHECK_API_TOKEN=your_facecheck_api_token
OPENAI_API_KEY=your_openai_api_key
FIRECRAWL_API_KEY=your_firecrawl_api_key
RECORDS_API_KEY=your_records_api_key

# Database configuration
DATABASE_URL=postgresql://username:password@localhost:5432/eyespy
# OR individual settings
DB_USER=your_db_user
DB_PASS=your_db_password
DB_NAME=eyespy
DB_HOST=localhost
DB_PORT=5432
```

### Docker Installation

1. Create a `.env` file with the same variables as above.

2. Build and start the containers:
```bash
# Build the Docker image
docker-compose build

# Start the server
docker-compose up -d

# View logs
docker-compose logs -f
```

## Usage

### Authentication

Before running the server, authenticate with Google Cloud:

```bash
gcloud auth application-default login
```

### Running the Server (Local)

```bash
# Basic server startup
python backend_server.py --port 8080

# With Google Cloud SQL connection
DATABASE_URL="postgresql://postgres:Madmaxme@localhost:5432/postgres?host=/cloudsql/eyespy-453816:europe-west9:eyespy-db" python3 backend_server.py
```

Options:
- `--token`: FaceCheckID API token (overrides .env file)
- `--firecrawl-key`: Firecrawl API key (overrides .env file)
- `--port`: Server port (default: 8080)

### Running the Server (Docker)

```bash
docker-compose up -d
```
```bash
python backend_server.py --port 8080
```

Options:
- `--token`: FaceCheckID API token (overrides .env file)
- `--firecrawl-key`: Firecrawl API key (overrides .env file)
- `--port`: Server port (default: 8080)

### Running the Server (Docker)

```bash
docker-compose up -d
```

## API Endpoints

- **GET /api/health**: Health check endpoint
- **GET /**: Root endpoint returning server status
- **POST /api/upload_face**: Upload a face image for processing

### API Examples

#### Health Check
```bash
curl http://localhost:8080/api/health
```

#### Upload Face
```bash
curl -X POST -F "face=@/path/to/face.jpg" http://localhost:8080/api/upload_face
```

## Architecture Components

### Core Modules

- **backend_server.py**: Flask API server and main entry point
- **FaceUpload.py**: Face identity search using FaceCheckID
- **db_connector.py**: Database connectivity and operations
- **NameResolver.py**: Shared name resolution logic for consistency

### Optional Integration Modules

- **bio_integration.py**: Integration for bio generation
- **BioGenerator.py**: Biographical summary creation using OpenAI
- **record_integration.py**: Integration for records checking
- **RecordChecker.py**: Public records search capabilities

### Database Structure

The system uses a PostgreSQL database with the following tables:

- **faces**: Stores uploaded face information and processing status
- **identity_matches**: Stores identity matches found for each face
- **person_profiles**: Stores biographical and records information
- **raw_results**: Stores raw API responses for debugging

## Deployment Options

### Local Development
- Run on your local machine
- Use local PostgreSQL database
- Accessible at http://localhost:8080

### Docker Development
- Run in Docker container on your local machine
- Uses the database configuration from .env
- Accessible at http://localhost:8080

### Cloud Deployment
The server is designed to be deployed to cloud services like Google Cloud Run:

1. Build the Docker image:
```bash
docker build -t eyespy-server .
```

2. Push to a container registry (e.g., Google Container Registry)

3. Deploy to Cloud Run or similar service

4. Configure environment variables and database connection

## Database Connection

The server supports multiple database connection methods:

1. **Direct PostgreSQL Connection**: Connect directly to a PostgreSQL server
2. **Cloud SQL with Unix Socket**: Connect to Cloud SQL when running in the cloud
3. **Cloud SQL Proxy**: Connect to Cloud SQL when running locally, using the included proxy

## Troubleshooting

- **API Key Issues**: Verify your API keys are correctly set in the .env file
- **Database Connection Problems**: Check database credentials and connection details
- **FaceCheckID API Errors**: Ensure your API key is valid and has sufficient credits
- **Docker Issues**: Check Docker logs for detailed error messages
- **OpenAI API Errors**: Verify your API key and check for rate limiting

## Development Notes

- The server logs extensive debugging information to the console
- Background processing uses threading to avoid blocking API responses
- Database operations use connection pooling for efficiency
- The cloud SQL proxy is automatically downloaded and started if needed

## Security Considerations

- Keep API keys and database credentials secure
- Use HTTPS in production environments
- Consider adding authentication for production deployments
- Ensure compliance with privacy laws when processing face data# EyeSpy_Server
