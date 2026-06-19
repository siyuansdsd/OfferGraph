import sys
import httpx
from google import genai
from cv_maker.ssl_helpers import configure_ssl_env, get_ca_bundle

configure_ssl_env()
ca_bundle = get_ca_bundle()

client = genai.Client(http_options={'client_args': {'verify': ca_bundle}})
print("Testing gemini-2.5-pro with large payload...")
try:
    # Just sending a long string to see if it's the size
    prompt = "Summarize this: \n" + "word " * 50000 
    response = client.models.generate_content(model='gemini-2.5-pro', contents=prompt)
    print(f"Success! Response length: {len(response.text)}")
except Exception as e:
    print(f"Failed: {type(e).__name__}: {e}")
