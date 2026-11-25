import base64
import os
import re
import json
import secrets
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.db.models import Sum, Count, Prefetch, F, Value
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.http import StreamingHttpResponse
from rest_framework import viewsets, views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from core.models import (
    Course, Module, Lesson, Quiz, UserProgress,
    UserCourse, ChatMessage, UserStreak, CourseStar,
    Certificate, DailyActivity, PlayPurchase, PasswordResetCode
)
from core.billing import sync_user_subscription_status
from core.api.serializers import (
    CaseInsensitiveTokenObtainPairSerializer,
    UserSerializer, CourseSerializer, CourseListSerializer,
    LessonSerializer, ChatMessageSerializer, UserStreakSerializer,
    CertificateSerializer
)
from core.services import (
    ECONOMY_CONFIG,
    chatbot_response,
    chatbot_response_stream,
    generate_course_from_ai,
    get_or_generate_lesson_content,
    evaluate_practice_submission,
    ask_lesson_tutor,
    _schedule_single_lesson_prewarm,
    extract_text_from_pdf,
)

User = get_user_model()


def _get_total_xp(user) -> tuple[int, int]:
    progress_xp = UserProgress.objects.filter(user=user).aggregate(Sum('score'))['score__sum'] or 0
    total_xp = int(progress_xp) + int(user.bonus_xp)
    available_xp = max(0, total_xp - int(user.redeemed_xp))
    return total_xp, available_xp


def _build_daily_quests(user, activity: DailyActivity) -> list[dict]:
    claimed = set(activity.claimed_quests or [])
    return [
        {
            'key': 'daily_lesson',
            'title': 'Complete 1 Lesson',
            'progress': min(activity.lessons_completed, 1),
            'target': 1,
            'reward_energy': 3,
            'reward_xp': 25,
            'completed': activity.lessons_completed >= 1,
            'claimed': 'daily_lesson' in claimed,
        },
        {
            'key': 'daily_quiz',
            'title': 'Answer 3 Quizzes Correctly',
            'progress': min(activity.quizzes_correct, 3),
            'target': 3,
            'reward_energy': 4,
            'reward_xp': 35,
            'completed': activity.quizzes_correct >= 3,
            'claimed': 'daily_quiz' in claimed,
        },
        {
            'key': 'daily_chat',
            'title': 'Ask AI Tutor 2 Questions',
            'progress': min(activity.chats_sent, 2),
            'target': 2,
            'reward_energy': 2,
            'reward_xp': 15,
            'completed': activity.chats_sent >= 2,
            'claimed': 'daily_chat' in claimed,
        },
    ]


# --- Auth & Profile ---
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView


class CaseInsensitiveTokenObtainPairView(BaseTokenObtainPairView):
    serializer_class = CaseInsensitiveTokenObtainPairSerializer
    throttle_scope = 'auth_sensitive'


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = UserSerializer
    throttle_scope = 'auth_sensitive'


class UserProfileView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        sync_user_subscription_status(user)
        serializer = UserSerializer(user)
        streak, _ = UserStreak.objects.get_or_create(user=user)
        streak_data = UserStreakSerializer(streak).data
        total_xp, available_xp = _get_total_xp(user)

        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        completed_lessons = UserProgress.objects.filter(user=user, is_completed=True).count()
        certificates_count = Certificate.objects.filter(user=user).count()

        sub = user.subscription_type or 'free'
        economy_payload = {
            'chat_cost': float(ECONOMY_CONFIG['chat_cost']),
            'course_cost': float(ECONOMY_CONFIG['course_cost'].get(sub, Decimal('15.00'))),
            'pdf_cost': float(ECONOMY_CONFIG['pdf_cost']),
            'lab_eval_cost': float(ECONOMY_CONFIG['lab_eval_cost'].get(sub, Decimal('2.00'))),
            'lesson_ask_cost': float(ECONOMY_CONFIG['lesson_ask_cost'].get(sub, Decimal('1.00'))),
            'xp_redeem_cost': ECONOMY_CONFIG['xp_redeem_cost'],
            'xp_redeem_reward': float(ECONOMY_CONFIG['xp_redeem_reward']),
            'daily_bonus': float(
                ECONOMY_CONFIG['daily_bonus_streak_7']
                if (streak.current_streak > 0 and streak.current_streak % 7 == 6)
                else ECONOMY_CONFIG['daily_bonus_base']
            ),
            'course_limit': ECONOMY_CONFIG['course_limit'].get(sub, 2),
            'pricing': ECONOMY_CONFIG['pricing'],
        }

        data = serializer.data
        data['streak'] = streak_data
        data['xp'] = total_xp
        data['available_xp'] = available_xp
        data['economy'] = economy_payload
        data['daily_quests'] = _build_daily_quests(user, activity)
        data['stats'] = {
            'completed_lessons': completed_lessons,
            'certificates_count': certificates_count,
            'chats_today': activity.chats_sent,
            'practice_today': activity.practice_completed,
        }
        return Response(data)

    def put(self, request):
        user = request.user
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        email = request.data.get('email')
        preferred_language = request.data.get('preferred_language')

        if first_name is not None:
            user.first_name = first_name.strip()
        if last_name is not None:
            user.last_name = last_name.strip()
        if email is not None:
            user.email = email.strip()
        if preferred_language in ('uz', 'en', 'ru', 'kaa'):
            user.preferred_language = preferred_language

        user.save()
        return Response({
            'success': True,
            'message': 'Profile updated successfully',
            'preferred_language': user.preferred_language,
        })


# --- Course & Dashboard ---
class CourseViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CourseSerializer

    def get_serializer_class(self):
        if self.action == 'list':
            return CourseListSerializer
        return CourseSerializer

    def get_queryset(self):
        user = self.request.user
        if self.action == 'list':
            # User dashboard shows their own created or enrolled courses
            queryset = Course.objects.filter(enrolled_users__user=user).distinct()
        else:
            queryset = Course.objects.all()

        return queryset.select_related('creator').prefetch_related(
            'modules',
            'modules__lessons',
            'modules__lessons__quizzes',
            Prefetch(
                'modules__lessons__userprogress_set',
                queryset=UserProgress.objects.filter(user=user),
                to_attr='user_progresses'
            )
        ).order_by('-created_at')

    def list(self, request, *args, **kwargs):
        user = request.user
        cache_key = f"courses_list_v2_{user.id}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        cache.set(cache_key, data, 10)
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        user = request.user
        sync_user_subscription_status(user)

        is_creator = (instance.creator == user)
        is_enrolled = UserCourse.objects.filter(user=user, course=instance).exists()

        top_25_ids = Course.objects.annotate(star_count=Count('stars')).order_by('-star_count')[:25].values_list('id', flat=True)
        is_top_25 = instance.id in top_25_ids

        is_preview = False
        if user.subscription_type == 'free' and not is_creator and not is_enrolled:
            # Allow Free users to preview Lesson 1 of any Explore course instead of blocking completely
            is_preview = True
        elif user.subscription_type == 'pro':
            if not is_creator and not is_enrolled and not is_top_25:
                return Response(
                    {'error': 'PRO users can open enrolled or Top 25 courses. Upgrade to ULTRA for unlimited access.'},
                    status=status.HTTP_403_FORBIDDEN
                )

        serializer = self.get_serializer(instance)
        data = dict(serializer.data)
        data['is_preview'] = is_preview

        first_seen = False
        prev_completed = True  # Lesson 1 is always unlocked
        for mod in data.get('modules', []):
            for les in mod.get('lessons', []):
                if is_preview and first_seen:
                    les['is_locked'] = True
                    les['prerequisite_locked'] = False
                    les['content'] = ''
                    les['quizzes'] = []
                    les['interactive_data'] = {}
                else:
                    unlocked = prev_completed
                    les['is_locked'] = not unlocked
                    les['prerequisite_locked'] = not unlocked
                    if not unlocked:
                        les['content'] = ''
                        les['quizzes'] = []
                        les['interactive_data'] = {}
                first_seen = True
                prev_completed = bool((les.get('user_progress') or {}).get('is_completed', False))
        return Response(data)


class LessonViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LessonSerializer

    def get_queryset(self):
        course_id = self.request.query_params.get('course_id')
        qs = Lesson.objects.select_related('module', 'module__course').prefetch_related('quizzes')
        if course_id:
            return qs.filter(module__course_id=course_id)
        return qs

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        course = instance.module.course
        user = request.user
        sub = getattr(user, 'subscription_type', 'free')

        ordered_lessons = list(
            Lesson.objects.filter(module__course=course)
            .order_by('module__order', 'order')
            .values_list('id', flat=True)
        )
        prev_lesson_id = None
        next_lesson_id = None
        lookahead_lesson_id = None
        if instance.id in ordered_lessons:
            idx = ordered_lessons.index(instance.id)
            if idx > 0:
                prev_lesson_id = ordered_lessons[idx - 1]
                # Enforce sequential mastery: must complete previous lesson before opening this one
                prev_done = UserProgress.objects.filter(
                    user=user, lesson_id=prev_lesson_id, is_completed=True
                ).exists()
                if not prev_done:
                    return Response(
                        {
                            'error': 'Keyingi darsga o\'tish uchun avval oldingi darsni tugatishingiz kerak!',
                            'prerequisite_locked': True,
                            'required_lesson_id': prev_lesson_id,
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
            if idx + 1 < len(ordered_lessons):
                next_lesson_id = ordered_lessons[idx + 1]
            if idx + 2 < len(ordered_lessons):
                lookahead_lesson_id = ordered_lessons[idx + 2]

        # Generate rich content lazily if empty or missing interactive blocks
        if len(instance.content.strip()) < 80 or not instance.quizzes.exists() or not instance.interactive_data:
            instance = get_or_generate_lesson_content(instance, course.language, tier=sub)

        # Lookahead N+2 pre-warming: Lesson 1+2 are generated upfront; opening N triggers N+2 (and N+1 fallback if empty)
        for target_id in (next_lesson_id, lookahead_lesson_id):
            if target_id is not None:
                target_les = Lesson.objects.filter(id=target_id).first()
                if target_les and (len(target_les.content.strip()) < 80 or not target_les.interactive_data):
                    _schedule_single_lesson_prewarm(target_id, course.language, sub)

        serializer = self.get_serializer(instance)
        data = dict(serializer.data)
        data['prev_lesson_id'] = prev_lesson_id
        data['next_lesson_id'] = next_lesson_id
        data['course_id'] = course.id
        data['course_title'] = course.title
        data['module_title'] = instance.module.title
        return Response(data)


class SubmitQuizView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, lesson_id):
        quiz_id = request.data.get('quiz_id')
        selected_option = request.data.get('option')

        if not quiz_id or not selected_option:
            return Response({'error': 'quiz_id and option are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            quiz = Quiz.objects.select_related('lesson__module__course').get(id=quiz_id, lesson_id=lesson_id)
        except Quiz.DoesNotExist:
            return Response({'error': 'Quiz not found'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        lesson = quiz.lesson
        course = lesson.module.course
        is_correct = (selected_option == quiz.correct_answer)

        progress, _ = UserProgress.objects.get_or_create(user=user, lesson=lesson)
        was_completed = progress.is_completed
        xp_gained = 0

        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        if is_correct and quiz_id not in progress.completed_quizzes:
            xp_gained = 10
            progress.score += xp_gained
            completed_list = list(progress.completed_quizzes or [])
            completed_list.append(quiz_id)
            progress.completed_quizzes = completed_list
            activity.quizzes_correct += 1

        # Count real quiz IDs (> 0; negative values reserved for lab XP flag)
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

                # Check if whole course just reached 100% completion
                all_course_lessons = Lesson.objects.filter(module__course=course).count()
                done_course_lessons = UserProgress.objects.filter(
                    user=user, lesson__module__course=course, is_completed=True
                ).count() + 1  # including current just-completed lesson before save
                if all_course_lessons > 0 and done_course_lessons >= all_course_lessons:
                    user.energy = Decimal(str(user.energy)) + Decimal('15.00')
                    user.save(update_fields=['energy'])
                    course_completed_bonus = True

        progress.save()
        activity.save()

        # Update user's daily streak cleanly on learning activity
        streak, _ = UserStreak.objects.get_or_create(user=user)
        streak.update_streak()

        cache.delete(f"courses_list_v2_{user.id}")
        cache.delete('api_leaderboard_cache')

        return Response({
            'success': True,
            'is_correct': is_correct,
            'correct_answer': quiz.correct_answer,
            'explanation': quiz.explanation or "",
            'xp_gained': xp_gained,
            'current_xp': progress.score,
            'lesson_completed': progress.is_completed,
            'lesson_just_completed': lesson_just_completed,
            'course_completed_bonus': course_completed_bonus,
            'current_energy': user.energy,
            'current_streak': streak.current_streak,
            'message': 'Correct answer!' if is_correct else 'Not quite — check the explanation!'
        })


class EvaluatePracticeView(views.APIView):
    """
    PRO & ULTRA Interactive Lab Evaluator:
    Users write code or practice answers inside lessons and receive instant AI feedback + XP.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, lesson_id):
        user = request.user
        sub = user.subscription_type or 'free'

        if sub == 'free':
            return Response(
                {'error': 'Interactive Code & Practice Lab is a PRO / ULTRA feature. Upgrade to unlock hands-on grading!'},
                status=status.HTTP_403_FORBIDDEN
            )

        submission = request.data.get('submission', '').strip()
        if not submission:
            return Response({'error': 'Please enter your code or answer first.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lesson = Lesson.objects.select_related('module__course').get(id=lesson_id)
        except Lesson.DoesNotExist:
            return Response({'error': 'Lesson not found'}, status=status.HTTP_404_NOT_FOUND)

        cost = ECONOMY_CONFIG['lab_eval_cost'].get(sub, Decimal('2.00'))
        if Decimal(str(user.energy)) < cost:
            return Response(
                {'error': f'Not enough Energy! Lab check costs {int(cost)}⚡.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if cost > 0:
            user.energy = Decimal(str(user.energy)) - cost
            user.save(update_fields=['energy'])

        try:
            result = evaluate_practice_submission(lesson, submission, user.preferred_language)
        except Exception as e:
            if cost > 0:
                user.energy = Decimal(str(user.energy)) + cost
                user.save(update_fields=['energy'])
            return Response({'error': f'Evaluation failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        xp_gained = 0
        if result.get('is_passed'):
            progress, _ = UserProgress.objects.get_or_create(user=user, lesson=lesson)
            completed_list = list(progress.completed_quizzes or [])
            if -1 not in completed_list:
                completed_list.append(-1)
                progress.completed_quizzes = completed_list
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
        result['current_energy'] = user.energy
        return Response(result)


class LessonAskAIView(views.APIView):
    """
    Contextual AI Mentor directly inside any lesson.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, lesson_id):
        user = request.user
        sub = user.subscription_type or 'free'
        question = request.data.get('question', '').strip()
        if not question:
            return Response({'error': 'Question is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lesson = Lesson.objects.get(id=lesson_id)
        except Lesson.DoesNotExist:
            return Response({'error': 'Lesson not found'}, status=status.HTTP_404_NOT_FOUND)

        cost = ECONOMY_CONFIG['lesson_ask_cost'].get(sub, Decimal('1.00'))
        if Decimal(str(user.energy)) < cost:
            return Response(
                {'error': f'Not enough Energy! Mentor question costs {int(cost)}⚡.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if cost > 0:
            user.energy = Decimal(str(user.energy)) - cost
            user.save(update_fields=['energy'])

        try:
            answer = ask_lesson_tutor(lesson, question, user.preferred_language)
            return Response({
                'success': True,
                'answer': answer,
                'cost': float(cost),
                'current_energy': user.energy,
            })
        except Exception as e:
            if cost > 0:
                user.energy = Decimal(str(user.energy)) + cost
                user.save(update_fields=['energy'])
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- Chatbot & Generation ---
class ChatbotView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        messages = ChatMessage.objects.filter(user=request.user)
        serializer = ChatMessageSerializer(messages, many=True)
        return Response(serializer.data)

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        # Fair daily limit for free tier (instead of permanent lifetime lock)
        if user.subscription_type == 'free' and activity.chats_sent >= ECONOMY_CONFIG['free_daily_chat_limit']:
            return Response(
                {'error': f"Daily limit of {ECONOMY_CONFIG['free_daily_chat_limit']} messages reached. Upgrade to PRO for unlimited AI tutoring!"},
                status=status.HTTP_400_BAD_REQUEST
            )

        chat_cost = ECONOMY_CONFIG['chat_cost']
        if Decimal(str(user.energy)) < chat_cost:
            return Response(
                {'error': f'Not enough Energy! Chat messages cost {int(chat_cost)}⚡.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_message = request.data.get('message', '').strip()
        if not user_message:
            return Response({'error': 'Message required'}, status=status.HTTP_400_BAD_REQUEST)

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

        return Response({
            'bot_message': bot_reply,
            'topic_clear': topic_clear,
            'topic': topic,
            'current_energy': user.energy
        })


class ChatbotStreamView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        if user.subscription_type == 'free' and activity.chats_sent >= ECONOMY_CONFIG['free_daily_chat_limit']:
            return Response(
                {'error': f"Daily limit of {ECONOMY_CONFIG['free_daily_chat_limit']} messages reached. Upgrade to PRO!"},
                status=status.HTTP_400_BAD_REQUEST
            )

        chat_cost = ECONOMY_CONFIG['chat_cost']
        if Decimal(str(user.energy)) < chat_cost:
            return Response(
                {'error': f'Not enough Energy! Chat messages cost {int(chat_cost)}⚡.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_message = request.data.get('message', '').strip()
        if not user_message:
            return Response({'error': 'Message required'}, status=status.HTTP_400_BAD_REQUEST)

        ChatMessage.objects.create(user=user, message=user_message, is_user=True)
        chat_history = ChatMessage.objects.filter(user=user).order_by('created_at')

        def event_stream():
            collected = []
            for chunk in chatbot_response_stream(user_message, chat_history, user.preferred_language, user=user):
                collected.append(chunk)
                yield f"data: {json.dumps({'delta': chunk})}\n\n"

            full_reply = "".join(collected)
            topic_clear = False
            topic = None
            if 'TOPIC_CLEAR:' in full_reply:
                topic_clear = True
                match = re.search(r'TOPIC_CLEAR:\s*(.+)', full_reply)
                if match:
                    topic = match.group(1).strip()
                    full_reply = re.sub(r'TOPIC_CLEAR:.+', '', full_reply).strip()

            ChatMessage.objects.create(user=user, message=full_reply, is_user=False)
            user.energy = Decimal(str(user.energy)) - chat_cost
            user.save(update_fields=['energy'])
            activity.chats_sent += 1
            activity.save(update_fields=['chats_sent'])
            yield f"data: {json.dumps({'done': True, 'topic_clear': topic_clear, 'topic': topic, 'current_energy': str(user.energy)})}\n\n"

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


class GenerateCourseView(views.APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = 'ai_generation'

    def post(self, request):
        user = request.user
        sync_user_subscription_status(user)
        topic = request.data.get('topic', '').strip()
        difficulty = request.data.get('difficulty', 'beginner').strip().lower()
        if not topic:
            return Response({'error': 'Topic is required'}, status=status.HTTP_400_BAD_REQUEST)

        sub = user.subscription_type or 'free'
        limit = ECONOMY_CONFIG['course_limit'].get(sub, 2)
        created_count = Course.objects.filter(creator=user).count()
        if created_count >= limit:
            return Response(
                {'error': f'{sub.upper()} tier limit ({limit} courses) reached. Upgrade your plan to create more!'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            course = generate_course_from_ai(topic, user.preferred_language, user, difficulty=difficulty)
            cache.delete(f"courses_list_v2_{user.id}")
            return Response({
                'success': True,
                'course_id': course.id,
                'title': course.title,
                'message': 'Course generated successfully',
                'current_energy': user.energy
            })
        except ValueError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UploadPDFCourseView(views.APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = 'ai_generation'

    def post(self, request):
        user = request.user
        sync_user_subscription_status(user)
        if user.subscription_type not in ('pro', 'ultra'):
            return Response({'error': 'PDF course generation requires PRO or ULTRA subscription.'}, status=status.HTTP_403_FORBIDDEN)

        pdf_file = request.FILES.get('pdf')
        if not pdf_file:
            return Response({'error': 'No PDF file provided.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            pdf_text = extract_text_from_pdf(pdf_file)
            if not pdf_text:
                return Response({'error': 'Could not extract text from PDF.'}, status=status.HTTP_400_BAD_REQUEST)

            course = generate_course_from_ai("Custom PDF Course", user.preferred_language, user, pdf_text=pdf_text)
            cache.delete(f"courses_list_v2_{user.id}")
            return Response({
                'success': True,
                'course_id': course.id,
                'title': course.title,
                'message': 'Course generated from PDF successfully',
                'current_energy': user.energy
            })
        except ValueError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ClearChatView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ChatMessage.objects.filter(user=request.user).delete()
        return Response({'success': True})


class ExploreCoursesView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        sub = user.subscription_type or 'free'

        courses_qs = Course.objects.annotate(
            star_count=Count('stars', distinct=True),
            lessons_count=Count('modules__lessons', distinct=True)
        ).select_related('creator')

        search_query = request.query_params.get('search', '').strip()
        lang_query = request.query_params.get('language', '').strip()
        category_query = request.query_params.get('category', '').strip()

        if search_query:
            courses_qs = courses_qs.filter(title__icontains=search_query)
        if lang_query:
            courses_qs = courses_qs.filter(language=lang_query)
        if category_query:
            courses_qs = courses_qs.filter(category=category_query)

        courses_qs = courses_qs.order_by('-star_count', '-created_at')

        if sub == 'free':
            courses = courses_qs[:10]
            total_pages = 1
            current_page = 1
            has_next = False
        elif sub == 'pro':
            courses = courses_qs[:25]
            total_pages = 1
            current_page = 1
            has_next = False
        else:
            paginator = Paginator(courses_qs, 12)
            page_number = request.query_params.get('page', 1)
            try:
                page_obj = paginator.get_page(page_number)
            except Exception:
                return Response({'error': 'Invalid page number'}, status=status.HTTP_400_BAD_REQUEST)
            courses = page_obj.object_list
            total_pages = paginator.num_pages
            current_page = page_obj.number
            has_next = page_obj.has_next()

        starred_course_ids = set(CourseStar.objects.filter(user=user).values_list('course_id', flat=True))
        enrolled_course_ids = set(UserCourse.objects.filter(user=user).values_list('course_id', flat=True))

        data = []
        for course in courses:
            data.append({
                'id': course.id,
                'title': course.title,
                'description': course.description,
                'language': course.language,
                'category': course.category,
                'difficulty': course.difficulty,
                'lessons_count': course.lessons_count,
                'image_url': course.image_url,
                'created_at': course.created_at,
                'creator_username': course.creator.username if course.creator else 'StuDy AI',
                'star_count': course.star_count,
                'is_starred': course.id in starred_course_ids,
                'is_enrolled': course.id in enrolled_course_ids,
            })

        return Response({
            'courses': data,
            'total_pages': total_pages,
            'current_page': current_page,
            'has_next': has_next,
        })


class ToggleStarCourseView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, course_id):
        user = request.user
        if user.subscription_type == 'free':
            return Response({'error': 'PRO subscription required to star courses.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({'error': 'Course not found'}, status=status.HTTP_404_NOT_FOUND)

        star_record = CourseStar.objects.filter(user=user, course=course).first()
        if star_record:
            star_record.delete()
            starred = False
        else:
            CourseStar.objects.create(user=user, course=course)
            starred = True

        star_count = CourseStar.objects.filter(course=course).count()
        return Response({
            'success': True,
            'starred': starred,
            'star_count': star_count
        })


class ToggleEnrollCourseView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, course_id):
        user = request.user
        sub = user.subscription_type or 'free'

        if sub == 'free':
            return Response({'error': 'PRO subscription required to save community courses.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({'error': 'Course not found'}, status=status.HTTP_404_NOT_FOUND)

        if sub == 'pro':
            top_25_ids = Course.objects.annotate(star_count=Count('stars')).order_by('-star_count')[:25].values_list('id', flat=True)
            if course.id not in top_25_ids and course.creator != user:
                return Response({'error': 'PRO subscription can save Top 25 courses. Upgrade to ULTRA for all.'}, status=status.HTTP_403_FORBIDDEN)

        enroll_record = UserCourse.objects.filter(user=user, course=course).first()
        if enroll_record:
            enroll_record.delete()
            enrolled = False
        else:
            limit = ECONOMY_CONFIG['course_limit'].get(sub, 15)
            if UserCourse.objects.filter(user=user).count() >= limit:
                return Response({'error': f'{sub.upper()} saved course limit ({limit}) reached.'}, status=status.HTTP_400_BAD_REQUEST)
            UserCourse.objects.create(user=user, course=course)
            enrolled = True

        cache.delete(f"courses_list_v2_{user.id}")
        return Response({'success': True, 'enrolled': enrolled})


# --- Gamification & Business Model API ---
class LeaderboardView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cached_data = cache.get('api_leaderboard_cache')
        if cached_data is not None:
            return Response(cached_data)

        users = User.objects.annotate(
            progress_xp=Coalesce(Sum('progress__score'), Value(0))
        ).annotate(
            total_xp=F('progress_xp') + F('bonus_xp')
        ).filter(
            total_xp__gt=0
        ).select_related('streak').order_by('-total_xp')[:100]

        data = []
        for u in users:
            streak_val = u.streak.current_streak if hasattr(u, 'streak') and u.streak else 0
            data.append({
                'id': u.id,
                'username': u.username,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'xp': u.total_xp,
                'subscription_type': u.subscription_type,
                'streak': streak_val,
            })

        cache.set('api_leaderboard_cache', data, 15)
        return Response(data)


class RedeemXPView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        total_xp, available_xp = _get_total_xp(user)
        cost_xp = ECONOMY_CONFIG['xp_redeem_cost']
        reward_energy = ECONOMY_CONFIG['xp_redeem_reward']

        if available_xp < cost_xp:
            return Response(
                {'error': f'You need at least {cost_xp} XP to redeem {int(reward_energy)}⚡.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.redeemed_xp += cost_xp
        user.energy = Decimal(str(user.energy)) + reward_energy
        user.save(update_fields=['redeemed_xp', 'energy'])

        return Response({
            'success': True,
            'message': f'Redeemed {cost_xp} XP for +{int(reward_energy)}⚡ Energy!',
            'current_energy': user.energy,
            'available_xp': available_xp - cost_xp
        })


class ClaimDailyBonusView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        today = timezone.localdate()

        if user.last_bonus_claimed == today:
            return Response({'error': 'You have already claimed your daily bonus today.'}, status=status.HTTP_400_BAD_REQUEST)

        streak, _ = UserStreak.objects.get_or_create(user=user)
        streak.update_streak()

        is_weekly_milestone = (streak.current_streak > 0 and streak.current_streak % 7 == 0)
        bonus_amount = ECONOMY_CONFIG['daily_bonus_streak_7'] if is_weekly_milestone else ECONOMY_CONFIG['daily_bonus_base']

        user.last_bonus_claimed = today
        user.energy = Decimal(str(user.energy)) + bonus_amount
        user.save(update_fields=['last_bonus_claimed', 'energy'])

        total_xp, _ = _get_total_xp(user)
        return Response({
            'success': True,
            'message': f"Daily bonus claimed! +{int(bonus_amount)}⚡{' (7-Day Streak Jackpot!)' if is_weekly_milestone else ''}",
            'current_energy': user.energy,
            'current_xp': total_xp,
            'current_streak': streak.current_streak,
        })


class ClaimQuestRewardView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        quest_key = request.data.get('quest_key')
        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        quests = {q['key']: q for q in _build_daily_quests(user, activity)}
        quest = quests.get(quest_key)
        if not quest:
            return Response({'error': 'Invalid quest key.'}, status=status.HTTP_400_BAD_REQUEST)
        if not quest['completed']:
            return Response({'error': 'Quest is not completed yet.'}, status=status.HTTP_400_BAD_REQUEST)
        if quest['claimed']:
            return Response({'error': 'Quest reward already claimed today.'}, status=status.HTTP_400_BAD_REQUEST)

        claimed = list(activity.claimed_quests or [])
        claimed.append(quest_key)
        activity.claimed_quests = claimed
        activity.save(update_fields=['claimed_quests'])

        user.energy = Decimal(str(user.energy)) + Decimal(str(quest['reward_energy']))
        user.bonus_xp += int(quest['reward_xp'])
        user.save(update_fields=['energy', 'bonus_xp'])
        cache.delete('api_leaderboard_cache')

        return Response({
            'success': True,
            'message': f"Quest claimed! +{quest['reward_energy']}⚡ and +{quest['reward_xp']} XP!",
            'current_energy': user.energy,
            'daily_quests': _build_daily_quests(user, activity),
        })


class PurchaseEnergyView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import sys
        from django.conf import settings
        if not settings.DEBUG and 'test' not in sys.argv:
            return Response(
                {'error': 'Direct mock purchases are disabled. Use Google Play Billing.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = request.user
        package = str(request.data.get('package', ''))
        amount = ECONOMY_CONFIG['energy_packs'].get(package)
        if amount is None:
            return Response({'error': 'Invalid package. Choose 50, 180, or 500.'}, status=status.HTTP_400_BAD_REQUEST)

        user.energy = Decimal(str(user.energy)) + amount
        user.save(update_fields=['energy'])

        return Response({
            'success': True,
            'message': f'Successfully added +{int(amount)}⚡ Energy!',
            'current_energy': user.energy
        })


class SubscribeView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import sys
        from django.conf import settings
        if not settings.DEBUG and 'test' not in sys.argv:
            return Response(
                {'error': 'Direct mock subscriptions are disabled. Use Google Play Billing.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = request.user
        plan = request.data.get('plan')
        is_annual = bool(request.data.get('is_annual', False))

        if plan not in ['pro', 'ultra', 'free']:
            return Response({'error': 'Invalid plan'}, status=status.HTTP_400_BAD_REQUEST)

        user.subscription_type = plan
        user.is_annual = is_annual

        grant = ECONOMY_CONFIG['subscription_energy'].get(plan, Decimal('30.00'))
        if Decimal(str(user.energy)) < grant:
            user.energy = grant
        else:
            user.energy = Decimal(str(user.energy)) + (grant if plan != 'free' else Decimal('0.00'))

        user.save(update_fields=['subscription_type', 'is_annual', 'energy'])
        cache.delete(f"courses_list_v2_{user.id}")
        cache.delete('api_leaderboard_cache')

        return Response({
            'success': True,
            'message': f'Successfully activated {plan.upper()}! (+{int(grant)}⚡)',
            'subscription_type': user.subscription_type,
            'current_energy': user.energy
        })


class VerifyGooglePurchaseView(views.APIView):
    """
    Production Google Play Billing receipt verifier.
    Verifies one-time energy packs and subscriptions directly with Google Play Android Publisher API,
    prevents purchaseToken replay, and grants entitlements atomically.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.db import transaction
        from core.billing import (
            BillingConfigError,
            BillingVerificationError,
            PLAY_ONE_TIME_PRODUCTS,
            PLAY_SUBSCRIPTIONS,
            verify_google_play_purchase,
        )

        user = request.user
        product_id = str(request.data.get('product_id', '')).strip()
        purchase_token = str(request.data.get('purchase_token', '')).strip()
        order_id = str(request.data.get('order_id', '')).strip()

        if not product_id or not purchase_token:
            return Response({'error': 'product_id and purchase_token are required.'}, status=status.HTTP_400_BAD_REQUEST)

        existing = PlayPurchase.objects.filter(purchase_token=purchase_token).first()
        if existing:
            if existing.user_id != user.id:
                return Response({'error': 'Purchase token belongs to another account.'}, status=status.HTTP_409_CONFLICT)
            return Response({
                'success': True,
                'already_processed': True,
                'message': 'Purchase already credited.',
                'subscription_type': user.subscription_type,
                'current_energy': user.energy,
            })

        try:
            verified = verify_google_play_purchase(product_id, purchase_token)
        except BillingConfigError as ce:
            return Response({'error': str(ce)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except BillingVerificationError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Verification error: {e}'}, status=status.HTTP_502_BAD_GATEWAY)

        with transaction.atomic():
            if PlayPurchase.objects.filter(purchase_token=purchase_token).exists():
                return Response({
                    'success': True,
                    'already_processed': True,
                    'subscription_type': user.subscription_type,
                    'current_energy': user.energy,
                })

            PlayPurchase.objects.create(
                user=user,
                product_id=product_id,
                purchase_token=purchase_token,
                order_id=verified.get('order_id') or order_id,
                purchase_type=verified['purchase_type'],
                verified=True,
                raw_response=verified.get('raw') or {},
            )

            if product_id in PLAY_ONE_TIME_PRODUCTS:
                amount = PLAY_ONE_TIME_PRODUCTS[product_id]
                user.energy = Decimal(str(user.energy)) + amount
                user.save(update_fields=['energy'])
                msg = f'+{int(amount)}⚡ Energiya hisobingizga qo\'shildi!'
            else:
                plan, is_annual = PLAY_SUBSCRIPTIONS[product_id]
                user.subscription_type = plan
                user.is_annual = is_annual
                user.subscription_expires_at = verified.get('expires_at')
                user.play_purchase_token = purchase_token
                user.last_play_product_id = product_id
                grant = ECONOMY_CONFIG['subscription_energy'].get(plan, Decimal('150.00'))
                user.energy = Decimal(str(user.energy)) + grant
                user.save(update_fields=[
                    'subscription_type', 'is_annual', 'subscription_expires_at',
                    'play_purchase_token', 'last_play_product_id', 'energy'
                ])
                cache.delete(f"courses_list_v2_{user.id}")
                cache.delete('api_leaderboard_cache')
                msg = f'{plan.upper()} obuna faollashtirildi! (+{int(grant)}⚡)'

        return Response({
            'success': True,
            'message': msg,
            'subscription_type': user.subscription_type,
            'current_energy': user.energy,
        })


class CertificateView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, course_id):
        user = request.user
        if user.subscription_type == 'free':
            return Response({'error': 'Certificates are only available for PRO and ULTRA subscribers.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({'error': 'Course not found'}, status=status.HTTP_404_NOT_FOUND)

        lessons = Lesson.objects.filter(module__course=course)
        total_lessons = lessons.count()
        completed_lessons = UserProgress.objects.filter(user=user, lesson__in=lessons, is_completed=True).count()

        if total_lessons == 0 or completed_lessons < total_lessons:
            return Response({
                'completed': False,
                'message': f'Course not complete. Finished {completed_lessons}/{total_lessons} lessons.'
            })

        certificate, _ = Certificate.objects.get_or_create(user=user, course=course)

        return Response({
            'completed': True,
            'certificate_id': certificate.id,
            'issued_at': certificate.issued_at,
            'user': f"{user.first_name} {user.last_name}".strip() or user.username,
            'course_title': course.title
        })


class CertificatesListView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        certs = Certificate.objects.filter(user=request.user).select_related('course').order_by('-issued_at')
        serializer = CertificateSerializer(certs, many=True)
        return Response(serializer.data)


class DeleteAccountView(views.APIView):
    """Google Play Store compliance: allows authenticated user to permanently delete their account."""
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        cache.delete(f"courses_list_v2_{user.id}")
        cache.delete('api_leaderboard_cache')
        user.delete()
        return Response({'success': True, 'message': 'Account deleted permanently.'})


class BlitzReviewView(views.APIView):
    """
    Zero-energy Active Recall & Spaced Repetition Blitz Mode.
    Pulls quizzes from the user's courses (prioritizing unmastered/missed concepts)
    so users retain what they learn instead of creating endless unused courses.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import random
        user = request.user
        enrolled_course_ids = list(
            UserCourse.objects.filter(user=user).values_list('course_id', flat=True)
        )
        quizzes_qs = Quiz.objects.select_related('lesson__module__course').filter(
            lesson__module__course_id__in=enrolled_course_ids
        )

        # If brand new user with no course quizzes yet, offer starter quizzes in preferred language
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

        unsolved = []
        solved = []
        for q in quizzes_qs[:80]:
            item = {
                'id': q.id,
                'lesson_id': q.lesson_id,
                'question': q.question,
                'options': q.options,
                'correct_answer': q.correct_answer,
                'explanation': q.explanation or '',
                'lesson_title': q.lesson.title,
                'course_title': q.lesson.module.course.title,
                'is_review': q.id in solved_ids,
            }
            if q.id in solved_ids:
                solved.append(item)
            else:
                unsolved.append(item)

        random.shuffle(unsolved)
        random.shuffle(solved)
        deck = (unsolved[:6] + solved[:4])[:8]

        return Response({
            'questions': deck,
            'total_available': len(unsolved) + len(solved),
            'energy_cost': 0,
        })

    def post(self, request):
        user = request.user
        correct_count = max(0, min(20, int(request.data.get('correct_count', 0))))
        solved_quiz_ids = request.data.get('solved_quiz_ids', [])

        xp_earned = correct_count * 5
        today = timezone.localdate()
        activity, _ = DailyActivity.objects.get_or_create(user=user, date=today)

        if isinstance(solved_quiz_ids, list) and solved_quiz_ids:
            quizzes = Quiz.objects.filter(id__in=solved_quiz_ids).select_related('lesson')
            for q in quizzes:
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
        return Response({
            'success': True,
            'xp_earned': xp_earned,
            'total_xp': total_xp,
            'current_streak': streak.current_streak,
        })


class GooglePlayRTDNView(views.APIView):
    """
    Google Play Real-time Developer Notifications (Cloud Pub/Sub push endpoint).
    Handles subscription renewals, grace periods, cancellations, revocations, and expirations automatically.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        rtdn_secret = (os.getenv('GOOGLE_PLAY_RTDN_SECRET') or '').strip()
        if rtdn_secret:
            token_param = request.query_params.get('secret') or request.headers.get('X-RTDN-Secret', '')
            if not secrets.compare_digest(token_param, rtdn_secret):
                return Response({'error': 'Unauthorized RTDN origin'}, status=status.HTTP_403_FORBIDDEN)

        msg = request.data.get('message') or {}
        raw_b64 = msg.get('data') or ''
        if not raw_b64:
            return Response({'status': 'ignored'}, status=status.HTTP_200_OK)

        try:
            payload = json.loads(base64.b64decode(raw_b64).decode('utf-8'))
        except Exception:
            return Response({'error': 'Invalid base64 payload'}, status=status.HTTP_400_BAD_REQUEST)

        sub_notif = payload.get('subscriptionNotification') or {}
        purchase_token = (sub_notif.get('purchaseToken') or '').strip()
        subscription_id = (sub_notif.get('subscriptionId') or '').strip()
        notif_type = sub_notif.get('notificationType')

        if not purchase_token:
            return Response({'status': 'ok'}, status=status.HTTP_200_OK)

        user = User.objects.filter(play_purchase_token=purchase_token).first()
        if not user:
            purchase = PlayPurchase.objects.filter(purchase_token=purchase_token).select_related('user').first()
            user = purchase.user if purchase else None

        if not user:
            return Response({'status': 'user_not_found'}, status=status.HTTP_200_OK)

        if subscription_id and user.last_play_product_id != subscription_id:
            user.last_play_product_id = subscription_id
            user.save(update_fields=['last_play_product_id'])

        # Notification types 12 (REVOKED) or 13 (EXPIRED) force immediate downgrade
        if notif_type in (12, 13):
            user.subscription_type = 'free'
            user.is_annual = False
            user.subscription_expires_at = None
            user.save(update_fields=['subscription_type', 'is_annual', 'subscription_expires_at'])
            cache.delete(f"courses_list_v2_{user.id}")
            cache.delete('api_leaderboard_cache')
            return Response({'status': 'downgraded'})

        # Force sync check against Google Play Developer API for renewals/recoveries/restarts
        user.subscription_expires_at = timezone.now() - timedelta(seconds=1)
        sync_user_subscription_status(user)
        return Response({'status': 'synced', 'subscription_type': user.subscription_type})


class PasswordResetRequestView(views.APIView):
    """Generates a 6-digit OTP and sends recovery email to the user's registered address."""
    permission_classes = [AllowAny]
    throttle_scope = 'auth_sensitive'

    def post(self, request):
        identifier = (request.data.get('identifier') or request.data.get('email') or '').strip()
        if not identifier:
            return Response({'error': 'Email yoki username kiriting.'}, status=status.HTTP_400_BAD_REQUEST)

        user = (
            User.objects.filter(email__iexact=identifier).first()
            or User.objects.filter(username__iexact=identifier).first()
        )
        if not user:
            return Response({
                'success': True,
                'message': 'Agar hisob va email mavjud bo\'lsa, 6 xonali tasdiqlash kodi yuborildi.',
            })

        if not user.email:
            return Response(
                {'error': 'Ushbu akkauntga email biriktirilmagan. Yordam markaziga murojaat qiling.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        PasswordResetCode.objects.filter(user=user, is_used=False).update(is_used=True)
        otp = f"{secrets.randbelow(900000) + 100000}"
        PasswordResetCode.objects.create(
            user=user,
            code=otp,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        try:
            send_mail(
                subject='StudyAi — Password Reset Code',
                message=(
                    f"Hi {user.first_name or user.username},\n\n"
                    f"Your StudyAi password reset code is: {otp}\n"
                    f"This code expires in 15 minutes.\n\n"
                    f"If you did not request this, ignore this email."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            return Response(
                {'error': 'Email xizmati vaqtincha ishlamayapti. Keyinroq urinib ko\'ring.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({
            'success': True,
            'message': '6 xonali tasdiqlash kodi emailingizga yuborildi.',
        })


class PasswordResetConfirmView(views.APIView):
    """Verifies the 6-digit OTP and updates the user's password."""
    permission_classes = [AllowAny]
    throttle_scope = 'auth_sensitive'

    def post(self, request):
        identifier = (request.data.get('identifier') or request.data.get('email') or '').strip()
        code = (request.data.get('code') or '').strip()
        new_password = request.data.get('new_password') or ''

        if not identifier or not code or not new_password:
            return Response(
                {'error': 'Barcha maydonlarni to\'ldiring.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = (
            User.objects.filter(email__iexact=identifier).first()
            or User.objects.filter(username__iexact=identifier).first()
        )
        if not user:
            return Response({'error': 'Noto\'g\'ri kod yoki foydalanuvchi.'}, status=status.HTTP_400_BAD_REQUEST)

        reset_obj = PasswordResetCode.objects.filter(
            user=user, is_used=False, expires_at__gt=timezone.now()
        ).first()
        if not reset_obj:
            return Response({'error': 'Tasdiqlash kodi muddati tugagan yoki topilmadi.'}, status=status.HTTP_400_BAD_REQUEST)

        if reset_obj.attempts >= 5:
            reset_obj.is_used = True
            reset_obj.save(update_fields=['is_used'])
            return Response({'error': 'Juda ko\'p noto\'g\'ri urinish. Yangi kod so\'rang.'}, status=status.HTTP_400_BAD_REQUEST)

        if not secrets.compare_digest(reset_obj.code, code):
            reset_obj.attempts += 1
            reset_obj.save(update_fields=['attempts'])
            return Response({'error': 'Tasdiqlash kodi noto\'g\'ri.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(new_password, user=user)
        except ValidationError as ve:
            return Response({'error': ' '.join(ve.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=['password'])
        reset_obj.is_used = True
        reset_obj.save(update_fields=['is_used'])

        return Response({'success': True, 'message': 'Parol muvaffaqiyatli yangilandi!'})
