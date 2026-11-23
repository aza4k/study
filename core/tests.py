from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from .models import Course, Module, Lesson, Quiz, DailyActivity, UserCourse

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
            content='## Intro\nPython is clean, readable, and designed for fast interactive learning and practical coding.',
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

    def test_sequential_lesson_lock_and_prewarm_only_on_open(self):
        les2 = Lesson.objects.create(
            module=self.module,
            title='Lesson 2',
            content='Content for lesson 2 that is long enough to avoid live AI generation calls in unit test.',
            lesson_type='coding',
            interactive_data={'flashcards': [{'front': 'A', 'back': 'B', 'example': ''}]},
            order=2,
        )
        Quiz.objects.create(
            lesson=les2,
            question='Q2?',
            options=['A', 'B', 'C', 'D'],
            correct_answer='A',
        )

        # Course detail marks Lesson 1 unlocked, Lesson 2 prerequisite_locked before Lesson 1 is done
        course_res = self.client.get(f'/api/v1/courses/{self.course.id}/', **self.headers)
        self.assertEqual(course_res.status_code, 200)
        lessons = course_res.data['modules'][0]['lessons']
        self.assertFalse(lessons[0]['prerequisite_locked'])
        self.assertTrue(lessons[1]['prerequisite_locked'])

        # Direct API access to Lesson 2 blocked until Lesson 1 is completed
        blocked_res = self.client.get(f'/api/v1/lessons/{les2.id}/', **self.headers)
        self.assertEqual(blocked_res.status_code, 403)
        self.assertTrue(blocked_res.data['prerequisite_locked'])

        # Opening Lesson 1 succeeds and schedules pre-warming if Lesson 2 is empty
        les2.content = ''
        les2.save()
        with patch('core.api.views._schedule_single_lesson_prewarm') as mock_prewarm:
            open1 = self.client.get(f'/api/v1/lessons/{self.lesson.id}/', **self.headers)
            self.assertEqual(open1.status_code, 200)
            mock_prewarm.assert_called_once_with(les2.id, 'uz', 'free')

    def test_play_store_compliance_pages_and_domain_host(self):
        from django.test import Client
        web_client = Client(HTTP_HOST='study-ai.uz')

        for name in ('privacy_policy', 'terms_of_use', 'support_page', 'delete_account_web'):
            res = web_client.get(reverse(name) + '?lang=uz')
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, 'StudyAi')

        # Web account deletion rejects bad password, then deletes on valid credentials
        bad_res = web_client.post(reverse('delete_account_web'), {
            'username': 'testlearner',
            'password': 'WrongPassword!',
            'confirm_delete': 'yes',
        })
        self.assertEqual(bad_res.status_code, 200)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

        ok_res = web_client.post(reverse('delete_account_web'), {
            'username': 'testlearner',
            'password': 'StrongPassword123!',
            'confirm_delete': 'yes',
        })
        self.assertEqual(ok_res.status_code, 200)
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_web_pages_sequential_lock_quiz_economy_and_blitz(self):
        from django.test import Client
        les2 = Lesson.objects.create(
            module=self.module,
            title='Lesson 2 Web',
            content='Detailed second lesson content for web sequential mastery verification.',
            lesson_type='coding',
            interactive_data={'flashcards': [{'front': 'X', 'back': 'Y', 'example': ''}]},
            order=2,
        )
        Quiz.objects.create(lesson=les2, question='Q2?', options=['A', 'B', 'C', 'D'], correct_answer='A')
        UserCourse.objects.get_or_create(user=self.user, course=self.course)

        wc = Client(HTTP_HOST='study-ai.uz')
        self.assertTrue(wc.login(username='testlearner', password='StrongPassword123!'))

        # All primary Neo-Brutalist pages render 200
        for name in ('dashboard', 'explore', 'blitz_web', 'chatbot', 'leaderboard', 'profile_web', 'pricing'):
            res = wc.get(reverse(name))
            self.assertEqual(res.status_code, 200, msg=f"Failed rendering {name}")

        # Sequential lock blocks Lesson 2 before Lesson 1 is completed
        blocked = wc.get(reverse('lesson_detail', kwargs={'pk': les2.id}))
        self.assertEqual(blocked.status_code, 302)

        # Opening Lesson 1 succeeds and pre-warms ONLY Lesson 2 if Lesson 2 needs generation
        les2.content = ''
        les2.save()
        with patch('core.views._schedule_single_lesson_prewarm') as mock_prewarm:
            ok1 = wc.get(reverse('lesson_detail', kwargs={'pk': self.lesson.id}))
            self.assertEqual(ok1.status_code, 200)
            mock_prewarm.assert_called_once_with(les2.id, 'uz', 'free')

        # Wrong quiz answer does NOT deduct XP
        wrong_res = wc.post(
            reverse('submit_quiz', kwargs={'lesson_id': self.lesson.id}),
            {'quiz_id': self.quiz.id, 'option': '0, 1, 2'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(wrong_res.status_code, 200)
        self.assertFalse(wrong_res.json()['is_correct'])
        self.assertEqual(wrong_res.json()['total_xp'], 0)

        # Correct quiz answer grants +10 XP + 15 XP lesson completion and unlocks Lesson 2
        right_res = wc.post(
            reverse('submit_quiz', kwargs={'lesson_id': self.lesson.id}),
            {'quiz_id': self.quiz.id, 'option': '1, 2, 3'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(right_res.status_code, 200)
        self.assertTrue(right_res.json()['is_correct'])
        self.assertTrue(right_res.json()['lesson_completed'])
        self.assertEqual(right_res.json()['total_xp'], 25)

        # Daily bonus & Blitz POST work cleanly
        bonus = wc.post(reverse('claim_bonus_web'))
        self.assertEqual(bonus.status_code, 200)
        blitz_post = wc.post(
            reverse('blitz_web'),
            data='{"correct_count": 3, "solved_quiz_ids": []}',
            content_type='application/json',
        )
        self.assertEqual(blitz_post.status_code, 200)
        self.assertEqual(blitz_post.json()['xp_earned'], 15)
