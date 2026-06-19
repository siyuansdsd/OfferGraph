
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

"""
Data models for the CV Maker application.
"""

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class EarlierExperience:
    """Represents a summarised early career role."""
    title: str
    company: str
    summary: str
    dates: str = ""

@dataclass
class Experience:
    """Represents a single professional experience entry."""
    title: str
    company: str
    location: str
    dates: str
    summary_italic: Optional[str] = None
    bullets: List[tuple[str, str]] = field(default_factory=list) # List of (Title, Description)

@dataclass
class Project:
    """Represents a technical project or open source contribution."""
    title: str
    description: str # The "Title: Description" format from my_cv.py

@dataclass
class CVData:
    """
    Structured data representing a complete CV.
    This is the data object used to generate the final DOCX.
    """
    name: str
    title: str
    contact_info: str
    executive_summary: str
    competencies: List[tuple[str, str]] # (Category, Skills)
    experience: List[Experience]
    earlier_experience: List[EarlierExperience] = field(default_factory=list)
    projects: List[tuple[str, str]] = field(default_factory=list)
    education: List[str] = field(default_factory=list)
    certifications: str = ""
    github_url: str = ""

@dataclass
class JobDescription:
    """Represents a parsed Job Description."""
    raw_text: str
    url: Optional[str] = None
    role_title: str = ""
    company_name: str = ""
    key_skills: List[str] = field(default_factory=list)
    summary: str = ""
