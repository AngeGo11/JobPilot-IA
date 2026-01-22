from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from matching.models import JobMatch
from django.core.paginator import Paginator


@login_required
def dashboard(request):
    """
    Vue principale du tableau de bord : liste toutes les candidatures de l'utilisateur
    """
    matches = JobMatch.objects.filter(
        user=request.user
    ).exclude(
        status='rejected'
    ).select_related('job_offer').order_by('-matched_at', '-score')

    page_number = request.GET.get('page', 1)
    paginator = Paginator(matches, 10)
    page_obj = paginator.get_page(page_number)
    
    # Statistiques rapides
    stats = {
        'total': matches.count(),
        'new': matches.filter(status='new').count(),
        'seen': matches.filter(status='seen').count(),
        'applied': matches.filter(status='applied').count(),
    }
    
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
