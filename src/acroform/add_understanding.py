import pymupdf as fitz
import json
from typing import List, Dict
import openai

def _get_full_pdf_text_for_llm(pdf_path: str) -> str:
    """Extracts all text content from a PDF using PyMuPDF for LLM context."""
    full_text_parts = []
    try:
        doc = fitz.open(pdf_path)
        if not doc.is_pdf: # Basic check
            print(f"Warning: File '{pdf_path}' may not be a valid PDF or is encrypted.")
            doc.close()
            return ""
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            full_text_parts.append(page.get_text("text")) # Get plain text
        doc.close()
        if not full_text_parts and len(doc) > 0:
            print(f"Warning: No text extracted from PDF '{pdf_path}', though it has pages. LLM context will be limited.")
            return ""
        elif not full_text_parts and len(doc) == 0:
            print(f"Warning: PDF '{pdf_path}' has no pages. No text extracted.")
            return ""
        return "\n---- Page Break ----\n".join(full_text_parts)
    except Exception as e:
        print(f"Error extracting full text from PDF '{pdf_path}': {e}")
        return ""

def add_llm_field_descriptions(
    form_fields: List[Dict], 
    pdf_path: str, 
    client: openai.OpenAI,
    model_name: str = "gpt-4o"
) -> None:
    """
    Uses an OpenAI LLM to generate a description for each PDF form field and
    adds it to the field's dictionary under the key "understanding".

    The description is based on the field's properties and the entire PDF content.
    Modifies the form_fields list in-place.

    Args:
        form_fields: A list of dictionaries, where each dictionary represents a form field.
                     It's expected to come from a function like `extract_form_fields` and
                     contain at least 'name', 'type'. It may also use 'text' (nearby context)
                     and 'opts' if available in the field dictionary.
        pdf_path: Path to the PDF file.
        client: An initialized OpenAI client.
        model_name: The OpenAI model to use for generating descriptions.
    """
    if not isinstance(form_fields, list):
        print("Error: form_fields argument must be a list.")
        return
    if not form_fields:
        print("Info: form_fields list is empty. No descriptions to generate.")
        return
    if not client:
        print("Error: OpenAI client is not provided. Cannot generate field descriptions.")
        return

    print("\n[INFO] Preparing to generate LLM field descriptions...")
    full_pdf_document_text = _get_full_pdf_text_for_llm(pdf_path)
    # The helper function will print a warning if text extraction fails or yields no text.

    field_details_for_prompt = []
    valid_field_names_for_mapping = [] # Keep track of names we expect in LLM response

    for field in form_fields:
        if not isinstance(field, dict):
            print(f"Warning: Found an item in form_fields that is not a dictionary: {type(field)}. Skipping.")
            continue
        
        field_name = field.get('name')
        if not field_name or not isinstance(field_name, str) or not field_name.strip():
            # Silently skip fields without a valid name for now, or print a warning
            # print(f"Warning: Skipping field with missing or invalid name: {field}")
            continue
        
        valid_field_names_for_mapping.append(field_name)
        details = f"  Field Name: {field_name}\n"
        details += f"  Type: {field.get('type', 'N/A')}\n"
        # 'text' key from get_contextual_text_for_field is used here
        details += f"  Nearby Contextual Text: {field.get('text', 'N/A')}\n" 
        if field.get('opts'):
            details += f"  Options: {field.get('opts')}\n"
        field_details_for_prompt.append(details.strip())
    
    if not field_details_for_prompt:
        print("No valid field details could be prepared to send to LLM for descriptions.")
        return

    fields_list_str = "\n\n".join(field_details_for_prompt)

    system_prompt = (
        "You are an AI assistant highly skilled in analyzing PDF forms. "
        "For each form field described below, your task is to provide a concise (1-2 sentences) "
        "description of what information or type of content is expected to be filled into that field. "
        "Base your description on the field's properties (like its name, type, and nearby text) "
        "AND your understanding of the entire PDF document's content, which is also provided. "
        "Your output MUST be a single, valid JSON object. The keys of this JSON object must be the "
        "exact field names for which details were provided, and the values must be your generated concise description strings for each field."
    )
    
    user_prompt = (
        "Please generate a concise (1-2 sentences) description for each of the following form fields, "
        "explaining what information is expected to be filled in. Consider all information provided: "
        "the properties of each field and the full text of the PDF document.\n\n"
        "FORM FIELDS DETAILS:\n"
        f"{fields_list_str}\n\n"
        "-- FULL PDF DOCUMENT TEXT START ---\n"
        f"{full_pdf_document_text if full_pdf_document_text else 'Note: No text could be extracted from the PDF document, or the document is text-free. Base descriptions on field properties alone if necessary.'}\n"
        "-- FULL PDF DOCUMENT TEXT END ---\n\n"
        "Provide your output as a single JSON object, mapping each field name to its concise description string."
    )

    try:
        print(f"[INFO] Requesting field descriptions from OpenAI model: {model_name}. This may take a moment...")
        
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"} 
        )
        
        response_content = completion.choices[0].message.content
        if not response_content:
            print("Error: LLM returned an empty response for field descriptions.")
            return

        llm_generated_descriptions = json.loads(response_content)
        if not isinstance(llm_generated_descriptions, dict):
            print(f"Error: LLM response for descriptions was not a JSON object (dictionary). Got: {type(llm_generated_descriptions)}")
            print(f"Raw response: {response_content}")
            return
            
        print("[INFO] Successfully received and parsed field descriptions from LLM.")

        updated_count = 0
        missing_from_llm = []

        for field_dict in form_fields:
            field_name = field_dict.get('name')
            if not field_name or field_name not in valid_field_names_for_mapping: # Ensure we only process fields we sent
                continue

            if field_name in llm_generated_descriptions:
                description = llm_generated_descriptions[field_name]
                if isinstance(description, str):
                    field_dict["understanding"] = description.strip()
                    updated_count += 1
                else:
                    print(f"Warning: LLM provided a non-string description for field '{field_name}': {description} (Type: {type(description)}). Skipping 'understanding' for this field.")
                    missing_from_llm.append(f"{field_name} (invalid type: {type(description)})")
            else:
                # This field was in our list sent to LLM but not in its response keys
                missing_from_llm.append(field_name)
        
        if updated_count > 0:
            print(f"[INFO] Added 'understanding' to {updated_count} field(s).")
        
        if not llm_generated_descriptions and valid_field_names_for_mapping:
             print("[INFO] LLM returned an empty set of descriptions.")
        elif missing_from_llm:
            print(f"Warning: LLM did not provide a valid description for the following field(s) (or they were missing from response): {', '.join(missing_from_llm)}.")
        elif updated_count == 0 and valid_field_names_for_mapping:
            print("[INFO] No fields were updated with an 'understanding' from the LLM. Check LLM response or field names.")


    except json.JSONDecodeError as e:
        raw_response_text = locals().get('response_content', 'Response content not available.')
        print(f"Error: Could not decode JSON response from LLM for field descriptions: {e}. Raw response: '{raw_response_text[:500]}...'")
    except openai.APIError as e:
        print(f"OpenAI API Error (model: {model_name}) during field description generation: {type(e).__name__} - {e}")
    except Exception as e:
        print(f"An unexpected error occurred during field description generation (model: {model_name}): {type(e).__name__} - {e}")