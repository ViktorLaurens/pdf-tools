import pikepdf
import json
import os
from typing import Dict, Any, Union
from pathlib import Path

def fill_pdf_form(
    input_pdf_path: str,
    field_mapping: Union[Dict[str, Any], str],
    output_pdf_path: str
) -> bool:
    """
    Fills PDF form fields based on a mapping dictionary and saves the result.
    
    Args:
        input_pdf_path: Path to the input PDF file
        field_mapping: Dictionary mapping field names to values, or path to JSON file
        output_pdf_path: Path where to save the filled PDF
        
    Returns:
        bool: True if successful, False otherwise
    """
    
    # Load field mapping if it's a file path
    if isinstance(field_mapping, str):
        if not os.path.exists(field_mapping):
            print(f"Error: Field mapping file {field_mapping} not found.")
            return False
        
        try:
            with open(field_mapping, 'r', encoding='utf-8') as f:
                field_mapping = json.load(f)
        except Exception as e:
            print(f"Error reading field mapping file: {e}")
            return False
    
    if not isinstance(field_mapping, dict):
        print("Error: Field mapping must be a dictionary or path to JSON file.")
        return False
    
    if not os.path.exists(input_pdf_path):
        print(f"Error: Input PDF file {input_pdf_path} not found.")
        return False
    
    try:
        # Open the PDF
        pdf = pikepdf.Pdf.open(input_pdf_path)
        
        # Get the AcroForm
        acro_form = pdf.Root.get("/AcroForm", None)
        if acro_form is None:
            print("Error: PDF does not contain form fields.")
            pdf.close()
            return False
        
        filled_count = 0
        total_fields = 0
        
        # Iterate through form fields
        for field in acro_form.get("/Fields", []):
            total_fields += 1
            field_name = str(field.get("/T", ""))
            
            if field_name in field_mapping:
                field_value = field_mapping[field_name]
                field_type = str(field.get("/FT", ""))
                
                try:
                    # Handle different field types
                    if field_type == "/Tx":  # Text field
                        field["/V"] = pikepdf.String(str(field_value))
                        filled_count += 1
                        print(f"Filled text field '{field_name}': {field_value}")
                        
                    elif field_type == "/Ch":  # Choice field (combo box, list box)
                        # For choice fields, the value should match one of the options
                        field["/V"] = pikepdf.String(str(field_value))
                        filled_count += 1
                        print(f"Filled choice field '{field_name}': {field_value}")
                        
                    elif field_type == "/Btn":  # Button field (checkbox, radio button)
                        # For checkboxes, handle boolean values
                        if isinstance(field_value, bool):
                            if field_value:
                                # Set checkbox to checked state
                                # The exact value depends on the field setup, commonly "Yes", "On", or "1"
                                possible_values = ["/Yes", "/On", "/1", "/Checked"]
                                # Try to find the correct "on" state from the field's appearance dictionary
                                ap_dict = field.get("/AP", {})
                                if ap_dict and "/N" in ap_dict:
                                    n_dict = ap_dict["/N"]
                                    if hasattr(n_dict, 'keys'):
                                        for key in n_dict.keys():
                                            if str(key) != "/Off":
                                                field["/V"] = key
                                                field["/AS"] = key  # Appearance state
                                                break
                                        else:
                                            field["/V"] = pikepdf.Name("Yes")
                                            field["/AS"] = pikepdf.Name("Yes")
                                    else:
                                        field["/V"] = pikepdf.Name("Yes")
                                        field["/AS"] = pikepdf.Name("Yes")
                                else:
                                    field["/V"] = pikepdf.Name("Yes")
                                    field["/AS"] = pikepdf.Name("Yes")
                            else:
                                # Set checkbox to unchecked state
                                field["/V"] = pikepdf.Name("Off")
                                field["/AS"] = pikepdf.Name("Off")
                        else:
                            # For non-boolean values, treat as string
                            field["/V"] = pikepdf.String(str(field_value))
                        
                        filled_count += 1
                        print(f"Filled button field '{field_name}': {field_value}")
                        
                    else:
                        # For unknown field types, try to set as string
                        field["/V"] = pikepdf.String(str(field_value))
                        filled_count += 1
                        print(f"Filled field '{field_name}' (type {field_type}): {field_value}")
                        
                except Exception as e:
                    print(f"Warning: Could not fill field '{field_name}': {e}")
            else:
                print(f"Info: No mapping found for field '{field_name}'")
        
        # Create output directory if it doesn't exist
        output_dir = os.path.dirname(output_pdf_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Save the filled PDF
        pdf.save(output_pdf_path)
        pdf.close()
        
        print(f"Success: Filled {filled_count} out of {total_fields} fields.")
        print(f"Filled PDF saved to: {output_pdf_path}")
        return True
        
    except Exception as e:
        print(f"Error filling PDF: {type(e).__name__} - {e}")
        return False

def auto_fill_pdf_workflow(
    input_pdf_path: str,
    field_mapping_json_path: str,
    output_dir: str,
    output_filename: str = None
) -> str:
    """
    Complete workflow to fill a PDF form using a JSON mapping file.
    
    Args:
        input_pdf_path: Path to the input PDF file
        field_mapping_json_path: Path to the JSON file containing field mappings
        output_dir: Directory where to save the filled PDF
        output_filename: Name for the output file (optional, defaults to adding "_filled" suffix)
        
    Returns:
        str: Path to the filled PDF file, or empty string if failed
    """
    
    if not output_filename:
        # Generate output filename by adding "_filled" suffix
        input_name = Path(input_pdf_path).stem
        output_filename = f"{input_name}_filled.pdf"
    
    output_pdf_path = os.path.join(output_dir, output_filename)
    
    print(f"Starting PDF auto-fill workflow...")
    print(f"Input PDF: {input_pdf_path}")
    print(f"Field mapping: {field_mapping_json_path}")
    print(f"Output PDF: {output_pdf_path}")
    
    success = fill_pdf_form(
        input_pdf_path=input_pdf_path,
        field_mapping=field_mapping_json_path,
        output_pdf_path=output_pdf_path
    )
    
    if success:
        print(f"PDF auto-fill completed successfully!")
        return output_pdf_path
    else:
        print(f"PDF auto-fill failed.")
        return ""
