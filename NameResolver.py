#!/usr/bin/env python3
"""
NameResolver.py - Shared name resolution logic for EyeSpy modules

This module extracts the canonical name resolution logic from BioGenerator
into a shared component that can be used across the system to ensure
consistent name handling.
"""

import re


class NameResolver:
    """Resolves canonical names from identity analyses using frequency-based approach"""
    
    @staticmethod
    def resolve_canonical_name(identity_analyses):
        """
        Extract the most frequently occurring person's name from the identity analyses
        This uses a frequency-based approach for consistent naming across the system
        
        Args:
            identity_analyses: List of identity analysis results
            
        Returns:
            The canonical name as a string, or a fallback like "Unknown Person"
        """
        if not identity_analyses:
            return "Unknown Person"

        try:
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
                    print(f"[NAMERESOLVER] Error processing name candidates: {e}")
            
            # Step 2: Group similar names (using our improved is_same_person method)
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
                    if other_name not in processed_names and NameResolver.is_same_person(name, other_name):
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
                print(f"[NAMERESOLVER] Name group: {group}, Frequency: {group_frequency}, Max score: {group_max_score}")
                
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
                    print(f"[NAMERESOLVER] Name candidate: {name}, Frequency: {name_to_frequency.get(name, 0)}, Score: {name_to_score.get(name, 0)}")
                
                # Get original case/format from name_to_analysis keys
                for original_name in name_to_analysis.keys():
                    if original_name.lower() == canonical_name:
                        canonical_name = original_name
                        break
                        
                print(f"[NAMERESOLVER] Selected canonical name: '{canonical_name}' with frequency: {top_frequency}")
            
            # If we couldn't find any names, return default
            if not canonical_name:
                print("[NAMERESOLVER] No names found in any analysis")
                return "Unknown Person"
                
            return canonical_name
            
        except Exception as e:
            print(f"[NAMERESOLVER] Error in resolve_canonical_name: {e}")
            
        # Fallback if anything fails
        return "Unknown Person"
    
    @staticmethod
    def is_same_person(name1, name2):
        """
        Improved comparison to check if two names likely refer to the same person
        Uses a more sophisticated approach than simple substring matching
        """
        if not name1 or not name2:
            return False
            
        name1 = name1.lower().strip()
        name2 = name2.lower().strip()
        
        # Exact match
        if name1 == name2:
            return True
            
        # Split names into components
        name1_parts = name1.split()
        name2_parts = name2.split()
        
        # If one is a single name and the other has multiple parts
        if len(name1_parts) == 1 and len(name2_parts) > 1:
            # Check if the single name is in the multi-part name
            return name1_parts[0] in name2_parts
        elif len(name2_parts) == 1 and len(name1_parts) > 1:
            # Check if the single name is in the multi-part name
            return name2_parts[0] in name1_parts
            
        # For multi-part names, check if first and last names match
        if len(name1_parts) > 1 and len(name2_parts) > 1:
            # Check if first names match
            first_match = name1_parts[0] == name2_parts[0]
            # Check if last names match
            last_match = name1_parts[-1] == name2_parts[-1]
            
            # Return true if both first and last match
            return first_match and last_match
            
        # Fallback to old method if the above checks don't apply
        return name1 in name2 or name2 in name1

    @staticmethod
    def clean_name_for_search(name):
        """
        Clean and format a name for API search, handling middle names/initials
        
        Args:
            name: Raw name string that might contain prefixes/formatting
            
        Returns:
            Cleaned name suitable for API search or list of variations to try
        """
        if not name:
            return None
            
        # Handle case where name is a list
        if isinstance(name, list):
            # If it's a list, process each name and return a list of variations
            all_variations = []
            for name_item in name:
                if isinstance(name_item, str):
                    variations = NameResolver.clean_name_for_search(name_item)
                    if variations:
                        if isinstance(variations, list):
                            all_variations.extend(variations)
                        else:
                            all_variations.append(variations)
            return all_variations if all_variations else None
            
        # Now we know name is a string
        # Remove any markdown formatting or prefixes
        prefixes = ["**Full Name and Professional Title:**", "Full Name:", "Name:", "- "]
        for prefix in prefixes:
            if isinstance(name, str) and name.startswith(prefix):
                name = name.replace(prefix, "").strip()
        
        # Remove any markdown characters
        if isinstance(name, str):
            name = re.sub(r'\*\*|\*|#|_|-', '', name).strip()
        
        # Try different name variations for better matching
        name_variations = []
        
        # Add original name
        if isinstance(name, str):
            name_variations.append(name)
            
            # Check if there might be a middle initial/name
            name_parts = name.split()
            if len(name_parts) > 2:
                # Version without middle name/initial
                first_last = f"{name_parts[0]} {name_parts[-1]}"
                name_variations.append(first_last)
                
                # If middle part is just one character (likely an initial)
                if len(name_parts) == 3 and len(name_parts[1]) == 1:
                    # Try with just initial (no period)
                    name_variations.append(f"{name_parts[0]} {name_parts[1]} {name_parts[2]}")
                    # Try with initial and period
                    name_variations.append(f"{name_parts[0]} {name_parts[1]}. {name_parts[2]}")
        
        print(f"[NAMERESOLVER] Name variations to try: {name_variations}")
        return name_variations


# For direct testing
if __name__ == "__main__":
    # Example test
    test_analyses = [
        {
            "score": 0.85,
            "scraped_data": {
                "person_info": {
                    "person": {
                        "fullName": "John A. Smith"
                    }
                }
            }
        },
        {
            "score": 0.90,
            "scraped_data": {
                "person_info": {
                    "fullName": "John Smith"
                }
            }
        }
    ]
    
    name = NameResolver.resolve_canonical_name(test_analyses)
    print(f"Test result: {name}")