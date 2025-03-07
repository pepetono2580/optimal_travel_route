from django.db import models


class FuelStation(models.Model):
    station_id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    rack_id = models.CharField(max_length=100, null=True, blank=True)
    price = models.FloatField(default=0.0)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state}"