import json
import random
import re
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, TemplateView

from core.api.views import _build_daily_quests, _get_total_xp
from .certificate import generate_certificate
from .forms import CustomAuthenticationForm, CustomUserCreationForm
from .models import (
    Certificate,
    ChatMessage,
    Course,
    CourseStar,
    CustomUser,
    DailyActivity,
    Lesson,
    Quiz,
    UserCourse,
    UserProgress,
    UserStreak,
)
from .services import (
    ECONOMY_CONFIG,
    _schedule_single_lesson_prewarm,
    ask_lesson_tutor,
    chatbot_response,
    evaluate_practice_submission,
    extract_text_from_pdf,
    generate_course_from_ai,
    get_or_generate_lesson_content,
)

User = get_user_model()


def get_user_xp(user):
    progress_xp = UserProgress.objects.filter(user=user).aggregate(Sum('score'))['score__sum'] or 0
    return int(progress_xp) + int(getattr(user, 'bonus_xp', 0))


def is_course_completed(user, course):
    total_lessons = Lesson.objects.filter(module__course=course).count()
    completed_lessons = UserProgress.objects.filter(
        user=user,
        lesson__module__course=course,
        is_completed=True,
    ).count()
    return total_lessons > 0 and total_lessons == completed_lessons


class LandingPageView(TemplateView):
    template_name = 'landing.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_count'] = User.objects.count()
        context['course_count'] = Course.objects.count()
        return context


class PricingView(TemplateView):
    template_name = 'pricing.html'


class StoreWebView(LoginRequiredMixin, TemplateView):
    template_name = 'store.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        total_xp, available_xp = _get_total_xp(user)
        context['total_xp'] = total_xp
        context['available_xp'] = available_xp
        context['xp_redeem_cost'] = ECONOMY_CONFIG['xp_redeem_cost']
        context['xp_redeem_reward'] = int(ECONOMY_CONFIG['xp_redeem_reward'])
        return context


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, 'register.html', {'form': CustomUserCreationForm()})

    def post(self, request):
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
        return render(request, 'register.html', {'form': form})


class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, 'login.html', {'form': CustomAuthenticationForm()})

    def post(self, request):
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('dashboard')
        return render(request, 'login.html', {'form': form})


class LogoutView(View):
    def get(self, request):
        logout(request)
        return redirect('landing')


class ChatbotView(LoginRequiredMixin, TemplateView):
    template_name = 'chatbot.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)
        context['chat_messages'] = ChatMessage.objects.filter(user=user).order_by('created_at')
        context['user_xp'] = get_user_xp(user)
        context['chat_cost'] = int(ECONOMY_CONFIG['chat_cost'])
        context['free_daily_limit'] = ECONOMY_CONFIG['free_daily_chat_limit']
        context['chats_sent_today'] = activity.chats_sent
        return context


@login_required
@require_POST
def send_message(request):
    """Handle AI Tutor chat messages with the same economy rules as the mobile app."""
    user = request.user
    today = timezone.localdate()
    activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

    if user.subscription_type == 'free' and activity.chats_sent >= ECONOMY_CONFIG['free_daily_chat_limit']:
        return JsonResponse(
            {'error': f"Kunlik limit ({ECONOMY_CONFIG['free_daily_chat_limit']} ta xabar) tugadi. PRO tarifiga o'ting!"},
            status=400,
        )

    chat_cost = ECONOMY_CONFIG['chat_cost']
    if Decimal(str(user.energy)) < chat_cost:
        return JsonResponse(
            {'error': f"Energiya yetarli emas! Xabar narxi {int(chat_cost)}⚡."},
            status=400,
        )

    user_message = request.POST.get('message', '').strip()
    if not user_message:
        return JsonResponse({'error': "Xabar bo'sh bo'lishi mumkin emas."}, status=400)

    ChatMessage.objects.create(user=user, message=user_message, is_user=True)
    chat_history = ChatMessage.objects.filter(user=user).order_by('created_at')

    bot_reply = chatbot_response(user_message, chat_history, user.preferred_language, user=user)

    topic_clear = False
    topic = None
    if 'TOPIC_CLEAR:' in bot_reply:
        topic_clear = True
        match = re.search(r'TOPIC_CLEAR:\s*(.+)', bot_reply)
        if match:
            topic = match.group(1).strip()
            bot_reply = re.sub(r'TOPIC_CLEAR:.+', '', bot_reply).strip()

    ChatMessage.objects.create(user=user, message=bot_reply, is_user=False)
    user.energy = Decimal(str(user.energy)) - chat_cost
    user.save(update_fields=['energy'])
    activity.chats_sent += 1
    activity.save(update_fields=['chats_sent'])

    return JsonResponse({
        'bot_message': bot_reply,
        'topic_clear': topic_clear,
        'topic': topic,
        'current_energy': float(user.energy),
    })


@login_required
@require_POST
def generate_course_view(request):
    """Handle course generation on web using the same tier limits, energy, and lazy Lesson 1 model."""
    user = request.user
    topic = request.POST.get('topic', '').strip()
    difficulty = (request.POST.get('difficulty') or 'beginner').strip().lower()
    if difficulty not in ('beginner', 'intermediate', 'advanced'):
        difficulty = 'beginner'

    if not topic:
        return JsonResponse({'error': "Mavzu kiritilishi shart."}, status=400)

    sub = user.subscription_type or 'free'
    limit = ECONOMY_CONFIG['course_limit'].get(sub, 2)
    created_count = Course.objects.filter(creator=user).count()
    if created_count >= limit:
        return JsonResponse(
            {'error': f"{sub.upper()} tarifi limiti ({limit} ta kurs) to'ldi. Ko'proq yaratish uchun tarifni oshiring!"},
            status=400,
        )

    course_cost = ECONOMY_CONFIG['course_cost'].get(sub, Decimal('10.00'))
    if Decimal(str(user.energy)) < course_cost:
        return JsonResponse(
            {'error': f"Energiya yetarli emas! Kurs yaratish uchun {int(course_cost)}⚡ kerak."},
            status=400,
        )

    try:
        if getattr(settings, 'USE_CELERY', False):
            from .tasks import generate_course_task
            task = generate_course_task.delay(
                topic=topic,
                language=user.preferred_language,
                user_id=user.id,
                difficulty=difficulty,
            )
            return JsonResponse({
                'success': True,
                'task_id': task.id,
                'message': "Kurs generatsiyasi boshlandi...",
                'status_url': f'/task-status/{task.id}/',
            })

        course = generate_course_from_ai(topic, user.preferred_language, user, difficulty=difficulty)
        cache.delete(f"courses_list_v2_{user.id}")
        return JsonResponse({
            'success': True,
            'course_id': course.id,
            'title': course.title,
            'message': f'"{course.title}" kursi yaratildi!',
            'redirect_url': f'/course/{course.id}/',
            'sync': True,
        })
    except ValueError as ve:
        return JsonResponse({'error': str(ve)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def generate_pdf_course_web(request):
    user = request.user
    if user.subscription_type not in ('pro', 'ultra'):
        return JsonResponse(
            {'error': "PDF hujjatdan kurs yaratish PRO yoki ULTRA tarifida ishlaydi."},
            status=403,
        )

    pdf_file = request.FILES.get('pdf')
    if not pdf_file:
        return JsonResponse({'error': "PDF fayl tanlanmadi."}, status=400)

    try:
        pdf_text = extract_text_from_pdf(pdf_file)
        if not pdf_text:
            return JsonResponse({'error': "PDF fayldan matn ajratib bo'lmadi."}, status=400)

        course = generate_course_from_ai("Custom PDF Course", user.preferred_language, user, pdf_text=pdf_text)
        cache.delete(f"courses_list_v2_{user.id}")
        return JsonResponse({
            'success': True,
            'course_id': course.id,
            'title': course.title,
            'redirect_url': f'/course/{course.id}/',
        })
    except ValueError as ve:
        return JsonResponse({'error': str(ve)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@method_decorator(never_cache, name='dispatch')
class DashboardView(LoginRequiredMixin, ListView):
    model = Course
    template_name = 'dashboard.html'
    context_object_name = 'courses'

    def get_queryset(self):
        return (
            Course.objects.filter(enrolled_users__user=self.request.user)
            .distinct()
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()

        total_xp, available_xp = _get_total_xp(user)
        streak_obj, _ = UserStreak.objects.get_or_create(user=user)
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        for course in context['courses']:
            total_lessons = Lesson.objects.filter(module__course=course).count()
            completed_lessons = UserProgress.objects.filter(
                user=user,
                lesson__module__course=course,
                is_completed=True,
            ).count()
            course.total_lessons_count = total_lessons
            course.completed_lessons_count = completed_lessons
            course.progress = int((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0

        sub = user.subscription_type or 'free'
        context['user_xp'] = total_xp
        context['available_xp'] = available_xp
        context['streak'] = streak_obj
        context['daily_quests'] = _build_daily_quests(user, activity)
        context['can_claim_bonus'] = (user.last_bonus_claimed != today)
        context['course_cost'] = int(ECONOMY_CONFIG['course_cost'].get(sub, Decimal('10.00')))
        context['course_limit'] = ECONOMY_CONFIG['course_limit'].get(sub, 2)
        context['created_courses_count'] = Course.objects.filter(creator=user).count()
        context['certificates_count'] = Certificate.objects.filter(user=user).count()
        return context


class ExploreCoursesWebView(LoginRequiredMixin, TemplateView):
    template_name = 'explore.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        sub = user.subscription_type or 'free'

        courses_qs = Course.objects.annotate(
            star_count=Count('stars', distinct=True),
            lessons_count=Count('modules__lessons', distinct=True),
        ).select_related('creator')

        search_query = self.request.GET.get('search', '').strip()
        lang_query = self.request.GET.get('language', '').strip()
        category_query = self.request.GET.get('category', '').strip()

        if search_query:
            courses_qs = courses_qs.filter(title__icontains=search_query)
        if lang_query:
            courses_qs = courses_qs.filter(language=lang_query)
        if category_query:
            courses_qs = courses_qs.filter(category=category_query)

        courses_qs = courses_qs.order_by('-star_count', '-created_at')

        page_obj = None
        if sub == 'free':
            courses = courses_qs[:10]
        elif sub == 'pro':
            courses = courses_qs[:25]
        else:
            paginator = Paginator(courses_qs, 12)
            page_obj = paginator.get_page(self.request.GET.get('page', 1))
            courses = page_obj.object_list

        context['explore_courses'] = courses
        context['page_obj'] = page_obj
        context['starred_ids'] = set(CourseStar.objects.filter(user=user).values_list('course_id', flat=True))
        context['enrolled_ids'] = set(UserCourse.objects.filter(user=user).values_list('course_id', flat=True))
        context['search_query'] = search_query
        context['lang_query'] = lang_query
        context['category_query'] = category_query
        context['user_xp'] = get_user_xp(user)
        return context


@login_required
@require_POST
def explore_star_web(request, course_id):
    user = request.user
    if user.subscription_type == 'free':
        return JsonResponse({'error': "Yulduzcha bosish PRO/ULTRA tarifida ishlaydi."}, status=403)
    course = get_object_or_404(Course, id=course_id)
    existing = CourseStar.objects.filter(user=user, course=course).first()
    if existing:
        existing.delete()
        starred = False
    else:
        CourseStar.objects.create(user=user, course=course)
        starred = True
    return JsonResponse({'success': True, 'starred': starred, 'star_count': CourseStar.objects.filter(course=course).count()})


@login_required
@require_POST
def explore_enroll_web(request, course_id):
    user = request.user
    sub = user.subscription_type or 'free'
    if sub == 'free':
        return JsonResponse({'error': "Jamoa kurslariga qo'shilish uchun PRO yoki ULTRA tarifi kerak."}, status=403)
    course = get_object_or_404(Course, id=course_id)
    if sub == 'pro':
        top_25_ids = list(Course.objects.annotate(sc=Count('stars')).order_by('-sc')[:25].values_list('id', flat=True))
        if course.id not in top_25_ids and course.creator != user:
            return JsonResponse({'error': "PRO tarifi Top-25 kurslarni saqlay oladi. Barchasi uchun ULTRA kerak."}, status=403)

    enroll_record = UserCourse.objects.filter(user=user, course=course).first()
    if enroll_record:
        enroll_record.delete()
        enrolled = False
    else:
        limit = ECONOMY_CONFIG['course_limit'].get(sub, 15)
        if UserCourse.objects.filter(user=user).count() >= limit:
            return JsonResponse({'error': f"{sub.upper()} saqlangan kurslar limiti ({limit}) to'ldi."}, status=400)
        UserCourse.objects.create(user=user, course=course)
        enrolled = True

    cache.delete(f"courses_list_v2_{user.id}")
    return JsonResponse({'success': True, 'enrolled': enrolled})


class CourseDetailView(LoginRequiredMixin, DetailView):
    model = Course
    template_name = 'course_detail.html'
    context_object_name = 'course'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        course = self.object

        is_enrolled = UserCourse.objects.filter(user=user, course=course).exists()
        is_preview = (not is_enrolled and course.creator_id != user.id)

        completed_ids = set(
            UserProgress.objects.filter(user=user, lesson__module__course=course, is_completed=True)
            .values_list('lesson_id', flat=True)
        )

        modules = list(course.modules.prefetch_related('lessons').order_by('order'))
        total_lessons = 0
        done_lessons = 0
        first_seen = False
        prev_completed = True

        for mod in modules:
            lessons_list = list(mod.lessons.order_by('order'))
            for les in lessons_list:
                total_lessons += 1
                les.user_done = les.id in completed_ids
                if les.user_done:
                    done_lessons += 1
                if is_preview and first_seen:
                    les.is_locked = True
                    les.prerequisite_locked = False
                else:
                    unlocked = prev_completed
                    les.is_locked = not unlocked
                    les.prerequisite_locked = not unlocked
                first_seen = True
                prev_completed = les.user_done
            mod.ordered_lessons = lessons_list

        context['modules'] = modules
        context['completed_lesson_ids'] = completed_ids
        context['is_preview'] = is_preview
        context['is_enrolled'] = is_enrolled
        context['total_lessons'] = total_lessons
        context['done_lessons'] = done_lessons
        context['progress_percent'] = int((done_lessons / total_lessons) * 100) if total_lessons > 0 else 0
        context['user_xp'] = get_user_xp(user)
        context['is_completed'] = total_lessons > 0 and done_lessons >= total_lessons
        return context


class LessonView(LoginRequiredMixin, DetailView):
    model = Lesson
    template_name = 'lesson.html'
    context_object_name = 'lesson'

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        course = obj.module.course
        user = request.user

        ordered_lessons = list(
            Lesson.objects.filter(module__course=course)
            .order_by('module__order', 'order')
            .values_list('id', flat=True)
        )

        if obj.id in ordered_lessons:
            idx = ordered_lessons.index(obj.id)
            if idx > 0:
                prev_id = ordered_lessons[idx - 1]
                if not UserProgress.objects.filter(user=user, lesson_id=prev_id, is_completed=True).exists():
                    messages.warning(
                        request,
                        "Keyingi darsga o'tish uchun avval oldingi darsni tugatishingiz kerak!",
                    )
                    return redirect('course_detail', pk=course.id)

        self.object = obj
        context = self.get_context_data(object=obj, ordered_lessons=ordered_lessons)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        ordered_lessons = kwargs.pop('ordered_lessons', None)
        context = super().get_context_data(**kwargs)
        obj = self.object
        course = obj.module.course
        user = self.request.user
        sub = getattr(user, 'subscription_type', 'free') or 'free'

        if len(obj.content.strip()) < 80 or not obj.quizzes.exists() or not obj.interactive_data:
            obj = get_or_generate_lesson_content(obj, course.language, tier=sub)
            self.object = obj
            context['lesson'] = obj

        if ordered_lessons is None:
            ordered_lessons = list(
                Lesson.objects.filter(module__course=course)
                .order_by('module__order', 'order')
                .values_list('id', flat=True)
            )

        prev_lesson = None
        next_lesson = None
        if obj.id in ordered_lessons:
            idx = ordered_lessons.index(obj.id)
            if idx > 0:
                prev_lesson = Lesson.objects.filter(id=ordered_lessons[idx - 1]).first()
            if idx + 1 < len(ordered_lessons):
                next_lesson = Lesson.objects.filter(id=ordered_lessons[idx + 1]).first()

        # Strictly pre-warm ONLY the immediate next lesson once this lesson is actually opened
        if next_lesson and (len(next_lesson.content.strip()) < 80 or not next_lesson.interactive_data):
            _schedule_single_lesson_prewarm(next_lesson.id, course.language, sub)

        progress = UserProgress.objects.filter(user=user, lesson=obj).first()
        completed_quizzes = set(progress.completed_quizzes or []) if progress else set()

        interactive = obj.interactive_data or {}
        context['visual_diagram'] = interactive.get('visual_diagram') or {}
        context['flashcards'] = interactive.get('flashcards') or []
        context['practice_lab'] = interactive.get('practice_lab') or {}
        context['quizzes'] = list(obj.quizzes.all())
        context['solved_quiz_ids'] = [q for q in completed_quizzes if isinstance(q, int) and q > 0]
        context['lab_passed'] = (-1 in completed_quizzes)
        context['is_completed'] = bool(progress and progress.is_completed)
        context['previous_lesson'] = prev_lesson
        context['next_lesson'] = next_lesson
        context['user_xp'] = get_user_xp(user)
        context['lab_cost'] = int(ECONOMY_CONFIG['lab_eval_cost'].get(sub, Decimal('2.00')))
        return context


@login_required
@require_POST
def submit_quiz(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    quiz_id = request.POST.get('quiz_id')
    selected_option = request.POST.get('option')

    is_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')

    if not quiz_id or not selected_option:
        if is_json:
            return JsonResponse({'error': "Iltimos, variantlardan birini tanlang."}, status=400)
        return HttpResponse('<div class="text-red-500">Variantni tanlang.</div>')

    quiz = get_object_or_404(Quiz, id=quiz_id, lesson=lesson)
    user = request.user
    course = lesson.module.course
    is_correct = (selected_option == quiz.correct_answer)

    progress, _ = UserProgress.objects.get_or_create(user=user, lesson=lesson)
    was_completed = progress.is_completed
    xp_gained = 0
    today = timezone.localdate()
    activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

    if is_correct and quiz.id not in (progress.completed_quizzes or []):
        xp_gained = 10
        progress.score += xp_gained
        comp = list(progress.completed_quizzes or [])
        comp.append(quiz.id)
        progress.completed_quizzes = comp
        activity.quizzes_correct += 1

    solved_quizzes = [qid for qid in (progress.completed_quizzes or []) if isinstance(qid, int) and qid > 0]
    total_quizzes = Quiz.objects.filter(lesson=lesson).count()

    lesson_just_completed = False
    course_completed_bonus = False
    if total_quizzes == 0 or len(solved_quizzes) >= total_quizzes:
        progress.is_completed = True
        if not was_completed:
            lesson_just_completed = True
            xp_gained += 15
            progress.score += 15
            activity.lessons_completed += 1

            all_course_lessons = Lesson.objects.filter(module__course=course).count()
            done_course_lessons = UserProgress.objects.filter(
                user=user, lesson__module__course=course, is_completed=True
            ).count() + 1
            if all_course_lessons > 0 and done_course_lessons >= all_course_lessons:
                user.energy = Decimal(str(user.energy)) + Decimal('15.00')
                user.save(update_fields=['energy'])
                course_completed_bonus = True

    progress.save()
    activity.save()

    streak, _ = UserStreak.objects.get_or_create(user=user)
    streak.update_streak()
    cache.delete(f"courses_list_v2_{user.id}")
    cache.delete('api_leaderboard_cache')

    if is_json:
        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'correct_answer': quiz.correct_answer,
            'explanation': quiz.explanation or "",
            'xp_gained': xp_gained,
            'total_xp': get_user_xp(user),
            'lesson_completed': progress.is_completed,
            'lesson_just_completed': lesson_just_completed,
            'course_completed_bonus': course_completed_bonus,
            'current_energy': float(user.energy),
            'current_streak': streak.current_streak,
        })

    ordered_ids = list(
        Lesson.objects.filter(module__course=course).order_by('module__order', 'order').values_list('id', flat=True)
    )
    next_lesson = None
    if lesson.id in ordered_ids:
        i = ordered_ids.index(lesson.id)
        if i + 1 < len(ordered_ids):
            next_lesson = Lesson.objects.filter(id=ordered_ids[i + 1]).first()

    return render(request, 'partials/quiz_result.html', {
        'success': is_correct,
        'correct_answer': quiz.correct_answer,
        'lesson': lesson,
        'quiz': quiz,
        'xp_gained': xp_gained,
        'lesson_completed': progress.is_completed,
        'next_lesson': next_lesson,
    })


@login_required
@require_POST
def evaluate_practice_web(request, lesson_id):
    user = request.user
    sub = user.subscription_type or 'free'
    if sub == 'free':
        return JsonResponse(
            {'error': "Amaliyot Lab PRO yoki ULTRA tarifida ishlaydi."},
            status=403,
        )

    submission = (request.POST.get('submission') or '').strip()
    if not submission:
        return JsonResponse({'error': "Avval kodingiz yoki javobingizni yozing."}, status=400)

    lesson = get_object_or_404(Lesson, id=lesson_id)
    cost = ECONOMY_CONFIG['lab_eval_cost'].get(sub, Decimal('2.00'))
    if Decimal(str(user.energy)) < cost:
        return JsonResponse({'error': f"Energiya yetarli emas! Tekshirish narxi {int(cost)}⚡."}, status=400)

    if cost > 0:
        user.energy = Decimal(str(user.energy)) - cost
        user.save(update_fields=['energy'])

    try:
        result = evaluate_practice_submission(lesson, submission, user.preferred_language)
    except Exception as e:
        if cost > 0:
            user.energy = Decimal(str(user.energy)) + cost
            user.save(update_fields=['energy'])
        return JsonResponse({'error': f'Tekshirishda xatolik: {e}'}, status=500)

    xp_gained = 0
    if result.get('is_passed'):
        progress, _ = UserProgress.objects.get_or_create(user=user, lesson=lesson)
        comp = list(progress.completed_quizzes or [])
        if -1 not in comp:
            comp.append(-1)
            progress.completed_quizzes = comp
            progress.score += 15
            progress.save()
            xp_gained = 15

        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)
        activity.practice_completed += 1
        activity.save()

        streak, _ = UserStreak.objects.get_or_create(user=user)
        streak.update_streak()
        cache.delete('api_leaderboard_cache')

    result['xp_gained'] = xp_gained
    result['current_energy'] = float(user.energy)
    return JsonResponse(result)


@login_required
@require_POST
def lesson_chatbot(request, lesson_id):
    """Lesson AI Tutor powered by core.services.ask_lesson_tutor (supports uz, kaa, ru, en)."""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    question = request.POST.get('message', '').strip()
    if not question:
        return JsonResponse({'error': "Savol yozing."}, status=400)

    user = request.user
    sub = user.subscription_type or 'free'
    cost = ECONOMY_CONFIG['chat_cost']
    if Decimal(str(user.energy)) < cost:
        return JsonResponse({'error': f"Energiya yetarli emas! ({int(cost)}⚡ kerak)"}, status=400)

    try:
        reply = ask_lesson_tutor(lesson, question, lesson.module.course.language, tier=sub)
        if cost > 0:
            user.energy = Decimal(str(user.energy)) - cost
            user.save(update_fields=['energy'])
        return JsonResponse({'reply': reply, 'current_energy': float(user.energy)})
    except Exception as e:
        return JsonResponse({'error': f'AI xatoligi: {e}'}, status=500)


class BlitzReviewWebView(LoginRequiredMixin, TemplateView):
    template_name = 'blitz.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        enrolled_ids = list(UserCourse.objects.filter(user=user).values_list('course_id', flat=True))
        quizzes_qs = Quiz.objects.select_related('lesson__module__course').filter(
            lesson__module__course_id__in=enrolled_ids
        )
        if not quizzes_qs.exists():
            quizzes_qs = Quiz.objects.select_related('lesson__module__course').filter(
                lesson__module__course__language=user.preferred_language
            )[:25]
            if not quizzes_qs.exists():
                quizzes_qs = Quiz.objects.select_related('lesson__module__course').all()[:25]

        solved_ids = set()
        for prog in UserProgress.objects.filter(user=user).only('completed_quizzes'):
            for qid in (prog.completed_quizzes or []):
                if isinstance(qid, int) and qid > 0:
                    solved_ids.add(qid)

        unsolved, solved = [], []
        for q in quizzes_qs[:80]:
            item = {
                'id': q.id,
                'question': q.question,
                'options': q.options,
                'correct_answer': q.correct_answer,
                'explanation': q.explanation or '',
                'lesson_title': q.lesson.title,
                'course_title': q.lesson.module.course.title,
                'is_review': q.id in solved_ids,
            }
            (solved if q.id in solved_ids else unsolved).append(item)

        random.shuffle(unsolved)
        random.shuffle(solved)
        deck = (unsolved[:6] + solved[:4])[:8]
        context['deck_json'] = json.dumps(deck)
        context['total_available'] = len(unsolved) + len(solved)
        context['user_xp'] = get_user_xp(user)
        return context

    def post(self, request):
        user = request.user
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            payload = {}
        correct_count = max(0, min(20, int(payload.get('correct_count', 0))))
        solved_quiz_ids = payload.get('solved_quiz_ids', [])

        xp_earned = correct_count * 5
        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        if isinstance(solved_quiz_ids, list) and solved_quiz_ids:
            for q in Quiz.objects.filter(id__in=solved_quiz_ids).select_related('lesson'):
                prog, _ = UserProgress.objects.get_or_create(user=user, lesson=q.lesson)
                comp = list(prog.completed_quizzes or [])
                if q.id not in comp:
                    comp.append(q.id)
                    prog.completed_quizzes = comp
                    prog.save(update_fields=['completed_quizzes'])

        if xp_earned > 0:
            user.bonus_xp += xp_earned
            user.save(update_fields=['bonus_xp'])
            activity.quizzes_correct += correct_count
            activity.save(update_fields=['quizzes_correct'])

        streak, _ = UserStreak.objects.get_or_create(user=user)
        streak.update_streak()
        cache.delete('api_leaderboard_cache')

        total_xp, _ = _get_total_xp(user)
        return JsonResponse({
            'success': True,
            'xp_earned': xp_earned,
            'total_xp': total_xp,
            'current_streak': streak.current_streak,
        })


class LeaderboardView(LoginRequiredMixin, TemplateView):
    template_name = 'leaderboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        users = (
            User.objects.annotate(progress_xp=Coalesce(Sum('progress__score'), Value(0)))
            .annotate(total_xp=F('progress_xp') + F('bonus_xp'))
            .filter(total_xp__gt=0)
            .select_related('streak')
            .order_by('-total_xp')[:50]
        )

        leaderboard_list = []
        for idx, u in enumerate(users, start=1):
            streak_val = u.streak.current_streak if hasattr(u, 'streak') and u.streak else 0
            leaderboard_list.append({
                'rank': idx,
                'user': u,
                'total_xp': u.total_xp,
                'league': self.get_league(u.total_xp),
                'streak': streak_val,
                'is_current_user': u.id == self.request.user.id,
            })

        current_user_xp = get_user_xp(self.request.user)
        if current_user_xp < 100:
            xp_to_next = 100 - current_user_xp
        elif current_user_xp < 500:
            xp_to_next = 500 - current_user_xp
        elif current_user_xp < 1000:
            xp_to_next = 1000 - current_user_xp
        else:
            xp_to_next = 0

        context['leaderboard'] = leaderboard_list
        context['current_user_xp'] = current_user_xp
        context['current_user_league'] = self.get_league(current_user_xp)
        context['xp_to_next_league'] = xp_to_next
        return context

    def get_league(self, xp):
        if xp >= 1000:
            return 'Gold'
        if xp >= 500:
            return 'Silver'
        if xp >= 100:
            return 'Bronze'
        return 'Beginner'


class ProfileWebView(LoginRequiredMixin, TemplateView):
    template_name = 'profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        total_xp, available_xp = _get_total_xp(user)
        streak, _ = UserStreak.objects.get_or_create(user=user)
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        context['total_xp'] = total_xp
        context['available_xp'] = available_xp
        context['xp_redeem_cost'] = ECONOMY_CONFIG['xp_redeem_cost']
        context['xp_redeem_reward'] = int(ECONOMY_CONFIG['xp_redeem_reward'])
        context['streak'] = streak
        context['courses_count'] = UserCourse.objects.filter(user=user).count()
        context['certificates'] = Certificate.objects.filter(user=user).select_related('course').order_by('-issued_at')
        context['daily_quests'] = _build_daily_quests(user, activity)
        context['can_claim_bonus'] = (user.last_bonus_claimed != today)
        return context

    def post(self, request):
        user = request.user
        user.first_name = (request.POST.get('first_name') or '').strip()[:30]
        user.last_name = (request.POST.get('last_name') or '').strip()[:30]
        user.email = (request.POST.get('email') or '').strip()
        lang = request.POST.get('preferred_language')
        if lang in ('uz', 'kaa', 'ru', 'en'):
            user.preferred_language = lang
            translation.activate(lang)
            request.session['_language'] = lang
        user.save()
        messages.success(request, "Profil ma'lumotlari saqlandi!")
        return redirect('profile_web')


@login_required
@require_POST
def claim_bonus_web(request):
    user = request.user
    today = timezone.localdate()
    if user.last_bonus_claimed == today:
        return JsonResponse({'error': "Bugungi bonus allaqachon olingan."}, status=400)

    streak, _ = UserStreak.objects.get_or_create(user=user)
    streak.update_streak()
    is_weekly = (streak.current_streak > 0 and streak.current_streak % 7 == 0)
    amount = ECONOMY_CONFIG['daily_bonus_streak_7'] if is_weekly else ECONOMY_CONFIG['daily_bonus_base']

    user.last_bonus_claimed = today
    user.energy = Decimal(str(user.energy)) + amount
    user.save(update_fields=['last_bonus_claimed', 'energy'])
    return JsonResponse({
        'success': True,
        'message': f"Kunlik bonus olindi! +{int(amount)}⚡",
        'current_energy': float(user.energy),
        'current_streak': streak.current_streak,
    })


@login_required
@require_POST
def claim_quest_web(request):
    user = request.user
    quest_key = request.POST.get('quest_key', '').strip()
    today = timezone.localdate()
    activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)
    quests = {q['key']: q for q in _build_daily_quests(user, activity)}
    quest = quests.get(quest_key)
    if not quest:
        return JsonResponse({'error': "Noto'g'ri topshiriq."}, status=400)
    if not quest['completed']:
        return JsonResponse({'error': "Topshiriq hali bajarilmagan."}, status=400)
    if quest['claimed']:
        return JsonResponse({'error': "Mukofot allaqachon olingan."}, status=400)

    claimed = list(activity.claimed_quests or [])
    claimed.append(quest_key)
    activity.claimed_quests = claimed
    activity.save(update_fields=['claimed_quests'])

    user.energy = Decimal(str(user.energy)) + Decimal(str(quest['reward_energy']))
    user.bonus_xp += int(quest['reward_xp'])
    user.save(update_fields=['energy', 'bonus_xp'])
    cache.delete('api_leaderboard_cache')

    return JsonResponse({
        'success': True,
        'message': f"+{quest['reward_energy']}⚡ va +{quest['reward_xp']} XP qo'shildi!",
        'current_energy': float(user.energy),
        'total_xp': get_user_xp(user),
    })


@login_required
@require_POST
def redeem_xp_web(request):
    user = request.user
    total_xp, available_xp = _get_total_xp(user)
    cost_xp = ECONOMY_CONFIG['xp_redeem_cost']
    reward = ECONOMY_CONFIG['xp_redeem_reward']
    if available_xp < cost_xp:
        return JsonResponse({'error': f"Kamida {cost_xp} XP kerak (sizda: {available_xp} XP)."}, status=400)

    user.redeemed_xp += cost_xp
    user.energy = Decimal(str(user.energy)) + reward
    user.save(update_fields=['redeemed_xp', 'energy'])
    return JsonResponse({
        'success': True,
        'message': f"{cost_xp} XP → +{int(reward)}⚡ Energiyaga almashtirildi!",
        'current_energy': float(user.energy),
        'available_xp': available_xp - cost_xp,
    })


class GamificationView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect('profile_web')


@login_required
def download_certificate(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_completed(request.user, course):
        return HttpResponse("Sertifikat olish uchun kursdagi barcha darslarni tugating.", status=403)
    Certificate.objects.get_or_create(user=request.user, course=course)
    pdf = generate_certificate(request.user, course)
    response = HttpResponse(pdf, content_type='application/pdf')
    filename = f"Certificate_{course.title.replace(' ', '_')}_{request.user.username}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@require_POST
def change_language(request):
    language_code = request.POST.get('language')
    valid_languages = [lang[0] for lang in settings.LANGUAGES]
    if language_code not in valid_languages:
        return JsonResponse({'error': 'Invalid language code'}, status=400)

    if request.user.is_authenticated:
        request.user.preferred_language = language_code
        request.user.save(update_fields=['preferred_language'])

    translation.activate(language_code)
    request.session['_language'] = language_code
    resp = JsonResponse({'success': True, 'language': language_code})
    resp.set_cookie(settings.LANGUAGE_COOKIE_NAME, language_code)
    return resp


@login_required
def check_task_status(request, task_id):
    from celery.result import AsyncResult

    task = AsyncResult(task_id)
    response_data = {'task_id': task_id, 'status': task.state}

    if task.state == 'PENDING':
        response_data['message'] = 'Navbatda kutilmoqda...'
    elif task.state == 'STARTED':
        response_data['message'] = 'AI kurs yaratmoqda...'
    elif task.state == 'SUCCESS':
        result = task.result or {}
        course_id = result.get('course_id')
        response_data['message'] = result.get('message', 'Kurs tayyor!')
        response_data['course_id'] = course_id
        response_data['title'] = result.get('title')
        response_data['redirect_url'] = f'/course/{course_id}/' if course_id else '/dashboard/'
    elif task.state == 'FAILURE':
        response_data['message'] = f'Xatolik: {str(task.info)}'
        response_data['error'] = True
    else:
        response_data['message'] = f'Holat: {task.state}'

    return JsonResponse(response_data)


@login_required
@require_POST
def clear_chat_history(request):
    try:
        ChatMessage.objects.filter(user=request.user).delete()
        return JsonResponse({'success': True, 'message': 'Chat tarixi tozalandi!'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def _resolve_legal_lang(request):
    lang = (request.GET.get('lang') or '').lower()
    if lang in ('en', 'uz', 'ru'):
        return lang
    current = (translation.get_language() or 'en').split('-')[0].lower()
    if current in ('uz', 'ru'):
        return current
    return 'en'


class PrivacyPolicyView(TemplateView):
    template_name = 'privacy_policy.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['page_lang'] = _resolve_legal_lang(self.request)
        ctx['active_tab'] = 'privacy'
        return ctx


class TermsOfUseView(TemplateView):
    template_name = 'terms.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['page_lang'] = _resolve_legal_lang(self.request)
        ctx['active_tab'] = 'terms'
        return ctx


class SupportView(TemplateView):
    template_name = 'support.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['page_lang'] = _resolve_legal_lang(self.request)
        ctx['active_tab'] = 'support'
        return ctx


class AccountDeletionWebView(View):
    template_name = 'delete_account.html'

    def get(self, request):
        return render(request, self.template_name, {
            'page_lang': _resolve_legal_lang(request),
            'active_tab': 'delete',
        })

    def post(self, request):
        page_lang = _resolve_legal_lang(request)
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        confirm = request.POST.get('confirm_delete') == 'yes'

        if not confirm:
            msg = {
                'uz': "Iltimos, o'chirish roziligini tasdiqlang.",
                'ru': 'Пожалуйста, подтвердите согласие на удаление.',
                'en': 'Please confirm that you want to permanently delete your account.',
            }[page_lang]
            return render(request, self.template_name, {
                'page_lang': page_lang,
                'active_tab': 'delete',
                'error_message': msg,
            })

        lookup_username = username
        if username and not User.objects.filter(username=username).exists():
            match = User.objects.filter(username__iexact=username).first()
            if match:
                lookup_username = match.username
        user = authenticate(request, username=lookup_username, password=password)
        if not user:
            msg = {
                'uz': "Foydalanuvchi nomi yoki parol noto'g'ri.",
                'ru': 'Неверное имя пользователя или пароль.',
                'en': 'Invalid username or password.',
            }[page_lang]
            return render(request, self.template_name, {
                'page_lang': page_lang,
                'active_tab': 'delete',
                'error_message': msg,
            })

        deleted_username = user.username
        user_id = user.id
        if request.user.is_authenticated and request.user.id == user_id:
            logout(request)
        with transaction.atomic():
            cache.delete(f"courses_list_v2_{user_id}")
            cache.delete('api_leaderboard_cache')
            user.delete()

        return render(request, self.template_name, {
            'page_lang': page_lang,
            'active_tab': 'delete',
            'deleted_success': True,
            'deleted_username': deleted_username,
        })
