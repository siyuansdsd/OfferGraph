import sys
import httpx
from google import genai
from cv_maker.ssl_helpers import configure_ssl_env, get_ca_bundle
import os

configure_ssl_env()
ca_bundle = get_ca_bundle()

verify_val = ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True
hclient = httpx.Client(timeout=httpx.Timeout(120.0), verify=verify_val)
http_options = {'httpx_client': hclient}
client = genai.Client(http_options=http_options)

print("Testing generate_content_stream to bypass 30s proxy idle limits...")
try:
    with open("src/cv_maker/main.py", "rb") as f:
        # A prompt requiring real generation time:
        prompt = "Write me a very long, detailed 15 paragraph story about a software engineer who fixes proxy timeouts, incorporating technical details from this:\n" + ("word " * 10000)
    
    print("Initiating stream...")
    response_stream = client.models.generate_content_stream(model='gemini-2.5-pro', contents=prompt)
    
    full_text = ""
    for chunk in response_stream:
        print(".", end="", flush=True)
        full_text += chunk.text
    
    print(f"\nSuccess! Total length: {len(full_text)}")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Failed: {type(e).__name__}: {e}")
