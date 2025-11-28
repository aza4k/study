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
