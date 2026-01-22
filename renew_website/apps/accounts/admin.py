from django.contrib import admin

from . models import UserProfile, UserPosition

admin.site.register(UserProfile)
admin.site.register(UserPosition)