"""
Formulaires pour la génération de lettres de motivation par IA.
"""
from django import forms


class CoverLetterGenerationForm(forms.Form):
    """
    Formulaire pour personnaliser la génération de la lettre de motivation.
    """
    custom_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea
    )
    
    tone = forms.ChoiceField(
        choices=[
            ('professional', 'Professionnel'),
            ('enthusiastic', 'Enthousiaste'),
            ('formal', 'Formel'),
        ],
        required=False
    )


class CoverLetterEditForm(forms.Form):
    """
    Formulaire pour éditer une lettre de motivation générée.
    """
    cover_letter_content = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 20,
            'class': 'w-full border border-slate-300 rounded-lg p-4 text-slate-700 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none font-mono text-sm'
        })
    )


class CoverLetterRefineForm(forms.Form):
    """
    Formulaire pour améliorer une lettre de motivation avec des instructions personnalisées.
    """
    instructions = forms.CharField(
        label="Instructions d'amélioration",
        help_text="Décrivez comment vous souhaitez améliorer votre lettre (ex: 'Rends-la plus courte', 'Ajoute plus d'enthousiasme', 'Corrige les fautes d'orthographe')",
        widget=forms.Textarea(attrs={
            'rows': 4,
            'class': 'w-full border border-slate-300 rounded-lg p-4 text-slate-700 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none',
            'placeholder': 'Exemples:\n- Rends-la plus concise (200 mots max)\n- Ajoute plus d\'enthousiasme et de dynamisme\n- Corrige toutes les fautes d\'orthographe et de grammaire\n- Rends le ton plus formel\n- Mets en avant mes compétences en Python et Django'
        }),
        required=True
    )
    
    improvement_type = forms.ChoiceField(
        label="Type d'amélioration",
        choices=[
            ('custom', 'Personnalisé (selon mes instructions)'),
            ('grammar', 'Correction orthographe et grammaire'),
            ('tone', 'Amélioration du ton (plus professionnel)'),
            ('length', 'Optimisation de la longueur'),
            ('structure', 'Amélioration de la structure'),
        ],
        required=False,
        initial='custom',
        widget=forms.Select(attrs={
            'class': 'w-full border border-slate-300 rounded-lg p-2 text-slate-700 focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        })
)
