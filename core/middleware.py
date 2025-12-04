from django.utils import translation

class UserLanguageMiddleware:
    """Automatically activate the user's preferred language"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            user_language = request.user.preferred_language
            translation.activate(user_language)
            request.LANGUAGE_CODE = user_language

        response = self.get_response(request)
        return response

from .models import UserStreak

class StreakMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Xatolik bo'lmasligi uchun try-except qo'shamiz
            try:
                streak, created = UserStreak.objects.get_or_create(user=request.user)
                streak.update_streak()
            except Exception as e:
                print(f"Streak update error: {e}")

        response = self.get_response(request)
        return response