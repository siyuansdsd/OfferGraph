# Copyright 2026 Justin Cook
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from docx import Document

def inspect_direct_formatting(path):
    print(f"--- Inspecting Formatting: {path} ---")
    doc = Document(path)
    
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text: continue
        
        # Check interesting headers
        if any(k in text.lower() for k in ['education', 'technical strengths', 'professional experience']):
            print(f"\n[HEADER detected]: '{text[:30]}'")
            print(f"  > Style Name: {p.style.name}")
            
            # Check Style Definition
            style_font = p.style.font
            print(f"  > Style Def: Size={style_font.size}, Bold={style_font.bold}, Color={style_font.color.rgb if style_font.color else 'None'}")
            
            # Check Direct Formatting on Runs
            for i, run in enumerate(p.runs):
                print(f"    > Run {i}: Text='{run.text[:10]}'")
                print(f"      - Size: {run.font.size}")
                print(f"      - Bold: {run.font.bold}")
                print(f"      - Color: {run.font.color.rgb if run.font.color else 'None'}")
                print(f"      - Name: {run.font.name}")
                
            # If Run has size/bold but Style doesn't, that's the smoking gun.

if __name__ == "__main__":
    inspect_direct_formatting("Justin_Cook_Engineering_Lead.docx")
