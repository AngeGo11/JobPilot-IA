# Generated for JobPilot - Smart Alerts (JobAlert)

import django.db.models.deletion
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('resumes', '0003_alter_resume_parsed_skills'),
        ('matching', '0005_alter_jobmatch_unique_together'),
    ]

    operations = [
        migrations.CreateModel(
            name='JobAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, verbose_name='Actif')),
                ('last_checked', models.DateTimeField(blank=True, null=True, verbose_name='Dernière vérification')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('resume', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='job_alerts', to='resumes.resume')),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('resume',)},
            },
        ),
    ]
