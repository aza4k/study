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
    
    This is a heavy, long-running task that can take 10-30 seconds.
    It's routed to the 'heavy_tasks' queue with lower concurrency.
    
    Args:
        topic (str): The topic for the course
        language (str): Language code ('en', 'ru', 'kaa')
        user_id (int, optional): User ID to enroll in the course
    
    Returns:
        dict: Course information including id, title, and description
    
    Raises:
        Exception: Any error during course generation (will auto-retry)
    """
    try:
        user = None
        if user_id:
            user = User.objects.get(id=user_id)
        
        # Generate the course
        course = generate_course_from_ai(topic, language, user)
        
        return {
            'success': True,
            'course_id': course.id,
            'title': course.title,
            'description': course.description,
            'message': f'Course "{course.title}" generated successfully!'
        }
    except Exception as e:
        # Log the error
        print(f"Error in generate_course_task (attempt {self.request.retries + 1}/{self.max_retries}): {e}")
        # Re-raise to trigger retry
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
    
    This is a quick task routed to the 'default' queue with high concurrency.
    
    Args:
        user_message (str): The user's message
        chat_history_ids (list): List of ChatMessage IDs for context
        language (str): Language code ('en', 'ru', 'kaa')
    
    Returns:
        str: The chatbot's response
    
    Raises:
        Exception: Any error during response generation (will auto-retry)
    """
    try:
        # Reconstruct chat history from IDs
        chat_history = ChatMessage.objects.filter(id__in=chat_history_ids).order_by('timestamp')
        
        # Generate response
        response = chatbot_response(user_message, chat_history, language)
        
        return response
    except Exception as e:
        # Log the error
        print(f"Error in chatbot_response_task (attempt {self.request.retries + 1}/{self.max_retries}): {e}")
        # Re-raise to trigger retry
        raise
