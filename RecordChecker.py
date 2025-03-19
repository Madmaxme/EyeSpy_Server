#!/usr/bin/env python3
"""
RecordChecker.py - Public records search extension for EyeSpy

This module integrates with the EyeSpy system to perform additional
record lookups based on the identified name and personal information.
It uses external APIs to find addresses, phone numbers, and other
specific personal details.
"""

import os
import json
import time
import re
import requests
import traceback
from typing import Dict, List, Any, Optional
from datetime import datetime
from dotenv import load_dotenv
from NameResolver import NameResolver

# Load environment variables from .env file
load_dotenv()

class RecordChecker:
    """
    Searches for additional personal records based on identified information.
    Supports multiple record search providers through a unified API.
    """
    
    # Supported provider APIs
    PROVIDER_PEOPLEDATA = "peopledata"
    PROVIDER_INTELIUS = "intelius"
    PROVIDER_SPOKEO = "spokeo"
    
    def __init__(self, api_key=None, provider=None):
        """
        Initialize the RecordChecker with API credentials
        
        Args:
            api_key: API key for the record search provider
            provider: Which provider to use (peopledata, intelius, spokeo)
        """
        # Use provided API key or get from environment
        self.api_key = api_key or os.getenv("RECORDS_API_KEY")
        if not self.api_key:
            raise ValueError("Records API key is required. Provide it as an argument or set RECORDS_API_KEY environment variable.")
        
        # Determine which provider to use
        self.provider = provider or os.getenv("RECORDS_PROVIDER") or self.PROVIDER_PEOPLEDATA
        print(f"[RECORDCHECKER] Using {self.provider} as records provider")
        
        # Initialize API endpoints based on provider
        if self.provider == self.PROVIDER_PEOPLEDATA:
            self.api_base_url = "https://api.peopledatalabs.com/v5"
            self.headers = {
                "X-Api-Key": self.api_key,
                "Content-Type": "application/json"
            }
        elif self.provider == self.PROVIDER_INTELIUS:
            self.api_base_url = "https://api.intelius.com/v2"
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        elif self.provider == self.PROVIDER_SPOKEO:
            self.api_base_url = "https://api.spokeo.com/v1"
            self.headers = {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json"
            }
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def clean_name_for_search(self, name):
        """
        Clean and format a name for API search, handling middle names/initials
        Now delegates to the shared NameResolver for consistency
        
        Args:
            name: Raw name string that might contain prefixes/formatting
            
        Returns:
            Cleaned name suitable for API search
        """
        name_variations = NameResolver.clean_name_for_search(name)
        print(f"[RECORDCHECKER] Using name variations from NameResolver: {name_variations}")
        return name_variations
    
    def extract_search_params(self, bio_data: Dict[str, Any], identity_analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract search parameters from bio data and identity analyses
        Now uses NameResolver to get the canonical name for consistency
        
        Args:
            bio_data: Biographical data (as text or parsed dict)
            identity_analyses: List of identity analyses from FaceUpload
            
        Returns:
            Dictionary of search parameters
        """
        search_params = {
            "name": None,
            "location": None,
            "age": None,
            "occupation": None,
            "company": None,
            "education": None,
            "social_profiles": []
        }
        
        # IMPORTANT CHANGE: First try to get the canonical name from the identity analyses
        if identity_analyses:
            canonical_name = NameResolver.resolve_canonical_name(identity_analyses)
            if canonical_name and canonical_name != "Unknown Person":
                search_params["name"] = canonical_name
                print(f"[RECORDCHECKER] Using canonical name from NameResolver: '{canonical_name}'")
        
        # Only proceed with other name extraction methods if we didn't get a canonical name
        if not search_params["name"]:
            print("[RECORDCHECKER] No canonical name found, falling back to bio data extraction")
            
            # Extract basic info from the bio if it's already parsed
            if isinstance(bio_data, dict):
                if "name" in bio_data:
                    search_params["name"] = bio_data["name"]
            
            # If bio is a string, try to extract key information using basic parsing
            elif isinstance(bio_data, str):
                # Try to extract name (usually in the first few lines)
                lines = bio_data.split('\n')
                
                # Common patterns for names in the bio text
                name_patterns = [
                    r'\*\*Full Name.*?:(.*?)(?:\*\*|$)',  # **Full Name**: John Doe
                    r'Name:(.*?)(?:$|\n)',                # Name: John Doe
                    r'^(.*?)(?:is|was|,|\n|$)'            # John Doe is a...
                ]
                
                # Try each pattern until we find a name
                for pattern in name_patterns:
                    for i, line in enumerate(lines[:5]):  # Check first 5 lines only
                        if line.strip():  # Skip empty lines
                            match = re.search(pattern, line, re.IGNORECASE)
                            if match:
                                potential_name = match.group(1).strip()
                                # Verify this looks like a name (at least 2 words, no special chars)
                                if ' ' in potential_name and len(potential_name.split()) >= 2:
                                    if re.match(r'^[A-Za-z\s\.\-\']+$', potential_name):
                                        search_params["name"] = potential_name
                                        break
                    if search_params["name"]:
                        break
                
                # If we failed with patterns, try a simple approach - take the first line if it looks like a name
                if not search_params["name"] and lines:
                    first_line = lines[0].strip()
                    # Remove any markdown formatting
                    first_line = re.sub(r'\*\*|\*|#', '', first_line)
                    # If it looks like a name (2+ words, only letters)
                    if ' ' in first_line and len(first_line.split()) >= 2:
                        if re.match(r'^[A-Za-z\s\.\-\']+$', first_line):
                            search_params["name"] = first_line
        
        # Extract location from bio data
        if isinstance(bio_data, dict):
            if "location" in bio_data:
                search_params["location"] = bio_data["location"]
            if "age" in bio_data:
                search_params["age"] = bio_data["age"]
            if "occupation" in bio_data:
                search_params["occupation"] = bio_data["occupation"]
            if "company" in bio_data:
                search_params["company"] = bio_data["company"]
        elif isinstance(bio_data, str):
            lines = bio_data.split('\n') if isinstance(bio_data, str) else []
            
            # Look for location patterns
            location_indicators = ["located in", "lives in", "based in", "from", "residing in", "location:", "address:"]
            for line in lines:
                for indicator in location_indicators:
                    if indicator.lower() in line.lower():
                        location_part = line.lower().split(indicator.lower(), 1)[1].strip()
                        # Take up to the next punctuation or end of line
                        location_match = re.search(r'^([^\.,:;]+)', location_part)
                        if location_match:
                            search_params["location"] = location_match.group(1).strip()
                            break
                if search_params["location"]:
                    break
            
            # Look for occupation
            occupation_indicators = ["works as", "is a", "profession:", "occupation:", "job:", "title:"]
            for line in lines:
                for indicator in occupation_indicators:
                    if indicator.lower() in line.lower():
                        occupation_part = line.lower().split(indicator.lower(), 1)[1].strip()
                        # Take up to the next punctuation or end of line
                        occupation_match = re.search(r'^([^\.,:;]+)', occupation_part)
                        if occupation_match:
                            search_params["occupation"] = occupation_match.group(1).strip()
                            break
                if search_params["occupation"]:
                    break
            
            # Look for company name
            company_indicators = ["works at", "employed by", "company:", "employer:", "works for"]
            for line in lines:
                for indicator in company_indicators:
                    if indicator.lower() in line.lower():
                        company_part = line.lower().split(indicator.lower(), 1)[1].strip()
                        # Take up to the next punctuation or end of line
                        company_match = re.search(r'^([^\.,:;]+)', company_part)
                        if company_match:
                            search_params["company"] = company_match.group(1).strip()
                            break
                if search_params["company"]:
                    break
        
        # Extract additional data from identity_analyses (only if not already found)
        for analysis in identity_analyses:
            # Extract data from scraped information
            if analysis.get("scraped_data") and analysis["scraped_data"].get("person_info"):
                person_info = analysis["scraped_data"]["person_info"]
                
                # Check if there's a nested person object
                if "person" in person_info:
                    person_data = person_info["person"]
                    # Extract name if not already found via canonical method
                    if not search_params["name"] and (person_data.get("fullName") or person_data.get("full_name")):
                        search_params["name"] = person_data.get("fullName") or person_data.get("full_name")
                    
                    # Extract location
                    if not search_params["location"] and person_data.get("location"):
                        search_params["location"] = person_data["location"]
                    
                    # Extract occupation
                    if not search_params["occupation"] and person_data.get("occupation"):
                        search_params["occupation"] = person_data["occupation"]
                    
                    # Extract company
                    if not search_params["company"] and person_data.get("company"):
                        search_params["company"] = person_data["company"]
                
                # Direct extraction if not nested
                else:
                    # Extract name if not already found via canonical method
                    if not search_params["name"] and (person_info.get("fullName") or person_info.get("full_name")):
                        search_params["name"] = person_info.get("fullName") or person_info.get("full_name")
                    
                    # Extract location
                    if not search_params["location"] and person_info.get("location"):
                        search_params["location"] = person_info["location"]
                    
                    # Extract occupation
                    if not search_params["occupation"] and person_info.get("occupation"):
                        search_params["occupation"] = person_info["occupation"]
                    
                    # Extract company
                    if not search_params["company"] and person_info.get("company"):
                        search_params["company"] = person_info["company"]
            
            # Extract social profile URLs
            if analysis.get("url"):
                url = analysis["url"]
                if any(social in url for social in ["facebook.com", "instagram.com", "twitter.com", "linkedin.com"]):
                    search_params["social_profiles"].append(url)
        
        # Clean up values
        for key, value in search_params.items():
            if isinstance(value, str):
                # Remove markdown formatting
                value = re.sub(r'\*\*|\*|#', '', value)
                # Remove leading/trailing spaces and standardize internal spaces
                value = re.sub(r'\s+', ' ', value).strip()
                search_params[key] = value
        
        # Filter out None values
        search_params = {k: v for k, v in search_params.items() if v is not None}
        
        # Log the extracted parameters
        print(f"[RECORDCHECKER] Extracted search parameters: {json.dumps(search_params)}")
        
        return search_params
    
    def search_records(self, search_params):
        """
        Search for records using the specific provider API
        
        Args:
            search_params: Dictionary of search parameters
            
        Returns:
            Search results from the API or None if not found
        """
        if self.provider == self.PROVIDER_PEOPLEDATA:
            return self._search_peopledata(search_params)
        elif self.provider == self.PROVIDER_INTELIUS:
            return self._search_intelius(search_params)
        elif self.provider == self.PROVIDER_SPOKEO:
            return self._search_spokeo(search_params)
        else:
            print(f"[RECORDCHECKER] Unsupported provider: {self.provider}")
            return None
    
    def _search_peopledata(self, search_params):
        """
        Search using the PeopleDataLabs API with improved name handling
        
        Args:
            search_params: Dictionary of search parameters
            
        Returns:
            PeopleDataLabs search results or None if not found
        """
        # If we don't have a name, we can't search effectively
        if not search_params.get("name"):
            print("[RECORDCHECKER] No name available for search")
            return None
        
        # Get name variations to try
        name_variations = self.clean_name_for_search(search_params.get("name"))
        
        # Set up other search parameters
        base_params = {}
        
        # Add location to search if available - ensuring correct format
        if search_params.get("location"):
            location = search_params["location"]
            # Location must be a string, not an object
            if isinstance(location, dict):
                # Convert from dict to string
                if location.get("city") and location.get("state"):
                    location = f"{location['city']}, {location['state']}"
                elif location.get("city"):
                    location = location["city"]
                elif location.get("state"):
                    location = location["state"]
            # Now add as a string
            base_params["location"] = [location]
        
        # Add work information
        if search_params.get("company"):
            base_params["company"] = [search_params["company"]]
        
        if search_params.get("occupation") or search_params.get("title"):
            title = search_params.get("occupation") or search_params.get("title")
            # Clean up formatting in title
            title = re.sub(r'\*\*|\*|#|_|-', '', title).strip()
            base_params["title"] = [title]
        
        # Include social profiles if available
        if search_params.get("social_profiles"):
            base_params["profile"] = []
            # Only use the first 3 social profiles
            for profile in search_params["social_profiles"][:3]:
                base_params["profile"].append(profile)
        
        # Try each name variation until we get a match
        for name in name_variations:
            # Create a copy of the base parameters
            pdl_params = base_params.copy()
            
            # Add the current name variation
            pdl_params["name"] = [name]
            
            try:
                print(f"[RECORDCHECKER] Trying PDL API with name: '{name}'")
                print(f"[RECORDCHECKER] PDL API parameters: {json.dumps(pdl_params)}")
                
                # Call the Person Enrichment API
                response = requests.post(
                    url=f"{self.api_base_url}/person/enrich",
                    headers=self.headers,
                    json=pdl_params
                )
                
                # Log the response for debugging
                print(f"[RECORDCHECKER] PDL API response status: {response.status_code}")
                
                # Check if we got a match
                if response.status_code == 200:
                    # Success - we found a match
                    data = response.json()
                    print(f"[RECORDCHECKER] Successfully found a match for '{name}'")
                    return data
                elif response.status_code == 404:
                    # Not found for this name variation - try the next one
                    print(f"[RECORDCHECKER] No match found for '{name}', trying next variation if available")
                else:
                    # Other error
                    print(f"[RECORDCHECKER] API error {response.status_code}: {response.text}")
                    
            except Exception as e:
                print(f"[RECORDCHECKER] Error searching records with '{name}': {e}")
        
        # If we've tried all name variations and found nothing
        print("[RECORDCHECKER] No matches found with any name variation")
        return None
    
    def _search_intelius(self, search_params):
        """Search using the Intelius API"""
        # Similar implementation to peopledata but for Intelius
        print("[RECORDCHECKER] Intelius search not fully implemented, using stub")
        return {"provider": "intelius", "stub": True}
    
    def _search_spokeo(self, search_params):
        """Search using the Spokeo API"""
        # Similar implementation to peopledata but for Spokeo
        print("[RECORDCHECKER] Spokeo search not fully implemented, using stub")
        return {"provider": "spokeo", "stub": True}
    
    def extract_personal_details(self, search_results):
        """
        Extract specific personal details from PeopleDataLabs search results
        
        Args:
            search_results: Raw search results from provider API
            
        Returns:
            Dictionary of structured personal details
        """
        personal_details = {
            "addresses": [],
            "phone_numbers": [],
            "emails": [],
            "relatives": [],
            "work_history": [],
            "education_history": [],
            "social_profiles": [],
            "basic_info": {},
            "skills": [],
            "languages": [],
            "certifications": []
        }
        
        if not search_results:
            return personal_details
        
        try:
            # PeopleDataLabs specific extraction
            if self.provider == self.PROVIDER_PEOPLEDATA:
                # Check if we have valid data
                if not search_results.get("data"):
                    print("[RECORDCHECKER] No data field in search results")
                    return personal_details
                    
                # Get the person data
                person = search_results["data"]
                
                # Debug the response structure
                print(f"[RECORDCHECKER] PDL response data keys: {list(person.keys())}")
                
                # Extract basic information
                basic_fields = [
                    "full_name", "first_name", "middle_name", "last_name", 
                    "birth_year", "birth_date", "headline", "industry", "job_title",
                    "summary", "location_name", "inferred_salary", "inferred_years_experience",
                    "linkedin_connections", "sex"
                ]
                
                for field in basic_fields:
                    if field in person and person[field]:
                        personal_details["basic_info"][field] = person[field]
                
                # Extract phone numbers
                if "phones" in person and isinstance(person["phones"], list):
                    # Use the detailed phones array if available
                    for phone in person["phones"]:
                        if isinstance(phone, dict) and "number" in phone:
                            phone_entry = {
                                "number": phone["number"],
                                "type": "unknown"
                            }
                            # Add additional metadata if available
                            if "first_seen" in phone:
                                phone_entry["first_seen"] = phone["first_seen"]
                            if "last_seen" in phone:
                                phone_entry["last_seen"] = phone["last_seen"]
                            personal_details["phone_numbers"].append(phone_entry)
                elif "phone_numbers" in person:
                    # Use the simple phone_numbers array as fallback
                    if isinstance(person["phone_numbers"], list):
                        for phone in person["phone_numbers"]:
                            if isinstance(phone, str):
                                personal_details["phone_numbers"].append({
                                    "number": phone,
                                    "type": "unknown"
                                })
                    elif person.get("mobile_phone"):
                        # Use mobile_phone as fallback
                        personal_details["phone_numbers"].append({
                            "number": person["mobile_phone"],
                            "type": "mobile"
                        })
                
                # Extract emails
                if "emails" in person and isinstance(person["emails"], list):
                    # Use the detailed emails array if available
                    for email in person["emails"]:
                        if isinstance(email, dict) and "address" in email:
                            email_entry = {
                                "address": email["address"],
                                "type": email.get("type", "unknown")
                            }
                            # Add additional metadata if available
                            if "first_seen" in email:
                                email_entry["first_seen"] = email["first_seen"]
                            if "last_seen" in email:
                                email_entry["last_seen"] = email["last_seen"]
                            personal_details["emails"].append(email_entry)
                elif "personal_emails" in person and isinstance(person["personal_emails"], list):
                    # Use personal_emails as fallback
                    for email in person["personal_emails"]:
                        if isinstance(email, str):
                            personal_details["emails"].append({
                                "address": email,
                                "type": "personal"
                            })
                
                # Extract addresses from street_addresses array
                if "street_addresses" in person and isinstance(person["street_addresses"], list):
                    for address in person["street_addresses"]:
                        if isinstance(address, dict):
                            address_parts = []
                            
                            # Build address string from components
                            if address.get("street_address") and isinstance(address.get("street_address"), str):
                                address_parts.append(address["street_address"])
                            if address.get("address_line_2") and isinstance(address.get("address_line_2"), str):
                                address_parts.append(address["address_line_2"])
                            if address.get("locality") and isinstance(address.get("locality"), str):
                                address_parts.append(address["locality"])
                            if address.get("region") and isinstance(address.get("region"), str):
                                address_parts.append(address["region"])
                            if address.get("postal_code") and isinstance(address.get("postal_code"), str):
                                address_parts.append(address["postal_code"])
                            if address.get("country") and isinstance(address.get("country"), str):
                                address_parts.append(address["country"])
                            
                            # Make sure we only have string parts before joining
                            address_parts = [part for part in address_parts if isinstance(part, str)]
                            full_address = ", ".join(address_parts) if address_parts else "Unknown Address"
                            
                            # Create address entry
                            address_entry = {
                                "address": full_address,
                                "status": "historical",
                                "type": "residential"
                            }
                            
                            # Add dates if available
                            if address.get("first_seen"):
                                address_entry["first_seen"] = address["first_seen"]
                            if address.get("last_seen"):
                                address_entry["last_seen"] = address["last_seen"]
                                # Mark as current if this is the most recent address
                                if address["last_seen"] == person.get("location_last_updated"):
                                    address_entry["status"] = "current"
                            
                            personal_details["addresses"].append(address_entry)
                
                # Add current location if no addresses found
                if not personal_details["addresses"] and person.get("location_name"):
                    location_parts = []
                    
                    # Build address string from location components - validate types first
                    if person.get("location_street_address") and isinstance(person.get("location_street_address"), str):
                        location_parts.append(person["location_street_address"])
                    if person.get("location_address_line_2") and isinstance(person.get("location_address_line_2"), str):
                        location_parts.append(person["location_address_line_2"])
                    if person.get("location_name") and isinstance(person.get("location_name"), str):
                        location_parts.append(person["location_name"])
                    
                    # Make sure we only have string parts before joining
                    location_parts = [part for part in location_parts if isinstance(part, str)]
                    full_location = ", ".join(location_parts) if location_parts else "Unknown Location"
                    
                    # Create address entry for current location
                    personal_details["addresses"].append({
                        "address": full_location,
                        "status": "current",
                        "type": "residential"
                    })
                
                # Extract work history from experience array
                if "experience" in person and isinstance(person["experience"], list):
                    for job in person["experience"]:
                        if isinstance(job, dict):
                            # Extract company name
                            company_name = "Unknown Company"
                            if isinstance(job.get("company"), dict) and job["company"].get("name"):
                                company_name = job["company"]["name"]
                            elif isinstance(job.get("company"), str):
                                company_name = job["company"]
                            
                            # Extract job title
                            job_title = "Unknown Position"
                            if isinstance(job.get("title"), dict) and job["title"].get("name"):
                                job_title = job["title"]["name"]
                            elif isinstance(job.get("title"), str):
                                job_title = job["title"]
                            
                            # Create job entry
                            job_entry = {
                                "company": company_name,
                                "title": job_title
                            }
                            
                            # Add dates
                            if job.get("start_date"):
                                job_entry["start_date"] = job["start_date"]
                            if job.get("end_date"):
                                job_entry["end_date"] = job["end_date"]
                            
                            # Add company details if available
                            if isinstance(job.get("company"), dict):
                                company = job["company"]
                                if company.get("industry"):
                                    job_entry["industry"] = company["industry"]
                                if company.get("website"):
                                    job_entry["website"] = company["website"]
                                if company.get("size"):
                                    job_entry["company_size"] = company["size"]
                                
                                # Add company location
                                if isinstance(company.get("location"), dict):
                                    loc = company["location"]
                                    if loc.get("name"):
                                        job_entry["location"] = loc["name"]
                            
                            # Add summary if available
                            if job.get("summary"):
                                job_entry["summary"] = job["summary"]
                            
                            personal_details["work_history"].append(job_entry)
                
                # Extract education history
                if "education" in person and isinstance(person["education"], list):
                    for edu in person["education"]:
                        if isinstance(edu, dict):
                            # Extract school name
                            school_name = "Unknown School"
                            if isinstance(edu.get("school"), dict) and edu["school"].get("name"):
                                school_name = edu["school"]["name"]
                            elif isinstance(edu.get("school"), str):
                                school_name = edu["school"]
                            
                            # Create education entry
                            edu_entry = {
                                "school": school_name
                            }
                            
                            # Add degree information
                            if edu.get("degrees") and isinstance(edu["degrees"], list) and edu["degrees"]:
                                edu_entry["degree"] = edu["degrees"][0]
                            
                            # Add dates
                            if edu.get("start_date"):
                                edu_entry["start_date"] = edu["start_date"]
                            if edu.get("end_date"):
                                edu_entry["end_date"] = edu["end_date"]
                            
                            # Add majors/minors
                            if edu.get("majors") and isinstance(edu["majors"], list) and edu["majors"]:
                                edu_entry["majors"] = edu["majors"]
                            if edu.get("minors") and isinstance(edu["minors"], list) and edu["minors"]:
                                edu_entry["minors"] = edu["minors"]
                            
                            # Add GPA if available
                            if edu.get("gpa"):
                                edu_entry["gpa"] = edu["gpa"]
                            
                            # Add summary if available
                            if edu.get("summary"):
                                edu_entry["summary"] = edu["summary"]
                            
                            personal_details["education_history"].append(edu_entry)
                
                # Extract social profiles
                if "profiles" in person and isinstance(person["profiles"], list):
                    for profile in person["profiles"]:
                        if isinstance(profile, dict) and profile.get("url") and profile.get("network"):
                            profile_entry = {
                                "network": profile["network"],
                                "url": profile["url"]
                            }
                            
                            if profile.get("username"):
                                profile_entry["username"] = profile["username"]
                            
                            # Add dates if available
                            if profile.get("first_seen"):
                                profile_entry["first_seen"] = profile["first_seen"]
                            if profile.get("last_seen"):
                                profile_entry["last_seen"] = profile["last_seen"]
                            
                            personal_details["social_profiles"].append(profile_entry)
                
                # Extract skills - ensure they're strings
                if "skills" in person and isinstance(person["skills"], list):
                    personal_details["skills"] = [
                        skill for skill in person["skills"] 
                        if isinstance(skill, str)
                    ]
                
                # Extract languages
                if "languages" in person and isinstance(person["languages"], list):
                    for language in person["languages"]:
                        if isinstance(language, dict) and language.get("name"):
                            language_entry = {
                                "name": language["name"]
                            }
                            
                            if language.get("proficiency"):
                                language_entry["proficiency"] = language["proficiency"]
                            
                            personal_details["languages"].append(language_entry)
                
                # Extract certifications
                if "certifications" in person and isinstance(person["certifications"], list):
                    for cert in person["certifications"]:
                        if isinstance(cert, dict) and cert.get("name"):
                            cert_entry = {
                                "name": cert["name"]
                            }
                            
                            if cert.get("organization"):
                                cert_entry["organization"] = cert["organization"]
                            
                            if cert.get("start_date"):
                                cert_entry["start_date"] = cert["start_date"]
                            if cert.get("end_date"):
                                cert_entry["end_date"] = cert["end_date"]
                            
                            personal_details["certifications"].append(cert_entry)
                
                # Check if we found any useful information
                has_data = False
                for key, value in personal_details.items():
                    if value and (isinstance(value, list) or isinstance(value, dict) and value):
                        has_data = True
                        break
                        
                if not has_data:
                    print("[RECORDCHECKER] Successfully matched person but no detailed fields available")
                    
                    # Add basic info if available
                    if person.get("full_name"):
                        personal_details["basic_info"]["full_name"] = person.get("full_name")
                        print(f"[RECORDCHECKER] Basic info found: Name: {person.get('full_name')}")
                    if person.get("location_name"):
                        personal_details["basic_info"]["location"] = person.get("location_name")
                        print(f"[RECORDCHECKER] Basic info found: Location: {person.get('location_name')}")
                    if person.get("job_title"):
                        personal_details["basic_info"]["job_title"] = person.get("job_title")
                        print(f"[RECORDCHECKER] Basic info found: Job: {person.get('job_title')}")
            
            # Other providers would have similar extraction logic
            elif self.provider == self.PROVIDER_INTELIUS:
                # Stub for Intelius
                pass
                
            elif self.provider == self.PROVIDER_SPOKEO:
                # Stub for Spokeo
                pass
        
        except Exception as e:
            print(f"[RECORDCHECKER] Error extracting personal details: {e}")
            traceback.print_exc()
        
        return personal_details
    
    def generate_records_report(self, personal_details):
        """
        Generate a formatted report of the personal records
        
        Args:
            personal_details: Structured personal details dictionary
            
        Returns:
            Formatted report as string
        """
        report = []
        report.append("## PERSONAL RECORDS REPORT")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Data Provider: {self.provider.upper()}")
        report.append("")
        
        # Add basic information section
        if personal_details.get("basic_info"):
            report.append("### BASIC INFORMATION")
            basic_info = personal_details["basic_info"]
            
            if basic_info.get("full_name"):
                report.append(f"**Name:** {basic_info['full_name']}")
            
            if basic_info.get("location_name"):
                report.append(f"**Location:** {basic_info['location_name']}")
            
            if basic_info.get("birth_date"):
                report.append(f"**Birth Date:** {basic_info['birth_date']}")
            elif basic_info.get("birth_year"):
                report.append(f"**Birth Year:** {basic_info['birth_year']}")
            
            if basic_info.get("job_title"):
                report.append(f"**Occupation:** {basic_info['job_title']}")
            
            if basic_info.get("inferred_salary"):
                report.append(f"**Estimated Salary:** {basic_info['inferred_salary']}")
            
            if basic_info.get("industry"):
                report.append(f"**Industry:** {basic_info['industry']}")
            
            report.append("")
        
        # Add addresses section
        if personal_details.get("addresses"):
            report.append("### ADDRESSES")
            for i, addr in enumerate(personal_details["addresses"], 1):
                addr_text = f"{i}. {addr['address']}"
                
                # Add status and type if available
                addr_meta = []
                if addr.get("status"):
                    addr_meta.append(addr["status"])
                if addr.get("type"):
                    addr_meta.append(addr["type"])
                
                if addr_meta:
                    addr_text += f" ({', '.join(addr_meta)})"
                
                report.append(addr_text)
                
                # Add dates if available
                if addr.get("first_seen") and addr.get("last_seen"):
                    report.append(f"   First seen: {addr['first_seen']} | Last seen: {addr['last_seen']}")
            
            report.append("")
        
        # Add phone numbers section
        if personal_details.get("phone_numbers"):
            report.append("### PHONE NUMBERS")
            for i, phone in enumerate(personal_details["phone_numbers"], 1):
                phone_text = f"{i}. {phone['number']}"
                
                if phone.get("type"):
                    phone_text += f" ({phone['type']})"
                
                report.append(phone_text)
                
                # Add dates if available
                if phone.get("first_seen") and phone.get("last_seen"):
                    report.append(f"   First seen: {phone['first_seen']} | Last seen: {phone['last_seen']}")
            
            report.append("")
        
        # Add emails section
        if personal_details.get("emails"):
            report.append("### EMAIL ADDRESSES")
            for i, email in enumerate(personal_details["emails"], 1):
                email_text = f"{i}. {email['address']}"
                
                if email.get("type"):
                    email_text += f" ({email['type']})"
                
                report.append(email_text)
                
                # Add dates if available
                if email.get("first_seen") and email.get("last_seen"):
                    report.append(f"   First seen: {email['first_seen']} | Last seen: {email['last_seen']}")
            
            report.append("")
        
        # Add relatives section
        if personal_details.get("relatives"):
            report.append("### KNOWN RELATIVES")
            for i, relative in enumerate(personal_details["relatives"], 1):
                report.append(f"{i}. {relative['name']} ({relative['type']})")
            report.append("")
        
        # Add social profiles section
        if personal_details.get("social_profiles"):
            report.append("### SOCIAL PROFILES")
            for i, profile in enumerate(personal_details["social_profiles"], 1):
                profile_text = f"{i}. {profile['network'].capitalize()}: {profile['url']}"
                
                if profile.get("username"):
                    profile_text += f" (Username: {profile['username']})"
                
                report.append(profile_text)
            
            report.append("")
        
        # Add work history
        if personal_details.get("work_history"):
            report.append("### WORK HISTORY")
            for i, job in enumerate(personal_details["work_history"], 1):
                job_text = f"{i}. {job['title']} at {job['company']}"
                
                # Add dates if available
                if job.get("start_date") and job.get("end_date"):
                    job_text += f" ({job['start_date']} to {job['end_date']})"
                elif job.get("start_date"):
                    job_text += f" (From {job['start_date']})"
                elif job.get("end_date"):
                    job_text += f" (Until {job['end_date']})"
                
                report.append(job_text)
                
                # Add additional job details if available
                if job.get("location"):
                    report.append(f"   Location: {job['location']}")
                if job.get("industry"):
                    report.append(f"   Industry: {job['industry']}")
                if job.get("website"):
                    report.append(f"   Website: {job['website']}")
            
            report.append("")
        
        # Add education history
        if personal_details.get("education_history"):
            report.append("### EDUCATION")
            for i, edu in enumerate(personal_details["education_history"], 1):
                edu_text = f"{i}. {edu['school']}"
                
                if edu.get("degree"):
                    edu_text += f" - {edu['degree']}"
                
                report.append(edu_text)
                
                # Add dates if available
                if edu.get("start_date") and edu.get("end_date"):
                    report.append(f"   Attended: {edu['start_date']} to {edu['end_date']}")
                
                # Add majors if available
                if edu.get("majors"):
                    report.append(f"   Majors: {', '.join(edu['majors'])}")
                
                # Add minors if available
                if edu.get("minors"):
                    report.append(f"   Minors: {', '.join(edu['minors'])}")
                
                # Add GPA if available
                if edu.get("gpa"):
                    report.append(f"   GPA: {edu['gpa']}")
            
            report.append("")
        
        # Add skills section
        if personal_details.get("skills"):
            report.append("### SKILLS")
            skills_text = ", ".join(personal_details["skills"])
            report.append(skills_text)
            report.append("")
        
        # Add languages section
        if personal_details.get("languages"):
            report.append("### LANGUAGES")
            for i, lang in enumerate(personal_details["languages"], 1):
                lang_text = f"{i}. {lang['name']}"
                
                if lang.get("proficiency"):
                    # Convert proficiency number to text description
                    proficiency_map = {
                        1: "Beginner",
                        2: "Elementary",
                        3: "Intermediate",
                        4: "Advanced",
                        5: "Fluent/Native"
                    }
                    proficiency = proficiency_map.get(lang["proficiency"], f"Level {lang['proficiency']}")
                    lang_text += f" ({proficiency})"
                
                report.append(lang_text)
            
            report.append("")
        
        # Add certifications section
        if personal_details.get("certifications"):
            report.append("### CERTIFICATIONS")
            for i, cert in enumerate(personal_details["certifications"], 1):
                cert_text = f"{i}. {cert['name']}"
                
                if cert.get("organization"):
                    cert_text += f" from {cert['organization']}"
                
                if cert.get("start_date") and cert.get("end_date"):
                    cert_text += f" ({cert['start_date']} to {cert['end_date']})"
                
                report.append(cert_text)
            
            report.append("")
        
        # Add disclaimer
        report.append("---")
        report.append("CONFIDENTIAL INFORMATION: For authorized use only. Use of this data must comply with applicable privacy laws and terms of service.")
        
        return "\n".join(report)
    
    def process_face_record(self, face_id):
        """
        Process a face record from the database, search for additional records,
        and save the results back to the database
        
        Args:
            face_id: The face ID to process
            
        Returns:
            True if records were found and saved, False otherwise
        """
        print(f"[RECORDCHECKER] Processing face ID: {face_id}")
        
        try:
            # Import database functions
            from db_connector import get_identity_analyses, get_bio_text, save_record_data
            
            # Get identity analyses from database
            identity_analyses = get_identity_analyses(face_id)
            if not identity_analyses:
                print(f"[RECORDCHECKER] No identity analyses found for face ID: {face_id}")
                return False
                
            # Get bio data if available
            bio_data = get_bio_text(face_id)
            
            # Extract search parameters
            search_params = self.extract_search_params(bio_data, identity_analyses)
            
            # If we don't have a name, we can't search
            if not search_params.get("name"):
                print("[RECORDCHECKER] No name found to search for records")
                return False
            
            print(f"[RECORDCHECKER] Searching for records for: {search_params.get('name')}")
            
            # Search for records
            search_results = self.search_records(search_params)
            
            # Check if we found any results
            if not search_results:
                print("[RECORDCHECKER] No records found")
                
                # Create empty record data
                empty_record_data = {
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                    "provider": self.provider,
                    "search_params": search_params,
                    "status": "no_records_found",
                    "personal_details": {
                        "addresses": [],
                        "phone_numbers": [],
                        "emails": [],
                        "relatives": [],
                        "work_history": [],
                        "education_history": [],
                        "social_profiles": []
                    }
                }
                
                # Save empty record data to database
                save_record_data(face_id, empty_record_data, search_params.get("name", "Unknown"))
                return False
            
            # Extract structured personal details
            personal_details = self.extract_personal_details(search_results)
            
            # Create record data
            record_data = {
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "provider": self.provider,
                "search_params": search_params,
                "status": "records_found",
                "personal_details": personal_details,
                "raw_results": search_results
            }
            
            # Save record data to database
            save_record_data(face_id, record_data, search_params.get("name", "Unknown"))
            print(f"[RECORDCHECKER] Added record data to database for face ID: {face_id}")
            return True
                
        except Exception as e:
            print(f"[RECORDCHECKER] Error processing face {face_id}: {e}")
            traceback.print_exc()
            return False


def integrate_with_biogen():
    """
    This integration is disabled because it causes race conditions with bio_integration.py
    bio_integration.py already handles record checking before bio generation.
    This function is kept as a placeholder for reference.
    """
    print("[RECORDCHECKER] BioGenerator integration through RecordChecker is disabled to prevent race conditions")
    print("[RECORDCHECKER] Use bio_integration.py for the proper integration flow")
    return False


# For command-line usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Check public records based on identity information')
    parser.add_argument('path', help='Path to the person directory containing identity analyses')
    parser.add_argument('--api-key', help='Records API key (optional if set in environment)')
    parser.add_argument('--provider', help='Records provider (peopledata, intelius, spokeo)')
    
    args = parser.parse_args()
    
    try:
        # Initialize the record checker
        checker = RecordChecker(api_key=args.api_key, provider=args.provider)
        
        # Process the directory
        output_file = checker.process_result_directory(args.path)
        
        if output_file:
            print(f"[RECORDCHECKER] Successfully generated records report. See {output_file}")
        
    except ValueError as e:
        print(f"[RECORDCHECKER] Error: {e}")
    except Exception as e:
        print(f"[RECORDCHECKER] Unexpected error: {e}")
        traceback.print_exc()