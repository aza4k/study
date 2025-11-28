from django.core.management.base import BaseCommand
from core.models import Quiz

class Command(BaseCommand):
    help = 'Fixes legacy quiz answers stored as indices instead of text'

    def handle(self, *args, **kwargs):
        quizzes = Quiz.objects.all()
        fixed_count = 0
        
        for quiz in quizzes:
            # 1. Check if the current correct_answer is already in the options list (exact match)
            if quiz.correct_answer in quiz.options:
                # It's already correct (text based), even if it looks like a number
                continue

            # 2. Check if correct_answer is a digit (index)
            if quiz.correct_answer.isdigit():
                index = int(quiz.correct_answer)
                options = quiz.options
                
                # Verify index is valid
                if 0 <= index < len(options):
                    actual_answer = options[index]
                    quiz.correct_answer = actual_answer
                    quiz.save()
                    fixed_count += 1
                    try:
                        self.stdout.write(self.style.SUCCESS(f'Fixed quiz {quiz.id}'))
                    except UnicodeEncodeError:
                        self.stdout.write(self.style.SUCCESS(f'Fixed quiz {quiz.id} (unicode name)'))
                else:
                    self.stdout.write(self.style.WARNING(f'Skipping quiz {quiz.id}: Index {index} out of range for options length {len(options)}'))
            else:
                # Already text or invalid format
                pass
                
        self.stdout.write(self.style.SUCCESS(f'Successfully fixed {fixed_count} quizzes'))
