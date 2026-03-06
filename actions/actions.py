import re
import json
import random
from rasa_sdk import Action, Tracker                 # --> Provides access to slots & conversation state
from rasa_sdk.executor import CollectingDispatcher   # --> Used to send messages back to the user
from rasa_sdk.events import SlotSet, ActiveLoop      # --> Used to update or reset slot values
from rasa_sdk import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Text, Dict
from rasa_sdk import FormValidationAction
from datetime import datetime
from dateutil import parser

#----------------- Tracking Shipment ------------------
class ActionTrackShipment(Action):

    def name(self):
        return "action_track_shipment"

    def run(self, dispatcher, tracker, domain):

        tracking_id = tracker.get_slot("tracking_id")

        if not tracking_id:
            dispatcher.utter_message(text="Please provide a valid tracking ID.")
            return []

        #  Load JSON file
        try:
            with open("tracking.json") as f:
                data = json.load(f)
        except:
            dispatcher.utter_message(text="Tracking system unavailable.")
            return []

        tracking_id = tracking_id.strip().upper()   # normalize input

        if tracking_id in data:
            shipment = data[tracking_id]

            dispatcher.utter_message(
                text=f"""
📦 Shipment Details

Tracking ID: {tracking_id}
Status: {shipment['status']}
Location: {shipment['location']}
ETA: {shipment['eta']}
                """
            )
        else:
            dispatcher.utter_message(
                text="Tracking ID not found. Please check again."
            )

        return [SlotSet("tracking_id", None)]
    

#---------------- Booking Validation -----------------
class ValidateBookingForm(FormValidationAction):

    def name(self) -> Text:
        return "validate_booking_form"

    def validate_sender_contact_number(
        self, value, dispatcher, tracker, domain
    ):
        if not re.fullmatch(r"\d{10}", value):
            dispatcher.utter_message(text="Mobile number must be 10 digits.")
            return {"sender_contact_number": None}

        return {"sender_contact_number": value}


    def validate_sender_email(
        self, value, dispatcher, tracker, domain
    ):
        if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", value):
            dispatcher.utter_message(text="Invalid email format.")
            return {"sender_email": None}

        return {"sender_email": value}
        
        
#------------------ Booking Shipment -----------------    
class ActionBookShipment(Action):

    def name(self):
        return "action_book_shipment"

    def run(self, dispatcher, tracker, domain):

        intent_name = tracker.latest_message.get("intent").get("name")

        if intent_name != "affirm":
            dispatcher.utter_message(text="Booking cancelled.")
            return []

        sender = tracker.get_slot("sender_name")
        sender_number = tracker.get_slot("sender_contact_number")
        sender_email = tracker.get_slot("sender_email")
        receiver = tracker.get_slot("receiver_name")
        receiver_number = tracker.get_slot("receiver_contact_number")
        location = tracker.get_slot("delivery_location")

        booking_id = "BKI" + str(random.randint(1000, 9999))

        # Simple cost logic
        base_cost = 100
        distance_charge = 50
        total_cost = base_cost + distance_charge

        booking_data = {
            "booking_id": booking_id,
            "sender": sender,
            "sender_number": sender_number,
            "sender_email": sender_email,
            "receiver": receiver,
            "receiver_number": receiver_number,
            "location": location,
            "cost": total_cost
        }

        # Save to JSON
        try:
            with open("bookings.json", "r") as f:
                data = json.load(f)
        except:
            data = []

        data.append(booking_data)

        with open("bookings.json", "w") as f:
            json.dump(data, f, indent=4)

        dispatcher.utter_message(
            text=f"""
🚚 Shipment Booked Successfully!

Booking ID: {booking_id}
Sender Name: {sender}
Sender Contact: {sender_number}
Sender Email: {sender_email}
Receiver Name: {receiver}
Receiver Contact :{receiver_number}
Delivery Location: {location}
Shipping Cost: ₹{total_cost}

Thank you for choosing LogiBot!
            """
        )

        return [
            SlotSet("sender_name", None),                     # --> SlotSet - Clear tracking_id slot after processing to avoid reusing old value
            SlotSet("sender_contact_number", None),
            SlotSet("sender_email", None),
            SlotSet("receiver_name", None),
            SlotSet("receiver_contact_number", None),
            SlotSet("delivery_location", None),
        ]
    
#-------------- Get Shipping rates -------------

class ActionGetShippingRates(Action):
    def name(self):
        return "action_get_shipping_rates"
    
    def run(self, dispatcher, tracker, domain):

        from_location = tracker.get_slot("from_location")
        to_location = tracker.get_slot("to_location")

        base_price = 100

        if from_location.lower() == to_location.lower():
            distance_charge = 50
        else:
            distance_charge = 100

            total_cost = base_price + distance_charge

            dispatcher.utter_message(
                text=f""" 
📦 Shipping Rates:
 From: {from_location}
 TO: {to_location}
 Estimated Rate: ₹{total_cost}
            """
            )
            return [
                SlotSet("from_location",None),
                SlotSet("to_location",None),
            ]   
    
#-------------- Cancel Booking -----------------
class ActionCancelBooking(Action):

    def name(self):
        return "action_cancel_booking"

    def run(self, dispatcher, tracker, domain):

        dispatcher.utter_message(text="Booking cancelled successfully.")

        return [
            SlotSet("sender_name", None),
            SlotSet("sender_contact_number", None),
            SlotSet("sender_email", None),
            SlotSet("receiver_name", None),
            SlotSet("receiver_contact_number", None),
            SlotSet("delivery_location", None),
        ]    
    
#-------------------- Nearest Branch -----------------

class ActionNearestForm(Action):

    def name(self):
        return "action_get_nearest_branch"
    
    def run(self, dispatcher, tracker, domain):

        city = tracker.get_slot("nearest_branch")

        if not city:
            dispatcher.utter_message(text="Please provide a city name.")
            return []
        
         # Normalize input
        city_key = city.strip().lower()

        # Alias mapping
        city_aliases = {
            "banglore": "bangalore",
            "bengaluru": "bangalore",
            "bombay": "mumbai",
            "delhi ncr": "delhi"
        }

        if city_key in city_aliases:
            city_key = city_aliases[city_key]
        
        # Load branch data
        try:
            with open("branch.json") as f:
                data = json.load(f)
        except:
            dispatcher.utter_message(text="Branch data not available.")
            return []
        
        city = city.strip().title()

        # Check if city exists
        if city_key in data:
            branch = data[city_key]

            dispatcher.utter_message(
                text=f"""
🏢 Nearest Branch Details

City: {city}
Address: {branch['address']}
Phone: {branch['phone']}
Email: {branch['email']}
Working Hours: {branch['working_hours']}
                """
            )
        else:
            dispatcher.utter_message(
                text="Sorry, no branch found in this city."
            )

        return [
            SlotSet("nearest_branch", None),
            
        ]
    
#------------------- Schedule Pickup -------------

class ActionSchedulePickup(Action):
    def name(self):
        return ("action_schedule_pickup")
    
    def run(self, dispatcher, tracker, domain):

        name = tracker.get_slot("pickup_name")
        contact = tracker.get_slot("pickup_contact")
        address = tracker.get_slot("pickup_address")
        date = tracker.get_slot("pickup_date")
        time = tracker.get_slot("pickup_time")

        pickup_id = "PCK" + str(random.randint(1000, 9999))

        pickup_data = {
            "pickup_id": pickup_id,
            "name": name,
            "contact": contact,
            "address": address,
            "date": date,
            "time": time
        }

        # Load existing pickups
        try:
            with open("pickup_data.json", "r") as file:
                data = json.load(file)
        except:
            data = {"pickups": []}

        # Add new pickup
        data["pickups"].append(pickup_data)

        # Save back
        with open("pickup_data.json", "w") as file:
            json.dump(data, file, indent=4)

        dispatcher.utter_message(
            text=f"""
📦 Pickup Scheduled Successfully!

Pickup ID: {pickup_id}

Name: {name}
Contact: {contact}
Address: {address}

Pickup Date: {date}
Pickup Time: {time}

Our agent will arrive as per pickup scheduled.
"""
        )

        return [
            SlotSet("pickup_name", None),
            SlotSet("pickup_contact", None),
            SlotSet("pickup_address", None),
            SlotSet("pickup_date", None),
            SlotSet("pickup_time", None)
        ]
       

class ValidatePickupForm(FormValidationAction):

    def name(self):
        return "validate_pickup_form"


    def validate_pickup_date(self, slot_value, dispatcher, tracker, domain):

        try:
            pickup_date = parser.parse(slot_value).date()
            today = datetime.today().date()

            if pickup_date < today:
                dispatcher.utter_message(
                    text="Pickup date cannot be in the past. Please enter a valid future date."
                )
                return {"pickup_date": None}

            return {"pickup_date": slot_value}

        except:
            dispatcher.utter_message(text="Enter pickup date (example: 9 March 2026).")
            return {"pickup_date": None}


    def validate_pickup_time(self, slot_value, dispatcher, tracker, domain):

        try:
            pickup_time = parser.parse(slot_value).time()

            start = datetime.strptime("09:00", "%H:%M").time()
            end = datetime.strptime("18:00", "%H:%M").time()

            if pickup_time < start or pickup_time > end:
                dispatcher.utter_message(
                    text="Pickup allowed only between 9 AM and 6 PM."
                )
                return {"pickup_time": None}

            return {"pickup_time": slot_value}

        except:
            dispatcher.utter_message(text="Please enter a valid time.")
            return {"pickup_time": None}