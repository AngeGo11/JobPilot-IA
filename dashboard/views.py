from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from matching.models import JobMatch
from django.core.paginator import Paginator
from django.db.models import Count, Case, When, IntegerField
import logging


@login_required
def dashboard(request):
    """
    Vue principale du tableau de bord : liste toutes les candidatures de l'utilisateur
    """
    # Exemple : Récupération des variables de session
    user_id = request.session.get('user_id')
    user_email = request.session.get('user_email')
    resume_count = request.session.get('resume_count', 0)
    
    # Vous pouvez utiliser ces variables comme vous le souhaitez
    # Par exemple, les passer au template ou les utiliser pour des calculs
    logging.info(f"Session - User ID: {user_id}, Email: {user_email}, Resume count: {resume_count}")
    
    matches = JobMatch.objects.filter(
        user=request.user
    ).exclude(
        status='rejected'
    ).select_related('job_offer').order_by('-matched_at', '-score')

    page_number = request.GET.get('page', 1)
    paginator = Paginator(matches, 10)
    page_obj = paginator.get_page(page_number)
    
    # Statistiques optimisées : une seule requête avec aggregate
    stats = matches.aggregate(
        total=Count('id'),
        new=Count(Case(When(status='new', then=1), output_field=IntegerField())),
        seen=Count(Case(When(status='seen', then=1), output_field=IntegerField())),
        applied=Count(Case(When(status='applied', then=1), output_field=IntegerField())),
    )


    
    return render(request, 'dashboard/dashboard.html', {
        'matches': matches,
        'stats': stats,
        'page_obj': page_obj
    })


@login_required
def application_workspace(request, match_id):
    """
    Workspace de candidature : vue détaillée avec split screen
    - Gauche : Description du poste
    - Droite : Éditeur de lettre de motivation
    """
    match = get_object_or_404(JobMatch, id=match_id, user=request.user)
    
    if request.method == 'POST':
        # Sauvegarde de la lettre de motivation
        cover_letter = request.POST.get('cover_letter_content', '')
        match.cover_letter_content = cover_letter
        
        # Si on marque comme "applied"
        if 'mark_as_applied' in request.POST:
            match.status = 'applied'
            messages.success(request, 'Candidature marquée comme "Postulé" !')
        elif 'save' in request.POST:
            messages.success(request, 'Lettre de motivation sauvegardée !')
        
        match.save()
        return redirect('application_workspace', match_id=match_id)
    
    return render(request, 'dashboard/detail.html', {
        'match': match,
        'job_offer': match.job_offer,
    })
