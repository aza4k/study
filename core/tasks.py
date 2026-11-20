"""
Celery tasks for the StuDy AI application.

Asynchronous background tasks:
- prewarm_single_lesson_task: Predictive 1-ahead lesson pre-warming (saves 60-70% tokens & VPS CPU)
- generate_ai_cover_task: Custom course cover illustration generation
- generate_course_task: Full async course creation
- chatbot_response_task: Async chat generation
"""

from celery import shared_task
from django.contrib.auth import get_user_model

User = get_user_model()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=2,
    name='core.tasks.prewarm_single_lesson_task'
)
def prewarm_single_lesson_task(self, lesson_id, language='en', tier='free'):
    """
    Lazily pre-warms a single upcoming lesson (N+1) so the user experiences zero wait
    without wastefully generating unread lessons.
    """
    from .models import Lesson
    from .services import get_or_generate_lesson_content

    try:
        lesson = Lesson.objects.select_related('module__course').get(id=lesson_id)
        if len(lesson.content.strip()) < 80 or not lesson.quizzes.exists():
            get_or_generate_lesson_content(lesson, language=language, tier=tier)
        return {'success': True, 'lesson_id': lesson_id}
    except Lesson.DoesNotExist:
        return {'success': False, 'reason': 'Lesson not found'}
    except Exception as e:
        print(f"Notice in prewarm_single_lesson_task ({lesson_id}): {e}")
        raise


@shared_task(
    bind=True,
    max_retries=1,
    name='core.tasks.generate_ai_cover_task'
)
def generate_ai_cover_task(self, course_id, topic, title):
    """
    Generates a custom AI course cover in Celery without blocking Gunicorn workers.
    """
    from .services import async_generate_ai_cover
    async_generate_ai_cover(course_id, topic, title)
    return {'success': True, 'course_id': course_id}


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
    name='core.tasks.generate_course_task'
)
def generate_course_task(self, topic, language='en', user_id=None, difficulty='beginner'):
    """
    Asynchronous task to generate a course using Google Gemini API.
    """
    from .services import generate_course_from_ai

    try:
        user = User.objects.get(id=user_id) if user_id else None
        course = generate_course_from_ai(topic, language, user, difficulty=difficulty)
        return {
            'success': True,
            'course_id': course.id,
            'title': course.title,
            'description': course.description,
            'message': f'Course "{course.title}" generated successfully!'
        }
    except Exception as e:
        print(f"Error in generate_course_task (attempt {self.request.retries + 1}/{self.max_retries}): {e}")
        raise


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name='core.tasks.chatbot_response_task'
)
def chatbot_response_task(self, user_message, chat_history_ids, language='en'):
    """
    Asynchronous task to generate chatbot responses.
    """
    from .models import ChatMessage
    from .services import chatbot_response

    try:
        chat_history = ChatMessage.objects.filter(id__in=chat_history_ids).order_by('created_at')
        response = chatbot_response(user_message, chat_history, language)
        return response
    except Exception as e:
        print(f"Error in chatbot_response_task (attempt {self.request.retries + 1}/{self.max_retries}): {e}")
        raise
