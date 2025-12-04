from django.db import models
from django.contrib.auth.models import AbstractUser

from django.utils.translation import gettext_lazy as _

class CustomUser(AbstractUser):
    LANGUAGE_CHOICES = [
        ('kaa', _('Qaraqalpaqsha')),
        ('en', _('English')),
        ('ru', _('Russian')),
    ]

    phone_number = models.CharField(max_length=20, blank=True, verbose_name=_("Phone Number"))
    age = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Age"))
    preferred_language = models.CharField(max_length=3, choices=LANGUAGE_CHOICES, default='en', verbose_name=_("Preferred Language"))

    def __str__(self):
        return self.username

class Course(models.Model):
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    language = models.CharField(max_length=3, default='en', verbose_name=_("Language"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    def __str__(self):
        return self.title

class Module(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='modules')
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    order = models.PositiveIntegerField(verbose_name=_("Order"))

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.course.title} - {self.title}"

class Lesson(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    content = models.TextField(help_text=_("Markdown content"), verbose_name=_("Content"))
    order = models.PositiveIntegerField(verbose_name=_("Order"))

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.title

class Quiz(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='quizzes')
    question = models.TextField(verbose_name=_("Question"))
    options = models.JSONField(help_text=_("List of options"), verbose_name=_("Options"))
    correct_answer = models.CharField(max_length=200, verbose_name=_("Correct Answer"))

    def __str__(self):
        return f"Quiz for {self.lesson.title}"

class UserProgress(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='progress')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    is_completed = models.BooleanField(default=False)
    score = models.IntegerField(default=0)
    completed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'lesson']

    def __str__(self):
        return f"{self.user.username} - {self.lesson.title}"

class UserCourse(models.Model):
    """Track which courses a user is enrolled in"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='enrolled_courses')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrolled_users')
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'course']

    def __str__(self):
        return f"{self.user.username} - {self.course.title}"

class ChatMessage(models.Model):
    """Store chat history for users"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='chat_messages')
    message = models.TextField()
    is_user = models.BooleanField(default=True)  # True if from user, False if from bot
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username} - {'User' if self.is_user else 'Bot'}: {self.message[:50]}"


from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

# ... boshqa modellaringiz (Course, Lesson va h.k.) ...

class UserStreak(models.Model):
    # User so'zini settings.AUTH_USER_MODEL ga almashtiramiz
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='streak')
    current_streak = models.IntegerField(default=0)
    last_activity = models.DateField(default=timezone.now)
    max_streak = models.IntegerField(default=0)

    def update_streak(self):
        today = timezone.now().date()

        # Agar bugun allaqachon kirgan bo'lsa, hech narsa qilmaymiz
        if self.last_activity == today:
            return

        # Agar oxirgi faollik kecha bo'lsa, streakni davom ettiramiz
        if self.last_activity == today - timedelta(days=1):
            self.current_streak += 1
        else:
            # Agar bir kundan ko'p o'tkazib yuborgan bo'lsa (va bu yangi user bo'lmasa)
            # Yangi userlar uchun (default=now) bo'lgani uchun tekshiramiz:
            if self.current_streak > 0:
                self.current_streak = 1
            else:
                self.current_streak = 1 # Birinchi marta boshlash

        # Rekordni yangilash
        if self.current_streak > self.max_streak:
            self.max_streak = self.current_streak

        self.last_activity = today
        self.save()

    def __str__(self):
        return f"{self.user} - {self.current_streak} kun"