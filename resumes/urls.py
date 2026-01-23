from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.upload_resume, name='upload_resume'),
    path('', views.resume_list, name='resume_list'),
    path('delete/<int:resume_id>/', views.delete_resume, name='delete_resume'),

]