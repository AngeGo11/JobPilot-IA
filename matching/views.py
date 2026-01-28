from django.shortcuts import render, get_object_or_404, redirect  # <--- Ajoute redirect ici
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
import logging
from resumes.models import Resume
from .models import JobMatch
from .services.francetravail import FranceTravail  # Vérifie que ton import est bon selon ton dossier
from .services.ai_letter_generator import AILetterGenerator
from .forms import CoverLetterGenerationForm, CoverLetterEditForm, CoverLetterRefineForm


class FindJobsLoadingView(LoginRequiredMixin, TemplateView):
    """
    Page de chargement intermédiaire affichée après avoir cliqué sur "Trouver des offres".
    Redirige automatiquement vers la recherche d'offres après un court délai.
    """
    template_name = 'matching/loading.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resume_id = self.kwargs.get('resume_id')
        context['resume_id'] = resume_id
        context['find_jobs_url'] = f'/matching/search/{resume_id}/'
        return context


@login_required
def find_jobs_for_resume(request, resume_id):
    page_number = request.GET.get('page', 1)
    resume = get_object_or_404(Resume, id=resume_id)
    user = resume.user

    # 1. Partie "Mise à jour via API" - Utilise detected_job_title comme source de vérité
    jobs_found = 0
    if resume.detected_job_title:
        service = FranceTravail()
        try:
            # Utilise le titre du poste détecté par l'IA comme mots-clés de recherche
            search_query = resume.detected_job_title
            logging.info(f"🔍 Recherche d'offres avec le titre détecté: {search_query}")
            api_results = service.search_jobs(search_query, page=int(page_number))
            logging.info(f"📊 Nombre d'offres trouvées via API: {len(api_results) if api_results else 0}")
            
            if api_results:
                saved_matches = service.save_jobs(api_results, user, resume)
                jobs_found = len(saved_matches)
                logging.info(f"✅ {jobs_found} offres sauvegardées en base de données")
            else:
                logging.info("⚠️ Aucune offre trouvée via l'API")
        except Exception as e:
            logging.info(f"❌ Erreur API : {e}")
            import traceback
    else:
        logging.info("⚠️ Aucun titre de poste détecté dans le CV. Impossible de rechercher des offres.")

    # 2. Partie "Récupération des données" - Filtrer par CV spécifique
    # On filtre par resume pour ne montrer QUE les offres liées à ce CV précis
    matches = JobMatch.objects.filter(
        resume=resume,  # Filtre par CV spécifique (cloisonnement)
        user=user  # Sécurité : on vérifie aussi que c'est bien l'utilisateur du CV
    ).exclude(
        status='rejected'
    ).select_related('job_offer').order_by('-score', '-matched_at')
    paginator = Paginator(matches, 9)

    # Obtenir les objets de la page demandée
    page_obj = paginator.get_page(page_number)

    
    logging.info(f"📋 Nombre de matches récupérés de la BDD: {matches.count()}")

    return render(request, 'matching/results.html', {
        'resume': resume,
        'matches': matches,
        'jobs_found': jobs_found,
        'job_title_used': resume.detected_job_title or 'Non détecté',
        'page_obj': page_obj
    })


@require_POST
def update_match_status(request, match_id):
    # Récupérer le match sans filtrer par user (pour permettre les utilisateurs anonymes en développement)
    # TODO: Réactiver la vérification user=request.user quand l'authentification sera en place

    match = get_object_or_404(JobMatch, id=match_id)
    new_status = request.POST.get('status')

    valid_statuses = ['new', 'applied', 'interviewed', 'rejected']
    if new_status in valid_statuses:
        match.status = new_status
        match.save()

    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def generate_cover_letter(request, match_id):
    """
    Vue pour générer une lettre de motivation automatiquement via IA.
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    if request.method == 'POST':
        form = CoverLetterGenerationForm(request.POST)
        if form.is_valid():
            # TODO: Implémenter la génération
            pass
    else:
        form = CoverLetterGenerationForm()
    
    return render(request, 'matching/generate_letter.html', {
        'match': match,
        'form': form,
    })


@login_required
@require_POST
def save_generated_letter(request, match_id):
    """
    Vue pour sauvegarder une lettre de motivation générée.
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    # TODO: Implémenter la sauvegarde
    pass


@login_required
def edit_cover_letter(request, match_id):
    """
    Vue pour éditer une lettre de motivation existante.
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    if request.method == 'POST':
        form = CoverLetterEditForm(request.POST)
        if form.is_valid():
            # TODO: Implémenter la sauvegarde
            pass
    else:
        form = CoverLetterEditForm(initial={
            'cover_letter_content': match.cover_letter_content
        })
    
    return render(request, 'matching/edit_letter.html', {
        'match': match,
        'form': form,
    })


@login_required
@require_POST
def quick_refine_cover_letter(request, match_id):
    """
    Vue pour améliorer rapidement une lettre avec des actions prédéfinies (improve, formalize, etc.).
    Appelée via AJAX depuis le workspace.
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    # Récupérer l'action demandée
    action = request.POST.get('action', 'improve')
    
    # Si l'action est 'generate', générer une nouvelle lettre de motivation
    if action == 'generate':
        try:
            generator = AILetterGenerator()
            
            # Récupérer le CV associé au match, ou le CV principal de l'utilisateur
            resume = match.resume
            if not resume:
                # Si le match n'a pas de CV associé, récupérer le CV principal de l'utilisateur
                resume = Resume.objects.filter(user=request.user, is_primary=True).first()
                if not resume:
                    # Si pas de CV principal, prendre le premier CV de l'utilisateur
                    resume = Resume.objects.filter(user=request.user).first()
            
            if not resume:
                return JsonResponse({
                    'success': False,
                    'error': "Aucun CV trouvé. Veuillez d'abord uploader un CV."
                }, status=400)
            
            if not resume.extracted_text:
                return JsonResponse({
                    'success': False,
                    'error': "Le CV n'a pas de texte extrait. Veuillez ré-uploader le CV."
                }, status=400)
            
            # Générer la lettre de motivation
            generated_letter = generator.generate_cover_letter(
                resume=resume,
                job_match=match,
                tone="professional"
            )
            
            # Ne pas sauvegarder automatiquement - l'utilisateur devra cliquer sur "Sauvegarder"
            # La lettre est seulement retournée pour être affichée dans l'éditeur
            
            return JsonResponse({
                'success': True,
                'refined_letter': generated_letter,
                'message': '✨ Lettre de motivation générée avec succès ! Vous pouvez maintenant la modifier et la sauvegarder.'
            })
            
        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': f"Erreur de validation : {str(e)}"
            }, status=400)
        except Exception as e:
            logging.error(f"Erreur lors de la génération de la lettre : {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"Erreur lors de la génération : {str(e)}"
            }, status=500)
    
    # Récupérer le texte actuel depuis le POST (au cas où il a été modifié)
    # Note: Cette vérification se fait après 'generate' car la génération ne nécessite pas de texte existant
    current_text = request.POST.get('cover_letter_content', match.cover_letter_content)
    
    if not current_text:
        return JsonResponse({
            'success': False,
            'error': "Vous devez d'abord rédiger une lettre de motivation."
        }, status=400)
    
    # Si l'action est export-pdf, rediriger vers la vue d'export
    if action == 'export-pdf':
        # Pour l'export PDF, on doit rediriger vers une nouvelle page ou retourner une réponse différente
        # Mais comme c'est appelé via AJAX, on va retourner une réponse JSON avec l'URL de téléchargement
        try:
            generator = AILetterGenerator()
            
            # Récupérer les informations
            user = request.user
            user_name = f"{user.first_name} {user.last_name}".strip() if (user.first_name or user.last_name) else user.username
            user_email = user.email if user.email else None
            job_offer = match.job_offer
            job_title = job_offer.title if job_offer else None
            company_name = job_offer.company_name if job_offer else None
            
            # Générer le PDF
            pdf_buffer = generator.export_to_pdf(
                cover_letter_content=current_text,
                user_name=user_name,
                user_email=user_email,
                user_address=None,
                job_title=job_title,
                company_name=company_name,
                recipient_name=None
            )
            
            # Retourner le PDF en base64 pour le téléchargement côté client
            import base64
            pdf_base64 = base64.b64encode(pdf_buffer.read()).decode('utf-8')
            
            return JsonResponse({
                'success': True,
                'pdf_data': pdf_base64,
                'filename': f"lettre_motivation_{job_title or 'candidature'}_{company_name or 'entreprise'}.pdf".replace(' ', '_'),
                'message': '📄 PDF généré avec succès !'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f"Erreur lors de l'export PDF : {str(e)}"
            }, status=500)
    
    # Mapping des actions vers les types d'amélioration
    action_mapping = {
        'improve': {
            'type': 'custom',
            'instructions': 'Améliore cette lettre de motivation : corrige les fautes, améliore la fluidité, optimise la structure et le style, tout en gardant le contenu factuel intact.'
        },
        'formalize': {
            'type': 'tone',
            'instructions': 'Rends cette lettre plus formelle et professionnelle, utilise un langage plus soutenu.'
        },
        'grammar': {
            'type': 'grammar',
            'instructions': 'Corrige toutes les fautes d\'orthographe, de grammaire et de syntaxe.'
        },
        'length': {
            'type': 'length',
            'instructions': 'Optimise la longueur de cette lettre pour qu\'elle soit concise mais complète.'
        }
    }
    
    action_config = action_mapping.get(action, action_mapping['improve'])
    
    try:
        generator = AILetterGenerator()
        
        # Construire les instructions finales
        final_instructions = generator._build_refinement_instructions(
            action_config['instructions'],
            action_config['type']
        )
        
        # Appeler le service de raffinement
        refined_letter = generator.refine_cover_letter(
            current_text,
            final_instructions
        )
        
        # Sauvegarder la lettre améliorée
        match.cover_letter_content = refined_letter
        match.save()
        
        return JsonResponse({
            'success': True,
            'refined_letter': refined_letter,
            'message': '✨ Votre lettre a été améliorée avec succès !'
        })
        
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': f"Erreur de validation : {str(e)}"
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"Erreur lors de l'amélioration : {str(e)}"
        }, status=500)


@login_required
def refine_cover_letter(request, match_id):
    """
    Vue pour améliorer une lettre de motivation existante via IA.
    Peut être appelée en GET (affiche le formulaire) ou POST (traite l'amélioration).
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    # Vérifier que la lettre existe
    if not match.cover_letter_content:
        messages.warning(
            request, 
            "Vous devez d'abord rédiger une lettre de motivation avant de pouvoir l'améliorer."
        )
        return redirect('application_workspace', match_id=match_id)
    
    if request.method == 'POST':
        form = CoverLetterRefineForm(request.POST)
        if form.is_valid():
            instructions = form.cleaned_data['instructions']
            improvement_type = form.cleaned_data.get('improvement_type', 'custom')
            
            try:
                generator = AILetterGenerator()
                
                # Construire les instructions finales selon le type d'amélioration
                final_instructions = generator._build_refinement_instructions(
                    instructions,
                    improvement_type
                )
                
                # Appeler le service de raffinement
                refined_letter = generator.refine_cover_letter(
                    match.cover_letter_content,
                    final_instructions
                )
                
                # Sauvegarder la lettre améliorée
                match.cover_letter_content = refined_letter
                match.save()
                
                messages.success(
                    request, 
                    '✨ Votre lettre de motivation a été améliorée avec succès !'
                )
                
                # Rediriger vers le workspace pour voir le résultat
                return redirect('application_workspace', match_id=match_id)
                
            except ValueError as e:
                messages.error(request, f"Erreur de validation : {str(e)}")
            except Exception as e:
                messages.error(
                    request, 
                    f"Erreur lors de l'amélioration de la lettre : {str(e)}"
                )
    else:
        form = CoverLetterRefineForm()
    
    return render(request, 'matching/refine_letter.html', {
        'match': match,
        'form': form,
        'current_letter': match.cover_letter_content,
    })


@login_required
@require_http_methods(["GET", "POST"])
def export_cover_letter_pdf(request, match_id):
    """
    Vue pour exporter une lettre de motivation en PDF.
    Peut être appelée en GET (utilise le contenu sauvegardé) ou POST (utilise le contenu fourni).
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    # Récupérer le contenu de la lettre
    if request.method == 'POST':
        # Si c'est un POST, récupérer le contenu depuis le formulaire
        cover_letter_content = request.POST.get('cover_letter_content', match.cover_letter_content)
    else:
        # Si c'est un GET, utiliser le contenu sauvegardé
        cover_letter_content = match.cover_letter_content
    
    if not cover_letter_content or not cover_letter_content.strip():
        messages.error(request, "Vous devez d'abord rédiger une lettre de motivation avant de l'exporter.")
        return redirect('application_workspace', match_id=match_id)
    
    try:
        generator = AILetterGenerator()
        
        # Récupérer les informations de l'utilisateur
        user = request.user
        user_name = f"{user.first_name} {user.last_name}".strip() if (user.first_name or user.last_name) else user.username
        user_email = user.email if user.email else None
        
        # Récupérer les informations de l'offre d'emploi
        job_offer = match.job_offer
        job_title = job_offer.title if job_offer else None
        company_name = job_offer.company_name if job_offer else None
        
        # Générer le PDF
        pdf_buffer = generator.export_to_pdf(
            cover_letter_content=cover_letter_content,
            user_name=user_name,
            user_email=user_email,
            user_address=None,  # Peut être ajouté plus tard si stocké dans le profil
            job_title=job_title,
            company_name=company_name,
            recipient_name=None  # Par défaut "Madame, Monsieur"
        )
        
        # Préparer le nom du fichier
        filename = f"lettre_motivation_{job_title or 'candidature'}_{company_name or 'entreprise'}"
        # Nettoyer le nom de fichier (enlever les caractères spéciaux)
        filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = filename.replace(' ', '_')
        filename = f"{filename}.pdf"
        
        # Créer la réponse HTTP avec le PDF
        response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except ValueError as e:
        messages.error(request, f"Erreur de validation : {str(e)}")
        return redirect('application_workspace', match_id=match_id)
    except Exception as e:
        messages.error(request, f"Erreur lors de l'export PDF : {str(e)}")
        return redirect('application_workspace', match_id=match_id)