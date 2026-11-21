from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from .models import Course, Module, Lesson, Quiz, DailyActivity

User = get_user_model()


class StuDyAPIEconomyAndFeaturesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testlearner',
            password='StrongPassword123!',
            preferred_language='uz',
        )
        self.client.force_authenticate(user=self.user)
        self.headers = {'HTTP_X_APP_SIGNATURE': 'StuDyAppKeySignature2026!'}

        self.course = Course.objects.create(
            title='Python Mastery',
            description='Learn Python step by step',
            language='uz',
            category='coding',
            difficulty='beginner',
            creator=self.user,
        )
        self.module = Module.objects.create(course=self.course, title='Basics', order=1)
        self.lesson = Lesson.objects.create(
            module=self.module,
            title='Variables and Loops',
            content='## Intro\nPython is clean.',
            lesson_type='coding',
            interactive_data={
                'visual_diagram': {'title': 'Flow', 'steps': ['Input', 'Process', 'Output'], 'summary': 'Core flow'},
                'flashcards': [{'front': 'List', 'back': 'Mutable sequence', 'example': 'nums = [1, 2]'}],
                'practice_lab': {
                    'enabled': True,
                    'lab_type': 'code',
                    'language': 'python',
                    'prompt': 'Print numbers 1 to 3',
                    'starter_code': 'for i in range(1, 4):\n    pass',
                    'expected_output': '1\n2\n3',
                    'hint': 'Use print(i)',
                }
            },
            order=1,
        )
        self.quiz = Quiz.objects.create(
            lesson=self.lesson,
            question='What does range(1, 4) yield?',
            options=['1, 2, 3', '1, 2, 3, 4', '0, 1, 2', '2, 3, 4'],
            correct_answer='1, 2, 3',
            explanation='range(start, stop) stops before the stop value.'
        )

    def test_profile_returns_economy_quests_and_welcome_energy(self):
        res = self.client.get(reverse('api_profile'), **self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(str(res.data['energy'])), Decimal('30.00'))
        self.assertIn('economy', res.data)
        self.assertEqual(res.data['economy']['xp_redeem_cost'], 250)
        self.assertEqual(len(res.data['daily_quests']), 3)

    def test_daily_bonus_and_xp_redeem(self):
        bonus_res = self.client.post(reverse('api_claim_bonus'), **self.headers)
        self.assertEqual(bonus_res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.energy, Decimal('33.00'))

        # Grant XP and redeem 250 XP -> +10 Energy
        self.user.bonus_xp = 300
        self.user.save()
        redeem_res = self.client.post(reverse('api_redeem_xp'), **self.headers)
        self.assertEqual(redeem_res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.energy, Decimal('43.00'))
        self.assertEqual(self.user.redeemed_xp, 250)

    def test_quiz_submit_returns_explanation_and_updates_quest_and_streak(self):
        res = self.client.post(
            reverse('api_submit_quiz', kwargs={'lesson_id': self.lesson.id}),
            {'quiz_id': self.quiz.id, 'option': '1, 2, 3'},
            format='json',
            **self.headers
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['is_correct'])
        self.assertIn('stops before', res.data['explanation'])
        self.assertTrue(res.data['lesson_just_completed'])
        self.assertGreaterEqual(res.data['current_streak'], 1)

        # Claim completed daily_lesson quest (+3 Energy)
        claim_res = self.client.post(
            reverse('api_claim_quest'),
            {'quest_key': 'daily_lesson'},
            format='json',
            **self.headers
        )
        self.assertEqual(claim_res.status_code, 200)
        self.user.refresh_from_db()
        self.assertGreater(self.user.energy, Decimal('30.00'))

    def test_practice_lab_requires_pro_or_ultra_and_evaluates_on_pro(self):
        # Free user blocked
        free_res = self.client.post(
            reverse('api_evaluate_practice', kwargs={'lesson_id': self.lesson.id}),
            {'submission': 'for i in range(1, 4): print(i)'},
            format='json',
            **self.headers
        )
        self.assertEqual(free_res.status_code, 403)

        # Upgrade to Pro
        self.client.post(
            reverse('api_mock_subscribe'),
            {'plan': 'pro', 'is_annual': False},
            format='json',
            **self.headers
        )
        with patch('core.api.views.evaluate_practice_submission') as mock_eval:
            mock_eval.return_value = {
                'is_passed': True,
                'score': 95,
                'feedback': 'Zo\'r yechim!',
                'improved_version': 'for i in range(1, 4):\n    print(i)'
            }
            pro_res = self.client.post(
                reverse('api_evaluate_practice', kwargs={'lesson_id': self.lesson.id}),
                {'submission': 'for i in range(1, 4):\n    print(i)'},
                format='json',
                **self.headers
            )
            self.assertEqual(pro_res.status_code, 200)
            self.assertTrue(pro_res.data['is_passed'])
            self.assertEqual(pro_res.data['xp_gained'], 15)

    def test_blitz_review_open_preview_and_delete_account(self):
        # Other user's course preview works for Free users (Lesson 1 unlocked, Lesson 2 locked)
        other_user = User.objects.create_user(username='author2', password='Password123!')
        other_course = Course.objects.create(title='Explore Course', description='Open preview', language='uz', creator=other_user)
        mod = Module.objects.create(course=other_course, title='M1', order=1)
        Lesson.objects.create(module=mod, title='L1', content='Free preview content', order=1)
        Lesson.objects.create(module=mod, title='L2', content='Locked Pro content', order=2)

        preview_res = self.client.get(f'/api/v1/courses/{other_course.id}/', **self.headers)
        self.assertEqual(preview_res.status_code, 200)
        self.assertTrue(preview_res.data['is_preview'])
        lessons = preview_res.data['modules'][0]['lessons']
        self.assertFalse(lessons[0]['is_locked'])
        self.assertTrue(lessons[1]['is_locked'])

        # Blitz Review loads & awards XP at 0 energy cost
        blitz_get = self.client.get(reverse('api_blitz_review'), **self.headers)
        self.assertEqual(blitz_get.status_code, 200)
        self.assertEqual(blitz_get.data['energy_cost'], 0)
        self.assertGreaterEqual(len(blitz_get.data['questions']), 1)

        blitz_post = self.client.post(
            reverse('api_blitz_review'),
            {'correct_count': 2, 'solved_quiz_ids': [self.quiz.id]},
            format='json',
            **self.headers
        )
        self.assertEqual(blitz_post.status_code, 200)
        self.assertEqual(blitz_post.data['xp_earned'], 10)

        # Delete account endpoint removes user cleanly
        del_res = self.client.delete(reverse('api_delete_account'), **self.headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertFalse(User.objects.filter(id=self.user.id).exists())
