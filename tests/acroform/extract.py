from src.acroform.acroform_extractor import extract_form_fields
import os 

pdf_name = "acroform.pdf"
pdf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "input", pdf_name)
if not os.path.exists(pdf_path):
    raise FileNotFoundError(f"File {pdf_path} not found")
else:
    fields = extract_form_fields(pdf_path)
    # add_llm_field_descriptions(fields, pdf_path, client)
    print("Extracted Fields:")
    for f in fields:
        print(f)

