from pydantic import BaseModel, Field
from typing import List, Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None


class LessonOutline(BaseModel):
    title: str = Field(description="Clear, concise lesson title")


class ModuleOutline(BaseModel):
    title: str = Field(description="Module title")
    order: int = Field(description="Order number starting from 1")
    lessons: List[LessonOutline] = Field(description="List of lessons in this module")


class CourseOutline(BaseModel):
    title: str = Field(description="Catchy, engaging course title")
    description: str = Field(description="Engaging 2-3 sentence overview of the course")
    category: str = Field(
        default="general",
        description="One of: coding, language, business, science, creative, general"
    )
    modules: List[ModuleOutline] = Field(description="List of modules")


class QuizItem(BaseModel):
    question: str = Field(description="Clear multiple-choice question testing understanding")
    options: List[str] = Field(description="Exactly 4 distinct options: [Option A, Option B, Option C, Option D]")
    correct_answer: int = Field(description="0-based index of the correct option: 0, 1, 2, or 3")
    explanation: str = Field(
        default="",
        description="Brief 1-2 sentence explanation of why the correct option is right"
    )


class VisualDiagram(BaseModel):
    title: str = Field(description="Short diagram or workflow title")
    steps: List[str] = Field(description="3 to 5 sequential visual nodes or concept steps (short labels)")
    summary: str = Field(description="One-sentence takeaway from this visual flow")


class FlashcardItem(BaseModel):
    front: str = Field(description="Term, concept, word, or question on the front")
    back: str = Field(description="Concise definition, translation, or answer on the back")
    example: str = Field(default="", description="Short practical example")


class PracticeLab(BaseModel):
    enabled: bool = Field(description="True if this lesson benefits from hands-on coding or practical exercise")
    lab_type: str = Field(
        default="exercise",
        description="One of: code (programming task), dialogue (language roleplay/sentence), exercise (analytical/business/math task)"
    )
    language: str = Field(
        default="python",
        description="Programming language if lab_type is code (e.g. python, javascript, dart, html, sql) or natural topic label"
    )
    prompt: str = Field(default="", description="Clear hands-on task instruction for the student to solve")
    starter_code: str = Field(default="", description="Starter template or code snippet with 3-8 lines for student to complete")
    expected_output: str = Field(default="", description="Expected output or key elements of a strong answer")
    hint: str = Field(default="", description="Helpful hint if the student gets stuck")


class LessonContent(BaseModel):
    lesson_type: str = Field(
        default="general",
        description="One of: coding, language, science, business, general"
    )
    content: str = Field(
        description="Comprehensive Markdown formatted lesson content with clear explanations, practical examples, code blocks (when relevant), and key takeaways"
    )
    visual_diagram: Optional[VisualDiagram] = Field(
        default=None,
        description="Optional structured step-by-step workflow/concept diagram ONLY when sequential visual flow genuinely clarifies the lesson; omit/null otherwise"
    )
    flashcards: List[FlashcardItem] = Field(
        default_factory=list,
        description="Optional 0 to 4 active-recall flashcards ONLY when vocabulary, formulas, or key definitions warrant memorization; leave empty [] for pure coding/story/hands-on lessons"
    )
    practice_lab: Optional[PracticeLab] = Field(
        default=None,
        description="Interactive hands-on code or domain practice exercise tailored to topic & subscription tier"
    )
    quizzes: List[QuizItem] = Field(description="2 to 4 multiple-choice quizzes checking real understanding")


class PracticeEvaluation(BaseModel):
    is_passed: bool = Field(description="True if the student's code or answer solves the prompt adequately")
    score: int = Field(description="Score from 0 to 100")
    feedback: str = Field(description="Constructive, encouraging feedback explaining what worked and what to improve")
    improved_version: str = Field(default="", description="Clean reference solution or improved snippet")
