"""
URL configuration for JobPilot project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('mentions-legales/', TemplateView.as_view(template_name='mentions_legales.html'), name='mentions_legales'),
    path('politique-confidentialite/', TemplateView.as_view(template_name='politiques_et_confidentialites.html'), name='politique_confidentialite'),
    path('cgu/', TemplateView.as_view(template_name='CGU.html'), name='cgu'),
    path('users/', include('users.urls')),
    path('resumes/', include('resumes.urls')),
    path('matching/', include('matching.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('subscriptions/', include('subscriptions.urls')),
    path('accounts/', include('allauth.urls')),
]

# Permet de servir les fichiers médias en mode DEBUG (Dev)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
