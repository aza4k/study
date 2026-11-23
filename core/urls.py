from django.urls import path
from . import views

urlpatterns = [
    path('', views.LandingPageView.as_view(), name='landing'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),

    # Core Learning & AI
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('explore/', views.ExploreCoursesWebView.as_view(), name='explore'),
    path('courses/<int:course_id>/star/', views.explore_star_web, name='explore_star_web'),
    path('courses/<int:course_id>/enroll/', views.explore_enroll_web, name='explore_enroll_web'),
    path('course/<int:pk>/', views.CourseDetailView.as_view(), name='course_detail'),
    path('lesson/<int:pk>/', views.LessonView.as_view(), name='lesson_detail'),
    path('lesson/<int:lesson_id>/submit-quiz/', views.submit_quiz, name='submit_quiz'),
    path('lesson/<int:lesson_id>/evaluate-practice/', views.evaluate_practice_web, name='evaluate_practice_web'),
    path('lesson/<int:lesson_id>/chatbot/', views.lesson_chatbot, name='lesson_chatbot'),
    path('course/<int:course_id>/certificate/', views.download_certificate, name='download_certificate'),

    # AI Chat & Generators
    path('chatbot/', views.ChatbotView.as_view(), name='chatbot'),
    path('send-message/', views.send_message, name='send_message'),
    path('clear-chat/', views.clear_chat_history, name='clear_chat_history'),
    path('generate-course/', views.generate_course_view, name='generate_course'),
    path('generate-pdf-course/', views.generate_pdf_course_web, name='generate_pdf_course_web'),
    path('task-status/<str:task_id>/', views.check_task_status, name='check_task_status'),

    # Blitz, Leaderboard, Profile & Economy
    path('blitz/', views.BlitzReviewWebView.as_view(), name='blitz_web'),
    path('leaderboard/', views.LeaderboardView.as_view(), name='leaderboard'),
    path('profile/', views.ProfileWebView.as_view(), name='profile_web'),
    path('store/', views.StoreWebView.as_view(), name='store_web'),
    path('gamification/', views.GamificationView.as_view(), name='gamification'),
    path('pricing/', views.PricingView.as_view(), name='pricing'),
    path('claim-bonus/', views.claim_bonus_web, name='claim_bonus_web'),
    path('claim-quest/', views.claim_quest_web, name='claim_quest_web'),
    path('redeem-xp/', views.redeem_xp_web, name='redeem_xp_web'),
    path('change-language/', views.change_language, name='change_language'),

    # Google Play Store Compliance & Support
    path('privacy/', views.PrivacyPolicyView.as_view(), name='privacy_policy'),
    path('privacy-policy/', views.PrivacyPolicyView.as_view(), name='privacy_policy_alias'),
    path('delete-account/', views.AccountDeletionWebView.as_view(), name='delete_account_web'),
    path('account-deletion/', views.AccountDeletionWebView.as_view(), name='account_deletion_alias'),
    path('terms/', views.TermsOfUseView.as_view(), name='terms_of_use'),
    path('terms-of-use/', views.TermsOfUseView.as_view(), name='terms_of_use_alias'),
    path('support/', views.SupportView.as_view(), name='support_page'),
    path('contact/', views.SupportView.as_view(), name='contact_alias'),
]
