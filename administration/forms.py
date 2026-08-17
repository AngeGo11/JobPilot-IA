from django import forms

from administration.models import SiteSettings

# Classes Tailwind réutilisées depuis les formulaires du site (users/forms.py).
INPUT_CLASSES = (
    "w-full px-4 py-2.5 rounded-lg border border-slate-300 text-slate-900 "
    "focus:outline-none focus:ring-2 focus:ring-[#125484] focus:border-[#125484] "
    "transition-colors"
)
CHECKBOX_CLASSES = (
    "h-5 w-5 rounded border-slate-300 text-[#125484] focus:ring-[#125484] cursor-pointer"
)


class SiteSettingsForm(forms.ModelForm):
    """Édition des paramètres généraux depuis le back-office."""

    class Meta:
        model = SiteSettings
        exclude = ("updated_at", "updated_by")
        widgets = {
            "maintenance_message": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = CHECKBOX_CLASSES
            else:
                field.widget.attrs["class"] = INPUT_CLASSES

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("maintenance_mode") and not cleaned.get("maintenance_message", "").strip():
            self.add_error(
                "maintenance_message",
                "Renseignez un message : il est affiché aux visiteurs pendant la coupure.",
            )
        return cleaned


class GrantCreditsForm(forms.Form):
    """Ajustement manuel du solde de crédits IA d'un utilisateur (geste commercial, litige)."""

    amount = forms.IntegerField(
        label="Crédits à ajouter",
        min_value=-1000,
        max_value=1000,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASSES, "placeholder": "ex. 10"}),
        help_text="Valeur négative pour retirer des crédits.",
    )
    reason = forms.CharField(
        label="Motif",
        max_length=200,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASSES, "placeholder": "ex. geste commercial – ticket #128"}
        ),
    )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == 0:
            raise forms.ValidationError("Indiquez une valeur différente de zéro.")
        return amount


class ExtendSubscriptionForm(forms.Form):
    """Prolongation manuelle d'un abonnement (dédommagement, incident de paiement)."""

    days = forms.IntegerField(
        label="Jours à ajouter",
        min_value=1,
        max_value=365,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASSES, "placeholder": "ex. 7"}),
    )
    reason = forms.CharField(
        label="Motif",
        max_length=200,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASSES, "placeholder": "ex. incident du 12/03"}
        ),
    )
