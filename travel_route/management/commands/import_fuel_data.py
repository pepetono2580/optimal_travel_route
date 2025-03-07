import pandas as pd
from django.core.management.base import BaseCommand
from travel_route.models import FuelStation
from django.db import IntegrityError


class Command(BaseCommand):
    help = 'Import fuel station data using float price values'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to the CSV file')
        parser.add_argument('--clear', action='store_true', help='Clear existing data before import')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file_path']
        clear_data = kwargs.get('clear', False)

        try:
            # Optionally clear existing data
            if clear_data:
                self.stdout.write("Clearing existing data...")
                FuelStation.objects.all().delete()
                self.stdout.write("Existing data cleared.")

            # Read the CSV file
            df = pd.read_csv(file_path)
            self.stdout.write(f"Successfully read CSV file with {len(df)} records")

            # Process each row
            total_processed = 0
            total_updated = 0
            total_failed = 0

            for i, row in df.iterrows():
                try:
                    # Get the price value directly as float
                    price = float(row['Retail Price'])
                    station_id = str(row['OPIS Truckstop ID'])

                    # Try to find existing station
                    try:
                        station = FuelStation.objects.get(station_id=station_id)
                        # Update existing station
                        station.name = str(row['Truckstop Name'])
                        station.address = str(row['Address'])
                        station.city = str(row['City'])
                        station.state = str(row['State'])
                        station.rack_id = str(row['Rack ID'])
                        station.price = price
                        station.save()
                        total_updated += 1
                    except FuelStation.DoesNotExist:
                        # Create new station
                        FuelStation.objects.create(
                            station_id=station_id,
                            name=str(row['Truckstop Name']),
                            address=str(row['Address']),
                            city=str(row['City']),
                            state=str(row['State']),
                            rack_id=str(row['Rack ID']),
                            price=price,
                            latitude=0.0,
                            longitude=0.0
                        )
                        total_processed += 1

                    if (i + 1) % 1000 == 0:
                        self.stdout.write(f"Progress: {i + 1}/{len(df)} records")

                except IntegrityError as e:
                    self.stdout.write(f"Integrity error for record {i + 1}: {str(e)}")
                    self.stdout.write(f"Station ID: {station_id}, Name: {row['Truckstop Name']}")
                    total_failed += 1
                except Exception as e:
                    self.stdout.write(f"Error processing record {i + 1}: {type(e).__name__}: {str(e)}")
                    total_failed += 1

            self.stdout.write(
                f"Import complete. New: {total_processed}, Updated: {total_updated}, Failed: {total_failed}")

        except Exception as e:
            self.stdout.write(f"Fatal error: {str(e)}")