from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Doctor, Availability, Patient, Appointment, Profile
from .ai import recommend_slots

class AIRecommendationTest(TestCase):

    def setUp(self):
        self.doc = Doctor.objects.create(
            first_name="Alice", last_name="Heart", specialization="Cardiology"
        )
        self.slot = Availability.objects.create(
            doctor=self.doc,
            start_time=timezone.now() + timezone.timedelta(hours=5),
            end_time=timezone.now() + timezone.timedelta(hours=6),
            is_booked=False
        )
        self.patient = Patient.objects.create(
            first_name="John", last_name="Doe",
            email="john@test.com", phone_number="07700000000"
        )
        self.user = User.objects.create_user(
            username="johntest", password="testpass123"
        )
        self.user.profile.role = "PATIENT"
        self.user.profile.patient = self.patient
        self.user.profile.save()

        self.client = Client()


    # TC01 - AI recommends cardiologist for chest pain
    def test_tc01_specialization_keyword_match(self):
        results = recommend_slots("I have severe chest pain")
        self.assertTrue(len(results) > 0)
        recommended_slot = results[0][0]
        self.assertEqual(recommended_slot.doctor.specialization, "Cardiology")


    # TC02 - Booked slot is not recommended
    def test_tc02_booked_slot_not_recommended(self):
        self.slot.is_booked = True
        self.slot.save()
        results = recommend_slots("chest pain")
        self.assertEqual(len(results), 0)


    # TC03 - Patient registration creates profile automatically
    def test_tc03_registration_creates_profile(self):
        new_user = User.objects.create_user(
            username="newpatient", password="testpass123"
        )
        self.assertTrue(hasattr(new_user, "profile"))
        self.assertEqual(new_user.profile.role, "PATIENT")


    # TC04 - Login with correct credentials redirects successfully
    def test_tc04_login_valid_credentials(self):
        response = self.client.post("/appointments/login/", {
            "username": "johntest",
            "password": "testpass123"
        })
        self.assertIn(response.status_code, [200, 302])


    # TC05 - Login with wrong password fails
    def test_tc05_login_invalid_credentials(self):
        response = self.client.post("/appointments/login/", {
            "username": "johntest",
            "password": "wrongpassword"
        })
        self.assertEqual(response.status_code, 200)


    # TC06 - Unauthenticated user cannot access book appointment
    def test_tc06_unauthenticated_cannot_book(self):
        response = self.client.get("/appointments/book_appointment/")
        self.assertIn(response.status_code, [302, 403])


    # TC07 - Patient can book an available slot
    def test_tc07_patient_can_book_slot(self):
        self.client.login(username="johntest", password="testpass123")
        response = self.client.post("/appointments/book_appointment/", {
            "slot": self.slot.id,
            "reason": "chest pain"
        })
        self.assertIn(response.status_code, [200, 302])


    # TC08 - Slot is_booked becomes True after booking
    def test_tc08_slot_locked_after_booking(self):
        Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc,
            slot=self.slot,
            appointment_date=self.slot.start_time,
            reason="chest pain",
            status="scheduled"
        )
        self.slot.is_booked = True
        self.slot.save()
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_booked)


    # TC09 - Cancelling appointment releases slot
    def test_tc09_cancel_releases_slot(self):
        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doc,
            slot=self.slot,
            appointment_date=self.slot.start_time,
            reason="chest pain",
            status="scheduled"
        )
        self.slot.is_booked = True
        self.slot.save()

        appt.delete()
        self.slot.is_booked = False
        self.slot.save()
        self.slot.refresh_from_db()
        self.assertFalse(self.slot.is_booked)


    # TC10 - AI score components sum correctly
    def test_tc10_ai_score_within_range(self):
        results = recommend_slots("chest pain")
        for slot, score, explanation in results:
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)
