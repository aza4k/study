from rest_framework import serializers
from django.contrib.auth import get_user_model
from core.models import Course, Module, Lesson, Quiz, UserProgress, UserCourse, ChatMessage, UserStreak, Certificate

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'password', 'first_name', 'last_name', 'email', 'phone_number',
            'age', 'preferred_language', 'subscription_type', 'energy',
            'is_annual', 'redeemed_xp', 'last_bonus_claimed', 'bonus_xp'
        )
        read_only_fields = (
            'subscription_type', 'energy', 'is_annual', 'redeemed_xp',
            'last_bonus_claimed', 'bonus_xp'
        )

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User.objects.create_user(**validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user


class UserStreakSerializer(serializers.ModelSerializer):
    last_activity = serializers.SerializerMethodField()

    class Meta:
        model = UserStreak
        fields = ('current_streak', 'max_streak', 'last_activity')

    def get_last_activity(self, obj):
        if not obj.last_activity:
            return None
        if hasattr(obj.last_activity, 'date'):
            return str(obj.last_activity.date())
        return str(obj.last_activity)


class QuizSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quiz
        fields = ('id', 'question', 'options', 'correct_answer', 'explanation')


class LessonSerializer(serializers.ModelSerializer):
    quizzes = QuizSerializer(many=True, read_only=True)
    user_progress = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = (
            'id', 'title', 'content', 'lesson_type', 'interactive_data',
            'image_url', 'order', 'quizzes', 'user_progress'
        )

    def get_user_progress(self, obj):
        if hasattr(obj, 'user_progresses'):
            progresses = obj.user_progresses
            if progresses:
                progress = progresses[0]
                return {
                    'is_completed': progress.is_completed,
                    'score': progress.score,
                    'completed_quizzes': progress.completed_quizzes
                }
            return {
                'is_completed': False,
                'score': 0,
                'completed_quizzes': []
            }

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            progress = UserProgress.objects.filter(user=request.user, lesson=obj).first()
            if progress:
                return {
                    'is_completed': progress.is_completed,
                    'score': progress.score,
                    'completed_quizzes': progress.completed_quizzes
                }
        return {
            'is_completed': False,
            'score': 0,
            'completed_quizzes': []
        }


class ModuleSerializer(serializers.ModelSerializer):
    lessons = LessonSerializer(many=True, read_only=True)

    class Meta:
        model = Module
        fields = ('id', 'title', 'order', 'lessons')


class CourseSerializer(serializers.ModelSerializer):
    modules = ModuleSerializer(many=True, read_only=True)
    is_frozen = serializers.SerializerMethodField()
    lessons_count = serializers.SerializerMethodField()
    completed_lessons_count = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = (
            'id', 'title', 'description', 'language', 'category', 'difficulty',
            'image_url', 'created_at', 'modules', 'is_frozen',
            'lessons_count', 'completed_lessons_count', 'progress_percent'
        )

    def get_is_frozen(self, obj):
        return False

    def _get_counts(self, obj):
        total = 0
        completed = 0
        for mod in obj.modules.all():
            for les in mod.lessons.all():
                total += 1
                if hasattr(les, 'user_progresses') and les.user_progresses:
                    if les.user_progresses[0].is_completed:
                        completed += 1
        return total, completed

    def get_lessons_count(self, obj):
        total, _ = self._get_counts(obj)
        return total

    def get_completed_lessons_count(self, obj):
        _, completed = self._get_counts(obj)
        return completed

    def get_progress_percent(self, obj):
        total, completed = self._get_counts(obj)
        if total == 0:
            return 0
        return round((completed / total) * 100)


class CourseListSerializer(serializers.ModelSerializer):
    modules_count = serializers.SerializerMethodField()
    lessons_count = serializers.SerializerMethodField()
    completed_lessons_count = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    creator_username = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = (
            'id', 'title', 'description', 'language', 'category', 'difficulty',
            'image_url', 'created_at', 'modules_count', 'lessons_count',
            'completed_lessons_count', 'progress_percent', 'creator_username'
        )

    def _stats(self, obj):
        mods = list(obj.modules.all())
        total = 0
        completed = 0
        for mod in mods:
            for les in mod.lessons.all():
                total += 1
                if hasattr(les, 'user_progresses') and les.user_progresses:
                    if les.user_progresses[0].is_completed:
                        completed += 1
        return len(mods), total, completed

    def get_modules_count(self, obj):
        return self._stats(obj)[0]

    def get_lessons_count(self, obj):
        return self._stats(obj)[1]

    def get_completed_lessons_count(self, obj):
        return self._stats(obj)[2]

    def get_progress_percent(self, obj):
        _, total, completed = self._stats(obj)
        return round((completed / total) * 100) if total > 0 else 0

    def get_creator_username(self, obj):
        return obj.creator.username if obj.creator else 'StuDy AI'


class UserProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProgress
        fields = ('id', 'lesson', 'is_completed', 'score', 'completed_at')


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ('id', 'message', 'is_user', 'created_at')


class CertificateSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    course_category = serializers.CharField(source='course.category', read_only=True)

    class Meta:
        model = Certificate
        fields = ('id', 'course', 'course_title', 'course_category', 'issued_at')
