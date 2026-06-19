import os
import httpx
from google import genai
from cv_maker.ssl_helpers import configure_ssl_env, get_ca_bundle

configure_ssl_env()
ca_bundle = get_ca_bundle()

print(f"HTTP_PROXY: {os.environ.get('HTTP_PROXY')}")
print(f"HTTPS_PROXY: {os.environ.get('HTTPS_PROXY')}")
print(f"CA Bundle: {ca_bundle}")

try:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"), http_options={'client_args': {'verify': ca_bundle}})
    print("Testing gemini-2.5-flash...")
    response = client.models.generate_content(model='gemini-2.5-flash', contents='Hello')
    print(f"Success: {response.text}")
except Exception as e:
    print(f"Failed: {type(e).__name__}: {e}")
