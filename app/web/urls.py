from django.contrib.auth import views as auth_views
from django.urls import path

from web import catalog_views, insights_views, views

app_name = "web"
urlpatterns = [
    path("", views.landing, name="landing"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="web:landing"), name="logout"),
    path("home/", views.home, name="home"),
    path("verify/", views.verify, name="verify"),
    path("rx/<str:prescription_id>/", views.prescription, name="prescription"),
    path("rx/<str:prescription_id>/close/", views.close_prescription, name="close_prescription"),
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
    path("insights/", insights_views.home, name="insights"),
    path("insights/overview/", insights_views.overview, name="insights_overview"),
    path("insights/new-drugs/", insights_views.new_drugs, name="insights_new_drugs"),
    path("insights/generics/", insights_views.generics, name="insights_generics"),
    path("insights/brand-locks/", insights_views.brand_locks, name="insights_brand_locks"),
    path("insights/volume/", insights_views.volume, name="insights_volume"),
    path(
        "insights/prescriber/<str:address>/",
        insights_views.prescriber,
        name="insights_prescriber",
    ),
    path("insights/pharmacy/<str:address>/", insights_views.pharmacy, name="insights_pharmacy"),
    path(
        "insights/medication/<str:address>/",
        insights_views.medication,
        name="insights_medication",
    ),
    path(
        "insights/manufacturer/<str:name>/",
        insights_views.manufacturer,
        name="insights_manufacturer",
    ),
    path("styleguide/", views.styleguide, name="styleguide"),
]
