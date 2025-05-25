from openai import OpenAI
from google import genai
from google.genai import types
import json
import os
from typing import List, Dict, Any

def acroform_mapping_using_gemini(
    client: genai.Client,
    model_name: str,
    system_instructions: str,
    prompt: str,
    form_fields: List[Dict],
    txt_path: str,
    output_json_path: str = "auto_fill_mapping.json"
    ) -> Dict[str, str]:
    """
    Uses Gemini to automatically fill out PDF form fields based on text file content.
    
    Args:
        client: Gemini client instance
        model_name: Name of the Gemini model to use
        system_instructions: System instructions for the model
        prompt: Base prompt for the model
        form_fields: List of dictionaries containing form field information
        txt_path: Path to the text file containing information to extract from
        output_json_path: Path where to save the output JSON file
        
    Returns:
        Dict[str, str]: Mapping of field names to suggested values
    """
    if not form_fields:
        print("Error: No form fields provided.")
        return {}
    
    if not os.path.exists(txt_path):
        print(f"Error: Text file {txt_path} not found.")
        return {}
    
    # Read the text file content
    try:
        with open(txt_path, 'r', encoding='utf-8') as file:
            text_content = file.read()
    except Exception as e:
        print(f"Error reading text file {txt_path}: {e}")
        return {}
    
    if not text_content.strip():
        print("Error: Text file is empty.")
        return {}
    
    # Prepare field information for the prompt
    field_names = []
    field_details = []
    
    for field in form_fields:
        if isinstance(field, dict) and field.get('name'):
            field_name = field.get('name')
            field_type = field.get('type', 'Unknown')
            field_text = field.get('text', 'No contextual text')
            field_options = field.get('opts', [])
            
            field_names.append(field_name)
            
            detail = f"- {field_name} (Type: {field_type})"
            if field_text and field_text != 'No contextual text':
                detail += f" - Context: {field_text}"
            if field_options:
                detail += f" - Options: {', '.join(map(str, field_options))}"
            
            field_details.append(detail)
    
    if not field_names:
        print("Error: No valid form fields found.")
        return {}
    
    # Create the complete prompt
    complete_prompt = f"""
        {prompt}

        TEXT CONTENT TO EXTRACT FROM:
        {text_content}

        FORM FIELDS TO FILL:
        {chr(10).join(field_details)}

        Please provide a JSON object where:
        - Keys are the exact field names: {', '.join(field_names)}
        - Values are the appropriate information extracted from the text content
        - If no information is found for a field, use an empty string ""

        Example format:
        {{
        "field_name_1": "extracted_value_1",
        "field_name_2": "extracted_value_2"
        }}
        """
    
    try:
        print(f"[INFO] Auto-filling form using Gemini model: {model_name}")
        
        contents = [complete_prompt]
        
        generate_content_config = types.GenerateContentConfig(
            temperature=0.2,  # Lower temperature for more consistent results
            top_p=0.9,
            max_output_tokens=4096,
            response_modalities=["TEXT"],
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF")
            ],
            system_instruction=[types.Part.from_text(text=system_instructions)]
        )
        
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=generate_content_config
        )
        
        response_text = response.text
        print(f"[DEBUG] Raw response: {response_text}")
        
        # Try to extract JSON from the response
        try:
            # Look for JSON in the response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            
            if start_idx != -1 and end_idx != 0:
                json_str = response_text[start_idx:end_idx]
                field_mapping = json.loads(json_str)
            else:
                # If no JSON brackets found, try parsing the whole response
                field_mapping = json.loads(response_text)
                
        except json.JSONDecodeError as e:
            print(f"Error: Could not parse JSON from Gemini response: {e}")
            print(f"Raw response: {response_text}")
            return {}
        
        if not isinstance(field_mapping, dict):
            print(f"Error: Response is not a JSON object. Got: {type(field_mapping)}")
            return {}
        
        # Save to JSON file
        try:
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump(field_mapping, f, indent=2, ensure_ascii=False)
            print(f"[INFO] Auto-fill mapping saved to: {output_json_path}")
        except Exception as e:
            print(f"Warning: Could not save JSON file {output_json_path}: {e}")
        
        print(f"[INFO] Successfully created auto-fill mapping for {len(field_mapping)} fields")
        
        # Print the mapping results
        print("\nAuto-Fill Results:")
        for field_name, value in field_mapping.items():
            print(f"  {field_name}: {value}")
        
        return field_mapping
        
    except Exception as e:
        print(f"Error during Gemini API call: {type(e).__name__} - {e}")
        return {}