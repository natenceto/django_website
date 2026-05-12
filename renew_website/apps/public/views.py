from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from renew_website.apps.charging_stations.services.exports import download_transactions_csv, get_filtered_transactions
from renew_website.apps.charging_stations.services.reporting import (
    build_public_dashboard_context,
    build_recent_transactions_payload,
    build_session_chart_payload,
)


def index(request: HttpRequest) -> HttpResponse:
    return render(request, "index.html", build_public_dashboard_context(request))


def recent_transactions_api(request: HttpRequest) -> JsonResponse:
    return JsonResponse(build_recent_transactions_payload(request))


def recent_transactions_csv(request: HttpRequest) -> HttpResponse:
    return download_transactions_csv(get_filtered_transactions(request))


def session_chart_api(request: HttpRequest) -> JsonResponse:
    return JsonResponse(build_session_chart_payload(request))


def about(request: HttpRequest) -> HttpResponse:
    return render(request, "about.html")


def contact(request: HttpRequest) -> HttpResponse:
    return render(request, "contact.html")


def map(request: HttpRequest) -> HttpResponse:
    return render(request, "map.html")