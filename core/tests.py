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
        other_course = Course.objects.create(title='Explore Course', description='Open preview', language='uz', creator=other_user, is_public=True)
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

        # All primary Neo-Brutalist pages render 200 (including Store!)
        for name in ('dashboard', 'explore', 'blitz_web', 'chatbot', 'leaderboard', 'profile_web', 'store_web', 'pricing'):
            res = wc.get(reverse(name))
            self.assertEqual(res.status_code, 200, msg=f"Failed rendering {name}")

        # Language switcher translates UI across uz, kaa, ru, en
        lang_checks = [
            ('ru', 'Магазин'),
            ('en', 'Store'),
            ('kaa', 'Dúkan'),
            ('uz', "Do&#x27;kon"),
        ]
        for code, expected in lang_checks:
            sw = wc.post(reverse('change_language'), {'language': code})
            self.assertEqual(sw.status_code, 200)
            page = wc.get(reverse('store_web'))
            self.assertContains(page, expected)

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

    def test_google_play_billing_verification_and_replay_protection(self):
        # Verify one-time energy pack credits +50 Energy once and rejects replay across users
        with patch('core.billing.verify_google_play_purchase') as mock_verify:
            mock_verify.return_value = {
                'purchase_type': 'one_time',
                'order_id': 'GPA.1234-5678-9012',
                'raw': {'purchaseState': 0},
            }
            res = self.client.post(
                reverse('api_verify_google_purchase'),
                {'product_id': 'energy_50', 'purchase_token': 'tok-abc-123', 'order_id': 'GPA.1'},
                format='json',
                **self.headers,
            )
            self.assertEqual(res.status_code, 200)
            self.user.refresh_from_db()
            self.assertEqual(self.user.energy, Decimal('80.00'))

            # Replay for same user is idempotent (no double credit)
            dup = self.client.post(
                reverse('api_verify_google_purchase'),
                {'product_id': 'energy_50', 'purchase_token': 'tok-abc-123'},
                format='json',
                **self.headers,
            )
            self.assertEqual(dup.status_code, 200)
            self.assertTrue(dup.data.get('already_processed'))
            self.user.refresh_from_db()
            self.assertEqual(self.user.energy, Decimal('80.00'))

            # Replay by a second user returns 409 Conflict
            user2 = User.objects.create_user(username='otherbuyer', password='Password123!')
            c2 = APIClient()
            c2.force_authenticate(user=user2)
            steal = c2.post(
                reverse('api_verify_google_purchase'),
                {'product_id': 'energy_50', 'purchase_token': 'tok-abc-123'},
                format='json',
                **self.headers,
            )
            self.assertEqual(steal.status_code, 409)

        # Verify subscription activates PRO + grants +150 Energy
        with patch('core.billing.verify_google_play_purchase') as mock_sub:
            mock_sub.return_value = {
                'purchase_type': 'subscription',
                'order_id': 'GPA.SUB-999',
                'raw': {'subscriptionState': 'SUBSCRIPTION_STATE_ACTIVE'},
            }
            sub_res = self.client.post(
                reverse('api_verify_google_purchase'),
                {'product_id': 'studyai_pro_annual', 'purchase_token': 'tok-sub-999'},
                format='json',
                **self.headers,
            )
            self.assertEqual(sub_res.status_code, 200)
            self.user.refresh_from_db()
            self.assertEqual(self.user.subscription_type, 'pro')
            self.assertTrue(self.user.is_annual)
            self.assertEqual(self.user.energy, Decimal('230.00'))

    def test_case_insensitive_username_registration_and_login(self):
        anon = APIClient()
        # Register with mixed-case username -> stored lowercase
        reg1 = anon.post(
            reverse('api_register'),
            {'username': 'AzamatTest', 'password': 'StrongPassword123!', 'first_name': 'Azamat'},
            format='json',
            **self.headers,
        )
        self.assertEqual(reg1.status_code, 201)
        self.assertEqual(reg1.data['username'], 'azamattest')

        # Second registration with different casing is rejected
        reg2 = anon.post(
            reverse('api_register'),
            {'username': 'azamattest', 'password': 'StrongPassword123!'},
            format='json',
            **self.headers,
        )
        self.assertEqual(reg2.status_code, 400)

        # Login works regardless of casing
        tok = anon.post(
            reverse('token_obtain_pair'),
            {'username': 'AZAMATTEST', 'password': 'StrongPassword123!'},
            format='json',
            **self.headers,
        )
        self.assertEqual(tok.status_code, 200)
        self.assertIn('access', tok.data)

    def test_n_plus_2_lesson_lookahead(self):
        les2 = Lesson.objects.create(
            module=self.module,
            title='Lesson 2 Ready',
            content='Detailed second lesson content that is definitely longer than eighty characters and ready upfront before opening lesson one.',
            lesson_type='coding',
            interactive_data={'visual_diagram': {'title': 'Flow', 'steps': ['A', 'B', 'C'], 'summary': 'ok'}},
            order=2,
        )
        Quiz.objects.create(lesson=les2, question='Q2?', options=['A', 'B', 'C', 'D'], correct_answer='A')
        les3 = Lesson.objects.create(module=self.module, title='Lesson 3 Empty', content='', order=3)
        les4 = Lesson.objects.create(module=self.module, title='Lesson 4 Empty', content='', order=4)

        # Opening Lesson 1 (with Lesson 2 already populated) pre-warms Lesson 3
        with patch('core.api.views._schedule_single_lesson_prewarm') as mock_prewarm:
            res1 = self.client.get(f'/api/v1/lessons/{self.lesson.id}/', **self.headers)
            self.assertEqual(res1.status_code, 200)
            mock_prewarm.assert_called_once_with(les3.id, 'uz', 'free')

        # Complete Lesson 1, open Lesson 2 -> pre-warms Lesson 4 (while Lesson 3 is already non-empty if generated)
        les3.content = 'Generated rich lesson three content that exceeds eighty characters for prewarm lookahead check.'
        les3.interactive_data = {'flashcards': []}
        les3.save()
        from core.models import UserProgress
        UserProgress.objects.update_or_create(
            user=self.user, lesson=self.lesson, defaults={'is_completed': True}
        )
        with patch('core.api.views._schedule_single_lesson_prewarm') as mock_prewarm:
            res2 = self.client.get(f'/api/v1/lessons/{les2.id}/', **self.headers)
            self.assertEqual(res2.status_code, 200)
            mock_prewarm.assert_called_once_with(les4.id, 'uz', 'free')

    def test_subscription_expiry_and_rtdn_webhook(self):
        import base64
        import json
        from datetime import timedelta
        from django.utils import timezone

        self.user.subscription_type = 'pro'
        self.user.play_purchase_token = 'rtdn-tok-123'
        self.user.last_play_product_id = 'studyai_pro_monthly'
        self.user.subscription_expires_at = timezone.now() - timedelta(minutes=5)
        self.user.save()

        # When expired and Google Play reports expired/canceled -> auto-downgrades to free on profile fetch
        with patch('core.billing.verify_google_play_purchase') as mock_play:
            from core.billing import BillingVerificationError
            mock_play.side_effect = BillingVerificationError('Obuna faol emas (holat: SUBSCRIPTION_STATE_EXPIRED).')
            prof = self.client.get(reverse('api_profile'), **self.headers)
            self.assertEqual(prof.status_code, 200)
            self.assertEqual(prof.data['subscription_type'], 'free')

        # RTDN Pub/Sub webhook without X-App-Signature re-syncs renewal and credits +150 Energy
        self.user.subscription_type = 'pro'
        self.user.save()
        payload = base64.b64encode(json.dumps({
            'subscriptionNotification': {
                'notificationType': 2,
                'purchaseToken': 'rtdn-tok-123',
                'subscriptionId': 'studyai_pro_monthly',
            }
        }).encode()).decode()

        with patch('core.billing.verify_google_play_purchase') as mock_play:
            mock_play.return_value = {
                'purchase_type': 'subscription',
                'order_id': 'GPA.RENEW-2',
                'expires_at': timezone.now() + timedelta(days=30),
                'raw': {'subscriptionState': 'SUBSCRIPTION_STATE_ACTIVE'},
            }
            anon = APIClient()
            rtdn_res = anon.post(
                reverse('api_google_play_rtdn'),
                {'message': {'data': payload}},
                format='json',
            )
            self.assertEqual(rtdn_res.status_code, 200)
            self.user.refresh_from_db()
            self.assertEqual(self.user.subscription_type, 'pro')
            self.assertEqual(self.user.energy, Decimal('180.00'))

    def test_password_reset_otp_flow(self):
        from django.core import mail
        from core.models import PasswordResetCode

        self.user.email = 'learner@example.com'
        self.user.save(update_fields=['email'])
        anon = APIClient()

        req = anon.post(
            reverse('api_password_reset_request'),
            {'identifier': 'testlearner'},
            format='json',
            **self.headers,
        )
        self.assertEqual(req.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        otp = PasswordResetCode.objects.filter(user=self.user, is_used=False).first().code

        # Wrong OTP fails
        bad = anon.post(
            reverse('api_password_reset_confirm'),
            {'identifier': 'learner@example.com', 'code': '000000', 'new_password': 'NewStrongPassword99!'},
            format='json',
            **self.headers,
        )
        self.assertEqual(bad.status_code, 400)

        # Valid OTP updates password and allows login
        ok = anon.post(
            reverse('api_password_reset_confirm'),
            {'identifier': 'learner@example.com', 'code': otp, 'new_password': 'NewStrongPassword99!'},
            format='json',
            **self.headers,
        )
        self.assertEqual(ok.status_code, 200)
        login_res = anon.post(
            reverse('token_obtain_pair'),
            {'username': 'testlearner', 'password': 'NewStrongPassword99!'},
            format='json',
            **self.headers,
        )
        self.assertEqual(login_res.status_code, 200)
        self.assertIn('access', login_res.data)

    def test_chatbot_stream_accepts_event_stream_header(self):
        with patch('core.api.views.chatbot_response_stream', return_value=iter(['Hello ', 'world!'])):
            res = self.client.post(
                reverse('api_chatbot_stream'),
                {'message': 'Hi'},
                format='json',
                HTTP_ACCEPT='text/event-stream',
                **self.headers,
            )
            self.assertEqual(res.status_code, 200)
            body = b''.join(res.streaming_content).decode('utf-8')
        self.assertIn('"delta": "Hello "', body)
        self.assertIn('"done": true', body)

        self.user.energy = Decimal('0.00')
        self.user.save(update_fields=['energy'])
        err_res = self.client.post(
            reverse('api_chatbot_stream'),
            {'message': 'Hi again'},
            format='json',
            HTTP_ACCEPT='text/event-stream',
            **self.headers,
        )
        self.assertEqual(err_res.status_code, 400)

    def test_chatbot_discovery_requires_prior_turn_before_topic_clear(self):
        # Turn 1: premature TOPIC_CLEAR must be suppressed until user shares goals/interests
        with patch('core.api.views.chatbot_response', return_value='Salom! Qaysi yo\'nalish qiziq?\nTOPIC_CLEAR: Python'):
            r1 = self.client.post(
                reverse('api_chatbot'),
                {'message': 'Salom, Python o\'rganmoqchiman'},
                format='json',
                **self.headers,
            )
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.data['topic_clear'])
        self.assertIsNone(r1.data['topic'])
        self.assertNotIn('TOPIC_CLEAR:', r1.data['bot_message'])

        # Turn 2: after discovery exchange, TOPIC_CLEAR is honored
        with patch('core.api.views.chatbot_response', return_value='Ajoyib! Backend kursi boshlaymiz.\nTOPIC_CLEAR: Python Django Backend'):
            r2 = self.client.post(
                reverse('api_chatbot'),
                {'message': 'Ish topish uchun backend o\'rganmoqchiman, boshlang\'ichman'},
                format='json',
                **self.headers,
            )
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data['topic_clear'])
        self.assertEqual(r2.data['topic'], 'Python Django Backend')

    def test_course_privacy_explore_filtering_and_settings(self):
        # Private course owned by another author must stay hidden from Explore & blocked from other users
        other_user = User.objects.create_user(username='private_author', password='Password123!')
        private_course = Course.objects.create(
            title='Private Secret Plan',
            description='Personal notes',
            language='uz',
            creator=other_user,
            is_public=False,
        )
        mod = Module.objects.create(course=private_course, title='Private M1', order=1)
        les = Lesson.objects.create(module=mod, title='Secret L1', content='Secret content', order=1)

        explore_res = self.client.get(reverse('api_explore_courses'), **self.headers)
        self.assertEqual(explore_res.status_code, 200)
        ids_in_explore = [c['id'] for c in explore_res.data['courses']]
        self.assertNotIn(private_course.id, ids_in_explore)

        self.assertEqual(self.client.get(f'/api/v1/courses/{private_course.id}/', **self.headers).status_code, 403)
        self.assertEqual(self.client.get(f'/api/v1/lessons/{les.id}/', **self.headers).status_code, 403)

        # Non-creator cannot change course settings
        forbidden_patch = self.client.patch(
            reverse('api_course_settings', kwargs={'course_id': private_course.id}),
            {'is_public': True},
            format='json',
            **self.headers,
        )
        self.assertEqual(forbidden_patch.status_code, 403)

        # Creator can publish and rename via settings, then it appears in Explore
        owner_client = APIClient()
        owner_client.force_authenticate(user=other_user)
        ok_patch = owner_client.patch(
            reverse('api_course_settings', kwargs={'course_id': private_course.id}),
            {'title': 'Public Python Guide', 'is_public': True, 'difficulty': 'intermediate'},
            format='json',
            **self.headers,
        )
        self.assertEqual(ok_patch.status_code, 200)
        self.assertTrue(ok_patch.data['is_public'])
        self.assertEqual(ok_patch.data['title'], 'Public Python Guide')

        explore_res2 = self.client.get(reverse('api_explore_courses'), **self.headers)
        self.assertIn(private_course.id, [c['id'] for c in explore_res2.data['courses']])

        # Creator can delete course cleanly
        del_res = owner_client.delete(reverse('api_course_settings', kwargs={'course_id': private_course.id}), **self.headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertFalse(Course.objects.filter(id=private_course.id).exists())
