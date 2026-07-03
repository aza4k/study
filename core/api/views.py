import re
from rest_framework import viewsets, views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth import get_user_model
from core.models import Course, Module, Lesson, Quiz, UserProgress, UserCourse, ChatMessage, UserStreak
from core.api.serializers import (
    UserSerializer, CourseSerializer, CourseListSerializer,
    LessonSerializer, QuizSerializer, UserProgressSerializer,
    ChatMessageSerializer, UserStreakSerializer
)
from core.services import chatbot_response, generate_course_from_ai
from django.db.models import Sum

User = get_user_model()

# --- Auth & Profile ---
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = UserSerializer

class UserProfileView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = UserSerializer(user)
        streak, _ = UserStreak.objects.get_or_create(user=user)
        streak_data = UserStreakSerializer(streak).data
        progress_xp = UserProgress.objects.filter(user=user).aggregate(Sum('score'))['score__sum'] or 0
        total_xp = progress_xp + user.bonus_xp
        available_xp = max(0, total_xp - user.redeemed_xp)
        
        data = serializer.data
        data['streak'] = streak_data
        data['xp'] = total_xp
        data['available_xp'] = available_xp
        return Response(data)

    def put(self, request):
        user = request.user
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        email = request.data.get('email')
        
        if first_name is not None:
            user.first_name = first_name.strip()
        if last_name is not None:
            user.last_name = last_name.strip()
        if email is not None:
            user.email = email.strip()
            
        user.save()
        return Response({
            'success': True,
            'message': 'Profile updated successfully'
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
        from django.db.models import Prefetch
        user = self.request.user
        queryset = Course.objects.all()
        if user.subscription_type not in ['pro', 'ultra']:
            # Free users only see their own enrolled courses
            queryset = Course.objects.filter(enrolled_users__user=user)
        
        return queryset.prefetch_related(
            'modules',
            'modules__lessons',
            'modules__lessons__quizzes',
            Prefetch(
                'modules__lessons__userprogress_set',
                queryset=UserProgress.objects.filter(user=user),
                to_attr='user_progresses'
            )
        )

    def list(self, request, *args, **kwargs):
        from django.core.cache import cache
        user = request.user
        
        # Determine cache key based on subscription type (or user ID for free tier)
        cache_key = f"courses_list_{user.subscription_type}"
        if user.subscription_type not in ['pro', 'ultra']:
            cache_key = f"courses_list_free_{user.id}"

        # Try to read from cache
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        # Retrieve and serialize
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        # Cache in Redis for 15 seconds
        cache.set(cache_key, data, 15)
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        # Prevent access if course is frozen
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        if data.get('is_frozen'):
            return Response({
                'error': 'This course has expired and is frozen. Upgrade to PRO or ULTRA to unfreeze it.',
                'is_frozen': True
            }, status=status.HTTP_403_FORBIDDEN)
        return Response(data)

class LessonViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LessonSerializer

    def get_queryset(self):
        course_id = self.request.query_params.get('course_id')
        if course_id:
            # Check if frozen
            try:
                course = Course.objects.get(id=course_id)
                # Check frozen dynamically
                if course.creator and course.creator.subscription_type == 'free':
                    from django.utils import timezone
                    from datetime import timedelta
                    if timezone.now() > course.created_at + timedelta(days=7):
                        return Lesson.objects.none()
            except Course.DoesNotExist:
                pass
            return Lesson.objects.filter(module__course_id=course_id)
        return Lesson.objects.all()

class SubmitQuizView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, lesson_id):
        quiz_id = request.data.get('quiz_id')
        selected_option = request.data.get('option')
        
        if not quiz_id or not selected_option:
            return Response({'error': 'quiz_id and option are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            quiz = Quiz.objects.get(id=quiz_id, lesson_id=lesson_id)
        except Quiz.DoesNotExist:
            return Response({'error': 'Quiz not found'}, status=status.HTTP_404_NOT_FOUND)

        lesson = quiz.lesson
        is_correct = (selected_option == quiz.correct_answer)

        progress, _ = UserProgress.objects.get_or_create(user=request.user, lesson=lesson)
        
        # Prevent XP farming: only add score if quiz_id is not in completed_quizzes
        if quiz_id not in progress.completed_quizzes:
            if is_correct:
                progress.score += 10
                progress.completed_quizzes.append(quiz_id)
            else:
                progress.score -= 5 # Can go negative for wrong attempts
        
        # Check if all quizzes in the lesson are now correctly answered
        total_quizzes = Quiz.objects.filter(lesson=lesson).count()
        if total_quizzes == 0 or len(progress.completed_quizzes) >= total_quizzes:
            progress.is_completed = True
        else:
            progress.is_completed = False

        progress.save()
        
        return Response({
            'success': True,
            'is_correct': is_correct,
            'correct_answer': quiz.correct_answer if not is_correct else None,
            'current_xp': progress.score,
            'message': 'Correct answer!' if is_correct else 'Incorrect answer.'
        })

# --- Chatbot & Generation ---
class ChatbotView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        messages = ChatMessage.objects.filter(user=request.user)
        serializer = ChatMessageSerializer(messages, many=True)
        return Response(serializer.data)

    def post(self, request):
        user = request.user
        from decimal import Decimal

        # Free tier chat count limit check
        if user.subscription_type == 'free':
            msg_count = ChatMessage.objects.filter(user=user, is_user=True).count()
            if msg_count >= 10:
                return Response({'error': 'Free tier limit of 10 chat messages reached. Please upgrade to Pro.'}, status=status.HTTP_400_BAD_REQUEST)

        # Energy check (each chat costs 0.1 energy)
        if user.energy < Decimal('0.1'):
            return Response({'error': 'Not enough Energy! Chat messages cost 0.1 Energy.'}, status=status.HTTP_400_BAD_REQUEST)

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
        
        # Deduct energy
        user.energy = Decimal(str(user.energy)) - Decimal('0.1')
        user.save()

        return Response({
            'bot_message': bot_reply,
            'topic_clear': topic_clear,
            'topic': topic,
            'current_energy': user.energy
        })

class GenerateCourseView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        topic = request.data.get('topic', '').strip()
        if not topic:
            return Response({'error': 'Topic is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Enforce subscription limits
        created_count = Course.objects.filter(creator=user).count()
        if user.subscription_type == 'free' and created_count >= 1:
            return Response({'error': 'Free tier users are limited to 1 course at a time. Please upgrade to Pro.'}, status=status.HTTP_400_BAD_REQUEST)
        elif user.subscription_type == 'pro' and created_count >= 10:
            return Response({'error': 'Pro tier users are limited to 10 courses. Please upgrade to Ultra.'}, status=status.HTTP_400_BAD_REQUEST)
        elif user.subscription_type == 'ultra' and created_count >= 30:
            return Response({'error': 'Ultra tier users are limited to 30 courses.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            course = generate_course_from_ai(topic, user.preferred_language, user)
            return Response({
                'success': True,
                'course_id': course.id,
                'title': course.title,
                'message': 'Course generated successfully',
                'current_energy': user.energy
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UploadPDFCourseView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.subscription_type != 'ultra':
            return Response({'error': 'PDF course generation is only available for Ultra subscribers.'}, status=status.HTTP_403_FORBIDDEN)
        
        pdf_file = request.FILES.get('pdf')
        if not pdf_file:
            return Response({'error': 'No PDF file provided.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from core.services import extract_text_from_pdf
            pdf_text = extract_text_from_pdf(pdf_file)
            if not pdf_text:
                return Response({'error': 'Could not extract text from PDF.'}, status=status.HTTP_400_BAD_REQUEST)
            
            course = generate_course_from_ai("Custom PDF Course", user.preferred_language, user, pdf_text=pdf_text)
            return Response({
                'success': True,
                'course_id': course.id,
                'title': course.title,
                'message': 'Course generated from PDF successfully',
                'current_energy': user.energy
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ClearChatView(views.APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        ChatMessage.objects.filter(user=request.user).delete()
        return Response({'success': True})

# --- Gamification & Business Model API ---
class LeaderboardView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from django.core.cache import cache
        from django.db.models import Sum, F, Value
        from django.db.models.functions import Coalesce

        # 1. Try to get cached leaderboard from Redis
        cached_data = cache.get('api_leaderboard_cache')
        if cached_data is not None:
            return Response(cached_data)

        # 2. Retrieve leaderboard in a single optimized SQL query (JOIN and Sum on DB level)
        users = User.objects.annotate(
            progress_xp=Coalesce(Sum('progress__score'), Value(0))
        ).annotate(
            total_xp=F('progress_xp') + F('bonus_xp')
        ).filter(
            total_xp__gt=0
        ).order_by('-total_xp')[:100]

        # 3. Format result
        data = []
        for user in users:
            data.append({
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'xp': user.total_xp,
            })

        # 4. Cache in Redis for 15 seconds
        cache.set('api_leaderboard_cache', data, 15)

        return Response(data)

class RedeemXPView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        progress_xp = UserProgress.objects.filter(user=user).aggregate(Sum('score'))['score__sum'] or 0
        total_xp = progress_xp + user.bonus_xp
        available_xp = total_xp - user.redeemed_xp

        if available_xp < 5000:
            return Response({'error': 'You need at least 5000 XP to redeem 1 Energy.'}, status=status.HTTP_400_BAD_REQUEST)

        from decimal import Decimal
        user.redeemed_xp += 5000
        user.energy = Decimal(str(user.energy)) + Decimal('1.0')
        user.save()

        return Response({
            'success': True,
            'message': 'Redeemed 5000 XP for 1.0 Energy!',
            'current_energy': user.energy,
            'available_xp': total_xp - user.redeemed_xp
        })

class ClaimDailyBonusView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        from django.utils import timezone
        today = timezone.now().date()

        if user.last_bonus_claimed == today:
            return Response({'error': 'You have already claimed your daily bonus today.'}, status=status.HTTP_400_BAD_REQUEST)

        from decimal import Decimal
        user.last_bonus_claimed = today
        user.energy = Decimal(str(user.energy)) + Decimal('0.1')
        user.save()

        return Response({
            'success': True,
            'message': 'Daily bonus claimed! +0.1 Energy',
            'current_energy': user.energy,
            'current_xp': (UserProgress.objects.filter(user=user).aggregate(Sum('score'))['score__sum'] or 0) + user.bonus_xp
        })

class PurchaseEnergyView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        package = request.data.get('package') # '5' or '15'
        if package not in ['5', '15']:
            return Response({'error': 'Invalid package'}, status=status.HTTP_400_BAD_REQUEST)

        from decimal import Decimal
        amount = Decimal(package)
        user.energy = Decimal(str(user.energy)) + amount
        user.save()

        return Response({
            'success': True,
            'message': f'Successfully purchased +{package} Energy!',
            'current_energy': user.energy
        })

class SubscribeView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        plan = request.data.get('plan') # 'pro' or 'ultra'
        is_annual = request.data.get('is_annual', False)

        if plan not in ['pro', 'ultra', 'free']:
            return Response({'error': 'Invalid plan'}, status=status.HTTP_400_BAD_REQUEST)

        from decimal import Decimal
        user.subscription_type = plan
        user.is_annual = is_annual
        
        # Grant welcome energy
        if plan == 'pro':
            user.energy = Decimal('30.0')
        elif plan == 'ultra':
            user.energy = Decimal('120.0')
        else:
            user.energy = Decimal('2.0')
            
        user.save()

        return Response({
            'success': True,
            'message': f'Successfully subscribed to {plan.upper()}!',
            'subscription_type': user.subscription_type,
            'current_energy': user.energy
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

        # Verify all lessons are completed
        lessons = Lesson.objects.filter(module__course=course)
        total_lessons = lessons.count()
        completed_lessons = UserProgress.objects.filter(user=user, lesson__in=lessons, is_completed=True).count()

        if total_lessons == 0 or completed_lessons < total_lessons:
            return Response({
                'completed': False,
                'message': f'Course not complete. Finished {completed_lessons}/{total_lessons} lessons.'
            })

        from core.models import Certificate
        certificate, created = Certificate.objects.get_or_create(user=user, course=course)

        return Response({
            'completed': True,
            'certificate_id': certificate.id,
            'issued_at': certificate.issued_at,
            'user': f"{user.first_name} {user.last_name}".strip() or user.username,
            'course_title': course.title
        })
