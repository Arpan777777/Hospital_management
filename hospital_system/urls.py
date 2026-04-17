from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView


urlpatterns = [
    path('admin/', admin.site.urls),
    path('appointments/', include('appointments.urls')),  # Include the appointments URLs
    path('', RedirectView.as_view(url='/appointments/', permanent=False)),  # Root should redirect to appointments
]
