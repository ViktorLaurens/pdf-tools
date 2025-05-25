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



