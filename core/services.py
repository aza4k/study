import os
import re
import json
import base64
from typing import Optional, List, Dict, Any
from pathlib import Path
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.core.cache import cache
from .models import Course, Module, Lesson, Quiz, UserCourse
from .ai_schemas import CourseOutline, LessonContent, PracticeEvaluation

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

# ==============================================================================
# CENTRALIZED ENERGY ECONOMY & TIER CONFIGURATION
# Balanced for high user retention + healthy profit margins on Gemini Flash-Lite
# ==============================================================================
ECONOMY_CONFIG = {
    'welcome_energy': Decimal('30.00'),
    'chat_cost': Decimal('1.00'),
    'free_daily_chat_limit': 15,
    'course_cost': {
        'free': Decimal('15.00'),
        'pro': Decimal('25.00'),
        'ultra': Decimal('35.00'),
    },
    'course_limit': {
        'free': 5,
        'pro': 50,
        'ultra': 200,
    },
    'pdf_cost': Decimal('40.00'),
    'lab_eval_cost': {
        'free': Decimal('999.00'),  # Locked for free
        'pro': Decimal('2.00'),
        'ultra': Decimal('0.00'),   # Included free for Ultra!
    },
    'lesson_ask_cost': {
        'free': Decimal('2.00'),
        'pro': Decimal('1.00'),
        'ultra': Decimal('0.00'),   # Included free for Ultra!
    },
    'xp_redeem_cost': 250,
    'xp_redeem_reward': Decimal('10.00'),
    'daily_bonus_base': Decimal('3.00'),
    'daily_bonus_streak_7': Decimal('15.00'),
    'subscription_energy': {
        'free': Decimal('30.00'),
        'pro': Decimal('150.00'),
        'ultra': Decimal('500.00'),
    },
    'energy_packs': {
        '50': Decimal('50.00'),
        '180': Decimal('180.00'),
        '500': Decimal('500.00'),
        # Legacy aliases kept for backwards compatibility
        '5': Decimal('50.00'),
        '15': Decimal('180.00'),
    },
    'pricing': {
        'pro_monthly_usd': '3.99',
        'pro_annual_usd': '2.79',
        'pro_monthly_uzs': '49,000',
        'ultra_monthly_usd': '9.99',
        'ultra_annual_usd': '6.99',
        'ultra_monthly_uzs': '119,000',
    }
}

LANG_NAMES = {
    'uz': "Uzbek (in Latin script)",
    'kaa': "Karakalpak (in Latin script)",
    'ru': "Russian",
    'en': "English"
}

# Initialize cached client
_client = None


def get_gemini_client():
    global _client
    if _client is None:
        api_key = getattr(settings, 'GEMINI_API_KEY', None) or os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured in settings or environment.")
        _client = genai.Client(api_key=api_key)
    return _client


# Language-specific system prompts for Chatbot
CHATBOT_SYSTEM_PROMPTS = {
    'en': """You are StuDy AI, an expert personal tutor. Your job is to answer questions clearly and help users pick what they want to learn next.
    - Give concise, actionable explanations with real examples or small code snippets when helpful
    - Ask clarifying questions if the user wants a custom course
    - When a clear course topic is requested and ready, end your reply with: TOPIC_CLEAR: [topic name]
    - Be encouraging and supportive""",

    'ru': """Вы StuDy AI, опытный персональный репетитор. Ваша задача — понятно объяснять темы и помогать выбирать программу обучения.
    - Давайте четкие, практические ответы с примерами или небольшими фрагментами кода при необходимости
    - Задавайте уточняющие вопросы, если пользователь хочет создать курс
    - Когда тема курса ясна, завершите ответ строкой: TOPIC_CLEAR: [название темы]
    - Будьте дружелюбны и мотивирующи""",

    'kaa': """Siz StuDy AI — tájiriybeli jeke oqıw járdemshisisiz.
TIYKARǴI QAǴIYDA: Tek ǵana ádebiy Qaraqalpaq tilinde (Latın grafikasında: ı, ú, ó, ǵ, ń) juwap beriń.
- Sorawlarǵa anıq, mısal hám ámeliy keńesler menen juwap beriń.
- Eger paydalanıwshı jańa kurs jaratıwdı qálese, anıqlawshı soraw berip tema tańlawǵa kómeklesiń.
- Kurs teması tolıq anıq bolǵanda, juwaptıń aqırına mına qatardı qosıń: TOPIC_CLEAR: [tema atı]""",

    'uz': """Siz StuDy AI — professional shaxsiy repetitorsiz.
ASOSIY QOIDA: Faqat adabiy O'zbek tilida (Lotin grafikasida) javob bering.
- Savollarga qisqa, tushunarli va hayotiy misollar (kerak bo'lsa kod namunalari) bilan javob bering.
- Agar foydalanuvchi yangi kurs yaratmoqchi bo'lsa, uning darajasi va maqsadini aniqlashtiring.
- Kurs mavzusi to'liq aniq bo'lganda, javob oxiriga quyidagi qatorni qo'shing: TOPIC_CLEAR: [mavzu nomi]"""
}

# Curated high-res educational topic covers & lesson banners (zero latency, cached CDN)
TOPIC_IMAGE_CATALOG = {
    'code': "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?w=800&auto=format&fit=crop&q=80",
    'python': "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=800&auto=format&fit=crop&q=80",
    'javascript': "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=800&auto=format&fit=crop&q=80",
    'flutter': "https://images.unsplash.com/photo-1551650975-87deedd944c3?w=800&auto=format&fit=crop&q=80",
    'web': "https://images.unsplash.com/photo-1547658719-da2b51169166?w=800&auto=format&fit=crop&q=80",
    'ai': "https://images.unsplash.com/photo-1677442136019-21780efad99a?w=800&auto=format&fit=crop&q=80",
    'data': "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=800&auto=format&fit=crop&q=80",
    'math': "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=800&auto=format&fit=crop&q=80",
    'language': "https://images.unsplash.com/photo-1457369804613-52c61a468e7d?w=800&auto=format&fit=crop&q=80",
    'english': "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=800&auto=format&fit=crop&q=80",
    'science': "https://images.unsplash.com/photo-1532094349884-543bc11b234d?w=800&auto=format&fit=crop&q=80",
    'business': "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=800&auto=format&fit=crop&q=80",
    'marketing': "https://images.unsplash.com/photo-1533750349088-cd871a92f312?w=800&auto=format&fit=crop&q=80",
    'design': "https://images.unsplash.com/photo-1561070791-2526d30994b5?w=800&auto=format&fit=crop&q=80",
    'history': "https://images.unsplash.com/photo-1461360370896-922624d12aa1?w=800&auto=format&fit=crop&q=80",
    'art': "https://images.unsplash.com/photo-1513364776144-60967b0f800f?w=800&auto=format&fit=crop&q=80",
    'music': "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=800&auto=format&fit=crop&q=80",
    'default': "https://images.unsplash.com/photo-1501504905252-473c47e087f8?w=800&auto=format&fit=crop&q=80"
}

LESSON_VISUAL_BY_TYPE = {
    'coding': "https://images.unsplash.com/photo-1542831371-29b0f74f9713?w=800&auto=format&fit=crop&q=80",
    'language': "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?w=800&auto=format&fit=crop&q=80",
    'science': "https://images.unsplash.com/photo-1507413245164-6160d8298b31?w=800&auto=format&fit=crop&q=80",
    'business': "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=800&auto=format&fit=crop&q=80",
    'general': "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?w=800&auto=format&fit=crop&q=80",
}


def detect_category(topic: str, title: str = "") -> str:
    text = f"{topic} {title}".lower()
    if any(k in text for k in ['python', 'code', 'program', 'js', 'javascript', 'react', 'flutter', 'dart', 'html', 'css', 'sql', 'docker', 'git', 'java', 'c++', 'dastur', 'backend', 'frontend', 'ai', 'ml']):
        return 'coding'
    if any(k in text for k in ['english', 'ingliz', 'til', 'language', 'russian', 'rus', 'spanish', 'ielts', 'grammar', 'speaking', 'tili', 'koreys', 'nemis', 'arab']):
        return 'language'
    if any(k in text for k in ['business', 'biznes', 'marketing', 'smm', 'sales', 'finance', 'moliya', 'startup', 'management', 'excel']):
        return 'business'
    if any(k in text for k in ['math', 'matematika', 'physics', 'fizika', 'chemistry', 'kimyo', 'biology', 'biologiya', 'science', 'fan', 'geometry']):
        return 'science'
    if any(k in text for k in ['design', 'dizayn', 'ui', 'ux', 'figma', 'photoshop', 'art', 'music', 'video']):
        return 'creative'
    return 'general'


def get_course_cover_image(topic: str, title: str) -> str:
    clean_topic = (topic + " " + title).lower()
    for key, url in TOPIC_IMAGE_CATALOG.items():
        if key in clean_topic:
            return url
    return TOPIC_IMAGE_CATALOG['default']


def get_lesson_visual_image(lesson_title: str, lesson_type: str, course_title: str) -> str:
    clean = f"{lesson_title} {course_title}".lower()
    for key, url in TOPIC_IMAGE_CATALOG.items():
        if key in clean:
            return url
    return LESSON_VISUAL_BY_TYPE.get(lesson_type, LESSON_VISUAL_BY_TYPE['general'])


def async_generate_ai_cover(course_id: int, topic: str, title: str):
    """
    Generates a custom AI illustration cover for Pro/Ultra courses via Gemini Image model.
    Called from Celery worker to keep Gunicorn workers light.
    """
    if not GENAI_AVAILABLE:
        return
    try:
        client = get_gemini_client()
        prompt = (
            f"Minimalist educational flat vector illustration for course '{title}', topic '{topic}', "
            f"clean vibrant Neo-Brutalist geometric style, crisp bold colors, high resolution, no text"
        )
        interaction = client.interactions.create(
            model="gemini-3.1-flash-lite-image",
            input=prompt
        )
        if getattr(interaction, 'output_image', None) and interaction.output_image.data:
            media_dir = Path(settings.MEDIA_ROOT) / 'courses'
            media_dir.mkdir(parents=True, exist_ok=True)
            safe_slug = re.sub(r'[^a-zA-Z0-9]', '_', title[:20]).lower()
            filename = f"{safe_slug}_{os.urandom(4).hex()}.png"
            filepath = media_dir / filename
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(interaction.output_image.data))

            Course.objects.filter(id=course_id).update(image_url=f"{settings.MEDIA_URL}courses/{filename}")
    except Exception:
        # Fallback image from TOPIC_IMAGE_CATALOG already protects UX
        pass


def chatbot_response(user_message, chat_history, language='en', user=None):
    """
    Generate chatbot response using Gemini 3.5 Flash-Lite.
    """
    if not GENAI_AVAILABLE:
        return "Sorry, the AI service is not available. Please install google-genai package."

    model_name = 'gemini-3.5-flash-lite'
    client = get_gemini_client()

    system_prompt = CHATBOT_SYSTEM_PROMPTS.get(language, CHATBOT_SYSTEM_PROMPTS['en'])
    conversation = f"{system_prompt}\n\n"
    recent_messages = list(chat_history)[-8:]

    for msg in recent_messages:
        role = "User" if msg.is_user else "Assistant"
        conversation += f"{role}: {msg.message}\n"
    conversation += f"User: {user_message}\nAssistant:"

    try:
        interaction = client.interactions.create(
            model=model_name,
            input=conversation,
        )
        return (interaction.output_text or "").strip()
    except Exception as e:
        print(f"Error in chatbot: {e}")
        return "Kechirasiz, xatolik yuz berdi. Iltimos qaytadan urinib ko'ring."


def chatbot_response_stream(user_message, chat_history, language='en', user=None):
    """
    Generator yielding real-time text chunks for SSE streaming.
    """
    if not GENAI_AVAILABLE:
        yield "AI service is unavailable."
        return

    model_name = 'gemini-3.5-flash-lite'
    client = get_gemini_client()

    system_prompt = CHATBOT_SYSTEM_PROMPTS.get(language, CHATBOT_SYSTEM_PROMPTS['en'])
    conversation = f"{system_prompt}\n\n"
    recent_messages = list(chat_history)[-8:]

    for msg in recent_messages:
        role = "User" if msg.is_user else "Assistant"
        conversation += f"{role}: {msg.message}\n"
    conversation += f"User: {user_message}\nAssistant:"

    try:
        stream = client.interactions.create(
            model=model_name,
            input=conversation,
            stream=True
        )
        for event in stream:
            if event.event_type == "step.delta" and hasattr(event, 'delta') and event.delta.type == "text":
                yield event.delta.text
    except Exception as e:
        print(f"Stream error: {e}")
        yield "Xatolik yuz berdi."


def extract_text_from_pdf(pdf_file):
    """
    Extracts text content from a PDF file using pypdf.
    """
    import pypdf
    try:
        reader = pypdf.PdfReader(pdf_file)
        text = ""
        for page in reader.pages[:25]:  # Cap pages to protect server memory
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        raise ValueError(f"Failed to parse PDF file: {str(e)}")


def get_or_generate_lesson_content(lesson: Lesson, language: str = 'en', tier: str = 'free') -> Lesson:
    """
    Generates comprehensive, domain-adaptive lesson content including:
    - Markdown explanation + practical code/examples
    - Visual Diagram (step-by-step concept flow)
    - Flashcards (active recall cards)
    - Practice Lab (interactive code editor / real-world exercise)
    - Quizzes with clear answer explanations
    """
    has_rich_interactive = bool(lesson.interactive_data)
    if len(lesson.content.strip()) > 80 and lesson.quizzes.exists() and has_rich_interactive:
        return lesson

    client = get_gemini_client()
    course = lesson.module.course
    lang_code = language or course.language or 'en'
    lang_name = LANG_NAMES.get(lang_code, "English")

    category = getattr(course, 'category', 'general') or detect_category(course.title)
    difficulty = getattr(course, 'difficulty', 'beginner')

    domain_hint = ""
    if category == 'coding':
        domain_hint = (
            "Since this is a PROGRAMMING/TECH course:\n"
            "- Include well-formatted fenced code blocks (```python, ```javascript, ```dart, etc.) with inline comments in content.\n"
            "- Set lesson_type='coding' and populate practice_lab with enabled=true, lab_type='code', a concise coding challenge prompt, "
            "3-8 lines of starter_code, expected_output, and a helpful hint."
        )
    elif category == 'language':
        domain_hint = (
            "Since this is a LANGUAGE learning course:\n"
            "- Include clear vocabulary tables/lists, pronunciation/usage notes, and realistic mini-dialogues.\n"
            "- Populate 3-4 flashcards with target phrase on front, translation/meaning on back, and example sentence.\n"
            "- Set lesson_type='language' and practice_lab with enabled=true, lab_type='dialogue' asking student to write 1-2 sentences using today's grammar/words."
        )
    elif category in ('science', 'business'):
        domain_hint = (
            f"Since this is a {category.upper()} course:\n"
            "- Include formulas, real-world case study numbers, or step-by-step calculations.\n"
            "- Populate visual_diagram with a clear framework/process and practice_lab with enabled=true, lab_type='exercise' containing a practical scenario for the student to solve."
        )
    else:
        domain_hint = (
            "- Include clear conceptual explanations, real-world analogies, and memorable key takeaways.\n"
            "- Populate visual_diagram, 2-3 flashcards, and practice_lab with a short reflection/application prompt."
        )

    prompt = f"""You are an elite interactive curriculum designer (Duolingo + Brilliant.org + Mimo style).
Course Title: "{course.title}" (Category: {category}, Difficulty: {difficulty})
Module Title: "{lesson.module.title}"
Lesson Title: "{lesson.title}"
Language requirement: Strictly write ALL text, explanations, flashcards, diagram nodes, practice prompts, and quizzes in {lang_name}.

{domain_hint}

Requirements:
1. "content": Engaging Markdown with clear headings (##), bullet points, bold highlights, and practical examples. Keep paragraphs scannable!
2. "visual_diagram": 3-5 sequential steps summarizing the core workflow/concept.
3. "flashcards": 3 high-yield flashcards for active recall.
4. "practice_lab": A hands-on micro-task the user can try right inside the lesson.
5. "quizzes": 3 multiple-choice questions. Every question MUST include a short "explanation" telling the learner why the right answer is correct.
"""

    try:
        interaction = client.interactions.create(
            model="gemini-3.5-flash-lite",
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": LessonContent.model_json_schema()
            }
        )
        data = LessonContent.model_validate_json(interaction.output_text)

        interactive_payload = {
            'visual_diagram': data.visual_diagram.model_dump() if data.visual_diagram else None,
            'flashcards': [fc.model_dump() for fc in (data.flashcards or [])],
            'practice_lab': data.practice_lab.model_dump() if data.practice_lab else None,
        }

        visual_img = lesson.image_url or get_lesson_visual_image(lesson.title, data.lesson_type, course.title)

        with transaction.atomic():
            lesson.content = data.content
            lesson.lesson_type = data.lesson_type or 'general'
            lesson.interactive_data = interactive_payload
            lesson.image_url = visual_img
            lesson.save()

            if not lesson.quizzes.exists():
                for q in data.quizzes:
                    options = q.options
                    idx = q.correct_answer
                    correct_text = options[idx] if (0 <= idx < len(options)) else options[0]
                    Quiz.objects.create(
                        lesson=lesson,
                        question=q.question,
                        options=options,
                        correct_answer=correct_text,
                        explanation=q.explanation or ""
                    )
        return lesson
    except Exception as e:
        print(f"Error generating lesson content for {lesson.id}: {e}")
        if not lesson.content:
            lesson.content = f"# {lesson.title}\n\nDars mazmuni tez orada yuklanadi..."
            lesson.save()
        return lesson


def evaluate_practice_submission(lesson: Lesson, submission: str, language: str = 'uz') -> dict:
    """
    Evaluates a user's code snippet or practical exercise answer using Gemini 3.5 Flash-Lite.
    """
    if not GENAI_AVAILABLE:
        raise ImportError("google-genai package is not available.")

    client = get_gemini_client()
    lang_name = LANG_NAMES.get(language, "Uzbek (in Latin script)")
    lab = (lesson.interactive_data or {}).get('practice_lab') or {}
    lab_prompt = lab.get('prompt', lesson.title)
    expected = lab.get('expected_output', '')
    lab_lang = lab.get('language', 'general')

    prompt = f"""You are a supportive coding/learning mentor evaluating a student's hands-on practice submission.
Lesson: "{lesson.title}"
Practice Type: {lab.get('lab_type', 'exercise')} ({lab_lang})
Task Prompt: {lab_prompt}
Expected Key Result: {expected}

Student Submission:
```
{submission[:3000]}
```

Language requirement: Write feedback strictly in {lang_name}.
Evaluate fairly: if the core logic/answer solves the task (even with minor style differences), mark is_passed=true and give encouraging tips. If incomplete or buggy, mark is_passed=false and explain clearly how to fix it in 2-4 sentences, plus provide a clean improved_version.
"""

    interaction = client.interactions.create(
        model="gemini-3.5-flash-lite",
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": PracticeEvaluation.model_json_schema()
        }
    )
    result = PracticeEvaluation.model_validate_json(interaction.output_text)
    return result.model_dump()


def ask_lesson_tutor(lesson: Lesson, question: str, language: str = 'uz') -> str:
    """
    Contextual Q&A scoped strictly to the current lesson so users never feel stuck.
    """
    if not GENAI_AVAILABLE:
        raise ImportError("google-genai package is not available.")

    client = get_gemini_client()
    lang_name = LANG_NAMES.get(language, "Uzbek (in Latin script)")

    prompt = f"""You are StuDy AI Mentor helping a student who is currently reading the lesson below.
Answer their question clearly in 3-5 sentences using {lang_name}. Use a concrete example or short code block if helpful.

Lesson Title: {lesson.title}
Lesson Excerpt:
{lesson.content[:2500]}

Student Question: {question}
"""
    interaction = client.interactions.create(
        model="gemini-3.5-flash-lite",
        input=prompt,
    )
    return (interaction.output_text or "").strip()


def _schedule_single_lesson_prewarm(lesson_id: int, language: str, tier: str):
    """
    Dispatches next-lesson pre-warming cleanly to Celery (zero Gunicorn overhead).
    """
    try:
        from .tasks import prewarm_single_lesson_task
        prewarm_single_lesson_task.delay(lesson_id, language, tier)
    except Exception:
        # Broker might be unavailable in local unit test mode; lesson still loads lazily on tap
        pass


def generate_course_from_ai(
    topic: str,
    language: str = 'en',
    user=None,
    pdf_text: Optional[str] = None,
    difficulty: str = 'beginner'
) -> Course:
    """
    Optimized Course Creation Pipeline:
    1. Generates Course Outline + Category in < 2.5s (structured JSON).
    2. Saves Course, Modules, and Lesson skeletons atomically.
    3. Immediately generates Lesson 1 (~3s) with full interactive labs, flashcards & quizzes.
    4. Pre-warms ONLY Lesson 2 via Celery (`1 + 1` strategy) to cut token costs & VPS load by ~65%!
    5. Schedules AI Cover generation via Celery for Pro/Ultra users.
    """
    if not GENAI_AVAILABLE:
        raise ImportError("google-genai package is not available.")

    sub_type = getattr(user, 'subscription_type', 'free') if user else 'free'

    if pdf_text:
        if sub_type == 'free':
            raise ValueError("PDF course generation requires PRO or ULTRA subscription.")
        cost = ECONOMY_CONFIG['pdf_cost']
        modules_count = 3 if sub_type == 'ultra' else 2
    else:
        cost = ECONOMY_CONFIG['course_cost'].get(sub_type, Decimal('15.00'))
        modules_count = 1 if sub_type == 'free' else (2 if sub_type == 'pro' else 3)

    model_name = 'gemini-3.5-flash-lite'

    # Check and deduct energy
    if user:
        if Decimal(str(user.energy)) < cost:
            raise ValueError(
                f"Energiya yetarli emas! Bu kurs uchun {int(cost)}⚡ kerak, sizda {user.energy}⚡ bor."
            )
        user.energy = Decimal(str(user.energy)) - cost
        user.save(update_fields=['energy'])

    lang_name = LANG_NAMES.get(language, "English")

    module_instruction = f"Generate exactly {modules_count} modules."
    if modules_count == 1:
        module_instruction += " The module must have exactly 4 progressive lessons."
    elif modules_count == 2:
        module_instruction += " Modules 1 and 2 must have 4 progressive lessons each."
    else:
        module_instruction += (
            " Modules 1 and 2 must have 4 lessons each. "
            "Module 3 must be named 'Final Project & Exam' (translated to target language) and contain 2 comprehensive capstone lessons."
        )

    source_info = f"on the topic: \"{topic}\" at '{difficulty}' difficulty level"
    if pdf_text:
        source_info = f"based strictly on this source text:\n\n{pdf_text[:6000]}"

    prompt = f"""You are a master curriculum architect.
Design a structured, engaging course outline {source_info}.
Language requirement: All titles and descriptions MUST be in {lang_name}.

{module_instruction}
Set category to one of: coding, language, business, science, creative, general.
Ensure lesson titles flow naturally from fundamentals to practical mastery.
"""

    client = get_gemini_client()

    try:
        interaction = client.interactions.create(
            model=model_name,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": CourseOutline.model_json_schema()
            }
        )
        outline = CourseOutline.model_validate_json(interaction.output_text)

        detected_cat = outline.category if outline.category in {'coding', 'language', 'business', 'science', 'creative', 'general'} else detect_category(topic, outline.title)
        cover_image_url = get_course_cover_image(topic, outline.title)

        with transaction.atomic():
            course = Course.objects.create(
                title=outline.title,
                description=outline.description,
                language=language,
                category=detected_cat,
                difficulty=difficulty if difficulty in {'beginner', 'intermediate', 'advanced'} else 'beginner',
                image_url=cover_image_url,
                creator=user
            )

            created_lessons = []
            for mod_idx, mod_data in enumerate(outline.modules, start=1):
                module = Module.objects.create(
                    course=course,
                    title=mod_data.title,
                    order=mod_data.order or mod_idx
                )

                for les_idx, les_data in enumerate(mod_data.lessons, start=1):
                    lesson = Lesson.objects.create(
                        module=module,
                        title=les_data.title,
                        content="",
                        lesson_type=detected_cat if detected_cat in {'coding', 'language', 'science', 'business'} else 'general',
                        order=les_idx
                    )
                    created_lessons.append(lesson)

            if user:
                UserCourse.objects.get_or_create(user=user, course=course)

        # Schedule AI cover upgrade in Celery ONLY for Pro/Ultra
        if sub_type in ('pro', 'ultra'):
            try:
                from .tasks import generate_ai_cover_task
                generate_ai_cover_task.delay(course.id, topic, outline.title)
            except Exception:
                pass

        # Populate Lesson 1 synchronously so the student can start immediately
        if created_lessons:
            get_or_generate_lesson_content(created_lessons[0], language, tier=sub_type)

        # Predictive 1+1: Pre-warm ONLY Lesson 2 in background via Celery
        if len(created_lessons) > 1:
            _schedule_single_lesson_prewarm(created_lessons[1].id, language, sub_type)

        cache.clear()
        return course

    except Exception as e:
        if user:
            user.energy = Decimal(str(user.energy)) + cost
            user.save(update_fields=['energy'])
        print(f"Error generating course: {e}")
        raise e
