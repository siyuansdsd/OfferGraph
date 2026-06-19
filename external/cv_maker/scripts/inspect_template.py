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

def inspect(path):
    print(f"--- Inspecting: {path} ---")
    doc = Document(path)
    
    print("\n[STYLES IN USE]")
    styles = set()
    for p in doc.paragraphs:
        styles.add(p.style.name)
        if len(p.text.strip()) > 0:
            print(f"Text: '{p.text[:30]}...' -> Style: '{p.style.name}'")
            
    print("\n[ALL SECTIONS]")
    for i, section in enumerate(doc.sections):
        print(f"Section {i}:")
        print(f"  Header: {not section.header.is_linked_to_previous}")
        print(f"  Footer: {not section.footer.is_linked_to_previous}")

if __name__ == "__main__":
    inspect("Justin_Cook_Engineering_Lead.docx")
