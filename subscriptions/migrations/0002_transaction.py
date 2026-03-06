# Generated for idempotent Stripe webhook (Transaction traçabilité)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_session_id', models.CharField(max_length=255, unique=True, verbose_name='ID session Stripe')),
                ('amount', models.DecimalField(blank=True, decimal_places=2, help_text='Montant payé (optionnel, depuis session.amount_total)', max_digits=10, null=True, verbose_name='Montant (€)')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Date de traitement')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stripe_transactions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Transaction Stripe',
                'verbose_name_plural': 'Transactions Stripe',
                'ordering': ['-created_at'],
            },
        ),
    ]
