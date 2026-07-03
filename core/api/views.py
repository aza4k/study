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
        instance = self.get_object()
        user = request.user
        
        # Enforce subscription access limits:
        is_creator = (instance.creator == user)
        is_enrolled = UserCourse.objects.filter(user=user, course=instance).exists()
        
        # Check if it's one of the top 10 starred courses
        from django.db.models import Count
        top_10_ids = Course.objects.annotate(star_count=Count('stars')).order_by('-star_count')[:10].values_list('id', flat=True)
        is_top_10 = instance.id in top_10_ids
        
        if user.subscription_type == 'free':
            # Free users can only view their own courses, NOT other people's courses
            if not is_creator and not is_enrolled:
                return Response({'error': 'Free users cannot access this course. Upgrade to PRO or ULTRA.'}, status=status.HTTP_403_FORBIDDEN)
            # Free users cannot view top 10 details either
            if not is_creator and is_top_10:
                return Response({'error': 'PRO subscription required to open this course.'}, status=status.HTTP_403_FORBIDDEN)
        
        elif user.subscription_type == 'pro':
            # Pro users can view their own courses OR any of the top 10 starred courses
            if not is_creator and not is_enrolled and not is_top_10:
                return Response({'error': 'PRO users can only access their own courses or Top 10 courses. Upgrade to ULTRA to access all courses.'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if frozen
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

class ExploreCoursesView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        from django.core.paginator import Paginator
        user = request.user
        
        # Prefetch creator relationship
        courses_qs = Course.objects.annotate(star_count=Count('stars')).select_related('creator')
        
        # 1. Access logic by subscription
        if user.subscription_type in ['free', 'pro']:
            # Free and Pro only see Top 10 starred courses
            courses = courses_qs.order_by('-star_count')[:10]
            total_pages = 1
            current_page = 1
            has_next = False
        else:
            # Ultra users see all courses with search and pagination!
            search_query = request.query_params.get('search', '').strip()
            lang_query = request.query_params.get('language', '').strip()
            
            if search_query:
                courses_qs = courses_qs.filter(title__icontains=search_query)
            if lang_query:
                courses_qs = courses_qs.filter(language=lang_query)
                
            courses_qs = courses_qs.order_by('-star_count', '-created_at')
            
            page_size = 10
            paginator = Paginator(courses_qs, page_size)
            page_number = request.query_params.get('page', 1)
            
            try:
                page_obj = paginator.get_page(page_number)
            except Exception:
                return Response({'error': 'Invalid page number'}, status=status.HTTP_400_BAD_REQUEST)
                
            courses = page_obj.object_list
            total_pages = paginator.num_pages
            current_page = page_obj.number
            has_next = page_obj.has_next()

        # Prefetch user's star and enrollment lists to avoid N+1 queries
        from core.models import CourseStar, UserCourse
        starred_course_ids = set(CourseStar.objects.filter(user=user).values_list('course_id', flat=True))
        enrolled_course_ids = set(UserCourse.objects.filter(user=user).values_list('course_id', flat=True))

        data = []
        for course in courses:
            data.append({
                'id': course.id,
                'title': course.title,
                'description': course.description,
                'language': course.language,
                'created_at': course.created_at,
                'creator_username': course.creator.username if course.creator else 'AI System',
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

        from core.models import CourseStar
        star_record = CourseStar.objects.filter(user=user, course=course).first()
        if star_record:
            star_record.delete()
            starred = False
        else:
            CourseStar.objects.create(user=user, course=course)
            starred = True

        star_count = CourseStar.objects.filter(course=course).count()

        # Invalidate course list cache
        from django.core.cache import cache
        cache.clear()
        
        return Response({
            'success': True,
            'starred': starred,
            'star_count': star_count
        })

class ToggleEnrollCourseView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, course_id):
        user = request.user
        if user.subscription_type == 'free':
            return Response({'error': 'PRO subscription required to enroll in courses.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({'error': 'Course not found'}, status=status.HTTP_404_NOT_FOUND)

        # Pro users can only enroll in top 10 starred courses
        if user.subscription_type == 'pro':
            from django.db.models import Count
            top_10_ids = Course.objects.annotate(star_count=Count('stars')).order_by('-star_count')[:10].values_list('id', flat=True)
            if course.id not in top_10_ids and course.creator != user:
                return Response({'error': 'PRO subscription is limited to enrolling in Top 10 courses. Upgrade to ULTRA to enroll in any course.'}, status=status.HTTP_403_FORBIDDEN)

        from core.models import UserCourse
        enroll_record = UserCourse.objects.filter(user=user, course=course).first()
        if enroll_record:
            enroll_record.delete()
            enrolled = False
        else:
            UserCourse.objects.create(user=user, course=course)
            enrolled = True

        from django.core.cache import cache
        cache.clear()

        return Response({
            'success': True,
            'enrolled': enrolled
        })

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
