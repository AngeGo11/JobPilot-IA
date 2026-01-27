from django.shortcuts import render, redirect


def pricing_view(request):
    """
    Vue pour afficher la page de tarification.
    """
    return render(request, 'subscriptions/pricing.html')


