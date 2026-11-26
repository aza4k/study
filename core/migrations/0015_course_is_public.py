from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_subscription_expiry_and_password_reset'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='is_public',
            field=models.BooleanField(default=True, verbose_name='Public in Catalog'),
        ),
        migrations.AlterField(
            model_name='course',
            name='is_public',
            field=models.BooleanField(default=False, verbose_name='Public in Catalog'),
        ),
    ]
