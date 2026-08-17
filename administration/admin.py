"""
Exposition minimale dans l'admin Django natif.

Le back-office `/administration/` est l'interface de travail ; ces
enregistrements servent de filet de sécurité (lecture du journal, réglages en
cas de problème sur le back-office) et restent en lecture seule pour l'audit,
qui perdrait toute valeur s'il était modifiable.
"""
from django.contrib import admin

from .models import AdminAuditLog, SiteSettings, TaskRun, Testimonial


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "maintenance_mode", "registrations_open", "updated_at", "updated_by")
    readonly_fields = ("updated_at", "updated_by")

    def has_add_permission(self, request):
        # Singleton : la ligne est créée par SiteSettings.load().
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("target", "actor__email")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "started_at", "finished_at", "items_processed")
    list_filter = ("name", "status")
    date_hierarchy = "started_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("author_name", "author_role", "result_metric", "is_published", "display_order")
    list_filter = ("is_published",)
    search_fields = ("author_name", "quote")
    list_editable = ("is_published", "display_order")
