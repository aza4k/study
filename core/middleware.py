from django.utils import translation

class UserLanguageMiddleware:
    """Activate user's chosen session/cookie or preferred language without overriding explicit switches."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        lang = (
            request.session.get('_language')
            or request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        )
        if not lang and request.user.is_authenticated:
            lang = request.user.preferred_language
        if lang:
            translation.activate(lang)
            request.LANGUAGE_CODE = lang

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

from django.http import JsonResponse, HttpResponse

class AppSignatureMiddleware:
    """Only allow requests to /api/ containing the mobile app signature header"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Filter all /api/ endpoints (exclude Django Admin, static files, etc.)
        if request.path.startswith('/api/'):
            # Direct successful response to all OPTIONS preflight requests
            if request.method == 'OPTIONS':
                response = HttpResponse(status=200)
                response['Access-Control-Allow-Origin'] = '*'
                response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
                response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-App-Signature'
                return response

            signature = request.headers.get('X-App-Signature') or request.META.get('HTTP_X_APP_SIGNATURE')
            if signature != 'StuDyAppKeySignature2026!':
                return JsonResponse(
                    {"detail": "Unauthorized request origin."}, 
                    status=403
                )

        response = self.get_response(request)
        return response