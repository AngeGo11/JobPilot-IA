from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from .forms import ResumeUploadForm
from .models import Resume
from .services.pdf_parser import PDFParser  # <--- Nouvel import

User = get_user_model()

@login_required  # Requiert l'authentification
def upload_resume(request):
    if request.method == 'POST':
        form = ResumeUploadForm(request.POST, request.FILES)
        if form.is_valid():
            resume = form.save(commit=False)
            # Assignation de l'utilisateur : connecté ou utilisateur par défaut pour les tests
            if request.user.is_authenticated:
                resume.user = request.user
            else:
                # Pour les tests sans authentification, utiliser un utilisateur par défaut
                default_user, _ = User.objects.get_or_create(
                    username='axel',
                    defaults={'email': 'axelangegomez2004@gmail.com'}
                )
                resume.user = default_user
            resume.save()

            # --- UTILISATION DE TON PARSER ---
            parser = PDFParser(resume.file.path)
            extracted_text = parser.extract_text()  # Étape 1
            parsed_data = parser.parse_data()  # Étape 2 (Structure)

            if extracted_text:
                resume.extracted_text = extracted_text
                # PostgreSQL stocke le dictionnaire directement dans le JSONField !
                resume.parsed_data = parsed_data
                resume.save()

            return redirect('resume_list')
    else:
        form = ResumeUploadForm()
    
    return render(request, 'resumes/upload.html', {'form': form})

def resume_list(request):
    resumes = Resume.objects.filter(user=request.user)
    return render(request, 'resumes/list.html', {'resumes': resumes})


def delete_resume(request, resume_id):
    resumes = Resume.objects.filter(user=request.user)
    if request.method == 'POST':
        resume = get_object_or_404(Resume, pk=resume_id, user = request.user)
        resume.delete()
    return render(request, 'resumes/list.html', {'resumes': resumes})

