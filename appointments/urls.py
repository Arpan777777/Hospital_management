from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),

    path("register/", views.register, name="register"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),

    path("add_patient/", views.add_patient, name="add_patient"),
    path("patient_list/", views.patient_list, name="patient_list"),

    path("book_appointment/", views.book_appointment, name="book_appointment"),
    path("appointment_list/", views.appointment_list, name="appointment_list"),

    path("my-appointments/", views.my_appointments, name="my_appointments"),

    path("ai/", views.ai_recommend, name="ai_recommend"),
    path("ai-analytics/", views.ai_analytics, name="ai_analytics"),
    path("doctor/schedule/", views.doctor_schedule, name="doctor_schedule"),
    path("appointment/<int:appointment_id>/cancel/", views.cancel_appointment, name="cancel_appointment"),
    path("appointment/<int:appointment_id>/complete/", views.complete_appointment, name="complete_appointment"),
    path('patient/<int:patient_id>/history/', views.patient_history, name='patient_history'),
    path('my-reports/', views.my_medical_records, name='my_medical_records'),
    path('export-csv/', views.export_appointments_csv, name='export_appointments_csv'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('ai-explain/', views.ai_explain, name='ai_explain'),
    path('add-availability/', views.add_availability, name='add_availability'),
    path('profile/', views.patient_profile, name='patient_profile'),
    path('patient/<int:patient_id>/add-record/', views.add_medical_record, name='add_medical_record'),
    path('availability/calendar/', views.availability_calendar, name='availability_calendar'),
    path("appointment/<int:appointment_id>/reopen/", views.reopen_appointment, name="reopen_appointment"),
]










