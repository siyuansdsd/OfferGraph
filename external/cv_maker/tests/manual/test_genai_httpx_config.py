import sys
import httpx
from google import genai
from google.genai import types
from cv_maker.ssl_helpers import configure_ssl_env, get_ca_bundle
import os

configure_ssl_env()
ca_bundle = get_ca_bundle()

verify_val = ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True
hclient = httpx.Client(timeout=httpx.Timeout(120.0), verify=verify_val)
http_options = {'httpx_client': hclient}
client = genai.Client(http_options=http_options)

print("Starting custom generation with httpx.Client and config timeout override...")
try:
    prompt = "Summarize this exactly as is: \n" + ("word " * 60000)
    config = types.GenerateContentConfig(
        http_options=http_options,  # You can pass http_options per call in the new SDK!
    )
    # Actually wait, let's just use the client we initialized
    response = client.models.generate_content(
        model='gemini-2.5-pro', 
        contents=prompt,
        config=config
    )
    print(f"Success! Response length: {len(response.text)}")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Failed: {type(e).__name__}: {e}")
