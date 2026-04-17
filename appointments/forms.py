from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Patient, Appointment, Availability


class PatientRegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=100, required=True)
    last_name = forms.CharField(max_length=100, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=15, required=True)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone_number", "password1", "password2")


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ["slot", "reason"]  # patient/doctor will be set automatically in views.py

    def __init__(self, *args, **kwargs):
        preselected_slot_id = kwargs.pop("preselected_slot_id", None)
        super().__init__(*args, **kwargs)

        # Only free slots
        self.fields["slot"].queryset = Availability.objects.filter(is_booked=False).order_by("start_time")

        # Preselect slot if passed in URL (from AI page)
        if preselected_slot_id:
            try:
                self.fields["slot"].initial = Availability.objects.get(id=preselected_slot_id, is_booked=False)
            except Availability.DoesNotExist:
                pass
