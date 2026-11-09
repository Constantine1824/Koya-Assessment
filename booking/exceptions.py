from rest_framework.views import exception_handler as drf_exception_handler


def custom_exception_handler(exc, context):
    """Collapse every DRF-raised error into {"error": "<message>"}."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    if isinstance(data, dict) and "error" in data:
        return response
    if isinstance(data, dict) and "detail" in data:
        message = str(data["detail"])
    elif isinstance(data, dict):
        parts = []
        for field, messages in data.items():
            if isinstance(messages, (list, tuple)):
                parts.append(f"{field}: {messages[0]}" if messages else field)
            else:
                parts.append(f"{field}: {messages}")
        message = "; ".join(parts) if parts else "invalid request"
    else:
        message = str(data)
    response.data = {"error": message}
    return response
