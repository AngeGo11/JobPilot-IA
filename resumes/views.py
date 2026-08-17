from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.views.generic import TemplateView
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin

from .forms import ResumeUploadForm
from .models import Resume
from .services.pdf_parser import PDFParser
from matching.models import JobAlert
from matching.services import consume_credit
from .services.ai_parser import AIParser
from utils.gemini_safe import FairUseExceeded, GeminiServiceUnavailable
from administration.models import SiteSettings
from matching.tasks import embed_resume_task

User = get_user_model()

@login_required  # Requiert l'authentification
def upload_resume(request):
    # Quota défini dans le back-office : chaque CV consomme du stockage et un
    # appel d'analyse IA, on plafonne donc le nombre de fichiers par compte.
    max_resumes = SiteSettings.load().max_resumes_per_user
    if Resume.objects.filter(user=request.user).count() >= max_resumes:
        messages.error(
            request,
            f"Vous avez atteint la limite de {max_resumes} CV. "
            f"Supprimez-en un avant d'en déposer un nouveau.",
        )
        return redirect('resume_list')

    if request.method == 'POST':
        form = ResumeUploadForm(request.POST, request.FILES)
        if form.is_valid():
            resume = form.save(commit=False)
            resume.user = request.user
            resume.save()

            # --- ÉTAPE 1 : EXTRACTION DU TEXTE DU PDF ---
            # Lecture en mémoire pour supporter le stockage local ET cloud (ex. Azure Blob)
            pdf_content = resume.file.read()
            parser = PDFParser(pdf_content)
            extracted_text = parser.extract_text()  # Extraction du texte brut
            parsed_data = parser.parse_data()  # Parsing basique (email, phone uniquement)

            if extracted_text:
                resume.extracted_text = extracted_text
                resume.parsed_data = parsed_data
                resume.save()


                try:
                    ai_parser = AIParser()
                    job_info = ai_parser.extract_job_info(extracted_text, user_id=request.user.id)
                    
                    # Sauvegarde des données extraites par l'IA
                    resume.detected_job_title = job_info.get('job_title')
                    resume.detected_skills = job_info.get('skills', [])
                    resume.save()

                    # Vectorisation en tâche de fond : le candidat n'attend pas,
                    # et le score sémantique sera disponible à la prochaine
                    # recherche d'offres.
                    embed_resume_task.delay(resume.pk)
                    
                    if resume.detected_job_title:
                        messages.success(
                            request, 
                            f'CV analysé ! Poste détecté : {resume.detected_job_title}'
                        )
                    else:
                        messages.warning(
                            request, 
                            'CV analysé mais aucun titre de poste détecté. La recherche d\'emploi pourrait être limitée.'
                        )
                        
                except FairUseExceeded:
                    messages.warning(
                        request,
                        "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte)."
                    )
                except GeminiServiceUnavailable:
                    messages.warning(
                        request,
                        "Nos serveurs sont momentanément surchargés. Réessayez dans quelques instants."
                    )
                except Exception as e:
                    # En cas d'erreur avec l'IA, on continue quand même (le CV est sauvegardé)
                    print(f"Erreur lors de l'analyse IA : {e}")
                    messages.warning(
                        request, 
                        f'⚠️ CV sauvegardé mais erreur lors de l\'analyse IA : {str(e)}'
                    )
            else:
                messages.error(request, '❌ Impossible d\'extraire le texte du PDF.')

            return redirect('resume_list')
    else:
        form = ResumeUploadForm()
    
    return render(request, 'resumes/upload.html', {'form': form})




@login_required
def resume_list(request):
    resumes = Resume.objects.filter(user=request.user)
    active_alert_resume_ids = set(
        JobAlert.objects.filter(resume__user=request.user, is_active=True).values_list('resume_id', flat=True)
    )
    return render(request, 'resumes/list.html', {
        'resumes': resumes,
        'active_alert_resume_ids': active_alert_resume_ids,
    })


@login_required
def delete_resume(request, resume_id):
    if request.method == 'POST':
        resume = get_object_or_404(Resume, pk=resume_id, user=request.user)
        resume.delete()
        messages.success(request, 'CV supprimé.')
    return redirect('resume_list')
