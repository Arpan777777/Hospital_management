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

    return render(request, "appointments/book_appointment.html", {"form": form})



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
    profile = request.user.profile
    if not profile.patient:
        # if user has no linked Patient record yet
        return render(request, "appointments/my_appointments.html", {"appointments": []})

    appointments = Appointment.objects.filter(patient=profile.patient).order_by("-appointment_date")
    return render(request, "appointments/my_appointments.html", {"appointments": appointments})

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


MEDICAL_DICTIONARY = {
    # Diagnoses
    "acute seasonal influenza": "This is the common flu. It is a viral infection that affects your nose, throat and lungs. Symptoms include fever, body aches, cough and tiredness. It usually gets better in 1-2 weeks with rest and fluids.",
    "influenza": "The flu is a common viral infection affecting your breathing system. It causes fever, body aches, cough and fatigue. Most people recover within 1-2 weeks with rest and plenty of fluids.",
    "hypertension": "This means your blood pressure is too high. It puts extra strain on your heart and blood vessels. It can be managed with medication, a healthy diet, regular exercise and reducing salt intake.",
    "diabetes": "A condition where your body cannot properly control blood sugar levels. Type 1 means your body does not make insulin. Type 2 means your body does not use insulin well. Both are manageable with diet, exercise and sometimes medication.",
    "pneumonia": "An infection that inflames the air sacs in your lungs. It can cause cough, fever, chills and difficulty breathing. It is usually treated with antibiotics and rest.",
    "asthma": "A condition where your airways become narrow and swollen, making it hard to breathe. It can cause wheezing, coughing and shortness of breath. It is managed with inhalers.",
    "bronchitis": "Inflammation of the tubes that carry air to your lungs. It causes coughing, mucus and shortness of breath. Acute bronchitis usually clears up in a few weeks.",
    "gastroenteritis": "Often called a stomach bug. It is inflammation of the stomach and intestines usually caused by a virus or bacteria. Symptoms include nausea, vomiting, diarrhoea and stomach cramps.",
    "migraine": "A severe type of headache that can cause intense throbbing pain, usually on one side of the head. It can also cause nausea and sensitivity to light and sound.",
    "eczema": "A skin condition that makes your skin red, itchy and inflamed. It is not contagious and can be managed with moisturisers and prescribed creams.",
    "dermatitis": "Inflammation of the skin causing redness, itching and sometimes blisters. It can be caused by allergies, irritants or other factors. Treatment depends on the cause.",
    "arthritis": "Inflammation of one or more joints causing pain and stiffness. There are many types but the most common are osteoarthritis and rheumatoid arthritis. It can be managed with medication and physiotherapy.",
    "osteoarthritis": "A type of arthritis where the protective cartilage on the ends of your bones wears down over time. It causes pain and stiffness mainly in knees, hips and hands.",
    "fracture": "A broken bone. It can range from a small crack to a complete break. Treatment usually involves keeping the bone in place with a cast or splint while it heals.",
    "sprain": "An injury to a ligament which is the tissue connecting bones. It usually happens when a joint is twisted awkwardly. Rest, ice and elevation help it heal.",
    "anaemia": "A condition where you do not have enough red blood cells or haemoglobin to carry oxygen around your body. It can cause tiredness, weakness and pale skin.",
    "urinary tract infection": "An infection in any part of your urinary system including kidneys, bladder and urethra. It causes a burning sensation when urinating and frequent urination. Treated with antibiotics.",
    "uti": "A urinary tract infection — an infection in your urinary system causing burning when urinating and frequent urges to urinate. Treated with antibiotics.",
    "tonsillitis": "Inflammation of the tonsils at the back of your throat. It causes a sore throat, difficulty swallowing and fever. It is often caused by a virus or bacteria.",
    "appendicitis": "Inflammation of the appendix which is a small pouch attached to your large intestine. It causes severe pain in the lower right abdomen and usually requires surgery.",
    "depression": "A mental health condition causing persistent feelings of sadness, hopelessness and loss of interest in activities. It is very treatable with therapy, medication or a combination of both.",
    "anxiety": "A feeling of worry and fear that is strong enough to interfere with daily life. It is very common and treatable with therapy, lifestyle changes and sometimes medication.",

    # Treatments
    "oseltamivir": "This is an antiviral medication commonly known as Tamiflu. It is used to treat and prevent influenza (flu). It works by stopping the flu virus from spreading in your body.",
    "oseltamivir 75mg": "This is a 75 milligram dose of Tamiflu, an antiviral medicine for treating flu. It is taken twice a day for 5 days to help reduce how long and how severe your flu symptoms are.",
    "amoxicillin": "A common antibiotic used to treat bacterial infections such as chest infections, dental infections and urinary tract infections. It is important to finish the full course even if you feel better.",
    "ibuprofen": "A painkiller and anti-inflammatory medicine used to reduce pain, fever and swelling. It is commonly used for headaches, muscle pain and period pain. Take with food to protect your stomach.",
    "paracetamol": "A common painkiller used to treat mild to moderate pain and reduce fever. It is one of the safest pain medicines when taken as directed.",
    "metformin": "A medicine used to treat type 2 diabetes. It helps control blood sugar levels by reducing the amount of sugar your liver releases and making your body more sensitive to insulin.",
    "salbutamol": "A reliever inhaler medicine for asthma and other breathing conditions. It works quickly to relax the muscles around your airways making it easier to breathe.",
    "antibiotic": "A medicine that kills or stops the growth of bacteria. It is used to treat bacterial infections. Always complete the full course even if you feel better to prevent resistance.",
    "antihistamine": "A medicine that reduces allergic reactions. It blocks the effects of histamine which your body releases during an allergic reaction. Used for hay fever, skin rashes and insect bites.",
    "steroid": "A medicine that reduces inflammation in the body. It is used for many conditions including asthma, arthritis and skin conditions. It is different from performance-enhancing steroids used illegally in sport.",

    # Procedures and medical terms
    "blood pressure": "The force of blood pushing against the walls of your arteries as your heart pumps. Normal blood pressure is around 120/80. High blood pressure is called hypertension.",
    "ecg": "Electrocardiogram — a painless test that records the electrical activity of your heart. It is used to check your heart rhythm and detect any heart problems.",
    "mri": "Magnetic Resonance Imaging — a scan that uses magnetic fields and radio waves to create detailed images of the inside of your body. It is painless and does not use radiation.",
    "x-ray": "A type of scan that uses radiation to create images of the inside of your body. It is commonly used to look at bones and detect fractures.",
    "blood test": "A test where a small sample of blood is taken from a vein. It can check many things including blood sugar, cholesterol, infections and organ function.",
    "vaccination": "An injection that helps your immune system learn to fight a specific disease without you getting sick. It is one of the most effective ways to prevent serious illness.",
    "physiotherapy": "A type of treatment that uses physical methods such as exercise, massage and heat to treat injuries and conditions. It helps restore movement and reduce pain.",
    "biopsy": "A procedure where a small sample of tissue is taken from your body and examined under a microscope to check for disease or cancer.",
    "prescription": "A written instruction from a doctor authorising you to receive a specific medicine from a pharmacist. Always follow the dosage instructions on your prescription.",
    "diagnosis": "The identification of a disease or condition based on your symptoms, medical history and test results. It is the first step in deciding the right treatment.",
    "chronic": "A condition that lasts a long time, usually more than three months. Chronic conditions are often managed rather than cured, for example diabetes or asthma.",
    "acute": "A condition that comes on suddenly and is usually short-lived. For example, an acute infection develops quickly but can be treated and goes away.",
    "inflammation": "Your body's response to injury or infection. The affected area becomes red, swollen, warm and painful. It is part of the healing process but can be harmful if it continues too long.",
    "infection": "When harmful microorganisms such as bacteria, viruses or fungi enter your body and multiply, causing illness. Infections can be treated with antibiotics or antiviral medicines depending on the cause.",
    "fever": "A body temperature above the normal range of 37 degrees Celsius. It is usually a sign that your body is fighting an infection. Rest and paracetamol can help reduce fever.",
    "hypertension": "High blood pressure. This means the force of blood against your artery walls is consistently too high. It can lead to heart disease and stroke if not treated.",
    "cholesterol": "A fatty substance found in your blood. Some cholesterol is needed by your body but too much can build up in your arteries and increase the risk of heart disease.",
    "cardiac": "Relating to the heart. For example, cardiac arrest means the heart has stopped pumping blood around the body.",
    "pulmonary": "Relating to the lungs. For example, pulmonary disease means a disease affecting the lungs.",
    "renal": "Relating to the kidneys. For example, renal failure means the kidneys are not working properly.",
    "cerebral": "Relating to the brain. For example, a cerebral stroke means a stroke affecting the brain.",
    "bed rest": "A period of resting in bed recommended by a doctor to help your body recover from illness or injury. It allows your body to focus its energy on healing.",
    "fluid intake": "The amount of liquid you drink. Increasing fluid intake means drinking more water and other liquids. This helps prevent dehydration especially during illness.",
    "increased fluid intake": "Your doctor is recommending you drink more water and liquids than usual. This helps flush out infections and keeps your body hydrated during recovery.",
}

@login_required
@require_POST
def ai_explain(request):
    try:
        data = json.loads(request.body)
        term = data.get('term', '').strip()

        if not term:
            return JsonResponse({'explanation': 'No term provided.'})

        import urllib.request
        import urllib.parse

        API_NINJAS_KEY = 'tmnrEC3pY6m2oVViys8nbDqd8a1uXQVIIulKjARk'

        # Use API Ninjas dictionary API to get word definition
        encoded_term = urllib.parse.quote(term)
        url = f'https://api.api-ninjas.com/v1/dictionary?word={encoded_term}'

        req = urllib.request.Request(
            url,
            headers={'X-Api-Key': API_NINJAS_KEY},
            method='GET'
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            definition = result.get('definition', '')

            if definition:
                # Clean up and shorten the definition
                explanation = definition[:300]
                return JsonResponse({'explanation': explanation})
            else:
                # Fallback to dictionary if no result
                return JsonResponse({'explanation': get_medical_explanation(term)})

    except Exception as e:
        return JsonResponse({'explanation': get_medical_explanation(term)})


def get_medical_explanation(term):
    """Fallback medical dictionary"""
    term_lower = term.lower().strip()
    explanation = MEDICAL_DICTIONARY.get(term_lower)
    if not explanation:
        for key in MEDICAL_DICTIONARY:
            if key in term_lower or term_lower in key:
                explanation = MEDICAL_DICTIONARY[key]
                break
    if not explanation:
        explanation = f'"{term}" is a medical term. Please ask your doctor or pharmacist for a personalised explanation.'
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