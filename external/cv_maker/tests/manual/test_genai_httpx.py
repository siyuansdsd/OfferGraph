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
print("Testing gemini-2.5-pro with custom httpx_client...")
try:
    with open("src/cv_maker/main.py", "rb") as f:
        prompt = "Summarize this exactly as is: \n" + ("word " * 60000)
    response = client.models.generate_content(model='gemini-2.5-pro', contents=prompt)
    print(f"Success! Response length: {len(response.text)}")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Failed: {type(e).__name__}: {e}")
