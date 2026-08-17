from django.urls import path

from . import views

app_name = "administration"

urlpatterns = [
    path("", views.overview, name="overview"),

    # Utilisateurs
    path("utilisateurs/", views.user_list, name="users"),
    path("utilisateurs/export/", views.export_users, name="export_users"),
    path("utilisateurs/<int:user_id>/", views.user_detail, name="user_detail"),
    path("utilisateurs/<int:user_id>/action/", views.user_action, name="user_action"),

    # Revenus
    path("revenus/", views.revenue, name="revenue"),

    # Contenu et matching
    path("contenu/", views.content, name="content"),

    # Paramètres
    path("parametres/", views.site_settings, name="settings"),

    # Supervision
    path("supervision/", views.supervision, name="supervision"),
    path("supervision/sante.json", views.health_json, name="health_json"),

    # Journal d'audit
    path("journal/", views.audit, name="audit"),
]
