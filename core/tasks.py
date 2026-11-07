"""
Celery tasks for the Study application.

This module contains asynchronous tasks for:
- Course generation (heavy, long-running tasks)
- Chat responses (quick tasks)
"""

from celery import shared_task
from django.contrib.auth import get_user_model
from .services import generate_course_from_ai, chatbot_response
from .models import ChatMessage

User = get_user_model()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,  # Max 10 minutes
    max_retries=5,
    name='core.tasks.generate_course_task'
)
def generate_course_task(self, topic, language='en', user_id=None):
    """
    Asynchronous task to generate a course using Google Gemini API.
    """
    try:
        user = None
        if user_id:
            user = User.objects.get(id=user_id)
        
        course = generate_course_from_ai(topic, language, user)
        
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
    try:
        chat_history = ChatMessage.objects.filter(id__in=chat_history_ids).order_by('created_at')
        response = chatbot_response(user_message, chat_history, language)
        return response
    except Exception as e:
        print(f"Error in chatbot_response_task (attempt {self.request.retries + 1}/{self.max_retries}): {e}")
        raise
