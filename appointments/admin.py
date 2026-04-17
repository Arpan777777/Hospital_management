from django.contrib import admin
from .models import Patient, Appointment, Availability, Doctor, MedicalRecord # Ensure MedicalRecord is here

admin.site.register(Patient)
admin.site.register(Appointment)
admin.site.register(Availability)
admin.site.register(Doctor)
admin.site.register(MedicalRecord) 