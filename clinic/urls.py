from django.urls import include, path
from django.views.generic.base import RedirectView

from booking.urls import apiurlpatterns

urlpatterns = [
    path("", include("booking.urls")),
    # The same API endpoints under the /api/ prefix (root paths above are
    # kept as aliases because the assessment spec pins them). Exactly /api
    # serves the Swagger explorer; /api/ redirects there.
    path(
        "api/",
        include(
            [
                path("", RedirectView.as_view(url="/api", permanent=False)),
                *apiurlpatterns,
            ]
        ),
    ),
]
