from django.urls import path
from . import views

urlpatterns = [
    path('pricing/', views.pricing_view, name='pricing'),
    path('create-checkout/', views.create_checkout, name='create_checkout'),
    path('success/', views.success_view, name='subscription_success'),
    path('cancel/', views.cancel_view, name='subscription_cancel'),
    path('webhook/', views.stripe_webhook, name='stripe_webhook'),
]