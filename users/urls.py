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

    # Connexion (On utilise la vue standard Django mais avec notre template et notre form)
    path('login/', auth_views.LoginView.as_view(
        template_name='users/login.html',
        authentication_form=UserLoginForm
    ), name='login'),

    # Déconnexion
    path('logout/', views.logout_user, name='logout'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password_reset.html',
        form_class=CustomPasswordResetForm
    ), name='password_reset'),

    # Django a besoin de cette URL pour dire "Email envoyé !"
    # Pour l'instant on utilise le template par défaut de Django pour aller vite,
    # mais tu pourras le styliser plus tard.
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
]