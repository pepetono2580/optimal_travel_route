from django.urls import path
from django.views.generic import RedirectView
from .views import RouteAPIView, RouteDebugView

urlpatterns = [
    path('route/', RouteAPIView.as_view(), name='route'),
    path('route-debug/', RouteDebugView.as_view(), name='route-debug'),
]