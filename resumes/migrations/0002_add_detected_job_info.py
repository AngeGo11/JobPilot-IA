# Generated manually for JobPilot AI dynamic job search

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('resumes', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='resume',
            name='detected_job_title',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Titre du poste visé'),
        ),
        migrations.AddField(
            model_name='resume',
            name='detected_skills',
            field=models.JSONField(blank=True, default=list, verbose_name='Compétences détectées'),
        ),
    ]
