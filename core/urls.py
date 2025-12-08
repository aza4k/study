from django.urls import path
from . import views

urlpatterns = [
    path('', views.LandingPageView.as_view(), name='landing'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('chatbot/', views.ChatbotView.as_view(), name='chatbot'),
    path('send-message/', views.send_message, name='send_message'),
    path('generate-course/', views.generate_course_view, name='generate_course'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('course/<int:pk>/', views.CourseDetailView.as_view(), name='course_detail'),
    path('lesson/<int:pk>/', views.LessonView.as_view(), name='lesson_detail'),
    path('lesson/<int:lesson_id>/submit-quiz/', views.submit_quiz, name='submit_quiz'),
    path('leaderboard/', views.LeaderboardView.as_view(), name='leaderboard'),
    path('gamification/', views.GamificationView.as_view(), name='gamification'),
    path('pricing/', views.PricingView.as_view(), name='pricing'),
    path('course/<int:course_id>/certificate/', views.download_certificate, name='download_certificate'),
    path('change-language/', views.change_language, name='change_language'),
    path('lesson/<int:lesson_id>/chatbot/', views.lesson_chatbot, name='lesson_chatbot'),
    path('task-status/<str:task_id>/', views.check_task_status, name='check_task_status'),
    path('clear-chat/', views.clear_chat_history, name='clear_chat_history'),
]

