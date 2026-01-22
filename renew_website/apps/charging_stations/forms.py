from django import forms
from django.core.validators import MinValueValidator, MaxValueValidator, EmailValidator
from .models import Station

# Common connector types for selection
CONNECTOR_TYPES = [
    ('CCS', 'CCS (Combo 2)'),
    ('Type2', 'Type 2 (Mennekes)'),
    ('CHAdeMO', 'CHAdeMO'),
    ('Type1', 'Type 1 (J1772)'),
    ('Tesla', 'Tesla Supercharger'),
    ('GB/T', 'GB/T (China)'),
]

class StationForm(forms.ModelForm):
    model = forms.CharField(
        required=False,
        help_text="Leave empty to auto-detect from OCPP connection"
    )
    
    class Meta:
        model = Station
        fields = [
            # Essential
            "model", "address", "latitude", "longitude",
            "connector_type", "power_output",
            # Secondary
            "status", "email"
        ]
        
        widgets = {
            # Essential fields
            "model": forms.TextInput(attrs={
                "class": "form-control form-control-user",
                "placeholder": "e.g., TACW22-G0135 (will be auto-detected if left empty)"
            }),
            "address": forms.TextInput(attrs={
                "class": "form-control form-control-user",
                "required": True,
                "placeholder": "123 Main St, City, Country"
            }),
            "latitude": forms.NumberInput(attrs={
                "class": "form-control form-control-user",
                "step": "0.000001",
                "min": "-90",
                "max": "90",
                "required": True,
                "placeholder": "42.123456"
            }),
            "longitude": forms.NumberInput(attrs={
                "class": "form-control form-control-user",
                "step": "0.000001",
                "min": "-180",
                "max": "180",
                "required": True,
                "placeholder": "23.456789"
            }),
            "connector_type": forms.Select(
                choices=CONNECTOR_TYPES,
                attrs={
                    "class": "form-control form-control-user",
                    "required": True
                }
            ),
            "power_output": forms.NumberInput(attrs={
                "class": "form-control form-control-user",
                "min": "1",
                "step": "0.1",
                "required": True,
                "placeholder": "e.g., 22.0"
            }),
            # Secondary fields
            "status": forms.Select(attrs={
                "class": "form-control form-control-user"
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control form-control-user",
                "placeholder": "owner@example.com"
            }),
        }
        
        labels = {
            "model": "Model Number",
            "address": "Address",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "connector_type": "Connector Type",
            "power_output": "Power Output (kW)",
            "status": "Status",
            "email": "Owner Email",
        }
        
        help_texts = {
            "model": "Manufacturer's model identifier",
            "power_output": "Maximum power output in kilowatts",
            "email": "For notifications and alerts",
        }