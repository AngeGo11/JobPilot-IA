# users/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import UserLoginForm, CustomPasswordResetForm  # Import du form de login

#     path('register/', views.register, name='register')
# views.register <== appel de la fonction register
# name = 'register' <== nom de l'URL quand on fait par exemple: {% url 'register' %}
#

urlpatterns = [
    # Inscription
    path('register/', views.register, name='register'),

    # Connexion (Vue personnalisée pour gérer les variables de session)
    path('login/', views.CustomLoginView.as_view(), name='login'),

    # Déconnexion
    path('logout/', views.logout_user, name='logout'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password_reset.html',
        form_class=CustomPasswordResetForm
    ), name='password_reset'),

    # Django a besoin de cette URL pour dire "Email envoyé !"
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password_reset_done.html'
    ), name='password_reset_done'),

    # Page du lien reçu par email (uidb64 + token)
    path('password-reset/confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password_reset_confirm.html'
    ), name='password_reset_confirm'),

    # Page "Mot de passe réinitialisé"
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password_reset_complete.html'
    ), name='password_reset_complete'),

    # Paramètres utilisateur
    path('settings/', views.UserSettingsView.as_view(), name='user_settings'),
    
    # Changement de mot de passe (vue Django standard avec formulaire personnalisé)
    path('password-change/', auth_views.PasswordChangeView.as_view(
        template_name='users/password_change.html',
        form_class=views.CustomPasswordChangeForm
    ), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='users/password_change_done.html'
    ), name='password_change_done'),

    # Page de chargement intermédiaire après login/inscription
    path('loading/', views.PostLoginLoadingView.as_view(), name='post_login_loading'),
]