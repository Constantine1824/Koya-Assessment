from django.urls import path
from django.views.generic.base import RedirectView

from . import views

urlpatterns = [
    path("", views.page_view, name="page"),
    path("api", views.api_page_view, name="api-docs"),
    # Browsers that ask for /favicon.ico get redirected to our SVG icon.
    path("favicon.ico", RedirectView.as_view(url="/static/booking/favicon.svg", permanent=False)),
    path("reset", views.reset_view, name="reset"),
    path("slots", views.slots_view, name="slots"),
    path("bookings", views.bookings_collection_view, name="bookings"),
    path("bookings/<str:booking_id>", views.booking_detail_view, name="booking-detail"),
]
