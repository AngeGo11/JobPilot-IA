# users/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View
from .forms import UserRegisterForm, UserLoginForm, UserUpdateForm, CustomPasswordChangeForm
from .models import CandidateProfile
import logging

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            CandidateProfile.objects.get_or_create(user=user)
            login(request, user) # On connecte l'utilisateur directement après inscription
            request.session["user_id"] = user.id
            messages.success(request, f'Compte créé pour {user.email} !')
            logging.info(request.session.get('user_id'))
            return redirect('dashboard') # Redirection vers le dashboard
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})



class CustomLoginView(LoginView):
    """
    Vue personnalisée pour la connexion qui permet de stocker des variables de session.
    """
    template_name = 'users/login.html'
    authentication_form = UserLoginForm
    
    def form_valid(self, form):
        """
        Appelé quand le formulaire de connexion est valide.
        On peut ici stocker des variables de session.
        """
        # Appeler la méthode parent pour effectuer la connexion
        response = super().form_valid(form)
        
        # Récupérer l'utilisateur connecté
        user = form.get_user()
        
        # Stocker des variables dans la session
        self.request.session['user_id'] = user.id
        self.request.session['user_email'] = user.email
        self.request.session['user_username'] = user.username
        self.request.session['login_time'] = str(self.request.user.last_login) if self.request.user.last_login else None
        
        # Vous pouvez ajouter d'autres variables de session ici
        # Exemple : nombre de CVs, dernière activité, etc.
        from resumes.models import Resume
        resume_count = Resume.objects.filter(user=user).count()
        self.request.session['resume_count'] = resume_count
        
        # Message de bienvenue
        messages.success(self.request, f'Bienvenue {user.get_full_name()} !')
        
        # Sauvegarder la session
        self.request.session.save()
        
        return response


def logout_user(request):
    if request.method == 'POST':
        logout(request)
        request.session.flush()
        messages.success(request, f'Déconnexion effectuée avec succès !')
    return render(request, '../templates/users/login.html')


class UserSettingsView(LoginRequiredMixin, View):
    """
    Vue pour la page de paramètres utilisateur.
    Permet de modifier les informations personnelles (prénom, nom, email).
    """
    template_name = 'users/settings.html'
    
    def get(self, request):
        form = UserUpdateForm(instance=request.user)
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        form = UserUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Vos informations ont été mises à jour.')
            return redirect('user_settings')
        return render(request, self.template_name, {'form': form})






