import sys
import httpx
from google import genai
from cv_maker.ssl_helpers import configure_ssl_env, get_ca_bundle

configure_ssl_env()
ca_bundle = get_ca_bundle()

# Increase timeout significantly
timeout = httpx.Timeout(60.0, read=120.0, write=120.0, connect=30.0)

client = genai.Client(http_options={'client_args': {'verify': ca_bundle, 'timeout': timeout}})
print("Testing gemini-2.5-pro with large payload and increased timeout...")
try:
    prompt = "Summarize this: \n" + "word " * 50000 
    response = client.models.generate_content(model='gemini-2.5-pro', contents=prompt)
    print(f"Success! Response length: {len(response.text)}")
except Exception as e:
    print(f"Failed: {type(e).__name__}: {e}")
