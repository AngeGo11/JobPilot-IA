from django.urls import path
from . import views

urlpatterns = [
    path('search/<int:resume_id>/', views.find_jobs_for_resume, name='find_jobs'),
# Nouvelle route pour changer le statut
    path('update-status/<int:match_id>/', views.update_match_status, name='update_match_status'),
    # Routes pour la génération de lettres de motivation par IA
    path('generate-letter/<int:match_id>/', views.generate_cover_letter, name='generate_cover_letter'),
    path('save-letter/<int:match_id>/', views.save_generated_letter, name='save_generated_letter'),
    path('edit-letter/<int:match_id>/', views.edit_cover_letter, name='edit_cover_letter'),
    path('refine-letter/<int:match_id>/', views.refine_cover_letter, name='refine_cover_letter'),
    path('quick-refine-letter/<int:match_id>/', views.quick_refine_cover_letter, name='quick_refine_cover_letter'),
]