from rest_framework import serializers

try:
    from drf_spectacular.types import OpenApiTypes  # type: ignore
    from drf_spectacular.utils import (  # type: ignore
        OpenApiParameter,
        OpenApiResponse,
        extend_schema,
        extend_schema_field,
        inline_serializer,
    )
except ImportError:
    class OpenApiTypes:
        OBJECT = dict
        STR = str
        BOOL = bool
        INT = int
        NUMBER = float
        BINARY = bytes
        ANY = object

    class OpenApiParameter:  # pragma: no cover - docs disabled fallback
        PATH = 'path'
        QUERY = 'query'

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class OpenApiResponse:  # pragma: no cover - docs disabled fallback
        def __init__(self, response=None, description=''):
            self.response = response
            self.description = description

    def extend_schema(*args, **kwargs):
        def decorator(obj):
            return obj
        return decorator

    def extend_schema_field(*args, **kwargs):
        def decorator(obj):
            return obj
        return decorator

    def inline_serializer(name, fields, **kwargs):
        attrs = dict(fields)
        return type(name, (serializers.Serializer,), attrs)