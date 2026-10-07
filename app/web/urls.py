from django.contrib.auth import views as auth_views
from django.urls import path

from web import catalog_views, views

app_name = "web"
urlpatterns = [
    path("", views.landing, name="landing"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="web:landing"), name="logout"),
    path("home/", views.home, name="home"),
    path("verify/", views.verify, name="verify"),
    path("rx/<str:prescription_id>/", views.prescription, name="prescription"),
    path("p/<str:token>/", views.patient_copy, name="patient_copy"),
    path("prescriber/", views.prescriber, name="prescriber"),
    path("dispenser/", views.dispenser, name="dispenser"),
    path("dispenser/dispense/", views.dispense, name="dispense"),
    path("authority/", views.authority, name="authority"),
    path("authority/enable/", views.enable_participant, name="enable"),
    path("authority/status/", views.set_status, name="set_status"),
    path("auditor/", views.auditor, name="auditor"),
    path("catalog/", catalog_views.public_catalog, name="catalog"),
    path("catalog.json", catalog_views.catalog_json, name="catalog_json"),
    path("catalog/search/", catalog_views.catalog_search, name="catalog_search"),
    path("catalog-office/", catalog_views.catalog_office, name="catalog_office"),
    path(
        "catalog-office/medication/", catalog_views.register_medication, name="register_medication"
    ),
    path("catalog-office/product/", catalog_views.register_product, name="register_product"),
    path("catalog-office/status/", catalog_views.set_catalog_status, name="set_catalog_status"),
    path("styleguide/", views.styleguide, name="styleguide"),
]
