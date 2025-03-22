# EyeSpy Server Architecture

## Overview

EyeSpy Server is a backend system that processes face images to find identity matches online, extract information, generate biographical summaries, and search public records. This document describes the architecture of the system.

## Architecture Components

The EyeSpy Server uses a centralized controller architecture that coordinates all components through well-defined interfaces, replacing the previous monkey-patching approach.

### Core Components

1. **Controller (controller.py)**
   - Central hub that coordinates all components
   - Manages configuration loading and distribution
   - Defines the processing flow between components
   - Handles background processing and queuing

2. **Configuration Manager (part of controller.py)**
   - Loads all environment variables in one place
   - Provides centralized access to configuration
   - Validates required configuration keys
   - Makes API keys and settings available to components

3. **Web Server (backend_server.py)**
   - Flask-based HTTP server
   - Provides REST API endpoints
   - Handles file uploads and initial processing
   - Delegates to the controller for actual work

4. **Database Connector (db_connector.py)**
   - Handles database connectivity
   - Manages connection pooling
   - Provides CRUD operations for all data entities
   - Handles Cloud SQL proxy for GCP integration

### Processing Components

5. **Face Uploader (FaceUpload.py)**
   - Communicates with FaceCheckID API
   - Processes face images for identity matching
   - Uses Firecrawl and Zyte for web scraping

6. **Name Resolver (NameResolver.py)**
   - Extracts canonical names from identity analyses
   - Uses frequency-based name detection
   - Provides consistent name resolution across components

7. **Bio Generator (BioGenerator.py)**
   - Creates biographical summaries using OpenAI
   - Integrates identity and record data
   - Formats comprehensive profiles

8. **Record Checker (RecordChecker.py)**
   - Searches public records using various APIs
   - Extracts structured personal information
   - Integrates with database for storage

## Data Flow

1. **Face Upload Flow**
   - Client sends face image to `/api/upload_face` endpoint
   - Server saves the image to a temporary location
   - Image is processed directly with FaceUpload in a background thread
   - After processing completes, the temporary file is deleted
   - Additional processing steps are queued through the controller

2. **Processing Pipeline**
   - Face image is processed directly by FaceUpload for identity matches
   - Results are saved to the database
   - After image processing, additional steps are triggered:
     - If record checking is enabled, RecordChecker searches for records
     - If bio generation is enabled, BioGenerator creates a biography
   - All results are stored in the database in their respective tables

3. **Database Structure**
   - `faces`: Stores face images and processing status
   - `identity_matches`: Stores identity matches found online
   - `person_profiles`: Stores biographical and record information
   - `raw_results`: Stores original API responses

## Benefits of the Architecture

1. **Clean Interfaces**
   - Components interact through well-defined interfaces
   - No monkey patching or direct modification of other components
   - Easy to test, maintain, and extend

2. **Centralized Configuration**
   - All configuration happens in one place
   - Environment variables are loaded once
   - API keys and settings are validated at startup

3. **Explicit Dependencies**
   - Components receive their dependencies explicitly
   - No hidden dependencies or side effects
   - Easier to understand and debug

4. **Centralized Coordination**
   - Processing flow is defined in one place
   - Clear visibility into the status of all components
   - Consistent error handling and logging

## Environment Variables

The system uses the following environment variables:

### API Keys
- `FACECHECK_API_TOKEN`: API key for FaceCheckID
- `FIRECRAWL_API_KEY`: API key for Firecrawl
- `OPENAI_API_KEY`: API key for OpenAI
- `RECORDS_API_KEY`: API key for records search
- `ZYTE_API_KEY`: API key for Zyte (optional)

### Database Configuration
- `DATABASE_URL`: Full database connection URL
- `DB_USER`: Database username
- `DB_PASS`: Database password
- `DB_NAME`: Database name
- `DB_HOST`: Database host
- `DB_PORT`: Database port
- `INSTANCE_CONNECTION_NAME`: GCP Cloud SQL instance name

### Server Configuration
- `PORT`: Server port (default: 8080)
- `UPLOAD_FOLDER`: Temporary folder for storing uploaded files during processing

## Extending the System

To add a new component to the system:

1. Create a new module with a clear public API
2. Add initialization code to the controller
3. Update the processing flow to include the new component
4. Configure environment variables for the new component

The centralized architecture makes it easy to add new components without modifying existing ones.