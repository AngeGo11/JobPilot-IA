# users/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import logout
from .forms import UserRegisterForm

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user) # On connecte l'utilisateur directement après inscription
            messages.success(request, f'Compte créé pour {user.email} !')
            return redirect('dashboard') # Redirection vers le dashboard
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})



def logout_user(request):
    if request.method == 'POST':
        logout(request)
        messages.success(request, f'Déconnexion effectuée avec succès !')
        return redirect('home') # Redirection vers le dashboard
    return render(request, 'index.html')






