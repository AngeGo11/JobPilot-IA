from django import forms
from .models import Resume

class ResumeUploadForm(forms.ModelForm):
    class Meta:
        model = Resume
        fields = ['title', 'file'] # On demande juste un titre et le fichier
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all',
                'placeholder': 'Ex: CV Développeur Python'
            }),
            'file': forms.FileInput(attrs={
                'class': 'hidden',
                'accept': '.pdf,application/pdf'
            }),
        }