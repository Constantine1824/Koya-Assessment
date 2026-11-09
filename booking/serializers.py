from datetime import timezone as dt_tz

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email as django_validate_email
from django.utils import timezone
from rest_framework import serializers

from .models import Booking, Slot

EMAIL_ERROR = "email is not valid"


class NewBookingSerializer(serializers.Serializer):
    """Level 2: strict validation for POST /bookings bodies.

    CharField trims surrounding whitespace by default, so "  Ada  " -> "Ada".
    """

    slot_id = serializers.CharField(
        required=True, allow_blank=False, allow_null=False, max_length=255,
        error_messages={
            "required": "slot_id is required",
            "blank": "slot_id is required",
            "null": "slot_id is required",
        },
    )
    name = serializers.CharField(
        required=True, allow_blank=False, allow_null=False, max_length=255,
        error_messages={
            "required": "name is required",
            "blank": "name is required",
            "null": "name is required",
        },
    )
    email = serializers.CharField(
        required=True, allow_blank=False, allow_null=False, max_length=254,
        error_messages={
            "required": "email is required",
            "blank": "email is required",
            "null": "email is required",
        },
    )

    def validate_email(self, value):
        cleaned = value.strip().lower()
        try:
            django_validate_email(cleaned)  # RFC-lite structural checks
        except DjangoValidationError:
            raise serializers.ValidationError(EMAIL_ERROR)
        domain = cleaned.rsplit("@", 1)[-1]
        if "." not in domain:  # require a dotted domain, e.g. "user@localhost" fails
            raise serializers.ValidationError(EMAIL_ERROR)
        return cleaned

    def validate_name(self, value):
        return value.strip()


class ZuluDateTimeField(serializers.DateTimeField):
    """Serializes datetimes as RFC3339 UTC strings ending in 'Z'."""

    def to_representation(self, value):
        if value is None:
            return None
        if timezone.is_naive(value):
            value = value.replace(tzinfo=dt_tz.utc)
        return value.astimezone(dt_tz.utc).isoformat().replace("+00:00", "Z")


class SlotListSerializer(serializers.ModelSerializer):
    start = ZuluDateTimeField()
    end = ZuluDateTimeField()
    available = serializers.SerializerMethodField()

    class Meta:
        model = Slot
        fields = ["id", "provider", "start", "end", "available"]

    def get_available(self, obj):
        return getattr(obj, "confirmed_count", 0) == 0


class BookingSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    slot_id = serializers.SerializerMethodField()
    created_at = ZuluDateTimeField()
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "slot_id", "name", "email", "status", "created_at"]

    def get_id(self, obj):
        return str(obj.pk)

    def get_slot_id(self, obj):
        return obj.slot_id
