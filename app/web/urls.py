from django.contrib.auth import views as auth_views
from django.urls import path

from web import views

app_name = "web"
urlpatterns = [
    path("", views.landing, name="landing"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="web:landing"), name="logout"),
    path("home/", views.home, name="home"),
    path("verify/", views.verify, name="verify"),
    path("rx/<str:prescription_id>/", views.prescription, name="prescription"),
    path("prescriber/", views.prescriber, name="prescriber"),
    path("dispenser/", views.dispenser, name="dispenser"),
    path("dispenser/dispense/", views.dispense, name="dispense"),
    path("authority/", views.authority, name="authority"),
    path("authority/enable/", views.enable_participant, name="enable"),
    path("authority/status/", views.set_status, name="set_status"),
    path("auditor/", views.auditor, name="auditor"),
]
