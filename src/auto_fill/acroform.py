import pikepdf
from typing import List, Dict, Any
import pymupdf as fitz
import os
import openai
import json

def extract_form_fields(pdf_path: str) -> List[Dict]:
    """Extract form field names, types, and positions from a PDF."""
    pdf = pikepdf.Pdf.open(pdf_path)
    fields = []
    acro_form = pdf.Root.get("/AcroForm", None)
    if acro_form is None:
        return []

    for field in acro_form.get("/Fields", []):
        fields.append({
            "name": str(field.get("/T", "")),
            "type": str(field.get("/FT", "")),
            "rect": [float(r) for r in field.get("/Rect", [])],
            "page": str(field.get("/Page", 0)), 
            "opts": get_field_options(field),
            "text": get_contextual_text_for_field(pdf_path, int(field.get("/Page", 0)), [float(r) for r in field.get("/Rect", [])])
        })
    return fields

def get_field_options(field_obj: pikepdf.Object) -> List[str]:
    """
    Extracts options for /Ch (Choice) fields from the raw field object.
    Options can be an array of strings or an array of [export_value, display_value] pairs.
    """
    options = []
    # Field options are typically stored in the /Opt key
    opt_array = field_obj.get("/Opt")
    if opt_array and isinstance(opt_array, pikepdf.Array):
        for item in opt_array:
            if isinstance(item, pikepdf.String):
                options.append(str(item))
            elif isinstance(item, pikepdf.Array) and len(item) == 2:
                # Convention is often [export_value, display_value] or [display_value, export_value].
                # We'll prefer the display value if possible (often the second string).
                if isinstance(item[1], pikepdf.String):
                    options.append(str(item[1]))
                elif isinstance(item[0], pikepdf.String): # Fallback to the first item
                    options.append(str(item[0]))
                else: # If neither is a string directly, represent the pair
                    options.append(f"[Non-string option: {str(item[0])}, {str(item[1])}]")
            #pikepdf.Array can contain other types, ensure we handle them gracefully
            elif isinstance(item, pikepdf.Name):
                 options.append(str(item))

    return options

def get_contextual_text_for_field(pdf_path: str, page_index: int, field_rect_coords: List[float]) -> str:
    """
    Extracts text near a field's bounding box using PyMuPDF (Fitz).
    Attempts to find labels to the left, above, and the overall closest words, ensuring distinct results.
    """
    if page_index < 0 or not field_rect_coords or len(field_rect_coords) != 4:
        return "Invalid page index or field coordinates for contextual analysis."

    MAX_RELEVANT_DISTANCE_SQ_OVERALL = 150*150 # Approx 150 points distance, tune as needed

    try:
        doc = fitz.open(pdf_path)
        if page_index >= len(doc):
            doc.close()
            return f"Page index {page_index} out of bounds for PyMuPDF."
        
        page = doc[page_index]
        
        # Field rectangle: [x0, y0, x1, y1] (PikePDF, origin bottom-left for y)
        f_x0, f_lly, f_x1, f_ury = field_rect_coords
        
        # PyMuPDF words: [x0, y0, x1, y1, "word", block_no, line_no, word_no] (origin top-left for y)
        words_raw = page.get_text("words") 

        # Define search parameters
        SEARCH_MARGIN_X_LEFT = 70
        VERTICAL_ALIGNMENT_TOLERANCE = 10
        SEARCH_MARGIN_Y_ABOVE = 30
        HORIZONTAL_ALIGNMENT_TOLERANCE = 50

        claimed_word_ids = set()
        
        # Lists to store the final strings for each category
        actual_left_text_list = []
        actual_above_text_list = []
        actual_closest_text_list = []

        # --- Heuristic 2: Text LEFT of the field (Computed First) ---
        # (Comments will reflect user's numbering preference for Heuristic 2 here)
        left_texts_candidates = []
        # Field's visual center-y (PikePDF coords) for alignment reference, though direct y-comparison is used
        # field_center_y_pikepdf_for_left = (f_lly + f_ury) / 2 
        
        for w_x0, w_y0, w_x1, w_y1, word_text, block_no, line_no, word_no in words_raw:
            word_id = (block_no, line_no, word_no)
            # Check for text to the LEFT
            if w_x1 < f_x0 and (f_x0 - w_x1) < SEARCH_MARGIN_X_LEFT:
                # Vertical alignment check (comparing PyMuPDF word y with converted PikePDF field y)
                # page.rect.height - f_ury is field top edge in PyMuPDF coords (from top)
                # page.rect.height - f_lly is field bottom edge in PyMuPDF coords (from top)
                field_top_y_pymu = page.rect.height - f_ury
                field_bottom_y_pymu = page.rect.height - f_lly
                
                # w_y0, w_y1 are word's top and bottom y in PyMuPDF coords
                # Check for overlap or close alignment
                is_vertically_aligned = (
                    abs(w_y1 - field_top_y_pymu) < VERTICAL_ALIGNMENT_TOLERANCE or # Word bottom near field top
                    abs(w_y0 - field_bottom_y_pymu) < VERTICAL_ALIGNMENT_TOLERANCE or # Word top near field bottom
                    (w_y0 < field_bottom_y_pymu and w_y1 > field_top_y_pymu) # Word overlaps vertically with field
                )
                if is_vertically_aligned:
                    left_texts_candidates.append({'text': word_text, 'id': word_id, 'x1': w_x1, 'y0': w_y0})

        left_texts_candidates.sort(key=lambda x: (-x['x1'], x['y0'])) # Rightmost first, then topmost
        if left_texts_candidates:
            for item in left_texts_candidates[:3]:
                actual_left_text_list.append(item['text'])
                claimed_word_ids.add(item['id'])
        
        # --- Heuristic 3: Text ABOVE the field (Computed Second) ---
        # (Comments will reflect user's numbering preference for Heuristic 3 here)
        above_texts_candidates = []
        # field_center_x_for_above = (f_x0 + f_x1) / 2 # PikePDF coords
        field_top_y_pymu = page.rect.height - f_ury # Field top edge in PyMuPDF coords

        for w_x0, w_y0, w_x1, w_y1, word_text, block_no, line_no, word_no in words_raw:
            word_id = (block_no, line_no, word_no)
            if word_id in claimed_word_ids:
                continue

            # Word is above: w_y1 (word bottom) < field_top_y_pymu
            # Word is close vertically: field_top_y_pymu - w_y1 < SEARCH_MARGIN_Y_ABOVE
            if w_y1 < field_top_y_pymu and (field_top_y_pymu - w_y1) < SEARCH_MARGIN_Y_ABOVE:
                # Horizontal alignment check (all X are in same coordinate system)
                # Check if word's x-span [w_x0, w_x1] overlaps or is close to field's x-span [f_x0, f_x1]
                if (max(f_x0, w_x0) < min(f_x1, w_x1) + HORIZONTAL_ALIGNMENT_TOLERANCE):
                     above_texts_candidates.append({'text': word_text, 'id': word_id, 'y1': w_y1, 'x0': w_x0})
        
        above_texts_candidates.sort(key=lambda x: (-x['y1'], x['x0'])) # Bottom-most first (closest to field), then leftmost
        if above_texts_candidates:
            for item in above_texts_candidates[:3]:
                actual_above_text_list.append(item['text'])
                claimed_word_ids.add(item['id'])

        # --- Heuristic 1: Find closest text overall (Computed Last) ---
        # (Comments will reflect user's numbering preference for Heuristic 1 here)
        closest_texts_candidates = []
        field_center_x_pikepdf = (f_x0 + f_x1) / 2
        field_center_y_pikepdf = (f_lly + f_ury) / 2 # Field center Y in PikePDF coords (bottom-origin)

        for w_x0, w_y0, w_x1, w_y1, word_text, block_no, line_no, word_no in words_raw:
            word_id = (block_no, line_no, word_no)
            if word_id in claimed_word_ids:
                continue
            
            word_center_x_pymu = (w_x0 + w_x1) / 2
            word_center_y_pymu = (w_y0 + w_y1) / 2 # Word center Y in PyMuPDF coords (top-origin)
            
            # Convert word center Y to PikePDF coordinate system (bottom-origin) for consistent distance calc
            word_center_y_pikepdf = page.rect.height - word_center_y_pymu
            
            dx = word_center_x_pymu - field_center_x_pikepdf # X coords are compatible
            dy = word_center_y_pikepdf - field_center_y_pikepdf
            distance_sq = dx*dx + dy*dy
            
            if distance_sq < MAX_RELEVANT_DISTANCE_SQ_OVERALL:
                closest_texts_candidates.append({
                    'text': word_text,
                    'id': word_id,
                    'distance': distance_sq
                    # 'x_center_pike': word_center_x_pymu, # Storing for debug if needed
                    # 'y_center_pike': word_center_y_pikepdf
                })

        closest_texts_candidates.sort(key=lambda x: x['distance'])
        if closest_texts_candidates:
            for item in closest_texts_candidates[:3]:
                actual_closest_text_list.append(item['text'])
                # No need to add to claimed_word_ids if this is the last heuristic consuming words

        # --- Assemble output string in desired order: Closest | Left | Above ---
        contextual_texts_output = []
        if actual_closest_text_list:
            # Comment for Heuristic 1
            contextual_texts_output.append("Closest: " + " ".join(actual_closest_text_list))
        if actual_left_text_list:
            # Comment for Heuristic 2
            contextual_texts_output.append("Left: " + " ".join(actual_left_text_list))
        if actual_above_text_list:
            # Comment for Heuristic 3
            contextual_texts_output.append("Above: " + " ".join(actual_above_text_list))

        doc.close()
        if not contextual_texts_output:
            return "No distinct contextual text found nearby (or heuristics need tuning)."
        return " | ".join(contextual_texts_output)

    except Exception as e:
        return f"Error during contextual text extraction: {str(e)}"

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



