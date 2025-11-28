from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, TemplateView
from django.views import View
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.db.models import Sum
from django.utils import translation
from .models import Course, Lesson, UserProgress, Quiz, ChatMessage, UserCourse, CustomUser
from .services import generate_course_from_ai, chatbot_response
from .forms import CustomUserCreationForm, CustomAuthenticationForm
from .certificate import generate_certificate
import json
import re

# Helper to get user XP
def get_user_xp(user):
    return UserProgress.objects.filter(user=user).aggregate(Sum('score'))['score__sum'] or 0

# Helper to check if course is completed
def is_course_completed(user, course):
    total_lessons = Lesson.objects.filter(module__course=course).count()
    completed_lessons = UserProgress.objects.filter(
        user=user,
        lesson__module__course=course,
        is_completed=True
    ).count()
    return total_lessons > 0 and total_lessons == completed_lessons

class LandingPageView(TemplateView):
    template_name = 'landing.html'
    
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('chatbot')
        return super().get(request, *args, **kwargs)

class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('chatbot')
        form = CustomUserCreationForm()
        return render(request, 'register.html', {'form': form})
    
    def post(self, request):
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('chatbot')
        return render(request, 'register.html', {'form': form})

class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('chatbot')
        form = CustomAuthenticationForm()
        return render(request, 'login.html', {'form': form})
    
    def post(self, request):
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('chatbot')
        return render(request, 'login.html', {'form': form})

class LogoutView(View):
    def get(self, request):
        logout(request)
        return redirect('landing')

class ChatbotView(LoginRequiredMixin, TemplateView):
    template_name = 'chatbot.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['chat_messages'] = ChatMessage.objects.filter(user=self.request.user)
        context['user_xp'] = get_user_xp(self.request.user)
        return context

@login_required
@require_POST
def send_message(request):
    """Handle chatbot message sending"""
    user_message = request.POST.get('message', '').strip()
    
    if not user_message:
        return JsonResponse({'error': 'Message cannot be empty'}, status=400)
    
    # Save user message
    ChatMessage.objects.create(user=request.user, message=user_message, is_user=True)
    
    # Get chat history
    chat_history = ChatMessage.objects.filter(user=request.user).order_by('created_at')
    
    # Get bot response
    bot_reply = chatbot_response(user_message, chat_history, request.user.preferred_language)
    
    # Check if topic is clear
    topic_clear = False
    topic = None
    if 'TOPIC_CLEAR:' in bot_reply:
        topic_clear = True
        # Extract topic
        match = re.search(r'TOPIC_CLEAR:\s*(.+)', bot_reply)
        if match:
            topic = match.group(1).strip()
            # Remove the TOPIC_CLEAR marker from the message
            bot_reply = re.sub(r'TOPIC_CLEAR:.+', '', bot_reply).strip()
    
    # Save bot message
    ChatMessage.objects.create(user=request.user, message=bot_reply, is_user=False)
    
    return JsonResponse({
        'bot_message': bot_reply,
        'topic_clear': topic_clear,
        'topic': topic
    })

@login_required
@require_POST
def generate_course_view(request):
    """Handle course generation"""
    topic = request.POST.get('topic', '').strip()
    
    if not topic:
        return JsonResponse({'error': 'Topic cannot be empty'}, status=400)
    
    try:
        # Generate course (this will take time)
        course = generate_course_from_ai(topic, request.user.preferred_language, request.user)
        
        return JsonResponse({
            'success': True,
            'course_id': course.id,
            'course_title': course.title,
            'redirect_url': '/dashboard/'
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

from django.views.decorators.cache import never_cache

@method_decorator(never_cache, name='dispatch')
class DashboardView(LoginRequiredMixin, ListView):
    model = Course
    template_name = 'dashboard.html'
    context_object_name = 'courses'
    
    def get_queryset(self):
        # Only show courses the user is enrolled in
        return Course.objects.filter(enrolled_users__user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_xp'] = get_user_xp(self.request.user)
        
        # Calculate progress for each course
        for course in context['courses']:
            total_lessons = Lesson.objects.filter(module__course=course).count()
            completed_lessons = UserProgress.objects.filter(
                user=self.request.user,
                lesson__module__course=course,
                is_completed=True
            ).count()
            
            if total_lessons > 0:
                course.progress = int((completed_lessons / total_lessons) * 100)
            else:
                course.progress = 0
                
        return context

class CourseDetailView(LoginRequiredMixin, DetailView):
    model = Course
    template_name = 'course_detail.html'
    context_object_name = 'course'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Fetch completed lesson IDs
        completed_ids = UserProgress.objects.filter(
            user=self.request.user, is_completed=True
        ).values_list('lesson_id', flat=True)
        context['completed_lesson_ids'] = set(completed_ids)
        context['user_xp'] = get_user_xp(self.request.user)
        context['is_completed'] = is_course_completed(self.request.user, self.object)
        return context

class LessonView(LoginRequiredMixin, DetailView):
    model = Lesson
    template_name = 'lesson.html'
    context_object_name = 'lesson'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_xp'] = get_user_xp(self.request.user)
        # Check if already completed
        context['is_completed'] = UserProgress.objects.filter(
            user=self.request.user, lesson=self.object, is_completed=True
        ).exists()
        
        # Get current module and all lessons in order
        current_module = self.object.module
        all_lessons = current_module.lessons.order_by('order')
        
        # Find next and previous lessons
        current_index = None
        for idx, lesson in enumerate(all_lessons):
            if lesson.id == self.object.id:
                current_index = idx
                break
        
        if current_index is not None:
            # Get previous lesson
            if current_index > 0:
                context['previous_lesson'] = all_lessons[current_index - 1]
            else:
                context['previous_lesson'] = None
            
            # Get next lesson
            if current_index < len(all_lessons) - 1:
                context['next_lesson'] = all_lessons[current_index + 1]
            else:
                context['next_lesson'] = None
        
        return context

@login_required
@require_POST
def submit_quiz(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    quiz_id = request.POST.get('quiz_id')
    selected_option = request.POST.get('option')
    
    if not quiz_id:
        # Try to get the first quiz if no ID provided (backward compatibility)
        quiz = lesson.quizzes.first()
        if not quiz:
            return HttpResponse('<div class="text-red-500">No quiz found for this lesson.</div>')
    else:
        quiz = get_object_or_404(Quiz, id=quiz_id)
    
    if not selected_option:
        return HttpResponse('<div class="text-red-500">Please select an option.</div>')

    is_correct = selected_option == quiz.correct_answer
    
    # Update progress
    progress, created = UserProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )
    
    # Mark as completed regardless of outcome (as per user request)
    if not progress.is_completed:
        progress.is_completed = True
        progress.save()

    if is_correct:
        progress.score += 10 # 10 XP per correct answer
        progress.save()
        
        return render(request, 'partials/quiz_result.html', {
            'success': True,
            'lesson': lesson,
            'quiz': quiz,
            'next_lesson': Lesson.objects.filter(module=lesson.module, order__gt=lesson.order).first() or 
                           Lesson.objects.filter(module__course=lesson.module.course, module__order__gt=lesson.module.order).first()
        })
    else:
        progress.score -= 5 # Deduct 5 XP for incorrect answer
        progress.save()
        return render(request, 'partials/quiz_result.html', {
            'success': False,
            'correct_answer': quiz.correct_answer,
            'quiz': quiz
        })

class LeaderboardView(LoginRequiredMixin, TemplateView):
    template_name = 'leaderboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all users with their total XP
        users_with_xp = []
        for user in CustomUser.objects.all():
            total_xp = get_user_xp(user)
            if total_xp > 0:  # Only include users with XP
                users_with_xp.append({
                    'user': user,
                    'total_xp': total_xp,
                    'league': self.get_league(total_xp),
                    'badge_color': self.get_badge_color(total_xp)
                })
        
        # Sort by XP descending and limit to top 100
        users_with_xp.sort(key=lambda x: x['total_xp'], reverse=True)
        users_with_xp = users_with_xp[:100]  # Limit to top 100
        
        # Add rank
        for index, user_data in enumerate(users_with_xp, start=1):
            user_data['rank'] = index
            user_data['is_current_user'] = user_data['user'].id == self.request.user.id
        
        # Get current user stats
        current_user_xp = get_user_xp(self.request.user)
        current_user_league = self.get_league(current_user_xp)
        
        # Calculate XP needed for next league
        if current_user_xp < 100:
            xp_to_next_league = 100 - current_user_xp
        elif current_user_xp < 500:
            xp_to_next_league = 500 - current_user_xp
        elif current_user_xp < 1000:
            xp_to_next_league = 1000 - current_user_xp
        else:
            xp_to_next_league = 0
        
        context['leaderboard'] = users_with_xp
        context['current_user_xp'] = current_user_xp
        context['current_user_league'] = current_user_league
        context['xp_to_next_league'] = xp_to_next_league
        
        return context
    
    def get_league(self, xp):
        """Determine league based on XP"""
        if xp >= 1000:
            return 'Gold'
        elif xp >= 500:
            return 'Silver'
        elif xp >= 100:
            return 'Bronze'
        else:
            return 'Beginner'
    
    def get_badge_color(self, xp):
        """Get badge color based on league"""
        if xp >= 1000:
            return 'yellow'  # Gold
        elif xp >= 500:
            return 'gray'  # Silver
        elif xp >= 100:
            return 'orange'  # Bronze
        else:
            return 'blue'  # Beginner

class GamificationView(LoginRequiredMixin, TemplateView):
    template_name = 'gamification.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add user XP to context
        context['user_xp'] = get_user_xp(self.request.user)
        
        # Get top 5 users for leaderboard preview
        users_with_xp = []
        for user in CustomUser.objects.all():
            total_xp = get_user_xp(user)
            if total_xp > 0:
                users_with_xp.append({
                    'username': user.username,
                    'xp': total_xp
                })
        
        # Sort by XP and get top 5
        users_with_xp.sort(key=lambda x: x['xp'], reverse=True)
        context['top_users'] = users_with_xp[:5]
        
        return context

@login_required
def download_certificate(request, course_id):
    """
    Generate and download PDF certificate for completed courses
    """
    course = get_object_or_404(Course, id=course_id)
    
    # Check if user has completed the course
    if not is_course_completed(request.user, course):
        return HttpResponse("You must complete all lessons to download the certificate.", status=403)
    
    # Generate the certificate PDF
    pdf = generate_certificate(request.user, course)
    
    # Create the HTTP response with PDF
    response = HttpResponse(pdf, content_type='application/pdf')
    filename = f"Certificate_{course.title.replace(' ', '_')}_{request.user.username}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response

@login_required
@require_POST
def change_language(request):
    """Handle language change requests"""
    from django.utils import translation
    
    language_code = request.POST.get('language')
    
    # Validate language code
    valid_languages = dict(CustomUser.LANGUAGE_CHOICES).keys()
    if language_code not in valid_languages:
        return JsonResponse({'error': 'Invalid language code'}, status=400)
    
    # Update user's preferred language
    request.user.preferred_language = language_code
    request.user.save()
    
    # Activate the new language for the current session
    translation.activate(language_code)
    request.session['_language'] = language_code
    
    return JsonResponse({'success': True, 'language': language_code})

@login_required
@require_POST
def lesson_chatbot(request, lesson_id):
    """
    AI chatbot that helps with lesson content but refuses to answer quiz questions
    """
    lesson = get_object_or_404(Lesson, id=lesson_id)
    user_message = request.POST.get('message', '').strip()
    
    if not user_message:
        return HttpResponse('<div class="text-red-500 text-sm">Please enter a message.</div>')
    
    # Get lesson content and quiz questions
    lesson_content = lesson.content[:2000]  # Limit content length
    quiz_questions = [q.question for q in lesson.quizzes.all()]
    course_language = lesson.module.course.language
    
    # Language-specific prompts
    language_prompts = {
        'en': {
            'system': f"""You are a helpful learning assistant for a specific lesson. Your role is to help students understand the lesson content.

LESSON TITLE: {lesson.title}
LESSON CONTENT (excerpt): {lesson_content}

QUIZ QUESTIONS (for reference only - DO NOT answer these):
{chr(10).join(f"- {q}" for q in quiz_questions)}

IMPORTANT RULES:
1. Help explain the lesson content and concepts
2. If asked about quiz answers or solutions, politely refuse and encourage the student to study the lesson
3. Keep responses concise and educational
4. Respond in English
5. Be encouraging and supportive""",
            'refusal': "I can't help with quiz answers, but I'd be happy to explain the lesson concepts to help you understand the material better!",
        },
        'ru': {
            'system': f"""Вы полезный помощник по обучению для конкретного урока. Ваша роль - помочь студентам понять содержание урока.

НАЗВАНИЕ УРОКА: {lesson.title}
СОДЕРЖАНИЕ УРОКА (отрывок): {lesson_content}

ВОПРОСЫ ТЕСТА (только для справки - НЕ отвечайте на них):
{chr(10).join(f"- {q}" for q in quiz_questions)}

ВАЖНЫЕ ПРАВИЛА:
1. Помогайте объяснять содержание урока и концепции
2. Если спрашивают об ответах на тесты, вежливо откажите и поощрите студента изучить урок
3. Давайте краткие и образовательные ответы
4. Отвечайте на русском языке
5. Будьте ободряющими и поддерживающими""",
            'refusal': "Я не могу помочь с ответами на тесты, но с удовольствием объясню концепции урока, чтобы помочь вам лучше понять материал!",
        },
        'kaa': {
            'system': f"""Siz belgili bir sabaq ushın paydali oqiw járdemshisisiz. Sizdiń rólińiz - studentlerge sabaq mazmunın túsiniwge járdem beriw.

SABAQ ATI: {lesson.title}
SABAQ MAZMUNI (úzindi): {lesson_content}

TEST SORAWLARI (tek anıqlama ushın - bularǵa juwap BERMEŃ):
{chr(10).join(f"- {q}" for q in quiz_questions)}

MÁNISLI QÁǴIDELER:
1. Sabaq mazmunı hám túsiniklerin túsindiriwge járdem beriń
2. Eger test juwapları haqqında sorasalar, sıylı túrde bas tartıń hám studentti sabaqti úyreniwge ruwxlandırıń
3. Qısqa hám bilim beriwshi juwaplar beriń
4. Qaraqalpaq tilinde juwap beriń
5. Qollap-quwatławshı hám ruwxlandırıwshı bolıń""",
            'refusal': "Men test juwaplarına járdem bere almayman, biraq sabaq túsiniklerin túsindirip, materialı jaqsı túsiniwińizge járdem beremın!",
        }
    }
    
    prompt_data = language_prompts.get(course_language, language_prompts['en'])
    system_prompt = prompt_data['system']
    
    # Check if user is asking about quiz answers
    quiz_keywords = ['answer', 'solution', 'correct', 'ответ', 'решение', 'правильн', 'juwap', 'durıs', 'sheshim']
    is_quiz_question = any(keyword in user_message.lower() for keyword in quiz_keywords) and \
                      any(q_word in user_message.lower() for q_word in ['quiz', 'test', 'question', 'тест', 'вопрос', 'soraw'])
    
    if is_quiz_question:
        response_text = prompt_data['refusal']
    else:
        # Generate AI response
        try:
            import google.generativeai as genai
            from django.conf import settings
            
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            full_prompt = f"{system_prompt}\n\nStudent question: {user_message}\n\nYour response:"
            response = model.generate_content(full_prompt)
            response_text = response.text.strip()
        except Exception as e:
            print(f"Error in lesson chatbot: {e}")
            response_text = "Sorry, I encountered an error. Please try again." if course_language == 'en' else \
                           "Извините, произошла ошибка. Попробуйте снова." if course_language == 'ru' else \
                           "Keshiriń, qátelik júz berdi. Qaytadan háreket etiń."
    
    # Return formatted response
    return render(request, 'partials/lesson_chatbot_message.html', {
        'message': response_text,
        'is_ai': True
    })
