import secrets

from django.conf import settings
from django.http import JsonResponse

EXEMPT_PATHS = ("/", "/api", "/api/", "/favicon.ico")
EXEMPT_PREFIXES = ("/static/",)


class ApiKeyMiddleware:
    """Level 2: every JSON API request must carry a valid X-API-Key header.

    The booking page, the /api explorer and static assets are exempt; the
    page receives the key server-rendered, and the explorer has its own
    Authorize dialog.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.get_full_path()
        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return self.get_response(request)

        provided = request.headers.get("X-API-Key", "")
        expected = getattr(settings, "X_API_KEY", "")
        if not provided or not secrets.compare_digest(provided, expected):
            return JsonResponse(
                {"error": "missing or invalid API key"}, status=401
            )
        return self.get_response(request)
