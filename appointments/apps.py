from django.apps import AppConfig

class AppointmentsConfig(AppConfig):
    name = 'appointments'

    def ready(self):
        import appointments.signals