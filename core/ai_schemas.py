import os
import re
import json
import base64
from pathlib import Path
from django.conf import settings
from pydantic import BaseModel, Field
from typing import List, Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

# Pydantic Schemas for Structured JSON Output
class LessonOutline(BaseModel):
    title: str = Field(description="Clear, concise lesson title")

class ModuleOutline(BaseModel):
    title: str = Field(description="Module title")
    order: int = Field(description="Order number starting from 1")
    lessons: List[LessonOutline] = Field(description="List of lessons in this module")

class CourseOutline(BaseModel):
    title: str = Field(description="Catchy, engaging course title")
    description: str = Field(description="Engaging 2-3 sentence overview of the course")
    modules: List[ModuleOutline] = Field(description="List of modules")

class QuizItem(BaseModel):
    question: str = Field(description="Clear multiple-choice question testing understanding")
    options: List[str] = Field(description="Exactly 4 distinct options: [Option A, Option B, Option C, Option D]")
    correct_answer: int = Field(description="0-based index of the correct option: 0, 1, 2, or 3")

class LessonContent(BaseModel):
    content: str = Field(description="Comprehensive Markdown formatted lesson content with clear explanations, practical examples, code/dialogue if applicable, and summary")
    quizzes: List[QuizItem] = Field(description="1 to 3 multiple-choice quizzes checking lesson mastery")
