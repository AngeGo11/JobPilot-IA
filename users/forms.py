from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordChangeForm, PasswordResetForm
from .models import CustomUser


class UserRegisterForm(UserCreationForm):
    first_name = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'w-full px-4 py-3 rounded-lg border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
        'placeholder': 'John'
    }))
    last_name = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'w-full px-4 py-3 rounded-lg border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
        'placeholder': 'Doe'
    }))
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        'class': 'w-full px-4 py-3 rounded-lg border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
        'placeholder': 'you@example.com'
    }))

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email']

    # On ajoute aussi le style pour le champ mot de passe (géré par UserCreationForm)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Masquer le champ username car on le génère automatiquement
        if 'username' in self.fields:
            self.fields['username'].widget = forms.HiddenInput()
        
        # Personnaliser les labels et help_text en français pour les champs de mot de passe
        if 'password1' in self.fields:
            self.fields['password1'].label = 'Mot de passe'
            # Le help_text n'est plus affiché par défaut, il est dans un tooltip au survol de l'icône info
            self.fields['password1'].help_text = ''
            # Personnaliser les messages d'erreur en français
            self.fields['password1'].error_messages = {
                'required': 'Ce champ est obligatoire.',
                'password_too_short': 'Ce mot de passe est trop court. Il doit contenir au moins 8 caractères.',
                'password_too_common': 'Ce mot de passe est trop commun.',
                'password_entirely_numeric': 'Ce mot de passe ne peut pas être entièrement numérique.',
            }
        
        if 'password2' in self.fields:
            self.fields['password2'].label = 'Confirmation du mot de passe'
            self.fields['password2'].help_text = 'Entrez le même mot de passe qu\'avant, pour vérification.'
            # Personnaliser les messages d'erreur en français
            self.fields['password2'].error_messages = {
                'required': 'Ce champ est obligatoire.',
                'password_mismatch': 'Les deux mots de passe ne correspondent pas.',
            }
        
        for field in self.fields:
            if field not in ['first_name', 'last_name', 'email', 'username']:
                 self.fields[field].widget.attrs.update({
                    'class': 'w-full px-4 py-3 rounded-lg border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
                    'placeholder': '••••••••'
                })
    
    def save(self, commit=True):
        user = super().save(commit=False)
        # Générer le username à partir de l'email (partie avant @)
        email = self.cleaned_data.get('email')
        if email:
            base_username = email.split('@')[0]
            username = base_username
            # S'assurer que le username est unique
            counter = 1
            while CustomUser.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            user.username = username
        
        if commit:
            user.save()
        return user

class UserLoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
            'placeholder': 'you@example.com'
        })
    )
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'w-full px-4 py-3 rounded-lg border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
        'placeholder': '••••••••'
    }))


    
    def clean_username(self):
        """
        Permet la connexion avec l'email au lieu du username.
        Si l'utilisateur entre un email, on trouve le username correspondant.
        """
        username_or_email = self.cleaned_data.get('username')
        
        # Si c'est un email (contient @), chercher l'utilisateur par email
        if '@' in username_or_email:
            # Utiliser filter().first() au lieu de get() pour gérer les doublons
            user = CustomUser.objects.filter(email=username_or_email).first()
            if user:
                return user.username
            else:
                raise forms.ValidationError(
                    "Aucun compte n'est associé à cet email.",
                    code='invalid_login',
                )
        
        # Sinon, utiliser le username tel quel
        return username_or_email


class CustomPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        'class': 'w-full px-4 py-3 rounded-lg border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
        'placeholder': 'you@example.com'
    }))


class UserUpdateForm(forms.ModelForm):
    """
    Formulaire pour mettre à jour les informations personnelles de l'utilisateur.
    """
    first_name = forms.CharField(
        label='Prénom',
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 focus:border-[#125484] focus:ring-2 focus:ring-[#125484]/20 outline-none transition-all',
            'placeholder': 'Jean'
        })
    )
    last_name = forms.CharField(
        label='Nom',
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 focus:border-[#125484] focus:ring-2 focus:ring-[#125484]/20 outline-none transition-all',
            'placeholder': 'Dupont'
        })
    )
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 focus:border-[#125484] focus:ring-2 focus:ring-[#125484]/20 outline-none transition-all',
            'placeholder': 'jean.dupont@example.com'
        })
    )

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email']


class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Formulaire personnalisé pour le changement de mot de passe avec widgets stylisés.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Styliser le champ ancien mot de passe
        self.fields['old_password'].widget.attrs.update({
            'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 focus:border-[#125484] focus:ring-2 focus:ring-[#125484]/20 outline-none transition-all',
            'placeholder': '••••••••'
        })
        self.fields['old_password'].label = 'Mot de passe actuel'
        
        # Styliser le champ nouveau mot de passe
        self.fields['new_password1'].widget.attrs.update({
            'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 focus:border-[#125484] focus:ring-2 focus:ring-[#125484]/20 outline-none transition-all',
            'placeholder': '••••••••'
        })
        self.fields['new_password1'].label = 'Nouveau mot de passe'
        
        # Styliser le champ confirmation
        self.fields['new_password2'].widget.attrs.update({
            'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 focus:border-[#125484] focus:ring-2 focus:ring-[#125484]/20 outline-none transition-all',
            'placeholder': '••••••••'
        })
        self.fields['new_password2'].label = 'Confirmer le nouveau mot de passe'