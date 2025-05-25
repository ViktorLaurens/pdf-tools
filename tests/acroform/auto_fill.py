from src.acroform.acroform_extractor import extract_form_fields
from src.acroform.llm import acroform_mapping_using_gemini
from src.acroform.acroform_filler import auto_fill_pdf_workflow
import os 
from openai import OpenAI
from google import genai

# PDF file path
pdf_name = "acroform.pdf"
pdf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "input", pdf_name)
if not os.path.exists(pdf_path):
    raise FileNotFoundError(f"File {pdf_path} not found")

# Extract form fields from PDF
fields = extract_form_fields(pdf_path)
print("Extracted Fields:")
for f in fields:
    print(f"  {f.get('name', 'Unknown')}: {f.get('type', 'Unknown type')}")

# Text file path
txt_name = "acroform.txt"
txt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "input", txt_name)
if not os.path.exists(txt_path):
    raise FileNotFoundError(f"File {txt_path} not found")

# Set up Gemini client and parameters
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")    
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set")

client = genai.Client(api_key=GEMINI_API_KEY)
model_name = "gemini-2.0-flash-001"
system_instructions = "You are a helpful assistant that can extract information from text and fill out PDF forms accurately. Always respond with valid JSON."
prompt = "Extract relevant information from the provided text and fill out the form fields with appropriate values:"

# Set up output paths
output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

output_json_name = "auto_fill_results.json"
output_json_path = os.path.join(output_dir, output_json_name)

# Call the mapping function
print("\n" + "="*50)
print("Creating field mapping using Gemini...")
mapping = acroform_mapping_using_gemini(
    client=client,
    model_name=model_name,
    system_instructions=system_instructions,
    prompt=prompt,
    form_fields=fields,
    txt_path=txt_path,
    output_json_path=output_json_path
)

# Fill the PDF using the mapping
if mapping:
    print("\n" + "="*50)
    print("Filling PDF form with mapped values...")
    filled_pdf_path = auto_fill_pdf_workflow(
        input_pdf_path=pdf_path,
        field_mapping_json_path=output_json_path,
        output_dir=output_dir,
        output_filename="acroform_filled.pdf"
    )
    
    if filled_pdf_path:
        print(f"\n✅ Complete workflow finished successfully!")
        print(f"📄 Original PDF: {pdf_path}")
        print(f"📝 Text data: {txt_path}")
        print(f"🗂️ Field mapping: {output_json_path}")
        print(f"✅ Filled PDF: {filled_pdf_path}")
    else:
        print(f"\n❌ PDF filling failed.")
else:
    print(f"\n❌ No mapping created, cannot fill PDF.") 