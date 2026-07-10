from django import forms
from django.core.exceptions import ValidationError
from .models import Resume

MAX_RESUME_SIZE = 10 * 1024 * 1024  # 10 Mo
PDF_MAGIC_BYTES = b'%PDF-'


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

    def clean_file(self):
        file = self.cleaned_data['file']

        if not file.name.lower().endswith('.pdf'):
            raise ValidationError("Seuls les fichiers PDF sont acceptés.")

        if file.content_type not in ('application/pdf', 'application/x-pdf'):
            raise ValidationError("Le type de fichier détecté n'est pas un PDF valide.")

        if file.size > MAX_RESUME_SIZE:
            raise ValidationError(f"Le fichier dépasse la taille maximale autorisée ({MAX_RESUME_SIZE // (1024 * 1024)} Mo).")

        header = file.read(len(PDF_MAGIC_BYTES))
        file.seek(0)
        if header != PDF_MAGIC_BYTES:
            raise ValidationError("Le contenu du fichier ne correspond pas à un PDF valide.")

        return file