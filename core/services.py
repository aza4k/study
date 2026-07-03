import json
import re
from django.conf import settings
from django.db import transaction
from .models import Course, Module, Lesson, Quiz, UserCourse

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

# Language-specific prompts
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

COURSE_GENERATION_PROMPTS = {
    'en': """Create a comprehensive course on: "{topic}".
    The output must be a valid JSON object with this structure:
    {{
        "title": "Course Title",
        "description": "Course Description",
        "modules": [
            {{
                "title": "Module Title",
                "order": 1,
                "lessons": [
                    {{
                        "title": "Lesson Title",
                        "content": "Detailed lesson content in Markdown format...",
                        "quizzes": [
                            {{
                                "question": "Quiz Question?",
                                "options": ["Option A", "Option B", "Option C", "Option D"],
                                "correct_answer": 0
                            }}
                        ]
                    }}
                ]
            }}
        ]
    }}
    Generate exactly 3 modules.
    Modules 1 and 2 must have 5 lessons each. Each lesson must have 1 or 2 quizzes.
    Module 3 must be named "Final Exam" and contain exactly 1 lesson named "Final Assessment". This lesson must have at least 10 quizzes covering the entire course.
    Ensure the JSON is valid and strictly follows the schema.
    All content must be in English.""",
    
    'ru': """Создайте всеобъемлющий курс по теме: "{topic}".
    Вывод должен быть валидным JSON объектом с такой структурой:
    {{
        "title": "Название курса",
        "description": "Описание курса",
        "modules": [
            {{
                "title": "Название модуля",
                "order": 1,
                "lessons": [
                    {{
                        "title": "Название урока",
                        "content": "Подробное содержание урока в формате Markdown...",
                        "quizzes": [
                            {{
                                "question": "Вопрос теста?",
                                "options": ["Вариант А", "Вариант Б", "Вариант В", "Вариант Г"],
                                "correct_answer": 0
                            }}
                        ]
                    }}
                ]
            }}
        ]
    }}
    Создайте ровно 3 модуля.
    Модули 1 и 2 должны содержать по 5 уроков. В каждом уроке должно быть 1 или 2 теста.
    Модуль 3 должен называться "Итоговый экзамен" и содержать ровно 1 урок под названием "Итоговая оценка". Этот урок должен содержать не менее 10 тестов, охватывающих весь курс.
    Убедитесь, что JSON действителен и строго соответствует схеме.
    Весь контент должен быть на русском языке.""",
    
    'kaa': """Siz tájiriybeli oqıw metodisti hám kontent jaratıwshısısız.
Sizden tómendegi tapsırmanı orınlaw talap etiledi:

TAPSIRMA: "{topic}" teması boyınsha tolıq oqıw kursın jaratıń.

TİL TALABI:
1. Barlıq kontent (atamalar, sabaq mazmunı, testler) TEK ǴANA Qaraqalpaq tilinde (Latın grafikasında) bolıwı shárt.
2. Ózbek, Qazaq yamasa basqa tillerdi aralastırmań.
3. Háriplerdi durıs qollanıń: (ı, ú, ó, ǵ, ń, sh, ch).

STRUKTURA TALABI:
Kurs 3 modulden ibarat bolıwı kerek:
- 1-modul hám 2-modul: Hárqaysısında 5 sabaqtan bolsın. Hár sabaqta 1 yamasa 2 test sorawı bolsın.
- 3-modul: Atı "Juwmaqlawshı imtihan" bolsın. Bul modulde "Juwmaqlawshı sınaq" atlı 1 ǵana sabaq bolsın. Bul sabaqta pútkil kurstı qamtıytuǵın keminde 10 test sorawı bolıwı kerek.

FORMAT TALABI:
Nátiyje tek ǵana tómendegi sxemaǵa sáykes keletuǵın valid JSON bolıwı kerek (basqa sóz yamasa tüsindirme jazbań):

{{
    "title": "Kurs atı",
    "description": "Kurs haqqında qısqasha táriyip",
    "modules": [
        {{
            "title": "Modul atı",
            "order": 1,
            "lessons": [
                {{
                    "title": "Sabaq atı",
                    "content": "Markdown formatındaǵı tolıq sabaq mazmunı (keminde 100 sóz)",
                    "quizzes": [
                        {{
                            "question": "Test sorawı?",
                            "options": ["Variant A", "Variant B", "Variant C", "Variant D"],
                            "correct_answer": 0
                        }}
                    ]
                }}
            ]
        }}
    ]
}}
""",

    'uz': """Siz tajribali o'quv metodisti va kontent yaratuvchisisiz.
Sizdan quyidagi vazifani bajarish talab etiladi:

VAZIFA: "{topic}" mavzusi bo'yicha to'liq o'quv kursini yarating.

TIL TALABI:
1. Barcha kontent (nomlar, dars mazmuni, testlar) FAQAT O'zbek tilida (Lotin grafikasida) bo'lishi shart.
2. Rus yoki boshqa tillarni aralashtirmang.

TUZILMA TALABI:
Kurs 3 moduldan iborat bo'lishi kerak:
- 1-modul va 2-modul: Har birida 5 tadan dars bo'lsin. Har bir darsda 1 yoki 2 test savoli bo'lsin.
- 3-modul: Nomi "Yakuniy imtihon" bo'lsin. Bu modulda "Yakuniy sinov" nomli 1 tagina dars bo'lsin. Bu darsda butun kursni qamrab oladigan kamida 10 ta test savoli bo'lishi kerak.

FORMAT TALABI:
Natija faqat quyidagi sxemaga mos keladigan valid JSON bo'lishi kerak (boshqa so'z yoki tushuntirish yozmang):

{{
    "title": "Kurs nomi",
    "description": "Kurs haqida qisqacha tavsif",
    "modules": [
        {{
            "title": "Modul nomi",
            "order": 1,
            "lessons": [
                {{
                    "title": "Dars nomi",
                    "content": "Markdown formatidagi to'liq dars mazmuni (kamida 100 so'z)",
                    "quizzes": [
                        {{
                            "question": "Test savoli?",
                            "options": ["Variant A", "Variant B", "Variant C", "Variant D"],
                            "correct_answer": 0
                        }}
                    ]
                }}
            ]
        }}
    ]
}}
"""
}

def chatbot_response(user_message, chat_history, language='en', user=None):
    """
    Generate chatbot response using Gemini API
    """
    if not GENAI_AVAILABLE:
        return "Sorry, the AI service is not available. Please install google-generativeai package."
    
    sub_type = 'free'
    if user:
        sub_type = user.subscription_type

    model_map = {
        'free': 'gemini-2.5-flash-lite',
        'pro': 'gemini-2.5-flash',
        'ultra': 'gemini-3-flash-preview',
    }
    model_name = model_map.get(sub_type, 'gemini-2.5-flash-lite')

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(model_name)
    
    system_prompt = CHATBOT_SYSTEM_PROMPTS.get(language, CHATBOT_SYSTEM_PROMPTS['en'])
    
    # Build conversation history
    conversation = f"{system_prompt}\n\n"
    
    # Get last 5 messages safely
    count = chat_history.count()
    start_index = max(0, count - 5)
    recent_messages = chat_history[start_index:]
    
    for msg in recent_messages:  # Last 5 messages for context
        role = "User" if msg.is_user else "Assistant"
        conversation += f"{role}: {msg.message}\n"
    conversation += f"User: {user_message}\nAssistant:"
    
    try:
        response = model.generate_content(conversation)
        return response.text.strip()
    except Exception as e:
        print(f"Error in chatbot: {e}")
        return "Sorry, I encountered an error. Please try again."

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

def generate_course_from_ai(topic, language='en', user=None, pdf_text=None):
    """
    Generates a course structure using Google Gemini API.
    Deducts user energy based on subscription tier and PDF usage.
    """
    if not GENAI_AVAILABLE:
        raise ImportError(
            "google-generativeai package is not installed. "
            "Install it with: pip install google-generativeai"
        )
    
    # 1. Determine cost, module count, and Gemini model based on user tier & PDF usage
    sub_type = 'free'
    if user:
        sub_type = user.subscription_type

    if pdf_text:
        if sub_type != 'ultra':
            raise ValueError("PDF course generation is only available for Ultra subscribers.")
        cost = 4.0
        modules_count = 3
        model_name = 'gemini-3-flash-preview'
    else:
        if sub_type == 'free':
            cost = 1.0
            modules_count = 1
            model_name = 'gemini-2.5-flash-lite'
        elif sub_type == 'pro':
            cost = 2.0
            modules_count = 2
            model_name = 'gemini-2.5-flash'
        else: # ultra
            cost = 3.0
            modules_count = 3
            model_name = 'gemini-3-flash-preview'

    # 2. Check and deduct energy
    if user:
        if user.energy < cost:
            raise ValueError(
                f"Not enough Energy! You need {cost} Energy to generate this course, "
                f"but you only have {user.energy}."
            )
        # Deduct energy
        user.energy = float(user.energy) - float(cost)
        user.save()

    # 3. Build dynamic prompt based on module count and language
    # Custom instructions for modules
    module_instruction = f"Generate exactly {modules_count} modules."
    if modules_count == 1:
        module_instruction += " The module must have exactly 5 lessons, and each lesson must have 1-2 quizzes."
    elif modules_count == 2:
        module_instruction += " Modules 1 and 2 must have exactly 5 lessons each, and each lesson must have 2-3 quizzes."
    else:
        module_instruction += " Modules 1 and 2 must have exactly 5 lessons each, and each lesson must have 2-3 quizzes. " \
                             "Module 3 must be named 'Final Exam' and contain exactly 1 lesson named 'Final Assessment' " \
                             "with at least 10 quizzes covering the entire course."

    # Language matching
    lang_name = "English"
    if language == 'uz':
        lang_name = "Uzbek (in Latin script)"
    elif language == 'kaa':
        lang_name = "Karakalpak (in Latin script)"
    elif language == 'ru':
        lang_name = "Russian"

    source_material = f"on the topic: \"{topic}\""
    if pdf_text:
        source_material = f"based strictly on the following source text (summarize and structure it into a course):\n\n{pdf_text[:4000]}"

    prompt = f"""You are a professional curriculum developer.
Create a comprehensive course {source_material}.

The output must be a valid JSON object with this structure:
{{
    "title": "Course Title",
    "description": "Course Description",
    "modules": [
        {{
            "title": "Module Title",
            "order": 1,
            "lessons": [
                {{
                    "title": "Lesson Title",
                    "content": "Detailed lesson content in Markdown format (at least 150 words)...",
                    "quizzes": [
                        {{
                            "question": "Quiz Question?",
                            "options": ["Option A", "Option B", "Option C", "Option D"],
                            "correct_answer": 0
                        }}
                    ]
                }}
            ]
        }}
    ]
}}

{module_instruction}
Ensure the JSON is valid and strictly follows the schema.
All content (titles, lessons, quizzes, options) must be in {lang_name}."""

    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    # Try premium model for Ultra, fallback to flash if it fails
    try:
        model = genai.GenerativeModel(model_name)
        generation_config = {'response_mime_type': 'application/json'}
        response = model.generate_content(prompt, generation_config=generation_config)
    except Exception as e:
        print(f"Failed to use model {model_name}: {e}. Falling back to gemini-2.5-flash.")
        model = genai.GenerativeModel('gemini-2.5-flash')
        generation_config = {'response_mime_type': 'application/json'}
        try:
            response = model.generate_content(prompt, generation_config=generation_config)
        except:
            response = model.generate_content(prompt)

    try:
        # Clean up the response to ensure it's valid JSON
        text = response.text.strip()
        
        # Remove markdown code blocks if present
        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        
        text = text.strip()
        
        # Extract JSON object using regex
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            text = match.group(0)
        
        try:
            course_data = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}. Attempting to repair...")
            try:
                text_fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
                course_data = json.loads(text_fixed)
                print("JSON repair successful!")
            except:
                raise ValueError(f"AI response was not valid JSON: {e}. Response text: {text[:100]}...")

        # Parsing and Saving to DB
        with transaction.atomic():
            course = Course.objects.create(
                title=course_data['title'],
                description=course_data['description'],
                language=language,
                creator=user
            )

            for mod_data in course_data['modules']:
                module = Module.objects.create(
                    course=course,
                    title=mod_data['title'],
                    order=mod_data['order']
                )

                for lesson_data in mod_data['lessons']:
                    lesson = Lesson.objects.create(
                        module=module,
                        title=lesson_data['title'],
                        content=lesson_data['content'],
                        order=lesson_data.get('order', 1)
                    )

                    # Handle multiple quizzes
                    quizzes_data = lesson_data.get('quizzes', [])
                    if 'quiz' in lesson_data:
                        quizzes_data.append(lesson_data['quiz'])

                    for quiz_data in quizzes_data:
                        correct_answer_index = quiz_data['correct_answer']
                        # Handle string/integer index variations safely
                        try:
                            idx = int(correct_answer_index)
                            correct_answer_text = quiz_data['options'][idx]
                        except:
                            correct_answer_text = str(correct_answer_index)
                        
                        Quiz.objects.create(
                            lesson=lesson,
                            question=quiz_data['question'],
                            options=quiz_data['options'],
                            correct_answer=correct_answer_text
                        )
            
            # Enroll user in the course if user is provided
            if user:
                UserCourse.objects.create(user=user, course=course)
                
        return course

    except Exception as e:
        # Refund energy in case of complete generation failure
        if user:
            user.energy = float(user.energy) + float(cost)
            user.save()
        print(f"Error generating course: {e}")
        raise e
