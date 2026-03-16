"""
Professional Admin Interface for EV Charging Platform
Complete CRUD operations with advanced features.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.db import models
from django.forms import ModelForm
from django import forms
import json

from ..accounts.models import UserProfile


class AdvancedAdminMixin:
    """Mixin for advanced admin features."""
    
    def get_queryset(self, request):
        """Optimize queryset with select_related/prefetch_related."""
        qs = super().get_queryset(request)
        return qs.select_related(*self.select_related_fields).prefetch_related(*self.prefetch_related_fields)
    
    def has_add_permission(self, request):
        """Control add permissions based on user role."""
        if request.user.is_superuser:
            return True
        return super().has_add_permission(request)
    
    def has_change_permission(self, request, obj=None):
        """Control change permissions based on user role."""
        if request.user.is_superuser:
            return True
        return super().has_change_permission(request, obj)
    
    def has_delete_permission(self, request, obj=None):
        """Control delete permissions based on user role."""
        if request.user.is_superuser:
            return True
        return super().has_delete_permission(request, obj)


# ===== USER MANAGEMENT =====

class UserProfileInline(admin.StackedInline):
    """Inline user profile editing."""
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'


class CustomUserAdmin(UserAdmin):
    """Enhanced user admin with profile."""
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )


# ===== CHARGING STATIONS =====

# StationAdmin removed due to duplication in charging_stations/admin.py


# ===== ENERGY MANAGEMENT =====

# Inverter/Reading Admin removed due to duplication in api/energy/admin.py


# ===== ADMIN CUSTOMIZATION =====

# Register custom admin
admin.site.site_title = "EV Charging Platform Admin"
admin.site.site_header = "EV Charging Platform Administration"
admin.site.index_title = "Welcome to EV Charging Platform Admin"

# Register custom user admin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
