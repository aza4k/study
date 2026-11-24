from django.db import models
from django.contrib.auth.models import AbstractUser

from django.utils.translation import gettext_lazy as _

class CustomUser(AbstractUser):
    LANGUAGE_CHOICES = [
        ('kaa', _('Qaraqalpaqsha')),
        ('en', _('English')),
        ('ru', _('Russian')),
        ('uz', _('Uzbek')),
    ]

    phone_number = models.CharField(max_length=20, blank=True, verbose_name=_("Phone Number"))
    age = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Age"))
    preferred_language = models.CharField(max_length=3, choices=LANGUAGE_CHOICES, default='en', verbose_name=_("Preferred Language"))

    # Business Model Fields
    subscription_type = models.CharField(
        max_length=10,
        choices=[('free', 'Free'), ('pro', 'Pro'), ('ultra', 'Ultra')],
        default='free',
        verbose_name=_("Subscription Type")
    )
    energy = models.DecimalField(max_digits=8, decimal_places=2, default=30.00, verbose_name=_("Energy"))
    is_annual = models.BooleanField(default=False, verbose_name=_("Is Annual"))
    redeemed_xp = models.PositiveIntegerField(default=0, verbose_name=_("Redeemed XP"))
    last_bonus_claimed = models.DateField(null=True, blank=True, verbose_name=_("Last Daily Bonus Claimed"))
    bonus_xp = models.PositiveIntegerField(default=0, verbose_name=_("Bonus XP"))

    def __str__(self):
        return self.username

class Course(models.Model):
    CATEGORY_CHOICES = [
        ('coding', _('Programming & Tech')),
        ('language', _('Languages')),
        ('business', _('Business & Marketing')),
        ('science', _('Math & Science')),
        ('creative', _('Design & Creative')),
        ('general', _('General Knowledge')),
    ]
    DIFFICULTY_CHOICES = [
        ('beginner', _('Beginner')),
        ('intermediate', _('Intermediate')),
        ('advanced', _('Advanced')),
    ]

    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    language = models.CharField(max_length=3, default='en', verbose_name=_("Language"))
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general', verbose_name=_("Category"))
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='beginner', verbose_name=_("Difficulty"))
    image_url = models.URLField(max_length=500, blank=True, null=True, verbose_name=_("Image URL"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    creator = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_courses',
        verbose_name=_("Creator")
    )

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
    LESSON_TYPE_CHOICES = [
        ('general', _('General')),
        ('coding', _('Coding & Interactive Lab')),
        ('language', _('Language & Dialogue')),
        ('science', _('Math & Science')),
        ('business', _('Business & Strategy')),
    ]

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    content = models.TextField(help_text=_("Markdown content"), verbose_name=_("Content"))
    lesson_type = models.CharField(max_length=20, choices=LESSON_TYPE_CHOICES, default='general', verbose_name=_("Lesson Type"))
    interactive_data = models.JSONField(default=dict, blank=True, help_text=_("Structured visual diagrams, flashcards, and practice lab"))
    image_url = models.URLField(max_length=500, blank=True, null=True, verbose_name=_("Image URL"))
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
    explanation = models.TextField(blank=True, default='', verbose_name=_("Explanation"))

    def __str__(self):
        return f"Quiz for {self.lesson.title}"

class UserProgress(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='progress')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    is_completed = models.BooleanField(default=False)
    score = models.IntegerField(default=0)
    completed_quizzes = models.JSONField(default=list, help_text=_("List of completed quiz IDs"))
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

from django.utils import timezone
from datetime import timedelta

class UserStreak(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='streak')
    current_streak = models.IntegerField(default=0)
    last_activity = models.DateField(default=timezone.localdate)
    max_streak = models.IntegerField(default=0)

    def update_streak(self):
        today = timezone.localdate()

        if self.last_activity == today and self.current_streak > 0:
            return

        if self.current_streak == 0:
            self.current_streak = 1
        elif self.last_activity == today - timedelta(days=1):
            self.current_streak += 1
        else:
            self.current_streak = 1

        if self.current_streak > self.max_streak:
            self.max_streak = self.current_streak

        self.last_activity = today
        self.save()

    def __str__(self):
        return f"{self.user} - {self.current_streak} kun"

class Certificate(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='certificates')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='certificates')
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'course']

    def __str__(self):
        return f"Certificate: {self.user.username} - {self.course.title}"

class CourseStar(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='course_stars')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='stars')
    starred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'course']

    def __str__(self):
        return f"{self.user.username} starred {self.course.title}"


class DailyActivity(models.Model):
    """Tracks daily user learning engagement for Quests, Analytics, and Fair Rate Limits."""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='daily_activities')
    date = models.DateField(default=timezone.localdate)
    lessons_completed = models.PositiveIntegerField(default=0)
    quizzes_correct = models.PositiveIntegerField(default=0)
    chats_sent = models.PositiveIntegerField(default=0)
    practice_completed = models.PositiveIntegerField(default=0)
    claimed_quests = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = ['user', 'date']
        ordering = ['-date']

    def __str__(self):
        return f"{self.user.username} - {self.date}"


class PlayPurchase(models.Model):
    """Verified Google Play Billing one-time & subscription purchases (prevents token replay)."""
    PURCHASE_TYPES = (
        ('one_time', 'One-time Energy Pack'),
        ('subscription', 'Subscription'),
    )
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='play_purchases')
    product_id = models.CharField(max_length=100)
    purchase_token = models.CharField(max_length=512, unique=True)
    order_id = models.CharField(max_length=128, blank=True, default='')
    purchase_type = models.CharField(max_length=20, choices=PURCHASE_TYPES)
    verified = models.BooleanField(default=True)
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.product_id} ({self.purchase_type})"
