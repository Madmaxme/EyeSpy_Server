#!/usr/bin/env python3
import json
import os
import traceback
from datetime import datetime
import openai
from dotenv import load_dotenv
from NameResolver import NameResolver
from db_connector import get_identity_analyses


# Load environment variables from .env file (if it exists)
load_dotenv()

class BioGenerator:
    """Generate formatted bios from face search results using OpenAI API"""
    
    def __init__(self, api_key=None):
        """Initialize the BioGenerator with OpenAI API key"""
        # Use provided API key or get from environment
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Provide it as an argument or set OPENAI_API_KEY environment variable.")
        
        # Initialize the OpenAI client
        self.client = openai.OpenAI(api_key=self.api_key)
    
    def load_data(self, face_id):
        """Load identity analyses data from the database"""
        try:
            from db_connector import get_identity_analyses
            identity_analyses = get_identity_analyses(face_id)
            
            if not identity_analyses:
                raise ValueError(f"No identity analyses found for face ID: {face_id}")
            
            # Return a data structure similar to what we'd get from JSON file
            return {"identity_analyses": identity_analyses}
        except Exception as e:
            print(f"[BIOGEN] Error loading data from database: {e}")
            raise
    
    def prepare_summarized_data(self, identity_analyses):
        """
        Create a focused version of the identity_analyses data by finding the most frequently
        occurring name and including entries that match this name.
        This approach ensures we identify the correct person while reducing token usage.
        """
        if not identity_analyses:
            return []
        
        # Step 1: Collect all names from all analyses
        all_names = []
        name_to_analysis = {}  # Maps names to original analysis objects
        name_to_score = {}     # Maps names to match scores (for weighting/tiebreaking)
        name_to_frequency = {} # Maps names to occurrence frequency
        
        for analysis in identity_analyses:
            match_score = analysis.get("score", 0)
            name_candidates = []
            
            # First, check for explicit candidate_names from Firecrawl
            if analysis.get("scraped_data") and analysis["scraped_data"].get("candidate_names"):
                candidate_names = analysis["scraped_data"]["candidate_names"]
                for candidate in candidate_names:
                    name_candidates.append(candidate["name"])
                    
                    # Track frequency of each name
                    norm_name = candidate["name"].lower().strip()
                    if norm_name not in name_to_frequency:
                        name_to_frequency[norm_name] = 0
                    name_to_frequency[norm_name] += 1
                
                print(f"[BIOGEN] Found {len(candidate_names)} explicit name candidates")
            
            # Fallback to old method if no explicit candidates
            if not name_candidates and analysis.get("scraped_data") and analysis["scraped_data"].get("person_info"):
                person_info = analysis["scraped_data"]["person_info"]
                
                # Check nested person object
                if "person" in person_info:
                    person_obj = person_info["person"]
                    if "fullName" in person_obj:
                        name_candidates.append(person_obj["fullName"])
                    elif "full_name" in person_obj:
                        name_candidates.append(person_obj["full_name"])
                    elif "name" in person_obj:
                        name_candidates.append(person_obj["name"])
                
                # Check flat structure
                if not name_candidates:
                    if "fullName" in person_info:
                        name_candidates.append(person_info["fullName"])
                    elif "full_name" in person_info:
                        name_candidates.append(person_info["full_name"])
                    elif "name" in person_info:
                        name_candidates.append(person_info["name"])
                
                # Update frequency for fallback names too
                for name in name_candidates:
                    if isinstance(name, str):
                        norm_name = name.lower().strip()
                        if norm_name not in name_to_frequency:
                            name_to_frequency[norm_name] = 0
                        name_to_frequency[norm_name] += 1
                    elif isinstance(name, list):
                        # Handle case where name is a list
                        for n in name:
                            if isinstance(n, str):
                                norm_name = n.lower().strip()
                                if norm_name not in name_to_frequency:
                                    name_to_frequency[norm_name] = 0
                                name_to_frequency[norm_name] += 1
            
            try:
                # Process all found names
                for person_name in name_candidates:
                    if not person_name:
                        continue
                        
                    # Handle both string and list cases
                    if isinstance(person_name, str):
                        # Normalize the name (lowercase, strip extra spaces)
                        norm_name = person_name.lower().strip()
                        all_names.append(norm_name)
                        
                        # Store analysis by name
                        if norm_name not in name_to_analysis:
                            name_to_analysis[norm_name] = []
                        name_to_analysis[norm_name].append(analysis)
                        
                        # Store highest score for this name
                        if norm_name not in name_to_score or match_score > name_to_score[norm_name]:
                            name_to_score[norm_name] = match_score
                    elif isinstance(person_name, list):
                        # Handle list of names
                        for name in person_name:
                            if isinstance(name, str) and name:
                                norm_name = name.lower().strip()
                                all_names.append(norm_name)
                                
                                # Store analysis by name
                                if norm_name not in name_to_analysis:
                                    name_to_analysis[norm_name] = []
                                name_to_analysis[norm_name].append(analysis)
                                
                                # Store highest score for this name
                                if norm_name not in name_to_score or match_score > name_to_score[norm_name]:
                                    name_to_score[norm_name] = match_score
            except Exception as e:
                print(f"[BIOGEN] Error processing name candidates: {e}")
                print(f"[BIOGEN] name_candidates type: {type(name_candidates).__name__}")
                print(f"[BIOGEN] name_candidates value: {name_candidates}")
            
            # Log the frequency counts
            print(f"[BIOGEN] Name frequency counts: {name_to_frequency}")
                    
        
        # Step 2: Group similar names (using our improved _is_same_person method)
        name_groups = []
        processed_names = set()
        
        for name in all_names:
            if name in processed_names:
                continue
                
            # Start a new group with this name
            current_group = [name]
            processed_names.add(name)
            
            # Find all similar names
            for other_name in all_names:
                if other_name not in processed_names and self._is_same_person(name, other_name):
                    current_group.append(other_name)
                    processed_names.add(other_name)
            
            # Add the group to our list of groups
            name_groups.append(current_group)
        
        # Step 3: Find the most common name group
        most_common_group = []
        highest_frequency = 0
        highest_score = 0
        
        for group in name_groups:
            # Calculate total frequency of this name group
            group_frequency = sum([name_to_frequency.get(name, 0) for name in group])
            
            # Find highest score in this group
            group_max_score = max([name_to_score.get(name, 0) for name in group])
            
            # Log group statistics
            print(f"[BIOGEN] Name group: {group}, Frequency: {group_frequency}, Max score: {group_max_score}")
            
            # Check if this group is more frequent, or equally frequent but higher scored
            if group_frequency > highest_frequency or (group_frequency == highest_frequency and group_max_score > highest_score):
                most_common_group = group
                highest_frequency = group_frequency
                highest_score = group_max_score
        
        # Step 4: Choose the canonical name from the most common group
        # Prefer the name with the highest frequency, using score as a tiebreaker
        canonical_name = None
        if most_common_group:
            # Sort the group by frequency first, then by score
            sorted_names = sorted(most_common_group, 
                                 key=lambda name: (name_to_frequency.get(name, 0), name_to_score.get(name, 0)), 
                                 reverse=True)
            
            # Get top name by frequency
            canonical_name = sorted_names[0]
            top_frequency = name_to_frequency.get(canonical_name, 0)
            
            # Log individual name frequencies
            for name in sorted_names[:5]:  # Log top 5 names
                print(f"[BIOGEN] Name candidate: {name}, Frequency: {name_to_frequency.get(name, 0)}, Score: {name_to_score.get(name, 0)}")
            
            # Get original case/format from name_to_analysis keys
            for original_name in name_to_analysis.keys():
                if original_name.lower() == canonical_name:
                    canonical_name = original_name
                    break
                    
            print(f"[BIOGEN] Selected canonical name: '{canonical_name}' with frequency: {top_frequency}")
        
        # If we couldn't find any names, return empty list
        if not canonical_name:
            print("[BIOGEN] No names found in any analysis")
            return []
            
        # Step 5: Collect all analyses that match the canonical name
        relevant_data = []
        for name in most_common_group:
            for analysis in name_to_analysis[name]:
                entry = self._extract_person_data(analysis)
                if entry:
                    relevant_data.append(entry)
        
        print(f"[BIOGEN] Found {len(relevant_data)} entries matching the canonical person")
        return relevant_data
    
    def _is_same_person(self, name1, name2):
        """
        Improved comparison to check if two names likely refer to the same person
        Uses a more sophisticated approach than simple substring matching
        
        Now calls the shared NameResolver implementation to ensure consistency
        """
        return NameResolver.is_same_person(name1, name2)
    
    def _extract_person_data(self, analysis):
        """
        Extract person data from an analysis entry
        Now includes full_content for more detailed bio generation
        """
        if not analysis:
            return None
            
        entry = {}
        
        # Basic match info
        entry["match_score"] = analysis.get("match_score", 0)
        entry["domain"] = analysis.get("domain", "unknown")
        
        # Extract person info
        if analysis.get("scraped_data") and analysis["scraped_data"].get("person_info"):
            person_info = analysis["scraped_data"]["person_info"]
            
            # Include all person info fields including potential full_content
            # For nested person object
            if "person" in person_info:
                entry["person_info"] = {"person": person_info["person"]}
            else:
                entry["person_info"] = person_info
            
            # Specifically check for full_content and make sure it's included
            if "full_content" in person_info:
                entry["full_content"] = person_info["full_content"]
            elif "person" in person_info and "full_content" in person_info["person"]:
                entry["full_content"] = person_info["person"]["full_content"]
        
        # Extract text content if available
        if analysis.get("scraped_data") and analysis["scraped_data"].get("text_content"):
            text = analysis["scraped_data"]["text_content"]
            # Keep this filter to avoid HTML content, but allow longer articles
            if not text.startswith("<html"):
                entry["text_content"] = text
        
        return entry
    
    def prepare_prompt(self, identity_analyses, record_analyses=None, record_search_names=None):
        """
        Prepare the prompt for OpenAI API using identity and record analyses
        Uses the improved frequency-based name selection
        
        Args:
            identity_analyses: List of identity analysis results from face search
            record_analyses: Optional record analysis data from RecordChecker
            record_search_names: Optional name(s) used for record search
        
        Returns:
            Formatted prompt string
        """
        # Get data for the most frequently occurring person and their matches
        person_data = self.prepare_summarized_data(identity_analyses)
        
        # Extract the canonical name using our improved approach
        canonical_name = self.extract_name(identity_analyses)
        name = canonical_name if canonical_name else "the subject"
        
        # Record search name info for reference
        record_search_info = ""
        if record_search_names:
            if isinstance(record_search_names, list):
                search_names_str = ", ".join(record_search_names)
                record_search_info = f"\n\nRecord search was performed using these name(s): {search_names_str}"
            else:
                record_search_info = f"\n\nRecord search was performed using name: {record_search_names}"
        
        prompt = f"""
        You are a professional intelligence analyst creating a profile for {name} based on the following data.
        
        All entries in the data are about the same person. Follow these instructions exactly to create a consistent profile.
        
        VERY IMPORTANT: The data includes full article content in the "full_content" field. Use this to create a DETAILED SUMMARY
        section, but keep all other sections concise and to the point.
        
        CRITICAL INSTRUCTION: If record data is provided (addresses, phone numbers, emails, education, work history, etc.), 
        you MUST include ALL of this record data in the appropriate sections of the profile. Do not omit any record data.{record_search_info}
        
        Create a profile with this exact template:

        **{name} - Professional Profile**

        **1. Full Name and Professional Title:**
           - {name}, [Professional Title - keep to one line]

        **2. Summary:**
           [THIS SECTION SHOULD BE DETAILED AND IN-DEPTH - 3-5 comprehensive paragraphs with specific stories, events, 
           achievements, and quotes from the full_content. Include specific dates, names, places, and detailed context 
           about their life and career. This is the main section where you should be thorough and detailed.]

        **3. Current and Past Organizations/Roles:**
           - Current: [Organization/Role in one concise line]
           - Past: [List ALL past roles from work_history, one line each]
           [If unknown, write "No current role information available."]

        **4. Education:**
           - [List ALL education entries from education_history, one line each]
           [If unknown, write "No education information available."]

        **5. Skills and Certifications:**
           - Skills: [List all skills]
           - Certifications: [List all certifications]
           - Languages: [List all languages]
           [If unknown, write "No skills or certifications information available."]

        **6. Location Information:**
           - [List ALL addresses from record data, one per line]
           [If unknown, write "No location information available."]

        **7. Contact Information:**
           - Phone: [List ALL phone numbers from record data, one per line]
           - Email: [List ALL email addresses from record data, one per line]
           - Social: [List ALL social profiles from record data, one per line]
           [If unknown, write "No contact information available."]

        **8. Personal Connections:**
           - Family: [List all relatives from record data]
           - Associates: [List other known connections]
           [If unknown, write "No relationship information available."]

        **9. Notable Achievements:**
           - [Achievement 1 - one concise line]
           - [Achievement 2 - one concise line]
           [If unknown, write "No achievement information available."]

        **10. Notable Quotes:**
           - "[Direct quote if available]"
           [If none, write "No notable quotes available."]

        Use facts only - no speculation outside the summary section. Be extremely concise in all sections except the Summary.
        Follow this template structure exactly without deviation. The Summary should contain all the rich details and depth,
        while other sections should be brief bullet points.
        
        AGAIN, I MUST EMPHASIZE: If record data is provided (under "personal_details"), you MUST list ALL addresses, 
        phone numbers, emails, education history, work history, and relationships in the appropriate sections. Do not 
        summarize or omit any record details, even if they seem redundant.
        """
        
        # Add the identity data section
        prompt += """
        
        Here is the IDENTITY MATCH data to analyze (all related to the same person):
        """
        
        # Add the person-specific data as a JSON string
        prompt += json.dumps(person_data, indent=2)
        
        # Add record data if available
        if record_analyses and record_analyses.get("personal_details"):
            prompt += """
            
            Here is additional PERSONAL RECORDS data found for this individual:
            """
            
            # Add the personal details from record search
            prompt += json.dumps(record_analyses["personal_details"], indent=2)
        
        # Return the prompt
        return prompt
    
    def generate_bio(self, identity_analyses, record_analyses=None, record_search_names=None):
        """
        Generate a bio using OpenAI's API with both identity and record data
        
        Args:
            identity_analyses: List of identity analysis results
            record_analyses: Optional record analysis data
            record_search_names: Optional name(s) used for record search
            
        Returns:
            Generated biographical text
        """
        prompt = self.prepare_prompt(identity_analyses, record_analyses, record_search_names)
        
        try:
            # Estimate token count (rough approximation: 1 token ≈ 4 chars for English text)
            estimated_tokens = len(prompt) / 4
            
            # Log token estimate
            print(f"[BIOGEN] Estimated prompt tokens: {int(estimated_tokens)}")
            
            # If potentially too large, apply emergency fallback
            # Significantly increased to accommodate the full_content field and allow for detailed narratives
            if estimated_tokens > 40000:  # GPT-4 Turbo can handle up to ~128K tokens
                print("[BIOGEN] Prompt too large, using emergency fallback...")
                
                # Use our canonical name approach even for the fallback
                name = self.extract_name(identity_analyses) or "the subject"
                # Take just the highest scored match for the fallback
                if identity_analyses and len(identity_analyses) > 0:
                    # Sort matches by score (highest first)
                    sorted_matches = sorted(identity_analyses, key=lambda x: x.get("score", 0), reverse=True)
                    first_match = sorted_matches[0]
                    
                    # Extract only the most critical info
                    critical_info = {
                        "name": name,
                        "source": first_match.get("domain", "unknown source")
                    }
                    
                    # Add record search names if available
                    if record_search_names:
                        critical_info["record_search_names"] = record_search_names
                    
                    if first_match.get("scraped_data") and first_match["scraped_data"].get("person_info"):
                        person_info = first_match["scraped_data"]["person_info"]
                        if "occupation" in person_info:
                            critical_info["occupation"] = person_info["occupation"]
                        if "organization" in person_info:
                            critical_info["organization"] = person_info["organization"]
                    
                    # Add critical record info if available
                    if record_analyses and record_analyses.get("personal_details"):
                        details = record_analyses["personal_details"]
                        
                        # Add current address if available
                        if details.get("addresses") and len(details["addresses"]) > 0:
                            critical_info["address"] = details["addresses"][0]["address"]
                        
                        # Add phone if available
                        if details.get("phone_numbers") and len(details["phone_numbers"]) > 0:
                            critical_info["phone"] = details["phone_numbers"][0]["number"]
                    
                    # Generate record search info for fallback prompt
                    record_search_info = ""
                    if record_search_names:
                        if isinstance(record_search_names, list):
                            search_names_str = ", ".join(record_search_names)
                            record_search_info = f"\n\nRecord search was performed using these name(s): {search_names_str}"
                        else:
                            record_search_info = f"\n\nRecord search was performed using name: {record_search_names}"
                    
                    # Fallback prompt following the exact template
                    prompt = f"""
                    Create a profile for {name} based on this limited data:
                    {json.dumps(critical_info, indent=2)}{record_search_info}
                    
                    Even with limited information, follow this EXACT template:

                    **{name} - Professional Profile**

                    **1. Full Name and Professional Title:**
                       - {name}, [Professional Title if known, otherwise just the name]

                    **2. Summary:**
                       [Make this section as detailed as possible with the available information. 
                       If very limited data, still write at least 1-2 paragraphs synthesizing what is known.]

                    **3. Current and Past Organizations/Roles:**
                       - Current: [Organization/Role in one concise line]
                       - Past: [List ALL past roles from work_history, one line each]
                       [If unknown, write "No current role information available."]

                    **4. Education:**
                       - [List ALL education entries from education_history, one line each]
                       [If unknown, write "No education information available."]

                    **5. Skills and Certifications:**
                       - Skills: [List all skills]
                       - Certifications: [List all certifications]
                       - Languages: [List all languages]
                       [If unknown, write "No skills or certifications information available."]

                    **6. Location Information:**
                       - [List ALL addresses from record data, one per line]
                       [If unknown, write "No location information available."]

                    **7. Contact Information:**
                       - Phone: [List ALL phone numbers from record data, one per line]
                       - Email: [List ALL email addresses from record data, one per line]
                       - Social: [List ALL social profiles from record data, one per line]
                       [If unknown, write "No contact information available."]

                    **8. Personal Connections:**
                       - Family: [List all relatives from record data]
                       - Associates: [List other known connections]
                       [If unknown, write "No relationship information available."]

                    **9. Notable Achievements:**
                       - [Achievement if known - one concise line]
                       [If unknown, write "No achievement information available."]

                    **10. Notable Quotes:**
                       - "[Direct quote if available]"
                       [If none, write "No notable quotes available."]
                    
                    IMPORTANT: Include ALL record data in the appropriate sections. Do not omit any record details.
                    Follow this template structure exactly. The Summary should be the most detailed section, everything else should be brief.
                    """
                    
                    print(f"[BIOGEN] Emergency fallback prompt tokens: {int(len(prompt) / 4)}")
            
            # Call the OpenAI API with the appropriate prompt
            response = self.client.chat.completions.create(
                model="gpt-4-turbo", # or another appropriate model
                messages=[
                    {"role": "system", "content": "You are a professional intelligence analyst creating biographical profiles following an exact template. The Summary section should be detailed while all other sections must be concise bullet points. Always include placeholder text for missing information. CRITICAL: You MUST include ALL record data provided in the appropriate sections - all addresses, phone numbers, emails, work history, education history, etc. Do not omit any information from the records data."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,  # Low temperature for consistent template adherence
                max_tokens=4000   # Allows for detailed summary while keeping other sections concise
            )
            
            # Extract and return the response text
            return response.choices[0].message.content.strip()
        
        except Exception as e:
            print(f"[BIOGEN] Error while calling OpenAI API: {e}")
            traceback.print_exc()
            return None
    
    def extract_name(self, identity_analyses):
        """
        Extract the most frequently occurring person's name from the data
        This now uses the shared NameResolver to ensure consistency across modules
        """
        # Call the shared implementation
        canonical_name = NameResolver.resolve_canonical_name(identity_analyses)
        
        print(f"[BIOGEN] Using canonical name from NameResolver: '{canonical_name}'")
        return canonical_name
    
    def process_result_directory(self, face_id):
        """
        Process face results from database and generate a bio
        
        Args:
            face_id: The face ID to process
            
        Returns:
            bio_text: Generated bio text or None if unsuccessful
        """
        print(f"[BIOGEN] Processing face ID: {face_id}")
        
        try:
            # Import database functions
            from db_connector import get_identity_analyses, get_record_analyses, save_bio
            
            # Get identity analyses from database
            identity_analyses = get_identity_analyses(face_id)
            if not identity_analyses:
                print(f"[BIOGEN] No identity analyses found for face ID: {face_id}")
                return None
            
            # Check if record_analyses is available
            record_analyses = get_record_analyses(face_id)
            record_search_names = None
            
            if record_analyses:
                print(f"[BIOGEN] Found record analyses from {record_analyses.get('provider', 'unknown')}")
                # Extract search parameters (names) for reference
                search_params = record_analyses.get("search_params", {})
                record_search_names = search_params.get("name", "Unknown")
                print(f"[BIOGEN] Record search used name(s): {record_search_names}")
            
            # Generate the bio with both identity and record data
            bio = self.generate_bio(identity_analyses, record_analyses, record_search_names)
            
            if bio:
                # Save directly to database - no file operations
                print(f"[BIOGEN] Saving bio to database for face: {face_id}")
                save_bio(face_id, bio, record_analyses, record_search_names)
                print(f"[BIOGEN] Bio successfully saved to database")
                
                return bio
            else:
                print("[BIOGEN] Failed to generate bio.")
                return None
                
        except Exception as e:
            print(f"[BIOGEN] Error processing face {face_id}: {e}")
            traceback.print_exc()
            return None
            


# For command-line usage (not typically used in the controller integration)
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate bios from face search results using OpenAI API')
    parser.add_argument('path', help='Path to the person directory containing identity analyses')
    parser.add_argument('--api-key', help='OpenAI API key (optional if set in environment)')
    
    args = parser.parse_args()
    
    try:
        # Initialize the bio generator
        generator = BioGenerator(api_key=args.api_key)
        
        output_file = generator.process_result_directory(args.path)
        
        if output_file:
            print(f"[BIOGEN] Successfully generated bio. See {output_file}")
        
    except ValueError as e:
        print(f"[BIOGEN] Error: {e}")
    except Exception as e:
        print(f"[BIOGEN] Unexpected error: {e}")
        traceback.print_exc()