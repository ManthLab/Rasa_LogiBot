import re
import json
import random
from rasa_sdk import Action, Tracker                 # --> Provides access to slots & conversation state
from rasa_sdk.executor import CollectingDispatcher   # --> Used to send messages back to the user
from rasa_sdk.events import SlotSet                  # --> Used to update or reset slot values
from rasa_sdk import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Text, Dict

#----------------- Tracking Shipment ------------------
class ActionTrackShipment(Action):

    def name(self):
        return "action_track_shipment"

    def run(self, dispatcher, tracker, domain):

        tracking_id = tracker.get_slot("tracking_id")

        #  Load JSON file
        with open("tracking.json") as f:
            data = json.load(f)

        #  Check if tracking ID exists
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
            dispatcher.utter_message(text="❌ Mobile number must be 10 digits.")
            return {"sender_contact_number": None}

        return {"sender_contact_number": value}


    def validate_sender_email(
        self, value, dispatcher, tracker, domain
    ):
        if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", value):
            dispatcher.utter_message(text="❌ Invalid email format.")
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
        receiver = tracker.get_slot("receiver_name")
        location = tracker.get_slot("delivery_location")

        booking_id = "BK" + str(random.randint(1000, 9999))

        # Simple cost logic
        base_cost = 100
        distance_charge = 50
        total_cost = base_cost + distance_charge

        booking_data = {
            "booking_id": booking_id,
            "sender": sender,
            "receiver": receiver,
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
    
#-------------- Cancel Booking ---------------
class ActionCancelBooking(Action):

    def name(self):
        return "action_cancel_booking"

    def run(self, dispatcher, tracker, domain):

        dispatcher.utter_message(text="❌ Booking cancelled successfully.")

        return [
            SlotSet("sender_name", None),
            SlotSet("sender_contact_number", None),
            SlotSet("sender_email", None),
            SlotSet("receiver_name", None),
            SlotSet("receiver_contact_number", None),
            SlotSet("delivery_location", None),
        ]    
