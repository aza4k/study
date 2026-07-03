from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

router = DefaultRouter()
router.register(r'courses', views.CourseViewSet, basename='course')
router.register(r'lessons', views.LessonViewSet, basename='lesson')

urlpatterns = [
    # Auth
    path('auth/register/', views.RegisterView.as_view(), name='api_register'),
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/profile/', views.UserProfileView.as_view(), name='api_profile'),

    # Viewsets
    path('', include(router.urls)),

    # Interactive endpoints
    path('lessons/<int:lesson_id>/submit-quiz/', views.SubmitQuizView.as_view(), name='api_submit_quiz'),
    path('chatbot/', views.ChatbotView.as_view(), name='api_chatbot'),
    path('chatbot/clear/', views.ClearChatView.as_view(), name='api_clear_chat'),
    path('chatbot/generate-course/', views.GenerateCourseView.as_view(), name='api_generate_course'),
    path('chatbot/generate-pdf-course/', views.UploadPDFCourseView.as_view(), name='api_generate_pdf_course'),
    
    # Gamification & Business Model
    path('leaderboard/', views.LeaderboardView.as_view(), name='api_leaderboard'),
    path('profile/redeem-xp/', views.RedeemXPView.as_view(), name='api_redeem_xp'),
    path('profile/claim-bonus/', views.ClaimDailyBonusView.as_view(), name='api_claim_bonus'),
    path('profile/mock-purchase/', views.PurchaseEnergyView.as_view(), name='api_mock_purchase'),
    path('profile/mock-subscribe/', views.SubscribeView.as_view(), name='api_mock_subscribe'),
    path('courses/<int:course_id>/certificate/', views.CertificateView.as_view(), name='api_certificate'),
]
