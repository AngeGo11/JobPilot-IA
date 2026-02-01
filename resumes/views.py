from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from .forms import ResumeUploadForm
from .models import Resume
from .services.pdf_parser import PDFParser
from matching.models import JobAlert
from .services.ai_parser import AIParser

User = get_user_model()

@login_required  # Requiert l'authentification
def upload_resume(request):
    if request.method == 'POST':
        form = ResumeUploadForm(request.POST, request.FILES)
        if form.is_valid():
            resume = form.save(commit=False)
            resume.user = request.user
            resume.save()

            # --- ÉTAPE 1 : EXTRACTION DU TEXTE DU PDF ---
            parser = PDFParser(resume.file.path)
            extracted_text = parser.extract_text()  # Extraction du texte brut
            parsed_data = parser.parse_data()  # Parsing basique (email, phone uniquement)

            if extracted_text:
                resume.extracted_text = extracted_text
                resume.parsed_data = parsed_data
                resume.save()

                # --- ÉTAPE 2 : ANALYSE IA AVEC GEMINI ---
                try:
                    ai_parser = AIParser()
                    job_info = ai_parser.extract_job_info(extracted_text)
                    
                    # Sauvegarde des données extraites par l'IA
                    resume.detected_job_title = job_info.get('job_title')
                    resume.detected_skills = job_info.get('skills', [])
                    resume.save()
                    
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
                        
                except Exception as e:
                    # En cas d'erreur avec l'IA, on continue quand même (le CV est sauvegardé)
                    print(f"❌ Erreur lors de l'analyse IA : {e}")
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

