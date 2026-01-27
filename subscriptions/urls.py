from django.urls import path
from . import views



urlpatterns = [
# Page de tarification
    path('pricing/', views.pricing_view, name='pricing'),
]