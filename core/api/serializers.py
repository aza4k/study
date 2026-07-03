from rest_framework import serializers
from django.contrib.auth import get_user_model
from core.models import Course, Module, Lesson, Quiz, UserProgress, UserCourse, ChatMessage, UserStreak

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
    class Meta:
        model = UserStreak
        fields = ('current_streak', 'max_streak', 'last_activity')

class QuizSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quiz
        fields = ('id', 'question', 'options', 'correct_answer')

class LessonSerializer(serializers.ModelSerializer):
    quizzes = QuizSerializer(many=True, read_only=True)
    user_progress = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = ('id', 'title', 'content', 'order', 'quizzes', 'user_progress')

    def get_user_progress(self, obj):
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

    class Meta:
        model = Course
        fields = ('id', 'title', 'description', 'language', 'created_at', 'modules', 'is_frozen')

    def get_is_frozen(self, obj):
        if obj.creator and obj.creator.subscription_type == 'free':
            from django.utils import timezone
            from datetime import timedelta
            return timezone.now() > obj.created_at + timedelta(days=7)
        return False

class CourseListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ('id', 'title', 'description', 'language', 'created_at')

class UserProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProgress
        fields = ('id', 'lesson', 'is_completed', 'score', 'completed_at')

class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ('id', 'message', 'is_user', 'created_at')
