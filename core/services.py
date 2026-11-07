import os
import re
import json
import base64
import threading
from typing import Optional, List, Dict, Any
from pathlib import Path
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from .models import Course, Module, Lesson, Quiz, UserCourse
from .ai_schemas import CourseOutline, LessonContent, QuizItem

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

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
    'en': """You are a helpful learning assistant. Your job is to help users discover what they want to learn.
    - Ask clarifying questions if the user is unsure
    - Provide suggestions based on their interests
    - When the topic is clear, respond with: TOPIC_CLEAR: [topic name]
    - Be encouraging and supportive
    - Keep responses concise and friendly""",
    
    'ru': """Вы полезный помощник по обучению. Ваша задача - помочь пользователям понять, что они хотят изучать.
    - Задавайте уточняющие вопросы, если пользователь не уверен
    - Предлагайте варианты на основе их интересов
    - Когда тема ясна, отвечайте: TOPIC_CLEAR: [название темы]
    - Будьте ободряющими и поддерживающими
    - Держите ответы краткими и дружелюбными""",
    
    'kaa': """Siz paydalı hám bilimli oqıw járdemshisisiz.
TIYKARǴI QAǴIYDA: Siz tek ǵana ádebiy Qaraqalpaq tilinde (Latın grafikasında) juwap beriń. Ózbek, Qazaq yamasa basqa tillerdi aralastırmań. Háriplerdiń durıs jazılıwına (mısalı: ı, ú, ó, ǵ, ń) itibar beriń.

Seniń maqsetiń - paydalanıwshıǵa ne úyreniwdi qáleytuǵının anıqlawǵa kómeklesiw.

Instrkciyalar:
1. ANÍQLAW: Eger paydalanıwshı ne oqıw kerekligin bilmese, oǵan anıqlawshı sorawlar beriń.
2. USINIS: Olardıń qızıǵıwshılıqlarına tiykarlanıp, paydalı usınıslar beriń.
3. TON: Hár dayım qollap-quwatlawshı, xoshametlewshi hám doslıq múnásibette bolıń.
4. JUWAP: Juwaplarıńız qısqa, túsinikli hám grammatikalıq jaqtan qatesiz bolsın.

NÁTIYJE:
Tema tolıq anıq bolǵanda, sóylesiwdi tómendegi formatta juwmaqlań:
TOPIC_CLEAR: [tema atı]""",

    'uz': """Siz foydali va bilimli o'quv yordamchisisiz.
ASOSIY QOIDA: Siz faqat adabiy O'zbek tilida (Lotin grafikasida) javob bering. Rus yoki boshqa tillarni aralashtirmang.

Sizning maqsadingiz - foydalanuvchiga nima o'rganishni xohlashini aniqlashga yordam berish.

Ko'rsatmalar:
1. ANIQLASH: Agar foydalanuvchi nima o'qish kerakligini bilmasa, unga aniqlovchi savollar bering.
2. TAKLIF: Ularning qiziqishlariga asoslanib, foydali takliflar bering.
3. TON: Har doim qo'llab-quvvatlovchi, rag'batlantiruvchi va do'stona munosabatda bo'ling.
4. JAVOB: Javoblaringiz qisqa, tushunarli va grammatik jihatdan xatosiz bo'lsin.

NATIJA:
Mavzu to'liq aniq bo'lganda, suhbatni quyidagi formatda yakunlang:
TOPIC_CLEAR: [mavzu nomi]"""
}

# Curated high-res educational topic covers (used as high-speed instant fallback if AI image quota is exhausted)
TOPIC_IMAGE_CATALOG = {
    'code': "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?w=800&auto=format&fit=crop&q=80",
    'python': "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=800&auto=format&fit=crop&q=80",
    'web': "https://images.unsplash.com/photo-1547658719-da2b51169166?w=800&auto=format&fit=crop&q=80",
    'ai': "https://images.unsplash.com/photo-1677442136019-21780efad99a?w=800&auto=format&fit=crop&q=80",
    'math': "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=800&auto=format&fit=crop&q=80",
    'language': "https://images.unsplash.com/photo-1457369804613-52c61a468e7d?w=800&auto=format&fit=crop&q=80",
    'english': "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=800&auto=format&fit=crop&q=80",
    'science': "https://images.unsplash.com/photo-1532094349884-543bc11b234d?w=800&auto=format&fit=crop&q=80",
    'business': "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=800&auto=format&fit=crop&q=80",
    'history': "https://images.unsplash.com/photo-1461360370896-922624d12aa1?w=800&auto=format&fit=crop&q=80",
    'art': "https://images.unsplash.com/photo-1513364776144-60967b0f800f?w=800&auto=format&fit=crop&q=80",
    'music': "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=800&auto=format&fit=crop&q=80",
    'default': "https://images.unsplash.com/photo-1501504905252-473c47e087f8?w=800&auto=format&fit=crop&q=80"
}

def get_course_cover_image(topic: str, title: str) -> str:
    """
    Returns an immediate matched high-res educational cover image so the user never waits.
    """
    clean_topic = (topic + " " + title).lower()
    for key, url in TOPIC_IMAGE_CATALOG.items():
        if key in clean_topic:
            return url
    return TOPIC_IMAGE_CATALOG['default']

def async_generate_ai_cover(course_id: int, topic: str, title: str):
    """
    Attempts to generate custom AI illustration with Gemini Nano Banana in background
    without blocking user course generation. If successful, updates course.image_url.
    """
    if not GENAI_AVAILABLE:
        return
    try:
        client = get_gemini_client()
        prompt = (
            f"Minimalist educational flat vector illustration for course '{title}', topic '{topic}', "
            f"clean vibrant Neo-Brutalist style, crisp colors, high resolution, no text"
        )
        interaction = client.interactions.create(
            model="gemini-3.1-flash-lite-image",
            input=prompt
        )
        if interaction.output_image and interaction.output_image.data:
            media_dir = Path(settings.MEDIA_ROOT) / 'courses'
            media_dir.mkdir(parents=True, exist_ok=True)
            safe_slug = re.sub(r'[^a-zA-Z0-9]', '_', title[:20]).lower()
            filename = f"{safe_slug}_{os.urandom(4).hex()}.png"
            filepath = media_dir / filename
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(interaction.output_image.data))
            
            Course.objects.filter(id=course_id).update(image_url=f"{settings.MEDIA_URL}courses/{filename}")
    except Exception:
        # Expected on Free Tier accounts without billing project attached
        pass

def chatbot_response(user_message, chat_history, language='en', user=None):
    """
    Generate chatbot response using high-speed Gemini 3.5 Flash-Lite / 3.8 Flash API
    """
    if not GENAI_AVAILABLE:
        return "Sorry, the AI service is not available. Please install google-genai package."
    
    sub_type = 'free'
    if user:
        sub_type = getattr(user, 'subscription_type', 'free')

    # Routing: 3.5 Flash-Lite is ultra fast for free/pro; 3.8 Flash for ultra
    model_name = 'gemini-3.8-flash' if sub_type == 'ultra' else 'gemini-3.5-flash-lite'
    client = get_gemini_client()
    
    system_prompt = CHATBOT_SYSTEM_PROMPTS.get(language, CHATBOT_SYSTEM_PROMPTS['en'])
    
    conversation = f"{system_prompt}\n\n"
    count = chat_history.count() if hasattr(chat_history, 'count') else len(chat_history)
    start_index = max(0, count - 6)
    recent_messages = chat_history[start_index:]
    
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
        # Graceful fallback to 3.5 flash-lite
        try:
            interaction = client.interactions.create(
                model='gemini-3.5-flash-lite',
                input=conversation,
            )
            return (interaction.output_text or "").strip()
        except Exception as inner_e:
            print(f"Fallback chatbot error: {inner_e}")
            return "Kechirasiz, xatolik yuz berdi. Iltimos qaytadan urinib ko'ring."

def chatbot_response_stream(user_message, chat_history, language='en', user=None):
    """
    Generator yielding real-time text chunks for Server-Sent Events (SSE) streaming
    """
    if not GENAI_AVAILABLE:
        yield "AI service is unavailable."
        return

    sub_type = 'free'
    if user:
        sub_type = getattr(user, 'subscription_type', 'free')

    model_name = 'gemini-3.8-flash' if sub_type == 'ultra' else 'gemini-3.5-flash-lite'
    client = get_gemini_client()
    
    system_prompt = CHATBOT_SYSTEM_PROMPTS.get(language, CHATBOT_SYSTEM_PROMPTS['en'])
    conversation = f"{system_prompt}\n\n"
    
    count = chat_history.count() if hasattr(chat_history, 'count') else len(chat_history)
    start_index = max(0, count - 6)
    recent_messages = chat_history[start_index:]
    
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
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        raise ValueError(f"Failed to parse PDF file: {str(e)}")

def get_or_generate_lesson_content(lesson: Lesson, language: str = 'en') -> Lesson:
    """
    Checks if a lesson already has rich content. If not, generates comprehensive
    content and interactive quizzes in ~3-4 seconds using Gemini 3.5 Flash-Lite.
    """
    # If already populated with substantial content and quizzes, return as is
    if len(lesson.content.strip()) > 80 and lesson.quizzes.exists():
        return lesson

    client = get_gemini_client()
    course = lesson.module.course
    lang_name = {
        'uz': "Uzbek (in Latin script)",
        'kaa': "Karakalpak (in Latin script)",
        'ru': "Russian",
        'en': "English"
    }.get(language or course.language, "English")

    prompt = f"""You are an expert tutor creating an interactive lesson for an online course.
Course Title: "{course.title}"
Module Title: "{lesson.module.title}"
Lesson Title: "{lesson.title}"
Language requirement: Strictly write everything in {lang_name}.

Generate comprehensive, engaging Markdown content for this lesson:
- Include a clear introduction, core concepts with concrete examples, bullet points, and key takeaways.
- Provide 2 or 3 multiple-choice quizzes that test understanding of this lesson. Each quiz must have exactly 4 options and the 0-based index of the correct answer.
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
        
        with transaction.atomic():
            lesson.content = data.content
            lesson.save()

            # Create quizzes if none exist yet
            if not lesson.quizzes.exists():
                for q in data.quizzes:
                    options = q.options
                    idx = q.correct_answer
                    correct_text = options[idx] if (0 <= idx < len(options)) else options[0]
                    Quiz.objects.create(
                        lesson=lesson,
                        question=q.question,
                        options=options,
                        correct_answer=correct_text
                    )
        return lesson
    except Exception as e:
        print(f"Error generating lesson content for {lesson.id}: {e}")
        if not lesson.content:
            lesson.content = f"# {lesson.title}\n\nDars mazmuni tez orada yuklanadi..."
            lesson.save()
        return lesson

def _background_populate_remaining_lessons(course_id: int, language: str):
    """
    Background worker thread to lazily pre-generate remaining lessons in a newly created course.
    """
    try:
        lessons = Lesson.objects.filter(module__course_id=course_id).order_by('module__order', 'order')
        for lesson in lessons:
            if len(lesson.content.strip()) < 80 or not lesson.quizzes.exists():
                get_or_generate_lesson_content(lesson, language)
    except Exception as e:
        print(f"Background lesson generation notice: {e}")

def generate_course_from_ai(topic: str, language: str = 'en', user=None, pdf_text: Optional[str] = None) -> Course:
    """
    High-speed, cost-efficient course generation:
    1. Generates course outline in ~2-3 seconds using structured JSON output.
    2. Immediately creates Course with an illustration cover, Modules, and Lesson records.
    3. Generates Lesson 1 content and quizzes right away (~3-4 seconds) so the course is playable immediately!
    4. Queues background generation for the remaining lessons.
    Total time: ~4-6 seconds (down from 51+ seconds)!
    """
    if not GENAI_AVAILABLE:
        raise ImportError("google-genai package is not available.")
    
    sub_type = 'free'
    if user:
        sub_type = getattr(user, 'subscription_type', 'free')

    # Energy costs and module counts
    if pdf_text:
        if sub_type != 'ultra':
            raise ValueError("PDF course generation is only available for Ultra subscribers.")
        cost = Decimal('4.0')
        modules_count = 3
        model_name = 'gemini-3.5-flash-lite'
    else:
        if sub_type == 'free':
            cost = Decimal('1.0')
            modules_count = 1
        elif sub_type == 'pro':
            cost = Decimal('2.0')
            modules_count = 2
        else: # ultra
            cost = Decimal('3.0')
            modules_count = 3
        # Use gemini-3.5-flash-lite for instant sub-3-second outline generation across all tiers
        model_name = 'gemini-3.5-flash-lite'

    # Check and deduct energy
    if user:
        if Decimal(str(user.energy)) < cost:
            raise ValueError(
                f"Not enough Energy! You need {cost} Energy to generate this course, "
                f"but you only have {user.energy}."
            )
        user.energy = Decimal(str(user.energy)) - cost
        user.save()

    lang_name = {
        'uz': "Uzbek (in Latin script)",
        'kaa': "Karakalpak (in Latin script)",
        'ru': "Russian",
        'en': "English"
    }.get(language, "English")

    module_instruction = f"Generate exactly {modules_count} modules."
    if modules_count == 1:
        module_instruction += " The module must have exactly 4 or 5 progressive lessons."
    elif modules_count == 2:
        module_instruction += " Modules 1 and 2 must have 4 or 5 progressive lessons each."
    else:
        module_instruction += " Modules 1 and 2 must have 4 or 5 lessons each. " \
                              "Module 3 must be named 'Final Exam' or 'Yakuniy Imtihon' and contain 1 comprehensive assessment lesson."

    source_info = f"on the topic: \"{topic}\""
    if pdf_text:
        source_info = f"based strictly on this source text:\n\n{pdf_text[:5000]}"

    prompt = f"""You are a master curriculum architect.
Design a structured, engaging course outline {source_info}.
Language requirement: All titles and descriptions MUST be in {lang_name}.

{module_instruction}
Ensure the outline is logical, pedagogical, and easy to follow.
"""

    client = get_gemini_client()

    try:
        # Step 1: Ultra-fast Outline Generation (< 3s)
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

        # Step 2: Generate or match course cover illustration
        cover_image_url = get_course_cover_image(topic, outline.title)

        # Step 3: Atomic database persistence of structure
        with transaction.atomic():
            course = Course.objects.create(
                title=outline.title,
                description=outline.description,
                language=language,
                image_url=cover_image_url,
                creator=user
            )

            first_lesson = None
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
                        content="",  # Generated lazily / on-demand
                        order=les_idx
                    )
                    if first_lesson is None:
                        first_lesson = lesson

            if user:
                UserCourse.objects.get_or_create(user=user, course=course)

        # Kick off background AI cover illustration generation (non-blocking)
        threading.Thread(
            target=async_generate_ai_cover,
            args=(course.id, topic, outline.title),
            daemon=True
        ).start()

        # Step 4: Populate Lesson 1 immediately so student can play right away
        if first_lesson:
            get_or_generate_lesson_content(first_lesson, language)

        # Step 5: Start background thread to pre-populate subsequent lessons smoothly
        bg_thread = threading.Thread(
            target=_background_populate_remaining_lessons,
            args=(course.id, language),
            daemon=True
        )
        bg_thread.start()

        return course

    except Exception as e:
        # Refund energy on complete failure
        if user:
            user.energy = Decimal(str(user.energy)) + cost
            user.save()
        print(f"Error generating course: {e}")
        raise e
