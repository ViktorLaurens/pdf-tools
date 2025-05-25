from src.acroform.acroform_extractor import extract_form_fields
import os 
from openai import OpenAI
from google import genai
from src.acroform.llm import auto_fill_acroform_using_gemini

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

# Call the auto-fill function
print("\n" + "="*50)
print("Auto-filling form using Gemini...")
output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
if not os.path.exists(output_path):
    raise FileNotFoundError(f"Output directory {output_path} not found")

output_name = "auto_fill_results.json"
output_path = os.path.join(output_path, output_name)

mapping = auto_fill_acroform_using_gemini(
    client=client,
    model_name=model_name,
    system_instructions=system_instructions,
    prompt=prompt,
    form_fields=fields,
    txt_path=txt_path,
    output_json_path=output_path
)