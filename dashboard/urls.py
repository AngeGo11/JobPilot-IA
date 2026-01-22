from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('application/<int:match_id>/', views.application_workspace, name='application_workspace'),
]
