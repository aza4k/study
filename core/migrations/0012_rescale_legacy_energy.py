from decimal import Decimal
from django.db import migrations


def rescale_energy(apps, schema_editor):
    CustomUser = apps.get_model('core', 'CustomUser')
    for user in CustomUser.objects.all():
        current = Decimal(str(user.energy or '0'))
        # Rescale legacy 2/30/120 economy up cleanly without clipping high test balances
        if user.subscription_type == 'free' and current < Decimal('30.00'):
            user.energy = max(current * Decimal('10'), Decimal('30.00'))
            user.save(update_fields=['energy'])
        elif user.subscription_type == 'pro' and current < Decimal('150.00'):
            user.energy = max(current * Decimal('5'), Decimal('150.00'))
            user.save(update_fields=['energy'])
        elif user.subscription_type == 'ultra' and current < Decimal('500.00'):
            user.energy = max(current * Decimal('4'), Decimal('500.00'))
            user.save(update_fields=['energy'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_course_category_course_difficulty_and_more'),
    ]

    operations = [
        migrations.RunPython(rescale_energy, migrations.RunPython.noop),
    ]
