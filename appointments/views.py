from unittest import result

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth import login, logout
from django.contrib import messages
from .models import Patient, Appointment, Availability
from .forms import AppointmentForm, PatientRegisterForm
from .ai import recommend_slots
from .models import Doctor
from django.utils import timezone
from datetime import time, timedelta
from .models import Appointment
from .permissions import role_required
from .models import Patient, Appointment, Availability, Doctor, MedicalRecord 
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
from django.core.mail import send_mail
from django.template.loader import render_to_string

@role_required("ADMIN")
def add_availability(request):
    doctors = Doctor.objects.all()
    if request.method == "POST":
        doctor_id = request.POST.get("doctor")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")

        try:
            doctor = Doctor.objects.get(id=doctor_id)
            Availability.objects.create(
                doctor=doctor,
                start_time=start_time,
                end_time=end_time,
                is_booked=False
            )
            messages.success(request, "Availability slot added successfully.")
            return redirect("add_availability")
        except Exception as e:
            messages.error(request, f"Error adding slot: {str(e)}")

    return render(request, "appointments/add_availability.html", {"doctors": doctors})

def register(request):
    if request.method == "POST":
        form = PatientRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data["email"]
            user.first_name = form.cleaned_data["first_name"]
            user.last_name = form.cleaned_data["last_name"]
            user.save()

            # Create Patient record
            patient = Patient.objects.create(
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                email=form.cleaned_data["email"],
                phone_number=form.cleaned_data["phone_number"]
            )

            # Link profile
            user.profile.role = "PATIENT"
            user.profile.patient = patient
            user.profile.save()

            messages.success(request, "Account created successfully. Please login.")
            return redirect("login")
    else:
        form = PatientRegisterForm()

    return render(request, "appointments/register.html", {"form": form})

def home(request):
    return render(request, "appointments/home.html")

def user_login(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)

            # ✅ role-based redirect
            role = getattr(getattr(user, "profile", None), "role", "PATIENT")

            if role == "ADMIN":
                return redirect("patient_list")
            elif role == "DOCTOR":
                return redirect("doctor_schedule")
            else:
                return redirect("home")
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()

    return render(request, "appointments/login.html", {"form": form})



def user_logout(request):
    logout(request)
    return redirect("login")


@role_required("ADMIN")
def add_patient(request):
    if request.method == "POST":
        Patient.objects.create(
            first_name=request.POST["first_name"],
            last_name=request.POST["last_name"],
            email=request.POST["email"],
            phone_number=request.POST["phone_number"],
        )
        messages.success(request, "Patient added successfully.")
        return redirect("patient_list")

    return render(request, "appointments/add_patient.html")


@role_required("ADMIN", "DOCTOR")
def patient_list(request):
    query = request.GET.get('q', '')
    if query:
        patients = Patient.objects.filter(
            first_name__icontains=query
        ) | Patient.objects.filter(
            last_name__icontains=query
        ) | Patient.objects.filter(
            email__icontains=query
        )
    else:
        patients = Patient.objects.all()
    return render(request, "appointments/patient_list.html", {
        "patients": patients,
        "query": query
    })


@role_required("ADMIN", "DOCTOR")
def appointment_list(request):
    appointments = Appointment.objects.all()
    return render(request, "appointments/appointment_list.html", {"appointments": appointments})


@role_required("PATIENT")
def book_appointment(request):
    slot_id = request.GET.get("slot_id")
    prefill_reason = request.GET.get("reason", "")

    if request.method == "POST":
        form = AppointmentForm(request.POST, preselected_slot_id=slot_id)
        if form.is_valid():
            appointment = form.save(commit=False)

            # patient from logged-in account
            profile = request.user.profile
            if not profile.patient:
                messages.error(request, "This account is not linked to a Patient record.")
                return redirect("home")

            appointment.patient = profile.patient

            # slot chosen
            slot = appointment.slot
            if not slot:
                messages.error(request, "Please choose a valid slot.")
                return redirect("book_appointment")

            # ✅ MUST set doctor + date (fixes your error)
            appointment.doctor = slot.doctor
            appointment.appointment_date = slot.start_time

            appointment.save()

            # mark slot booked
            slot.is_booked = True
            slot.save()

            messages.success(request, "Appointment booked successfully!")
            return redirect("my_appointments")
    else:
        form = AppointmentForm(preselected_slot_id=slot_id)

    return render(request, "appointments/book_appointment.html", {
    "form": form,
    "prefill_reason": prefill_reason
})



@role_required("DOCTOR")
def doctor_schedule(request):
    doctor = request.user.profile.doctor
    if not doctor:
        messages.error(request, "This doctor account is not linked to a Doctor record.")
        return redirect("home")

    appointments = Appointment.objects.filter(doctor=doctor).order_by("appointment_date")
    return render(request, "appointments/doctor_schedule.html", {"appointments": appointments, "doctor": doctor})


@login_required
def ai_recommend(request):
    doctors = Doctor.objects.all()
    specializations = sorted({d.specialization for d in doctors if d.specialization})

    recommended = []
    reason = ""
    preferred_specialization = ""

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        preferred_specialization = request.POST.get("preferred_specialization", "").strip()

        preferred = preferred_specialization if preferred_specialization else None
        recommended = recommend_slots(reason, preferred, top_n=3)

        # Debug message so you KNOW it posted
        if not recommended:
            messages.warning(request, "No slots found. Add free availability slots or remove specialization filter.")

    return render(request, "appointments/ai_recommend.html", {
        "recommended": recommended,
        "reason": reason,
        "specializations": specializations,
        "preferred_specialization": preferred_specialization,
    })

@login_required
def ai_analytics(request):
    now = timezone.now()
    start = now - timedelta(days=30)

    appts = Appointment.objects.filter(appointment_date__gte=start).values_list("appointment_date", flat=True)

    hours = [0] * 24
    days = [0] * 7  # 0=Mon ... 6=Sun

    for dt in appts:
        hours[dt.hour] += 1
        days[dt.weekday()] += 1

    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    context = {
        "hours": hours,
        "days": days,
        "day_labels": day_labels,
        "total_30d": len(appts),
    }
    return render(request, "appointments/ai_analytics.html", context)

@role_required("PATIENT")
def my_appointments(request):
    from django.utils import timezone
    profile = request.user.profile
    appointments = Appointment.objects.filter(
        patient=profile.patient,
        appointment_date__gte=timezone.now()
    ).order_by('appointment_date')
    return render(request, 'appointments/my_appointments.html', {
        'appointments': appointments
    })

@role_required("ADMIN", "DOCTOR", "PATIENT")
def cancel_appointment(request, appointment_id):
    appt = Appointment.objects.get(id=appointment_id)

    role = request.user.profile.role

    # Permission rules
    if role == "PATIENT" and appt.patient != request.user.profile.patient:
        messages.error(request, "You cannot cancel someone else's appointment.")
        return redirect("home")

    if role == "DOCTOR" and appt.doctor != request.user.profile.doctor:
        messages.error(request, "You cannot cancel an appointment not assigned to you.")
        return redirect("home")

    # Free the slot if exists
    if appt.slot:
        appt.slot.is_booked = False
        appt.slot.save()

    appt.delete()
    messages.success(request, "Appointment cancelled successfully.")

    # Redirect by role
    if role == "PATIENT":
        return redirect("my_appointments")
    if role == "DOCTOR":
        return redirect("doctor_schedule")
    return redirect("appointment_list")


@role_required("ADMIN", "DOCTOR")
def complete_appointment(request, appointment_id):
    appt = Appointment.objects.get(id=appointment_id)

    # doctor can only complete their own
    if request.user.profile.role == "DOCTOR":
        if appt.doctor != request.user.profile.doctor:
            messages.error(request, "You cannot complete an appointment not assigned to you.")
            return redirect("home")




    appt.status = "completed"
    appt.save()
    messages.success(request, "Appointment marked as completed.")
    return redirect("doctor_schedule" if request.user.profile.role == "DOCTOR" else "appointment_list")

@role_required("ADMIN", "DOCTOR")
def reopen_appointment(request, appointment_id):
    appt = Appointment.objects.get(id=appointment_id)

    if request.user.profile.role == "DOCTOR":
        if appt.doctor != request.user.profile.doctor:
            messages.error(request, "You cannot reopen an appointment not assigned to you.")
            return redirect("home")

    appt.status = "scheduled"
    appt.save()
    messages.success(request, "Appointment reopened successfully.")
    return redirect("doctor_schedule" if request.user.profile.role == "DOCTOR" else "appointment_list")

@role_required("ADMIN", "DOCTOR")
def patient_history(request, patient_id):
    patient = Patient.objects.get(id=patient_id)
    records = MedicalRecord.objects.filter(patient=patient).order_by('-date')
    return render(request, "appointments/patient_history.html", {
        "patient": patient,
        "records": records
    })


import csv
from django.http import HttpResponse

@role_required("ADMIN")
def export_appointments_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="appointments_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['Patient', 'Doctor', 'Date', 'Reason', 'Status'])

    appointments = Appointment.objects.all()
    for appt in appointments:
        writer.writerow([
            appt.patient, 
            appt.slot.doctor, 
            appt.appointment_date, 
            appt.reason, 
            appt.status
        ])

    return response


from django.db.models import Count

@login_required
@role_required("ADMIN")
def dashboard(request):
    total_patients = Patient.objects.count()
    total_appointments = Appointment.objects.count()
    
    # AI Logic: Find the doctor with the most appointments
    busiest_doctor = Doctor.objects.annotate(
        num_appts=Count('appointment')
    ).order_by('-num_appts').first()

    return render(request, "appointments/dashboard.html", {
        "total_patients": total_patients,
        "total_appointments": total_appointments,
        "busiest_doctor": busiest_doctor,
        "free_slots": Availability.objects.filter(is_booked=False).count(),
    })



@role_required("PATIENT")
def my_medical_records(request):
    # Fix: Get the patient by filtering through their profile
    try:
        patient = Patient.objects.get(profile=request.user.profile)
        records = MedicalRecord.objects.filter(patient=patient).order_by('-date')
    except Patient.DoesNotExist:
        records = []
        
    return render(request, "appointments/my_medical_records.html", {
        "records": records
    })




@login_required
@require_POST
def ai_explain(request):
    try:
        import urllib.request
        data = json.loads(request.body)
        term = data.get('term', '').strip()

        if not term:
            return JsonResponse({'explanation': 'No term provided.'})

        OPENROUTER_KEY = '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'

        payload = json.dumps({
            "model": "openrouter/auto",
            "messages": [
                {
                    "role": "user",
                    "content": f"Explain the medical term '{term}' in 2-3 simple sentences for a patient with no medical background. Be friendly and clear."
                }
            ]
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + OPENROUTER_KEY,
                'HTTP-Referer': 'http://127.0.0.1:8000',
                'X-Title': 'Hospital System'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            explanation = result['choices'][0]['message']['content']
            return JsonResponse({'explanation': explanation})

    except Exception as e:
        print(f"AI EXPLAIN ERROR: {str(e)}")
        return JsonResponse({'explanation': str(e)})
    
def get_medical_explanation(term):
    return f'"{term}" is a medical term. Our AI explainer is temporarily unavailable. Please ask your doctor for a personalised explanation.'
    from .ai import MEDICAL_DICTIONARY
    term_lower = term.lower().strip()
    explanation = MEDICAL_DICTIONARY.get(term_lower)
    if not explanation:
        for key in MEDICAL_DICTIONARY:
            if key in term_lower or term_lower in key:
                explanation = MEDICAL_DICTIONARY[key]
                break
    if not explanation:
        explanation = f'"{term}" is a medical term. Please ask your doctor for a personalised explanation.'
    return explanation

@role_required("PATIENT")
def patient_profile(request):
    profile = request.user.profile
    patient = profile.patient

    if not patient:
        messages.error(request, "No patient record linked to your account.")
        return redirect("home")

    if request.method == "POST":
        patient.first_name = request.POST.get("first_name", patient.first_name)
        patient.last_name = request.POST.get("last_name", patient.last_name)
        patient.email = request.POST.get("email", patient.email)
        patient.phone_number = request.POST.get("phone_number", patient.phone_number)
        patient.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("patient_profile")

    return render(request, "appointments/patient_profile.html", {
        "patient": patient
    })

@role_required( "DOCTOR")
def add_medical_record(request, patient_id):
    patient = Patient.objects.get(id=patient_id)
    doctors = Doctor.objects.all()

    if request.method == "POST":
        diagnosis = request.POST.get("diagnosis")
        treatment = request.POST.get("treatment")
        notes = request.POST.get("notes", "")
        doctor_id = request.POST.get("doctor")

        doctor = Doctor.objects.get(id=doctor_id)

        MedicalRecord.objects.create(
            patient=patient,
            doctor=doctor,
            diagnosis=diagnosis,
            treatment=treatment,
            notes=notes
        )
        messages.success(request, "Medical report added successfully.")
        return redirect("patient_history", patient_id=patient.id)

    return render(request, "appointments/add_medical_record.html", {
        "patient": patient,
        "doctors": doctors
    })



def send_appointment_email(appointment, action):
    """Send email notification for appointment actions"""
    patient_email = appointment.patient.email
    if not patient_email:
        return

    subject_map = {
        'booked':    '✅ Appointment Confirmed — Hospital System',
        'cancelled': '❌ Appointment Cancelled — Hospital System',
        'completed': '📋 Appointment Completed — Hospital System',
    }

    message_map = {
        'booked': f"""
Dear {appointment.patient.first_name},

Your appointment has been confirmed.

Doctor:   Dr. {appointment.doctor.first_name} {appointment.doctor.last_name}
Date:     {appointment.slot.start_time.strftime('%A, %d %B %Y')}
Time:     {appointment.slot.start_time.strftime('%H:%M')} — {appointment.slot.end_time.strftime('%H:%M')}
Reason:   {appointment.reason}

Please arrive 10 minutes early.

Hospital System
""",
        'cancelled': f"""
Dear {appointment.patient.first_name},

Your appointment has been cancelled.

Doctor:   Dr. {appointment.doctor.first_name} {appointment.doctor.last_name}
Date:     {appointment.slot.start_time.strftime('%A, %d %B %Y')}
Time:     {appointment.slot.start_time.strftime('%H:%M')}

The slot is now available for rebooking.

Hospital System
""",
        'completed': f"""
Dear {appointment.patient.first_name},

Your appointment has been marked as completed.

Doctor:   Dr. {appointment.doctor.first_name} {appointment.doctor.last_name}
Date:     {appointment.slot.start_time.strftime('%A, %d %B %Y')}

Please check your medical records in the system for any reports.

Hospital System
""",
    }

    try:
        send_mail(
            subject=subject_map.get(action, 'Appointment Update'),
            message=message_map.get(action, 'Your appointment has been updated.'),
            from_email=None,  # Uses DEFAULT_FROM_EMAIL from settings
            recipient_list=[patient_email],
            fail_silently=True,  # Won't crash if email fails
        )
    except Exception:
        pass  # Silent fail so app still works if email is not set up

@login_required
def availability_calendar(request):
    from django.utils import timezone
    slots = Availability.objects.select_related('doctor').filter(
        start_time__gte=timezone.now()
    ).order_by('start_time')
    doctors = Doctor.objects.all()
    return render(request, 'appointments/availability_calendar.html', {
        'slots': slots,
        'doctors': doctors,
    })
