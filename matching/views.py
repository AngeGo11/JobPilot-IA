from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
import logging
from resumes.models import Resume
from .models import JobMatch, JobAlert
from .services import consume_credit, refund_credit
from .services.francetravail import FranceTravail
from .services.ai_letter_generator import AILetterGenerator
from .forms import CoverLetterGenerationForm, CoverLetterEditForm, CoverLetterRefineForm
from resumes.services.ai_optimizer import AIOptimizer
from utils.gemini_safe import FairUseExceeded, GeminiServiceUnavailable

logger = logging.getLogger(__name__)

# Message d'erreur UX rassurant (aucun crédit décompté en cas d'échec IA)
MSG_IA_SURCHARGE_NO_CREDIT = (
    "Notre assistant IA est momentanément très sollicité. "
    "Ne vous inquiétez pas, AUCUN crédit n'a été décompté. Veuillez réessayer dans quelques instants."
)
MSG_IA_SURCHARGE_JSON = (
    "Nos serveurs d'IA sont momentanément surchargés. Aucun crédit n'a été décompté. Veuillez réessayer dans quelques instants."
)


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
    resume = get_object_or_404(Resume, id=resume_id)
    if resume.user_id != request.user.id:
        messages.error(request, "Ce CV ne vous appartient pas.")
        return redirect('resume_list')
    user = resume.user
    page_number = request.GET.get('page', 1)
    confirmed = request.GET.get('confirmed') == '1'

    # --- GET : Étape 1 (La Découverte) — recherche API uniquement sur la première page
    # Pour les pages 2+ ou après confirmation, on ne rappelle jamais l'API : on pagine
    # uniquement sur les matches déjà en base (évite de consommer un crédit à chaque changement de page).
    jobs_found = 0
    is_first_search_page = not confirmed and (page_number == 1 or str(page_number) == '1')
    if is_first_search_page and resume.detected_job_title:
        service = FranceTravail()
        try:
            search_query = resume.detected_job_title
            logging.info(f"🔍 Recherche d'offres avec le titre détecté: {search_query}")
            # Premier appel uniquement : page 1 de l'API, avec une limite plus grande pour avoir
            # assez de résultats à paginer côté Django sans rappeler l'API.
            api_results = service.search_jobs(search_query, page=1, limit=30)
            logging.info(f"📊 Nombre d'offres trouvées via API: {len(api_results) if api_results else 0}")
            if api_results:
                saved_matches = service.save_jobs(api_results, user, resume)
                jobs_found = len(saved_matches)
                # Utilisateurs Premium : déblocage immédiat sans consommer de crédit
                if getattr(user, 'is_premium', False):
                    JobMatch.objects.filter(
                        pk__in=[m.pk for m in saved_matches]
                    ).update(is_unlocked=True)
                logging.info(f"✅ {jobs_found} offres sauvegardées en base de données")
            else:
                logging.info("⚠️ Aucune offre trouvée via l'API")
        except Exception as e:
            logging.info(f"❌ Erreur API : {e}")
    elif not resume.detected_job_title and is_first_search_page:
        logging.info("⚠️ Aucun titre de poste détecté dans le CV. Impossible de rechercher des offres.")

    # Affichage : uniquement les offres débloquées (is_unlocked=True)
    matches = JobMatch.objects.filter(
        resume=resume,
        user=user,
        is_unlocked=True,
    ).exclude(status='rejected').select_related('job_offer').order_by('-score', '-matched_at')
    paginator = Paginator(matches, 9)
    page_obj = paginator.get_page(page_number)
    logging.info(f"📋 Nombre de matches débloqués: {matches.count()}")

    return render(request, 'matching/results.html', {
        'resume': resume,
        'matches': matches,
        'jobs_found': jobs_found,
        'job_title_used': resume.detected_job_title or 'Non détecté',
        'page_obj': page_obj,
        'search_confirmed': confirmed,
    })


@login_required
@require_POST
def unlock_jobs(request, resume_id):
    """
    Étape 2 (Le Déblocage) : consomme 1 crédit et passe toutes les offres "en attente"
    de ce CV en is_unlocked=True. Appelée quand l'utilisateur clique sur "Oui" dans la modale.
    """
    resume = get_object_or_404(Resume, id=resume_id)
    if resume.user_id != request.user.id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
            return JsonResponse({'success': False, 'error': 'Ce CV ne vous appartient pas.'}, status=403)
        messages.error(request, "Ce CV ne vous appartient pas.")
        return redirect('resume_list')

    pending = JobMatch.objects.filter(resume=resume, user=request.user, is_unlocked=False)
    pending_count = pending.count()
    if pending_count == 0:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
            return JsonResponse({
                'success': False,
                'error': 'Aucune offre en attente à débloquer pour ce CV.',
                'redirect': reverse('find_jobs', kwargs={'resume_id': resume_id}),
            }, status=400)
        messages.warning(request, "Aucune offre à débloquer pour ce CV.")
        return redirect('find_jobs', resume_id=resume_id)

    if not consume_credit(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
            return JsonResponse({
                'success': False,
                'error': "Vous n'avez plus de crédits. Veuillez recharger votre compte pour utiliser l'analyse IA.",
                'redirect': reverse('pricing'),
            }, status=402)
        messages.error(
            request,
            "Vous n'avez plus de crédits. Veuillez recharger votre compte pour utiliser l'analyse IA.",
        )
        return redirect('pricing')

    try:
        pending.update(is_unlocked=True)
    except Exception as e:
        logger.exception("Erreur lors du déblocage des offres pour user_id=%s : %s", request.user.pk, e)
        refund_credit(request.user)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
            return JsonResponse({
                'success': False,
                'error': "Une erreur s'est produite. Aucun crédit n'a été décompté. Veuillez réessayer.",
                'redirect': reverse('find_jobs', kwargs={'resume_id': resume_id}),
            }, status=500)
        messages.error(request, "Une erreur s'est produite. Aucun crédit n'a été décompté. Veuillez réessayer.")
        return redirect('find_jobs', resume_id=resume_id)

    request.user.refresh_from_db()
    redirect_url = reverse('find_jobs', kwargs={'resume_id': resume_id}) + '?confirmed=1'
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
        return JsonResponse({
            'success': True,
            'redirect': redirect_url,
            'message': f'{pending_count} offre(s) débloquée(s).',
            'new_credits': getattr(request.user, 'ai_credits', 0) or 0,
        })
    messages.success(request, f'{pending_count} offre(s) débloquée(s).')
    return redirect(redirect_url)


@login_required
@require_POST
def update_match_status(request, match_id):
    # Récupérer le match sans filtrer par user (pour permettre les utilisateurs anonymes en développement)

    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
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
    Lors de l'implémentation de l'appel IA : déduire le crédit après succès ou rembourser dans except.
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    if request.method == 'POST':
        form = CoverLetterGenerationForm(request.POST)
        if form.is_valid():
            if not consume_credit(request.user):
                messages.error(
                    request,
                    "Vous n'avez plus de crédits. Veuillez recharger votre compte pour utiliser l'analyse IA.",
                )
                return redirect('pricing')
            try:
                # TODO: Implémenter la génération IA ici ; en cas d'exception, le except ci-dessous rembourse le crédit
                pass
            except Exception as e:
                refund_credit(request.user)
                logger.exception("Erreur génération lettre (generate_cover_letter) user_id=%s : %s", request.user.pk, e)
                messages.error(request, MSG_IA_SURCHARGE_NO_CREDIT)
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
    action = request.POST.get('action', 'improve')

    # --- export-pdf : pas d'IA, pas de crédit
    if action == 'export-pdf':
        current_text = request.POST.get('cover_letter_content', match.cover_letter_content)
        if not current_text:
            return JsonResponse({
                'success': False,
                'error': "Vous devez d'abord rédiger une lettre de motivation."
            }, status=400)
        try:
            generator = AILetterGenerator()
            user = request.user
            user_name = f"{user.first_name} {user.last_name}".strip() if (user.first_name or user.last_name) else user.email
            user_email = user.email if user.email else None
            job_offer = match.job_offer
            job_title = job_offer.title if job_offer else None
            company_name = job_offer.company_name if job_offer else None
            pdf_buffer = generator.export_to_pdf(
                cover_letter_content=current_text,
                user_name=user_name,
                user_email=user_email,
                user_address=None,
                job_title=job_title,
                company_name=company_name,
                recipient_name=None
            )
            import base64
            pdf_base64 = base64.b64encode(pdf_buffer.read()).decode('utf-8')
            return JsonResponse({
                'success': True,
                'pdf_data': pdf_base64,
                'filename': f"lettre_motivation_{job_title or 'candidature'}_{company_name or 'entreprise'}.pdf".replace(' ', '_'),
                'message': 'PDF généré avec succès !'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f"Erreur lors de l'export PDF : {str(e)}"
            }, status=500)

    # --- generate : validation puis crédit puis IA (remboursement en cas d'erreur)
    if action == 'generate':
        resume = match.resume
        if not resume:
            resume = Resume.objects.filter(user=request.user, is_primary=True).first()
            if not resume:
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
        if not consume_credit(request.user):
            return JsonResponse({
                'success': False,
                'error': "Vous n'avez plus de crédits. Veuillez recharger votre compte pour utiliser l'analyse IA.",
                'redirect': reverse('pricing'),
            }, status=402)
        request.user.refresh_from_db()
        try:
            generator = AILetterGenerator()
            generated_letter = generator.generate_cover_letter(
                resume=resume,
                job_match=match,
                tone="professional",
                user_id=request.user.id,
            )
            return JsonResponse({
                'success': True,
                'refined_letter': generated_letter,
                'message': 'Lettre de motivation générée avec succès ! Vous pouvez maintenant la modifier et la sauvegarder.',
                'new_credits': getattr(request.user, 'ai_credits', 0) or 0,
            })
        except (BrokenPipeError, ConnectionError):
            refund_credit(request.user)
            logger.info("Client déconnecté (BrokenPipe/ConnectionError) lors de la génération lettre, crédit remboursé user_id=%s", request.user.pk)
            return JsonResponse({
                'success': False,
                'error': MSG_IA_SURCHARGE_NO_CREDIT,
            }, status=499)
        except FairUseExceeded:
            refund_credit(request.user)
            return JsonResponse({
                'success': False,
                'error': "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte). Ne vous inquiétez pas, AUCUN crédit n'a été décompté."
            }, status=429)
        except GeminiServiceUnavailable:
            refund_credit(request.user)
            return JsonResponse({
                'success': False,
                'error': MSG_IA_SURCHARGE_NO_CREDIT,
            }, status=503)
        except ValueError as e:
            refund_credit(request.user)
            return JsonResponse({
                'success': False,
                'error': f"Erreur de validation : {str(e)}. Aucun crédit n'a été décompté."
            }, status=400)
        except Exception as e:
            try:
                refund_credit(request.user)
            except Exception:
                pass
            try:
                logger.exception("Erreur lors de la génération de la lettre user_id=%s : %s", request.user.pk, e)
            except Exception:
                pass
            return JsonResponse({
                'success': False,
                'error': MSG_IA_SURCHARGE_JSON,
            }, status=503)

    # --- improve / formalize / grammar / length : validation du texte puis crédit puis IA
    current_text = request.POST.get('cover_letter_content', match.cover_letter_content)
    if not current_text:
        return JsonResponse({
            'success': False,
            'error': "Vous devez d'abord rédiger une lettre de motivation."
        }, status=400)
    if not consume_credit(request.user):
        return JsonResponse({
            'success': False,
            'error': "Vous n'avez plus de crédits. Veuillez recharger votre compte pour utiliser l'analyse IA.",
            'redirect': reverse('pricing'),
        }, status=402)

    request.user.refresh_from_db()
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
        final_instructions = generator._build_refinement_instructions(
            action_config['instructions'],
            action_config['type']
        )
        refined_letter = generator.refine_cover_letter(
            current_text,
            final_instructions,
            user_id=request.user.id,
        )
        match.cover_letter_content = refined_letter
        match.save()
        return JsonResponse({
            'success': True,
            'refined_letter': refined_letter,
            'message': 'Votre lettre a été améliorée avec succès !',
            'new_credits': getattr(request.user, 'ai_credits', 0) or 0,
        })
    except (BrokenPipeError, ConnectionError):
        refund_credit(request.user)
        logger.info("Client déconnecté lors de l'amélioration lettre, crédit remboursé user_id=%s", request.user.pk)
        return JsonResponse({
            'success': False,
            'error': MSG_IA_SURCHARGE_NO_CREDIT,
        }, status=499)
    except FairUseExceeded:
        refund_credit(request.user)
        return JsonResponse({
            'success': False,
            'error': "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte). Ne vous inquiétez pas, AUCUN crédit n'a été décompté."
        }, status=429)
    except GeminiServiceUnavailable:
        refund_credit(request.user)
        return JsonResponse({
            'success': False,
            'error': MSG_IA_SURCHARGE_NO_CREDIT,
        }, status=503)
    except ValueError as e:
        refund_credit(request.user)
        return JsonResponse({
            'success': False,
            'error': f"Erreur de validation : {str(e)}. Aucun crédit n'a été décompté."
        }, status=400)
    except Exception as e:
        try:
            refund_credit(request.user)
        except Exception:
            pass
        try:
            logger.exception("Erreur lors de l'amélioration de la lettre user_id=%s : %s", request.user.pk, e)
        except Exception:
            pass
        return JsonResponse({
            'success': False,
            'error': MSG_IA_SURCHARGE_JSON,
        }, status=503)


@login_required
@require_POST
def toggle_job_alert(request, resume_id):
    """
    Crée ou active/désactive l'alerte (JobAlert) pour un CV.
    Réservé aux utilisateurs Premium.
    """
    if not getattr(request.user, 'is_premium', False):
        return JsonResponse({
            'success': False,
            'error': "Les alertes email sont réservées aux abonnés Premium.",
            'redirect': '/subscriptions/pricing/',
        }, status=403)
    resume = get_object_or_404(Resume, id=resume_id, user=request.user)
    alert, created = JobAlert.objects.get_or_create(
        resume=resume,
        defaults={'is_active': True, 'last_checked': None}
    )
    if not created:
        alert.is_active = not alert.is_active
        alert.save(update_fields=['is_active'])
    return JsonResponse({
        'success': True,
        'is_active': alert.is_active,
        'message': 'Alerte activée.' if alert.is_active else 'Alerte désactivée.'
    })


@login_required
def job_alert_status(request, resume_id):
    """
    Retourne le statut de l'alerte pour un CV (pour afficher le toggle correctement).
    Les non-premium reçoivent is_active=False et can_use_alerts=False.
    """
    resume = get_object_or_404(Resume, id=resume_id, user=request.user)
    if not getattr(request.user, 'is_premium', False):
        return JsonResponse({
            'success': True,
            'is_active': False,
            'can_use_alerts': False,
        })
    alert = JobAlert.objects.filter(resume=resume).first()
    return JsonResponse({
        'success': True,
        'is_active': alert.is_active if alert else False,
        'can_use_alerts': True,
    })


@login_required
@require_POST
def optimize_cv_view(request, match_id):
    """
    Lance l'analyse d'adaptation du CV à l'offre (CV Optimizer) et retourne les suggestions en JSON.
    Appelée via AJAX depuis le workspace (bouton "Adapter mon CV à cette offre").
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    resume = match.resume
    if not resume:
        resume = Resume.objects.filter(user=request.user, is_primary=True).first()
        if not resume:
            resume = Resume.objects.filter(user=request.user).first()
    if not resume:
        return JsonResponse({
            'success': False,
            'error': "Aucun CV trouvé. Veuillez d'abord uploader un CV."
        }, status=400)
    if not resume.extracted_text or not resume.extracted_text.strip():
        return JsonResponse({
            'success': False,
            'error': "Le CV n'a pas de texte extrait. Veuillez ré-uploader le CV."
        }, status=400)
    job_offer = match.job_offer
    if not job_offer:
        return JsonResponse({
            'success': False,
            'error': "Offre d'emploi introuvable."
        }, status=400)

    if not consume_credit(request.user):
        return JsonResponse({
            'success': False,
            'error': "Vous n'avez plus de crédits. Veuillez recharger votre compte pour utiliser l'analyse IA.",
            'redirect': reverse('pricing'),
        }, status=402)

    request.user.refresh_from_db()
    try:
        optimizer = AIOptimizer()
        result = optimizer.optimize_for_offer(
            cv_text=resume.extracted_text,
            job_description=job_offer.description or '',
            job_title=job_offer.title or '',
            user_id=request.user.id,
        )
        return JsonResponse({
            'success': True,
            'data': result,
            'message': "Suggestions d'adaptation du CV générées avec succès.",
            'new_credits': getattr(request.user, 'ai_credits', 0) or 0,
        })
    except (BrokenPipeError, ConnectionError):
        refund_credit(request.user)
        logger.info("Client déconnecté lors de l'optimisation CV, crédit remboursé user_id=%s", request.user.pk)
        return JsonResponse({
            'success': False,
            'error': MSG_IA_SURCHARGE_NO_CREDIT,
        }, status=499)
    except FairUseExceeded:
        refund_credit(request.user)
        return JsonResponse({
            'success': False,
            'error': "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte). Ne vous inquiétez pas, AUCUN crédit n'a été décompté."
        }, status=429)
    except GeminiServiceUnavailable:
        refund_credit(request.user)
        return JsonResponse({
            'success': False,
            'error': MSG_IA_SURCHARGE_NO_CREDIT,
        }, status=503)
    except ValueError as e:
        refund_credit(request.user)
        return JsonResponse({
            'success': False,
            'error': str(e) + " Aucun crédit n'a été décompté."
        }, status=400)
    except Exception as e:
        try:
            refund_credit(request.user)
        except Exception:
            pass
        try:
            logger.exception("Erreur CV Optimizer user_id=%s : %s", request.user.pk, e)
        except Exception:
            pass
        return JsonResponse({
            'success': False,
            'error': MSG_IA_SURCHARGE_JSON,
        }, status=503)


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
            if not consume_credit(request.user):
                messages.error(
                    request,
                    "Vous n'avez plus de crédits. Veuillez recharger votre compte pour utiliser l'analyse IA.",
                )
                return redirect('pricing')
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
                    final_instructions,
                    user_id=request.user.id,
                )

                # Sauvegarder la lettre améliorée
                match.cover_letter_content = refined_letter
                match.save()

                messages.success(
                    request,
                    'Votre lettre de motivation a été améliorée avec succès !'
                )

                # Rediriger vers le workspace pour voir le résultat
                return redirect('application_workspace', match_id=match_id)

            except (BrokenPipeError, ConnectionError):
                try:
                    refund_credit(request.user)
                except Exception:
                    pass
                logger.info("Client déconnecté lors du raffinement lettre (refine_cover_letter), crédit remboursé user_id=%s", request.user.pk)
                messages.error(request, MSG_IA_SURCHARGE_NO_CREDIT)
                return redirect('refine_cover_letter', match_id=match_id)
            except FairUseExceeded:
                try:
                    refund_credit(request.user)
                except Exception:
                    pass
                messages.warning(
                    request,
                    "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte). Ne vous inquiétez pas, AUCUN crédit n'a été décompté."
                )
                return redirect('refine_cover_letter', match_id=match_id)
            except GeminiServiceUnavailable:
                try:
                    refund_credit(request.user)
                except Exception:
                    pass
                messages.error(request, MSG_IA_SURCHARGE_NO_CREDIT)
                return redirect('refine_cover_letter', match_id=match_id)
            except ValueError as e:
                try:
                    refund_credit(request.user)
                except Exception:
                    pass
                messages.error(request, f"Erreur de validation : {str(e)}. Aucun crédit n'a été décompté.")
                return redirect('refine_cover_letter', match_id=match_id)
            except Exception as e:
                try:
                    refund_credit(request.user)
                except Exception:
                    pass
                try:
                    logger.exception("Erreur lors de l'amélioration de la lettre (refine_cover_letter) user_id=%s : %s", request.user.pk, e)
                except Exception:
                    pass
                messages.error(request, MSG_IA_SURCHARGE_NO_CREDIT)
                return redirect('refine_cover_letter', match_id=match_id)
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
        user_name = f"{user.first_name} {user.last_name}".strip() if (user.first_name or user.last_name) else user.email
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