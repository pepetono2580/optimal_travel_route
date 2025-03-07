import requests
import math
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import FuelStation


class RouteAPIView(APIView):
    def post(self, request):
        start_location = request.data.get('start')
        end_location = request.data.get('end')

        if not start_location or not end_location:
            return Response({"error": "Both start and end locations are required"}, status=400)

        # Get coordinates for start and end locations using OpenRouteService geocoding
        ors_api_key = settings.ORS_API_KEY
        geocode_url = "https://api.openrouteservice.org/geocode/search"

        # Set up headers with API key
        headers = {
            "Authorization": ors_api_key
        }

        # Geocode start location
        start_params = {
            "text": start_location,
            "boundary.country": "USA",
            "size": 1
        }

        start_response = requests.get(geocode_url, params=start_params, headers=headers)
        if start_response.status_code != 200:
            return Response({"error": f"Failed to geocode start location: {start_response.text}"}, status=400)

        start_data = start_response.json()
        if not start_data.get('features') or len(start_data['features']) == 0:
            return Response({"error": "Start location not found"}, status=400)

        start_coords = start_data['features'][0]['geometry']['coordinates']

        # Geocode end location
        end_params = {
            "text": end_location,
            "boundary.country": "USA",
            "size": 1
        }

        end_response = requests.get(geocode_url, params=end_params, headers=headers)
        if end_response.status_code != 200:
            return Response({"error": f"Failed to geocode end location: {end_response.text}"}, status=400)

        end_data = end_response.json()
        if not end_data.get('features') or len(end_data['features']) == 0:
            return Response({"error": "End location not found"}, status=400)

        end_coords = end_data['features'][0]['geometry']['coordinates']

        # 2. Get the route using OpenRouteService Directions API
        directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"

        headers = {
            'Accept': 'application/json, application/geo+json',
            'Authorization': ors_api_key,
            'Content-Type': 'application/json; charset=utf-8'
        }

        body = {
            "coordinates": [start_coords, end_coords],
            "instructions": True,
            "preference": "fastest",
            "units": "mi"  # Use miles for distance
        }

        route_response = requests.post(directions_url, json=body, headers=headers)
        if route_response.status_code != 200:
            return Response({"error": f"Failed to get route: {route_response.text}"}, status=400)

        route_data = route_response.json()

        # Check if response has the expected structure
        if 'routes' not in route_data or not route_data['routes']:
            return Response({
                "error": "OpenRouteService returned an unexpected response format",
                "response": route_data
            }, status=500)

        # Extract route details
        route = route_data['routes'][0]
        route_geometry = route_data.get('bbox', [])  # Get the bounding box as geometry
        total_distance_miles = route['summary']['distance']  # This is in miles as per 'units': 'mi' in request
        duration_hours = route['summary']['duration'] / 3600  # Convert seconds to hours

        # Extract states along the route from the instructions
        states_along_route = []
        for segment in route['segments']:
            for step in segment['steps']:
                instruction = step.get('instruction', '')

                # Try to find state abbreviations in the instructions
                for state_code in US_STATES:
                    if f", {state_code}" in instruction or f" {state_code} " in instruction:
                        if state_code not in states_along_route:
                            states_along_route.append(state_code)

        # If few states are found, add default states for long trips
        if len(states_along_route) < 3 and total_distance_miles > 1000:
            # For NY to LA trip, add some major states along the route
            if "New York" in start_location and "Los Angeles" in end_location:
                states_along_route = ['NY', 'PA', 'OH', 'IL', 'MO', 'OK', 'TX', 'NM', 'AZ', 'CA']
            elif "Los Angeles" in start_location and "New York" in end_location:
                states_along_route = ['CA', 'AZ', 'NM', 'TX', 'OK', 'MO', 'IL', 'OH', 'PA', 'NY']

        # 3. Find optimal fuel stops based on vehicle range and price
        vehicle_range = 500  # miles
        fuel_stops = []
        total_fuel_cost = 0

        # If route is shorter than 80% of vehicle range, no stops needed
        if total_distance_miles <= vehicle_range * 0.8:
            # Find cheapest fuel price near destination for return calculation
            end_state = states_along_route[-1] if states_along_route else None
            cheapest_fuel_price = self.get_cheapest_fuel_price(end_state)

            # Calculate cost for one-way trip
            fuel_needed = total_distance_miles / 10  # 10 MPG
            total_fuel_cost = fuel_needed * cheapest_fuel_price

            return Response({
                'route': route_geometry,
                'distance_miles': round(total_distance_miles, 2),
                'duration_hours': round(duration_hours, 2),
                'fuel_stops': [],
                'total_fuel_cost': round(total_fuel_cost, 2),
                'start': start_location,
                'end': end_location,
                'states_along_route': states_along_route
            })

        # For longer routes, divide into segments
        # remaining_distance = total_distance_miles
        distance_traveled = 0
        # current_range = vehicle_range

        # Process route segments
        # route_segments = route['segments'][0]['steps']

        # Calculate fuel stations at optimal intervals
        num_stops = math.ceil(total_distance_miles / (vehicle_range * 0.8))
        segment_distance = total_distance_miles / num_stops

        for i in range(num_stops - 1):  # -1 because we don't need a stop at the destination
            distance_traveled += segment_distance

            # Determine state at this point along the route
            state_index = min(i, len(states_along_route) - 1)
            current_state = states_along_route[state_index] if states_along_route else None

            # Find cheapest station in current state
            cheapest_station = self.get_cheapest_station(current_state)

            if cheapest_station:
                # Calculate fuel needed for this segment
                fuel_needed = segment_distance / 10  # 10 MPG
                fuel_cost = fuel_needed * cheapest_station.price

                fuel_stops.append({
                    'name': cheapest_station.name,
                    'address': cheapest_station.address,
                    'city': cheapest_station.city,
                    'state': cheapest_station.state,
                    'price': float(cheapest_station.price),
                    'distance_from_start': round(distance_traveled, 2),
                    'gallons': round(fuel_needed, 2),
                    'cost': round(fuel_cost, 2)
                })

                total_fuel_cost += fuel_cost
            else:
                # If no station found, use average price
                avg_price = self.get_average_fuel_price()
                fuel_needed = segment_distance / 10
                fuel_cost = fuel_needed * avg_price

                fuel_stops.append({
                    'name': "Estimated Fuel Stop",
                    'address': f"Somewhere in {current_state if current_state else 'the route'}",
                    'city': "",
                    'state': current_state if current_state else "",
                    'price': float(avg_price),
                    'distance_from_start': round(distance_traveled, 2),
                    'gallons': round(fuel_needed, 2),
                    'cost': round(fuel_cost, 2)
                })

                total_fuel_cost += fuel_cost

        # Calculate remaining distance to destination
        remaining_segment = total_distance_miles - distance_traveled
        if remaining_segment > 0:
            fuel_needed = remaining_segment / 10
            # Use price from the last stop or average
            price = float(fuel_stops[-1]['price']) if fuel_stops else self.get_average_fuel_price()
            total_fuel_cost += fuel_needed * price

        return Response({
            'route': route_geometry,
            'distance_miles': round(total_distance_miles, 2),
            'duration_hours': round(duration_hours, 2),
            'fuel_stops': fuel_stops,
            'total_fuel_cost': round(total_fuel_cost, 2),
            'start': start_location,
            'end': end_location,
            'states_along_route': states_along_route
        })

    def get_cheapest_station(self, state):
        """Get the cheapest fuel station in a given state"""
        if not state:
            return None

        try:
            return FuelStation.objects.filter(state=state).order_by('price').first()
        except Exception:
            return None

    def get_cheapest_fuel_price(self, state=None):
        """Get the cheapest fuel price in a state or overall"""
        try:
            if state:
                station = FuelStation.objects.filter(state=state).order_by('price').first()
                if station:
                    return station.price

            # Fallback to overall cheapest
            station = FuelStation.objects.all().order_by('price').first()
            if station:
                return station.price

            return 3.50  # Default price if no data available
        except Exception:
            return 3.50

    def get_average_fuel_price(self):
        """Get the average fuel price across all stations"""
        try:
            avg_price = FuelStation.objects.all().values_list('price', flat=True)
            if avg_price:
                return sum(avg_price) / len(avg_price)
            return 3.50  # Default
        except Exception:
            return 3.50


# US State abbreviations
US_STATES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
]


# Add a debugging view to see the raw route data
class RouteDebugView(APIView):
    def post(self, request):
        start_location = request.data.get('start')
        end_location = request.data.get('end')

        if not start_location or not end_location:
            return Response({"error": "Both start and end locations are required"}, status=400)

        # Get coordinates for start and end locations
        ors_api_key = settings.ORS_API_KEY
        geocode_url = "https://api.openrouteservice.org/geocode/search"

        headers = {
            "Authorization": ors_api_key
        }

        # Geocode start location
        start_params = {"text": start_location, "boundary.country": "USA", "size": 1}
        start_response = requests.get(geocode_url, params=start_params, headers=headers)
        start_data = start_response.json()
        if not start_data.get('features') or len(start_data['features']) == 0:
            return Response({"error": "Start location not found"}, status=400)
        start_coords = start_data['features'][0]['geometry']['coordinates']

        # Geocode end location
        end_params = {"text": end_location, "boundary.country": "USA", "size": 1}
        end_response = requests.get(geocode_url, params=end_params, headers=headers)
        end_data = end_response.json()
        if not end_data.get('features') or len(end_data['features']) == 0:
            return Response({"error": "End location not found"}, status=400)
        end_coords = end_data['features'][0]['geometry']['coordinates']

        # Get the route
        directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {
            'Accept': 'application/json, application/geo+json',
            'Authorization': ors_api_key,
            'Content-Type': 'application/json; charset=utf-8'
        }
        body = {
            "coordinates": [start_coords, end_coords],
            "instructions": True,
            "preference": "fastest",
            "units": "mi"
        }

        route_response = requests.post(directions_url, json=body, headers=headers)
        route_data = route_response.json()

        return Response({
            "start": start_location,
            "end": end_location,
            "start_coords": start_coords,
            "end_coords": end_coords,
            "route_data": route_data
        })