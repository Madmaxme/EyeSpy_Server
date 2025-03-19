import os
import time
import json
import base64
import requests
import argparse
import glob
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import urllib.parse
from dotenv import load_dotenv
import openai
import traceback


try:
    import db_connector
except ImportError:
    raise ImportError("Database connector module is required. Make sure db_connector.py is available.")

# Load environment variables from .env file
load_dotenv()

# Try importing firecrawl, provide installation instructions if not found
try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
    print("Firecrawl module found and imported successfully")
except ImportError:
    FIRECRAWL_AVAILABLE = False
    print("Firecrawl package not found. Please install using: pip install firecrawl-py")
    print("Continuing without Firecrawl integration...")

# FaceCheckID API Configuration
TESTING_MODE = False  # Set to False for production use
APITOKEN = os.getenv('FACECHECK_API_TOKEN')

# Firecrawl API Configuration
FIRECRAWL_API_KEY = os.getenv('FIRECRAWL_API_KEY')

# Zyte API Configuration
ZYTE_API_KEY = os.getenv('ZYTE_API_KEY')
ZYTE_AVAILABLE = ZYTE_API_KEY is not None and ZYTE_API_KEY != ''

# OPEN API KEY
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

# Default directory for detected faces (should match FotoRec.py save_dir)
DEFAULT_FACES_DIR = "detected_faces"


# WITH this minimal function:
def setup_directories():
    """Ensure the detected_faces directory exists for input images"""
    if not os.path.exists(DEFAULT_FACES_DIR):
        os.makedirs(DEFAULT_FACES_DIR)
        print(f"Created faces input directory: {DEFAULT_FACES_DIR}")
    return None

def load_processed_faces():
    """Load the list of already processed face files from database only"""
    from db_connector import load_processed_faces as db_load_processed_faces
    return db_load_processed_faces()

def save_processed_faces(processed_faces):
    """This function is now a no-op as the database tracks processed faces"""
    pass
        

def get_unprocessed_faces(faces_dir, processed_faces):
    """Get list of face image files that haven't been processed yet"""
    # Get all image files in the faces directory
    image_files = glob.glob(os.path.join(faces_dir, "face_*.jpg"))
    
    # Filter out already processed files
    unprocessed = [file for file in image_files if file not in processed_faces]
    
    return unprocessed

def search_by_face(image_file, timeout=300):
    """
    Search FaceCheckID API using a face image
    
    Args:
        image_file: Path to the image file
        timeout: Maximum time in seconds to wait for search (default: 5 minutes)
    
    Returns:
        Tuple of (error_message, search_results)
    """
    mode_message = "****** TESTING MODE search, results are inaccurate, and queue wait is long, but credits are NOT deducted ******" if TESTING_MODE else "PRODUCTION MODE: Credits will be deducted for this search"
    print(f"\n{mode_message}")
    
    site = 'https://facecheck.id'
    headers = {'accept': 'application/json', 'Authorization': APITOKEN}
    
    # Step 1: Upload the image
    try:
        with open(image_file, 'rb') as img_file:
            files = {'images': img_file, 'id_search': None}
            response = requests.post(site + '/api/upload_pic', headers=headers, files=files).json()
    except Exception as e:
        return f"Error uploading image: {str(e)}", None
    
    if response.get('error'):
        return f"{response['error']} ({response['code']})", None
    
    id_search = response['id_search']
    print(response['message'] + ' id_search=' + id_search)
    
    
    # Step 2: Run the search with timeout
    json_data = {
        'id_search': id_search,
        'with_progress': True,
        'status_only': False,
        'demo': TESTING_MODE  # This is the key change - using the TESTING_MODE flag
    }
    
    start_time = time.time()
    last_progress = -1
    
    while True:
        # Check if timeout exceeded
        if time.time() - start_time > timeout:
            return f"Search timed out after {timeout} seconds", None
        
        try:
            response = requests.post(site + '/api/search', headers=headers, json=json_data).json()
        except Exception as e:
            return f"Error during search: {str(e)}", None
        
        if response.get('error'):
            return f"{response['error']} ({response['code']})", None
        
        if response.get('output'):
            return None, response['output']['items']
        
        # Only print progress if it's changed
        current_progress = response.get('progress', 0)
        if current_progress != last_progress:
            print(f"{response['message']} progress: {current_progress}%")
            last_progress = current_progress
        

def save_thumbnail_from_base64(base64_str, filename):
    """Save Base64 encoded image to file"""
    try:
        # Extract the actual base64 content (after the comma)
        if ',' in base64_str:
            base64_content = base64_str.split(',', 1)[1]
        else:
            base64_content = base64_str
        
        # Decode and save
        image_data = base64.b64decode(base64_content)
        with open(filename, 'wb') as f:
            f.write(image_data)
        return True
    except Exception as e:
        print(f"Error saving thumbnail: {e}")
        return False

def collect_fallback_urls(search_results: List[Dict], primary_index: int) -> List[str]:
    """
    Collect fallback URLs from search results that aren't the primary one
    
    Args:
        search_results: List of search results from FaceCheckID
        primary_index: Index of the primary result being processed
        
    Returns:
        List of fallback URLs to try
    """
    fallback_urls = []
    
    try:
        # Skip the primary URL we already tried
        for i, result in enumerate(search_results):
            if i != primary_index and result.get('url'):
                fallback_urls.append(result.get('url'))
    except Exception as e:
        print(f"Error collecting fallback URLs: {e}")
    
    return fallback_urls

def scrape_with_zyte(url: str) -> Optional[Dict[str, Any]]:
    """
    Scrape a social media URL using Zyte API to extract profile information.
    
    Args:
        url: The social media profile URL to scrape
        
    Returns:
        Dictionary containing the scraped information or None if scraping failed
    """
    if not ZYTE_AVAILABLE:
        print(f"Zyte API key not set. Cannot scrape social media profile: {url}")
        return None
    
    try:
        # Normalize URL to profile URL (remove post paths, etc.)
        original_url = url
        normalized_url = normalize_social_media_url(url)
        
        if normalized_url != original_url:
            print(f"Normalized social media URL: {original_url} → {normalized_url}")
        
        print(f"Scraping social media profile with Zyte API: {normalized_url}")
        
        # Make request to Zyte API
        api_response = requests.post(
            "https://api.zyte.com/v1/extract",
            auth=(ZYTE_API_KEY, ""),
            json={
                "url": normalized_url,
                "product": True,
                "productOptions": {"extractFrom": "httpResponseBody", "ai": True},
            },
            timeout=30
        )
        
        # Check if request was successful
        if api_response.status_code != 200:
            print(f"Zyte API request failed with status {api_response.status_code}: {api_response.text}")
            return None
        
        # Get the product data from response
        product_data = api_response.json().get("product", {})
        if not product_data:
            print(f"No product data returned from Zyte API for {url}")
            return None
            
        print(f"Successfully scraped profile with Zyte API: {url}")
        
        # Extract name from product data
        # For social media profiles, it's typically in format "Name (@username) • ..."
        name = product_data.get("name", "")
        extracted_name = None
        
        # Parse name using regex to extract actual name
        if name:
            # Pattern for "Name (@username)" format
            name_match = re.match(r'^([^(@]+).*', name)
            if name_match:
                extracted_name = name_match.group(1).strip()
                print(f"Extracted name from profile: '{extracted_name}'")
        
        # Extract username from URL
        username = None
        domain = extract_domain(url).lower()
        
        if "instagram.com" in domain:
            username_match = re.search(r'instagram\.com/([^/\?]+)', url)
            if username_match:
                username = username_match.group(1)
        elif "twitter.com" in domain or "x.com" in domain:
            username_match = re.search(r'(?:twitter|x)\.com/([^/\?]+)', url)
            if username_match:
                username = username_match.group(1)
        elif "facebook.com" in domain:
            username_match = re.search(r'facebook\.com/([^/\?]+)', url)
            if username_match:
                username = username_match.group(1)
        
        # If no name was extracted but we have a username, use it as a fallback
        if not extracted_name and username:
            extracted_name = username
            print(f"No name found in profile, using username as fallback: '{username}'")
            
        # If we still don't have a name, we can't proceed
        if not extracted_name:
            print(f"Could not extract name or username from profile: {url}")
            return None
            
        # Create properly structured candidate name
        candidate_names = []
        candidate_names.append({
            "name": extracted_name,
            "source": f"zyte_api_{domain}",
            "url": url,
            "confidence": 0.9 if extracted_name != username else 0.7  # Lower confidence if using username as name
        })
        
        # Create structured data that matches Firecrawl's format
        # This ensures compatibility with the rest of the pipeline
        full_content = f"Profile: {name}\nDescription: {product_data.get('description', '')}"
        
        return {
            'person_info': {
                'person': {
                    'fullName': extracted_name if extracted_name else "Unknown",
                    'username': username,
                    'full_content': full_content
                }
            },
            'page_content': full_content,
            'metadata': product_data.get('metadata', {}),
            'source_url': url,
            'candidate_names': candidate_names
        }
        
    except Exception as e:
        print(f"Error scraping {url} with Zyte API: {e}")
        return None

def normalize_social_media_url(url: str) -> str:
    """
    Normalize social media URLs to profile URLs by removing post paths, etc.
    
    Args:
        url: The original social media URL
        
    Returns:
        Normalized profile URL (e.g., instagram.com/username from instagram.com/username/p/postid)
    """
    domain = extract_domain(url).lower()
    
    # Extract just the username part for profile URLs
    if "instagram.com" in domain:
        username_match = re.search(r'instagram\.com/([^/\?]+)', url)
        if username_match and username_match.group(1) not in ['p', 'explore', 'reels']:
            username = username_match.group(1)
            return f"https://instagram.com/{username}"
    elif "twitter.com" in domain or "x.com" in domain:
        username_match = re.search(r'(?:twitter|x)\.com/([^/\?]+)', url)
        if username_match and username_match.group(1) not in ['status', 'hashtag', 'search', 'home']:
            username = username_match.group(1)
            return f"https://{'twitter' if 'twitter' in domain else 'x'}.com/{username}"
    elif "facebook.com" in domain:
        username_match = re.search(r'facebook\.com/([^/\?]+)', url)
        if username_match and username_match.group(1) not in ['pages', 'groups', 'photos', 'events']:
            username = username_match.group(1)
            return f"https://facebook.com/{username}"
            
    # If we couldn't normalize it, return original
    return url

def is_social_media_url(url: str) -> bool:
    """
    Determine if a URL is for a social media platform that Zyte can handle better.
    
    Args:
        url: The URL to check
        
    Returns:
        True if it's a social media URL that should use Zyte, False otherwise
    """
    domain = extract_domain(url).lower()
    
    # Social platforms Zyte handles well (excluding LinkedIn)
    return any(platform in domain for platform in ['instagram.com', 'twitter.com', 'x.com', 'facebook.com'])

def scrape_with_firecrawl(url: str, fallback_urls: List[str] = None) -> Optional[Dict[str, Any]]:
    """
    Scrape a URL using Firecrawl to extract information about the person.
    If the URL is for a social media platform that Zyte handles better, use Zyte instead.
    If scraping fails and fallback_urls are provided, attempts to scrape those.
    
    Args:
        url: The primary URL to scrape
        fallback_urls: A list of alternative URLs to try if the primary fails
        
    Returns:
        Dictionary containing the scraped information or None if all scraping failed
    """
    

    if "linkedin.com/in/" in url.lower():
        print(f"Detected LinkedIn URL: {url} - attempting LLM name extraction")
        linkedin_data = extract_name_from_linkedin_url(url)
        if linkedin_data:
            print(f"Successfully extracted name via LLM from LinkedIn URL")
            return linkedin_data
        print("LinkedIn URL name extraction failed, continuing with other methods")
    
    # If URL is LinkedIn but LLM extraction failed, don't try to scrape with Firecrawl
    if "linkedin.com/in/" in url.lower():
        print(f"Skipping Firecrawl scraping for LinkedIn URL: {url}")
        return None

    # Normalize social media URLs first
    original_url = url
    if is_social_media_url(url):
        url = normalize_social_media_url(url)
        if url != original_url:
            print(f"Normalized primary URL: {original_url} → {url}")
    
    # Normalize fallback URLs if they're social media
    normalized_fallbacks = []
    if fallback_urls:
        for fallback_url in fallback_urls:
            if is_social_media_url(fallback_url):
                normalized = normalize_social_media_url(fallback_url)
                if normalized != fallback_url:
                    print(f"Normalized fallback URL: {fallback_url} → {normalized}")
                normalized_fallbacks.append(normalized)
            else:
                normalized_fallbacks.append(fallback_url)
        fallback_urls = normalized_fallbacks
            
    # Check if this is a social media URL that Zyte can handle better
    if is_social_media_url(url) and ZYTE_AVAILABLE:
        print(f"Detected social media URL: {url} - using Zyte API instead of Firecrawl")
        zyte_result = scrape_with_zyte(url)
        if zyte_result:
            return zyte_result
        print("Zyte scraping failed, falling back to Firecrawl")
        
    
    # If not a social media URL or Zyte failed, proceed with Firecrawl
    global FIRECRAWL_AVAILABLE
    
    if not FIRECRAWL_AVAILABLE:
        print("Firecrawl not available. Skipping web scraping.")
        return None
    
    # Skip if the API key isn't set
    if not FIRECRAWL_API_KEY or FIRECRAWL_API_KEY == 'YOUR_FIRECRAWL_API_KEY':
        print("Firecrawl API key not set. Skipping web scraping.")
        return None
    
    # Initialize a list of URLs to try, starting with the primary URL
    urls_to_try = [url]
    
    # Add any fallback URLs if provided
    if fallback_urls:
        urls_to_try.extend(fallback_urls)
    
    # Try each URL in sequence until one succeeds
    for current_url in urls_to_try:
        try:
            # Skip empty or invalid URLs
            if not current_url or not current_url.startswith(('http://', 'https://')):
                continue
                
            # Check if this fallback URL is a social media URL that Zyte can handle
            # (We already normalized the URL earlier, so we can use it directly)
            if current_url != url and is_social_media_url(current_url) and ZYTE_AVAILABLE:
                print(f"Trying fallback social media URL with Zyte: {current_url}")
                zyte_result = scrape_with_zyte(current_url)
                if zyte_result:
                    return zyte_result
                print(f"Zyte failed for fallback URL, trying Firecrawl")
                
            print(f"Scraping {current_url} with Firecrawl...")
            
            # Initialize Firecrawl
            firecrawl_app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
            
            # Define the extraction prompt rather than using a schema
            # This approach is more flexible and works better with Firecrawl
            extraction_prompt = """
            Extract the following information about the person featured in this page:
            - Full name of the person
            - Description or bio
            - Job, role, or occupation
            - Location information
            - Social media handles or usernames
            - Age or birthdate information
            - Organizations or companies they're affiliated with
            
            IMPORTANT: Also include the entire article or page content in a field called "full_content" - this should contain all the textual information from the page that could be relevant to the person.
            
            If the page is a social media profile, extract the profile owner's information.
            If the page is a news article or blog post, extract information about the main person featured AND include the full article text.
            If certain information isn't available, that's okay.
            
            IMPORTANT: Be sure to include ALL possible forms of the person's name that appear on the page.
            Look for different name variants, nicknames, formal names, etc.
            """
            
            # Parameters for scraping with prompt-based extraction
            params = {
                'formats': ['json', 'markdown'],
                'jsonOptions': {
                    'prompt': extraction_prompt
                }
            }
            
            result = firecrawl_app.scrape_url(current_url, params)
            
            if result and 'json' in result and result['json']:
                print(f"Successfully scraped person information from {current_url}")
                
                # Extract and collect all possible names explicitly
                extracted_names = extract_name_candidates(result.get('json', {}), result.get('markdown', ''), current_url)
                
                return {
                    'person_info': result.get('json', {}),
                    'page_content': result.get('markdown', ''),
                    'metadata': result.get('metadata', {}),
                    'source_url': current_url,  # Track which URL was actually used
                    'candidate_names': extracted_names  # Add explicit name candidates
                }
            else:
                print(f"No structured data returned from Firecrawl for {current_url}, trying next URL if available")
                
        except Exception as e:
            print(f"Error scraping {current_url} with Firecrawl: {e}")
            # Continue to the next URL
    
    # If we get here, all URLs failed
    print("All scraping attempts failed")
    return None

def extract_name_from_linkedin_url(url: str) -> Optional[Dict[str, Any]]:
    """
    Extract a person's name from a LinkedIn URL using OpenAI's LLM
    
    Args:
        url: LinkedIn profile URL
        
    Returns:
        Dictionary with name information or None if extraction failed
    """
    # Verify it's a LinkedIn URL
    if "linkedin.com/in/" not in url.lower():
        return None
    
    # Extract the URL slug (part after /in/)
    try:
        match = re.search(r'linkedin\.com/in/([^/\?]+)', url)
        if not match:
            return None
            
        slug = match.group(1)
        
        # Skip if it's not a name-based URL (like numeric IDs)
        if slug.isdigit() or not slug:
            return None
            
        print(f"Using OpenAI API to extract name from LinkedIn slug: {slug}")
        
        # Create a prompt for name extraction
        prompt = f"""
        Extract the first name and last name from this LinkedIn profile URL: {url}
        The name should be extracted from the URL slug: {slug}
        
        Return JSON format only:
        {{
            "first_name": "FirstName",
            "last_name": "LastName"
        }}
        """
        
        # Initialize the OpenAI client properly for v1.0+
        client = openai.OpenAI()
        
        # Call OpenAI API with the new format
        response = client.chat.completions.create(
            model="gpt-4-turbo", 
            messages=[
                {"role": "system", "content": "You extract names from LinkedIn URLs."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1  # Low temperature for consistent extraction
        )
        
        # Process response using the new response format
        content = response.choices[0].message.content
        print(f"OpenAI API response: {content}")
        extracted_data = json.loads(content)
        
        # Validate response
        if "first_name" in extracted_data and "last_name" in extracted_data:
            first_name = extracted_data["first_name"]
            last_name = extracted_data["last_name"]
            full_name = f"{first_name} {last_name}"
            
            print(f"Successfully extracted name from LinkedIn URL: {full_name}")
            
            # Create structured data to match existing pipeline
            return {
                'person_info': {
                    'person': {
                        'fullName': full_name,
                        'firstName': first_name,
                        'lastName': last_name
                    }
                },
                'source_url': url,
                'candidate_names': [{
                    "name": full_name,
                    "source": "linkedin_url_llm",
                    "url": url,
                    "confidence": 0.75  # Good confidence for LLM extraction
                }]
            }
        
        # If we get here, something went wrong with the parsing
        print(f"Failed to extract name from LinkedIn URL with LLM: {url}")
        return None
            
    except Exception as e:
        print(f"Error extracting name from LinkedIn URL: {e}")
        traceback.print_exc()  # Add this for better debugging
        return None
    
def extract_name_candidates(json_data: Dict, page_content: str, source_url: str) -> List[Dict[str, Any]]:
    """
    Extract all potential name candidates from scraped data
    
    Args:
        json_data: Structured JSON data from Firecrawl
        page_content: Raw page content as markdown
        source_url: Source URL (for tracking origin)
        
    Returns:
        List of name candidates with metadata
    """
    candidates = []
    
    try:
        # 1. Extract names from person_info structure
        if json_data:
            # Check nested person object
            if "person" in json_data:
                person_obj = json_data["person"]
                # Check for different name formats
                for key in ["fullName", "full_name", "name", "display_name"]:
                    if key in person_obj and person_obj[key]:
                        candidates.append({
                            "name": person_obj[key],
                            "source": "json_person_" + key,
                            "url": source_url,
                            "confidence": 0.9  # High confidence for structured data
                        })
            
            # Check flat structure
            for key in ["fullName", "full_name", "name", "display_name"]:
                if key in json_data and json_data[key]:
                    candidates.append({
                        "name": json_data[key],
                        "source": "json_root_" + key,
                        "url": source_url,
                        "confidence": 0.8  # Good confidence for structured data
                    })
        
        # 2. Look for additional name formats in the JSON
        if json_data:
            # Look for author fields
            if "author" in json_data and json_data["author"]:
                if isinstance(json_data["author"], str):
                    candidates.append({
                        "name": json_data["author"],
                        "source": "json_author",
                        "url": source_url,
                        "confidence": 0.7
                    })
                elif isinstance(json_data["author"], dict) and "name" in json_data["author"]:
                    candidates.append({
                        "name": json_data["author"]["name"],
                        "source": "json_author_name",
                        "url": source_url,
                        "confidence": 0.7
                    })
            
            # Look for profile fields
            if "profile" in json_data and json_data["profile"]:
                if isinstance(json_data["profile"], dict) and "name" in json_data["profile"]:
                    candidates.append({
                        "name": json_data["profile"]["name"],
                        "source": "json_profile_name",
                        "url": source_url,
                        "confidence": 0.7
                    })
                    
            # Check for description field which might contain a name
            if "description" in json_data and json_data["description"]:
                desc = json_data["description"]
                if isinstance(desc, str) and len(desc) < 100:  # Only use short descriptions
                    candidates.append({
                        "name": desc,
                        "source": "json_description",
                        "url": source_url,
                        "confidence": 0.6
                    })
                    
            # Check for full_content field which might contain names
            if "full_content" in json_data and json_data["full_content"]:
                full_content = json_data["full_content"]
                if isinstance(full_content, str):
                    # Try to extract potential names from the full_content
                    # Look for patterns like "Name: John Smith" or "Author: Jane Doe"
                    name_patterns = [
                        r"(?:name|author|by|written by)[:;]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
                        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+(?:is|was|has|had|author)"
                    ]
                    
                    for pattern in name_patterns:
                        matches = re.findall(pattern, full_content, re.IGNORECASE)
                        for match in matches:
                            candidates.append({
                                "name": match,
                                "source": "full_content_extracted",
                                "url": source_url,
                                "confidence": 0.5
                            })
        
        # 3. Look for names in the page_content if no candidates found yet
        if not candidates and page_content:
            # Try to extract potential names from headers or prominent text
            # Look for patterns like "Profile: John Smith" or "About Jane Doe"
            content_patterns = [
                r"(?:profile|about|info|user|member)[:;]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
                r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})'s\s+(?:profile|page|account)",
                r"Welcome\s+(?:back|to)?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})"
            ]
            
            for pattern in content_patterns:
                matches = re.findall(pattern, page_content, re.IGNORECASE)
                for match in matches:
                    candidates.append({
                        "name": match,
                        "source": "page_content_extracted",
                        "url": source_url,
                        "confidence": 0.4
                    })
        
        # 4. Fall back to extracting domain name if no candidates found
        if not candidates:
            domain = extract_domain(source_url)
            domain_parts = domain.split('.')
            
            # Check if domain has a recognizable name part at the beginning
            if len(domain_parts) >= 3 and domain_parts[0] != 'www':
                potential_name = domain_parts[0]
                # Only add if it looks like a name (not a service name like "api", "blog", etc.)
                if len(potential_name) > 3 and potential_name not in ['api', 'blog', 'forum', 'shop', 'store', 'news']:
                    candidates.append({
                        "name": potential_name.capitalize(),
                        "source": "domain_name",
                        "url": source_url,
                        "confidence": 0.3
                    })
                        
        # Only include non-empty names and remove duplicates
        filtered_candidates = []
        seen_names = set()
        
        for candidate in candidates:
            name = candidate["name"]
            if name and isinstance(name, str) and name.strip() and name.strip().lower() not in seen_names:
                # Normalize the name
                candidate["name"] = name.strip()
                filtered_candidates.append(candidate)
                seen_names.add(name.strip().lower())
        
        # Log the extraction results
        print(f"Extracted {len(filtered_candidates)} name candidates from {source_url}")
        for candidate in filtered_candidates:
            print(f"  - {candidate['name']} (confidence: {candidate['confidence']}, source: {candidate['source']})")
        
        return filtered_candidates
        
    except Exception as e:
        print(f"Error extracting name candidates: {e}")
        traceback.print_exc()  # Print full exception for debugging
        return candidates  # Return whatever we have

def analyze_search_result(result: Dict[str, Any], result_index: int, temp_images_dir: str = None, fallback_urls: List[str] = None) -> Dict[str, Any]:
    """
    Analyze a single search result to extract identity information
    
    Args:
        result: Single result from FaceCheckID
        result_index: Index number of this result
        temp_images_dir: Directory to temporarily save images (will be moved later)
        fallback_urls: A list of fallback URLs to try if scraping the primary URL fails
        
    Returns:
        Dictionary with enriched information
    """
    url = result.get('url', '')
    score = result.get('score', 0)
    
    # Store the base64 image data directly
    base64_str = result.get('base64', '')
    thumbnail_path = None  # Keep this for backward compatibility
    
    # Get identity sources
    sources = get_identity_sources(url)
    source_type = sources[0] if sources else "Unknown source"
    
    # Scrape the URL if Firecrawl is available, with fallbacks
    scraped_data = scrape_with_firecrawl(url, fallback_urls)
    
    # Combine all information
    analysis = {
        'url': url,
        'score': score,
        'source_type': source_type,
        'thumbnail_base64': base64_str,  # Store base64 directly in the JSON
        'thumbnail_path': None,  # Keep field for backward compatibility
        'scraped_data': scraped_data
    }
    
    return analysis

def get_identity_sources(url: str) -> List[str]:
    """
    Determine possible identity sources based on the URL
    
    Args:
        url: The URL to analyze
        
    Returns:
        List of potential identity source types
    """
    domain = extract_domain(url).lower()
    
    sources = []
    
    # Social media platforms
    if any(sm in domain for sm in ['facebook', 'fb.com']):
        sources.append('Facebook profile')
    elif 'instagram' in domain:
        sources.append('Instagram profile')
    elif 'twitter' in domain or 'x.com' in domain:
        sources.append('Twitter/X profile')
    elif 'linkedin' in domain:
        sources.append('LinkedIn profile')
    elif 'tiktok' in domain:
        sources.append('TikTok profile')
    elif 'youtube' in domain:
        sources.append('YouTube channel')
    
    # News and media
    if any(news in domain for news in ['news', 'article', 'post', 'blog', 'thesun', 'daily', 'times', 'herald', 'cnn', 'bbc']):
        sources.append('News article')
    
    # Default if none matched
    if not sources:
        sources.append('Web page')
    
    return sources

def extract_domain(url: str) -> str:
    """Extract the main domain from a URL"""
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc
        return domain
    except:
        return url

def process_single_face(image_file, timeout=300):
    """
    Process a single face image
    
    Args:
        image_file: Path to the face image file
        timeout: Maximum time to wait for search results
        
    Returns:
        True if processing was successful, False otherwise
    """
    if not os.path.exists(image_file):
        print(f"Error: Face file '{image_file}' does not exist!")
        return False
    
    print(f"Processing: {os.path.basename(image_file)}")
    
    try:
        # Read and encode the source image as base64
        with open(image_file, 'rb') as img_file:
            source_image_data = img_file.read()
            import base64
            source_image_base64 = base64.b64encode(source_image_data).decode('utf-8')
            
        # Search for the face with timeout
        error, search_results = search_by_face(image_file, timeout=timeout)
        
        if search_results:
            # Print the search results summary
            print(f"Found {len(search_results)} potential matches")
            
            # Process each result to get identity information
            identity_analyses = []
            
            # Process top 5 results (original limit) with fallback functionality
            for j, result in enumerate(search_results[:5], 1):  # Process top 5 results
                # Collect fallback URLs from other results
                fallback_urls = collect_fallback_urls(search_results, j-1)
                
                # Analyze this result with base64 data stored directly
                analysis = analyze_search_result(result, j, None, fallback_urls)
                identity_analyses.append(analysis)
            
            # Generate timestamp for the results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Save the results with enhanced information
            results_data = {
                "source_image_path": image_file,  # Keep for backward compatibility
                "source_image_base64": source_image_base64,  # Store source image as base64
                "search_timestamp": timestamp,
                "original_results": search_results,
                "identity_analyses": identity_analyses
            }
            
            # Extract the basename without extension and path - this will be our face_id
            face_id = os.path.basename(image_file)
            face_id = os.path.splitext(face_id)[0]  # Remove extension
            
            from db_connector import save_face_result
            print(f"Saving results to database for face: {face_id}")
            save_face_result(face_id, results_data)
            
            # Mark as processed
            processed_faces = load_processed_faces()
            if image_file not in processed_faces:
                processed_faces.append(image_file)
                save_processed_faces(processed_faces)
            
            return True
        else:
            print(f"Search failed: {error}")
            return False
    
    except Exception as e:
        print(f"Error processing face {os.path.basename(image_file)}: {e}")
        traceback.print_exc()  # Print stack trace for better debugging
        return False

def process_faces(faces_dir, limit=None, force=False, timeout=300):
    """Process face images and search for matches
    
    Args:
        faces_dir: Directory containing face images
        limit: Maximum number of faces to process
        force: Process all faces even if previously processed
        timeout: Maximum time in seconds to wait for each search
    """
    processed_faces = [] if force else load_processed_faces()
    
    # Get unprocessed face images
    unprocessed_files = get_unprocessed_faces(faces_dir, processed_faces)
    
    if not unprocessed_files:
        print("No new faces to process.")
        return
    
    print(f"Found {len(unprocessed_files)} unprocessed face images.")
    
    # Apply limit if specified
    if limit and limit > 0:
        unprocessed_files = unprocessed_files[:limit]
        print(f"Processing first {limit} images...")
    
    for i, image_file in enumerate(unprocessed_files, 1):
        print(f"\n[{i}/{len(unprocessed_files)}] Processing: {os.path.basename(image_file)}")
        
        try:
            # Process single face with the new method
            success = process_single_face(image_file, timeout=timeout)
            
            if not success:
                print(f"Failed to process: {image_file}")
            
        except KeyboardInterrupt:
            print("\nProcess interrupted by user. Saving progress...")
            # Save progress before exiting
            if image_file not in processed_faces:
                processed_faces.append(image_file)
                save_processed_faces(processed_faces)
            print("You can resume processing later.")
            raise

def queue_worker(face_queue, shutdown_event=None, timeout=300):
    """
    Worker function that processes faces from a queue
    
    Args:
        face_queue: Queue to get face images from
        shutdown_event: Event to signal shutdown
        timeout: Search timeout in seconds
    """
    print(f"[FACEUPLOAD] Face processing worker started")
    print(f"[FACEUPLOAD] Worker ready to process faces")
    
    # Set up necessary directories
    setup_directories()
    
    try:
        while True:
            # Check if shutdown is requested and queue is empty
            if shutdown_event and shutdown_event.is_set() and face_queue.is_empty():
                print("[FACEUPLOAD] Shutdown requested and queue empty, stopping worker...")
                break
                
            try:
                # Get a face from the queue (with timeout to check for shutdown)
                print("[FACEUPLOAD] Checking queue for faces...")
                face_path = face_queue.get(block=True, timeout=2.0)
                
                # Process the face
                try:
                    print(f"[FACEUPLOAD] Processing face from queue: {os.path.basename(face_path)}")
                    success = process_single_face(face_path, timeout=timeout)
                    
                    # Mark the task as done regardless of success
                    face_queue.task_done()
                    
                    if success:
                        print(f"[FACEUPLOAD] Successfully processed: {os.path.basename(face_path)}")
                    else:
                        print(f"[FACEUPLOAD] Failed to process: {os.path.basename(face_path)}")
                        
                except Exception as e:
                    print(f"[FACEUPLOAD] Error processing face from queue: {e}")
                    face_queue.task_done()
            except queue.Empty:
                # Queue.get timed out, which is expected for the polling loop
                print("[FACEUPLOAD] No faces in queue, waiting...")
                # Sleep a bit longer to reduce log spam
                time.sleep(2.0)
            
    except KeyboardInterrupt:
        print("Worker interrupted by user")
        
    except Exception as e:
        print(f"Worker encountered an error: {e}")
        
    finally:
        print("Face processing worker stopped")

def main(face_queue=None, shutdown_event=None):
    """
    Main function to run the face upload and search tool
    
    Args:
        face_queue: Optional queue to get faces from (for worker mode)
        shutdown_event: Optional event to signal shutdown
    """
    # Skip argument parsing if we're called with a queue (worker mode)
    if face_queue:
        print(f"Running in worker mode with provided queue (Queue object type: {type(face_queue).__name__})")
        print(f"Queue size: {face_queue.queue.qsize()}")
        # Set up necessary directories
        setup_directories()
        # Start the worker
        queue_worker(face_queue, shutdown_event, timeout=300)
        return

    # Only parse arguments when running standalone
    parser = argparse.ArgumentParser(description='Upload detected faces to FaceCheckID and search for matches')
    parser.add_argument('--dir', default=DEFAULT_FACES_DIR, help='Directory containing face images')
    parser.add_argument('--limit', type=int, help='Limit the number of faces to process')
    parser.add_argument('--force', action='store_true', help='Process all faces, even if previously processed')
    parser.add_argument('--token', help='FaceCheckID API token')
    parser.add_argument('--firecrawl-key', help='Firecrawl API key')
    parser.add_argument('--zyte-api-key', help='Zyte API key for social media scraping')
    parser.add_argument('--timeout', type=int, default=300, help='Search timeout in seconds (default: 300)')
    parser.add_argument('--skip-scrape', action='store_true', help='Skip all web scraping')
    parser.add_argument('--skip-social', action='store_true', help='Skip social media scraping with Zyte')
    parser.add_argument('--file', help='Process a specific face file instead of all unprocessed faces')
    parser.add_argument('--worker', action='store_true', help='Run in worker mode (requires parent process)')
    args = parser.parse_args()
    
    # Set up the API tokens
    global APITOKEN, FIRECRAWL_API_KEY, FIRECRAWL_AVAILABLE, ZYTE_API_KEY, ZYTE_AVAILABLE
    if args.token:
        APITOKEN = args.token
    if args.firecrawl_key:
        FIRECRAWL_API_KEY = args.firecrawl_key
    if args.zyte_api_key:
        ZYTE_API_KEY = args.zyte_api_key
        ZYTE_AVAILABLE = True
    
    # Override scraping availability if requested
    if args.skip_scrape:
        FIRECRAWL_AVAILABLE = False
        ZYTE_AVAILABLE = False
        print("All web scraping disabled by command line argument")
    elif args.skip_social:
        ZYTE_AVAILABLE = False
        print("Social media scraping with Zyte disabled by command line argument")
        
    # Print scraping capabilities
    print("\nScraping capabilities:")
    if FIRECRAWL_AVAILABLE:
        print("- Firecrawl: ENABLED (for general websites and LinkedIn)")
    else:
        print("- Firecrawl: DISABLED")
        
    if ZYTE_AVAILABLE:
        print("- Zyte API: ENABLED (for Instagram, Twitter, Facebook)")
    else:
        print("- Zyte API: DISABLED - set ZYTE_API_KEY in .env file to enable social media scraping")
    
    # Set up necessary directories
    setup_directories()
    
    # If worker mode requested but no queue provided, error out
    if args.worker:
        print("Worker mode requested but no queue provided. This mode should only be used from controller.py")
        return
    
    # Handle single file processing if specified
    if args.file:
        if not os.path.exists(args.file):
            print(f"Error: Specified file '{args.file}' does not exist!")
            return
        
        process_single_face(args.file, args.timeout)
        return
    
    # Check if faces directory exists for batch processing
    if not os.path.exists(args.dir):
        print(f"Error: Faces directory '{args.dir}' does not exist!")
        print(f"Make sure FotoRec.py has run and saved faces, or specify a different directory with --dir")
        return
    
    # Process face images
    process_faces(args.dir, args.limit, args.force, args.timeout)
    
    print("\nProcessing complete!")
    print(f"Results have been saved to the database.")

if __name__ == "__main__":
    # When run directly, no queue is provided
    main(face_queue=None, shutdown_event=None)