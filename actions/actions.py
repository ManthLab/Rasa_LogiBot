import re
import json
import random
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop, AllSlotsReset
from rasa_sdk import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Text, Dict, List, Optional
from datetime import datetime
from dateutil import parser
from rasa_sdk.events import EventType
import logging
import os
from rasa_sdk.events import SessionStarted, ActionExecuted

#----------------- Helper – clear all booking slots

BOOKING_SLOTS = [
    "sender_name", "sender_contact_number", "sender_email",
    "receiver_name", "receiver_contact_number", "delivery_address",
    "delivery_city", "delivery_pincode",
]

PICKUP_SLOTS = [
    "pickup_name", "pickup_contact", "pickup_address", "pickup_date", "pickup_time",
]

RATES_SLOTS = ["from_location", "to_location"]


def _clear(slots):
    return [SlotSet(s, None) for s in slots]


#-------------------- Track Shipment
class ActionTrackShipment(Action):
    def name(self):
        return "action_track_shipment"

    def run(self, dispatcher, tracker, domain):

        log_conversation(tracker)
        tracking_id = tracker.get_slot("tracking_id")

        if not tracking_id:
            dispatcher.utter_message(text="❗ Please provide a valid tracking ID.")
            return []

        try:
            with open("tracking.json") as f:
                data = json.load(f)
        except Exception:
            dispatcher.utter_message(text="⚠️ Tracking system is temporarily unavailable. Please try again later.")
            return []

        tracking_id = tracking_id.strip().upper()

        if tracking_id in data:
            shipment = data[tracking_id]
            status_emoji = {
                "In Transit": "🚚",
                "Delivered": "✅",
                "Out for Delivery": "🛵",
                "Pending": "⏳",
            }.get(shipment["status"], "📦")

            dispatcher.utter_message(
                text=f"""📦 *Shipment Tracking Details*

🔖 Tracking ID : `{tracking_id}`
{status_emoji} Status     : {shipment['status']}
📍 Location    : {shipment['location']}
📅 ETA         : {shipment['eta']}

Is there anything else I can help you with?"""
            )
        else:
            dispatcher.utter_message(
                text=f"❌ Tracking ID *{tracking_id}* not found.\nPlease double-check and try again."
            )

        return [
    ActiveLoop(None),
    SlotSet("requested_slot", None),
    SlotSet("tracking_id", None)
]

#-------------------- Booking Form – Validation
class ValidateBookingForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_booking_form"

    def _is_cancel_intent(self, tracker) -> bool:
        intent = tracker.latest_message.get("intent", {}).get("name")
#        print(f"DEBUG intent: {intent}")
        return intent in [
        "deny", "stop", "cancel_booking", 
        "cancel_shipment"
    ]

    # ── validators ────────────────────────────────────────────────────────
    def validate_sender_name(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "sender_name":             None,
                "sender_contact_number":   None,
                "sender_email":            None,
                "receiver_name":           None,
                "receiver_contact_number": None,
                "delivery_address":        None,
                "delivery_city":           None,
                "delivery_pincode":        None,
                "requested_slot":          None
            }
        if not slot_value:
            return {"sender_name": None}
        val = slot_value.strip()
        if len(val) < 2:
            dispatcher.utter_message(text="👤 Please enter a valid sender name (at least 2 characters).")
            return {"sender_name": None}
        return {"sender_name": val}

    def validate_sender_contact_number(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "sender_contact_number":   None,
                "sender_email":            None,
                "receiver_name":           None,
                "receiver_contact_number": None,
                "delivery_address":        None,
                "delivery_city":           None,
                "delivery_pincode":        None,
                "requested_slot":          None
            }
        if not slot_value:
            return {"sender_contact_number": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{10}", val):
            dispatcher.utter_message(text="📵 Mobile number must be exactly 10 digits. Please re-enter.")
            return {"sender_contact_number": None}
        return {"sender_contact_number": val}

    def validate_sender_email(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "sender_email":            None,
                "receiver_name":           None,
                "receiver_contact_number": None,
                "delivery_address":        None,
                "delivery_city":           None,
                "delivery_pincode":        None,
                "requested_slot":          None
            }
        if not slot_value:
            return {"sender_email": None}
        val = slot_value.strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", val):
            dispatcher.utter_message(text="📧 Invalid email format. Please enter a valid email (e.g. name@example.com).")
            return {"sender_email": None}
        return {"sender_email": val.lower()}

    def validate_receiver_name(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "receiver_name":           None,
                "receiver_contact_number": None,
                "delivery_address":        None,
                "delivery_city":           None,
                "delivery_pincode":        None,
                "requested_slot":          None
            }
        if not slot_value:
            return {"receiver_name": None}
        val = slot_value.strip()
        if len(val) < 2:
            dispatcher.utter_message(text="👤 Please enter a valid receiver name (at least 2 characters).")
            return {"receiver_name": None}
        return {"receiver_name": val}

    def validate_receiver_contact_number(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "receiver_contact_number": None,
                "delivery_address":        None,
                "delivery_city":           None,
                "delivery_pincode":        None,
                "requested_slot":          None
            }
        if not slot_value:
            return {"receiver_contact_number": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{10}", val):
            dispatcher.utter_message(text="📵 Receiver's mobile number must be exactly 10 digits. Please re-enter.")
            return {"receiver_contact_number": None}
        return {"receiver_contact_number": val}

    def validate_delivery_address(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "delivery_address": None,
                "delivery_city":    None,
                "delivery_pincode": None,
                "requested_slot":   None
            }
        if not slot_value:
            return {"delivery_address": None}
        val = slot_value.strip()
        if len(val) < 10:
            dispatcher.utter_message(text="🏠 Please enter a more complete address (e.g. Flat 5B, Shiv Nagar, MG Road).")
            return {"delivery_address": None}
        return {"delivery_address": val}

    def validate_delivery_city(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "delivery_city":    None,
                "delivery_pincode": None,
                "requested_slot":   None
            }
        if not slot_value:
            return {"delivery_city": None}
        val = slot_value.strip()
        if len(val) < 2 or not re.fullmatch(r"[A-Za-z\s\-]+", val):
            dispatcher.utter_message(text="🏙️ Please enter a valid city name.")
            return {"delivery_city": None}
        return {"delivery_city": val.title()}

    def validate_delivery_pincode(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
                "delivery_pincode": None,
                "requested_slot":   None
            }
        if not slot_value:
            return {"delivery_pincode": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{6}", val):
            dispatcher.utter_message(text="📮 Pincode must be exactly 6 digits. Please re-enter.")
            return {"delivery_pincode": None}
        return {"delivery_pincode": val}

#------------------- Book Shipment – Action --------------------
class ActionBookShipment(Action):
    def name(self):
        return "action_book_shipment"

    def run(self, dispatcher, tracker, domain):
        log_conversation(tracker)
        intent_name = tracker.latest_message.get("intent", {}).get("name")
        # if intent_name != "affirm":
        if intent_name not in ["affirm", "confirm_booking"]:
            dispatcher.utter_message(text="❌ Booking cancelled. How else can I help you?")
            return _clear(BOOKING_SLOTS)

        sender          = tracker.get_slot("sender_name")
        sender_number   = tracker.get_slot("sender_contact_number")
        sender_email    = tracker.get_slot("sender_email")
        receiver        = tracker.get_slot("receiver_name")
        receiver_number = tracker.get_slot("receiver_contact_number")
        address         = tracker.get_slot("delivery_address")
        city            = tracker.get_slot("delivery_city")
        pincode         = tracker.get_slot("delivery_pincode")

        booking_id   = "BKI" + str(random.randint(1000, 9999))
        full_address = f"{address}, {city} - {pincode}"
        total_cost   = 150

        booking_data = {
            "booking_id":       booking_id,
            "sender":           sender,
            "sender_number":    sender_number,
            "sender_email":     sender_email,
            "receiver":         receiver,
            "receiver_number":  receiver_number,
            "delivery_address": full_address,
            "cost":             total_cost,
            "booked_at":        datetime.now().strftime("%d %b %Y %H:%M"),
        }

        try:
            with open("bookings.json", "r") as f:
                data = json.load(f)
        except Exception:
            data = []

        data.append(booking_data)

        with open("bookings.json", "w") as f:
            json.dump(data, f, indent=4)

        # dispatcher.utter_message(text=
        #     f"✅ Shipment Booked Successfully!\n\n"
        #     f"🔖 Booking ID     : {booking_id}\n\n"
        #     f"👤 Sender         : {sender}\n"
        #     f"📞 Contact        : {sender_number}\n"
        #     f"📧 Email          : {sender_email}\n\n"
        #     f"👤 Receiver       : {receiver}\n"
        #     f"📞 Contact        : {receiver_number}\n"
        #     f"📦 Delivery To    : {full_address}\n\n"
        #     f"💰 Shipping Cost  : Rs.{total_cost}\n"
        #     f"📅 Booked On      : {booking_data['booked_at']}\n\n"
        #     f"Thank you for choosing LogiExpress! 🚚"
        # )
        dispatcher.utter_message(
    text=f"""
📦 Shipment Booked Successfully!

Booking ID: {booking_id}

👤 Sender: {sender}
📞 Contact: {sender_number}
📧 Email: {sender_email}

📍 Receiver: {receiver}
📞 Contact: {receiver_number}
🏠 Address: {full_address}

💰 Cost: ₹{total_cost}
📅 Booked On: {booking_data['booked_at']}

Thank you for choosing LogiExpress!
"""
)

        dispatcher.utter_message(
            text="How else can I help you?",
            buttons=[
                {"title": "📦 Track Shipment", "payload": "/track_shipment"},
                {"title": "🚚 Book Shipment", "payload": "/book_shipment"},
                {"title": "💰 Shipping Rates", "payload": "/get_shipping_rates"},
            ]
        )

        return (
    [
        ActiveLoop(None),
        SlotSet("requested_slot", None)
    ]
    + _clear(BOOKING_SLOTS)
)

#----------------- Confirm Booking ---------------
class ActionAskConfirmBooking(Action):
    def name(self):
        return "action_ask_confirm_booking"

    def run(self, dispatcher, tracker, domain):

        required = {
            "sender_name":             tracker.get_slot("sender_name"),
            "sender_contact_number":   tracker.get_slot("sender_contact_number"),
            "sender_email":            tracker.get_slot("sender_email"),
            "receiver_name":           tracker.get_slot("receiver_name"),
            "receiver_contact_number": tracker.get_slot("receiver_contact_number"),
            "delivery_address":        tracker.get_slot("delivery_address"),
            "delivery_city":           tracker.get_slot("delivery_city"),
            "delivery_pincode":        tracker.get_slot("delivery_pincode"),
        }

        missing = [k for k, v in required.items() if not v]

        if missing:
            dispatcher.utter_message(
                text="❌ Booking could not be completed — some details are missing. Please start again.",
                buttons=[
                    {"title": "🚚 Book Shipment", "payload": "/book_shipment"},
                    {"title": "🏠 Main Menu",      "payload": "/greet"},
                ]
            )
            return _clear(BOOKING_SLOTS)

        dispatcher.utter_message(
            text=f"""📋 Please review your shipment details:

┌─ SENDER ────────────────────────────
👤 Name    : {required['sender_name']}
📞 Contact : {required['sender_contact_number']}
📧 Email   : {required['sender_email']}

┌─ RECEIVER ──────────────────────────
👤 Name    : {required['receiver_name']}
📞 Contact : {required['receiver_contact_number']}

┌─ DELIVERY ──────────────────────────
🏠 Address : {required['delivery_address']}
🏙️ City    : {required['delivery_city']}
📮 Pincode : {required['delivery_pincode']}

Confirm booking?""",
            buttons=[
                {"title": "✅ Yes, Confirm", "payload": "/confirm_booking"},
                {"title": "❌ No, Cancel",   "payload": "/cancel_booking"},
            ]
        )
        return []

#-------------- Cancel Booking Mid-Form 
class ActionCancelBooking(Action):
    def name(self):
        return "action_cancel_booking"

    def run(self, dispatcher, tracker, domain):
        log_conversation(tracker)
        dispatcher.utter_message(
            text="❌ Booking cancelled.\n\nHow else can I assist you?",
            buttons=[
                {"title": "📦 Track Shipment",  "payload": "/track_shipment"},
                {"title": "💰 Get Rates",        "payload": "/get_shipping_rates"},
                {"title": "📍 Nearest Branch",   "payload": "/nearest_branch"},
            ]
        )
        return (
    [
        ActiveLoop(None),
        SlotSet("requested_slot", None)
    ]
    + _clear(BOOKING_SLOTS)
)


#------------- Shipping Rates ---------------
class ActionGetShippingRates(Action):
    def name(self):
        return "action_get_shipping_rates"

    def run(self, dispatcher, tracker, domain):
        log_conversation(tracker)
        from_location = tracker.get_slot("from_location")
        to_location   = tracker.get_slot("to_location")

        if not from_location or not to_location:
            dispatcher.utter_message(text="⚠️ Could not determine locations. Please try again.")
            return _clear(RATES_SLOTS)

        from_loc = from_location.strip().title()
        to_loc   = to_location.strip().title()

        if from_loc.lower() == to_loc.lower():
            base, distance, tier = 100, 50, "Inter-city"
        else:
            base, distance, tier = 100, 100, "Domestic"

        total_cost = base + distance

        dispatcher.utter_message(
            text=f"""💰 *Shipping Rate Estimate*

📍 From     : {from_loc}
📍 To       : {to_loc}
🏷️ Tier     : {tier}

Base Charge    : ₹{base}
Distance Charge: ₹{distance}
─────────────────
💵 Total       : ₹{total_cost}

_Rates are estimates and may vary based on weight & dimensions._

Would you like to book a shipment?""",
            buttons=[
                {"title": "✅ Book Now",    "payload": "/book_shipment"},
                {"title": "🔙 Main Menu",   "payload": "/greet"},
            ]
        )

        return (
    [
        ActiveLoop(None),
        SlotSet("requested_slot", None)
    ]
    + _clear(RATES_SLOTS)
)

#------------------------- Rates Validation -------------------
class ValidateRatesForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_rates_form"

    def _is_cancel_intent(self, tracker) -> bool:
        intent = tracker.latest_message.get("intent", {}).get("name")
        return intent in [
            "deny", "stop", "cancel_booking",
            "cancel_shipment"
        ]

    def validate_from_location(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {"from_location": None, "to_location": None, "requested_slot": None}
        if not slot_value:
            return {"from_location": None}
        val = slot_value.strip().title()
        if not re.fullmatch(r"[A-Za-z\s\-]+", val) or len(val) < 3:
            dispatcher.utter_message(text="📍 Please enter a valid origin city name (letters only).")
            return {"from_location": None}
        return {"from_location": val}

    def validate_to_location(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {"to_location": None, "requested_slot": None}
        if not slot_value:
            return {"to_location": None}
        val = slot_value.strip().title()
        if not re.fullmatch(r"[A-Za-z\s\-]+", val) or len(val) < 3:
            dispatcher.utter_message(text="📍 Please enter a valid destination city name (letters only).")
            return {"to_location": None}
        return {"to_location": val}  

#----------- Nearest Branch ----------------------
class ActionNearestBranch(Action):
    def name(self):
        return "action_get_nearest_branch"

    def run(self, dispatcher, tracker, domain):
        log_conversation(tracker)
        city = tracker.get_slot("nearest_branch")

        if not city:
            dispatcher.utter_message(text="❗ Please provide a city name.")
            return []

        city_key = city.strip().lower()

        city_aliases = {
            "banglore":  "bangalore",
            "bengaluru": "bangalore",
            "bombay":    "mumbai",
            "delhi ncr": "delhi",
            "new delhi": "delhi",
            "ahmedabad": "ahemdabad",
        }
        city_key = city_aliases.get(city_key, city_key)

        try:
            with open("branch.json") as f:
                data = json.load(f)
        except Exception:
            dispatcher.utter_message(text="⚠️ Branch data is currently unavailable.")
            return [SlotSet("nearest_branch", None)]

        if city_key in data:
            branch = data[city_key]
            dispatcher.utter_message(
                text=f"""🏢 *Nearest Branch – {city.strip().title()}*

📍 Address       : {branch['address']}
📞 Phone         : {branch['phone']}
📧 Email         : {branch['email']}
🕐 Working Hours : {branch['working_hours']}

Would you like to book a shipment or schedule a pickup?""",
                buttons=[
                    {"title": "🚚 Book Shipment",    "payload": "/book_shipment"},
                    {"title": "📦 Schedule Pickup",  "payload": "/schedule_pickup"},
                ]
            )
        else:
            dispatcher.utter_message(
                text=f"😔 Sorry, no branch found in *{city.strip().title()}* yet.\n"
                     "We currently have branches in Mumbai, Delhi, Bangalore, and Ahmedabad."
            )

        return [
    ActiveLoop(None),
    SlotSet("requested_slot", None),
    SlotSet("nearest_branch", None)
]

#------------- Schedule Pickup – Action

class ActionSchedulePickup(Action):
    def name(self):
        return "action_schedule_pickup"

    def run(self, dispatcher, tracker, domain):
        log_conversation(tracker)
        # ── guard: check all required slots are filled ────────────────
        required_slots = {
            "pickup_name":    tracker.get_slot("pickup_name"),
            "pickup_contact": tracker.get_slot("pickup_contact"),
            "pickup_address": tracker.get_slot("pickup_address"),
            "pickup_date":    tracker.get_slot("pickup_date"),
            "pickup_time":    tracker.get_slot("pickup_time"),
        }
        missing = [k for k, v in required_slots.items() if not v]
        if missing:
            dispatcher.utter_message(
                text="❌ Pickup could not be scheduled — some details are missing.\n"
                     "Please start again.",
                buttons=[
                    {"title": "🔄 Schedule Pickup", "payload": "/schedule_pickup"},
                    {"title": "🏠 Main Menu",        "payload": "/greet"},
                ]
            )
            return [AllSlotsReset()]
        name    = tracker.get_slot("pickup_name")
        contact = tracker.get_slot("pickup_contact")
        address = tracker.get_slot("pickup_address")
        date    = tracker.get_slot("pickup_date")
        time    = tracker.get_slot("pickup_time")

        pickup_id = "PCK" + str(random.randint(1000, 9999))

        pickup_data = {
            "pickup_id":    pickup_id,
            "name":         name,
            "contact":      contact,
            "address":      address,
            "date":         date,
            "time":         time,
            "scheduled_at": datetime.now().strftime("%d %b %Y %H:%M"),
        }

        try:
            with open("pickup_data.json", "r") as file:
                data = json.load(file)
        except Exception:
            data = {"pickups": []}

        data["pickups"].append(pickup_data)

        with open("pickup_data.json", "w") as file:
            json.dump(data, file, indent=4)

        dispatcher.utter_message(text=
            f"✅ Pickup Scheduled Successfully!\n\n"
            f"🔖 Pickup ID   : {pickup_id}\n\n"
            f"👤 Name        : {name}\n"
            f"📞 Contact     : {contact}\n"
            f"📍 Address     : {address}\n\n"
            f"📅 Date        : {date}\n"
            f"🕐 Time        : {time}\n\n"
            f"Our agent will arrive on time.\n"
            f"Thank you for choosing LogiExpress! 🚀"
        )

        return (
    [
        ActiveLoop(None),
        SlotSet("requested_slot", None)
    ]
    + _clear(PICKUP_SLOTS)
)

#--------------- PickUp Validations ---------------------
class ValidatePickupForm(FormValidationAction):
    def name(self):
        return "validate_pickup_form"

    # ── helper ────────────────────────────────────────────────────────────
    def _is_cancel_intent(self, tracker) -> bool:
        intent = tracker.latest_message.get("intent", {}).get("name")
        return intent in [
        "deny", "stop", "cancel_booking",
        "cancel_shipment"
    ]

    # ── validators ────────────────────────────────────────────────────────
    def validate_pickup_name(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {"pickup_name": None,
                    "pickup_contact": None,
                    "pickup_address": None,
                    "pickup_date":    None,   
                    "pickup_time":   None,   
                    "requested_slot": None
        }
        if not slot_value:
            return {"pickup_name": None}
        val = slot_value.strip()
        if len(val) < 2:
            dispatcher.utter_message(text="👤 Please enter a valid name.")
            return {"pickup_name": None}
        return {"pickup_name": val}

    def validate_pickup_contact(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {"pickup_contact": None,
                    "pickup_address": None,
                    "pickup_date":    None,   
                    "pickup_time":   None,   
                    "requested_slot": None
        }
        if not slot_value:
            return {"pickup_contact": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{10}", val):
            dispatcher.utter_message(text="📵 Contact number must be exactly 10 digits. Please re-enter.")
            return {"pickup_contact": None}
        return {"pickup_contact": val}

    def validate_pickup_address(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
            "pickup_address": None,
            "pickup_date":    None,   
            "pickup_time":   None,   
            "requested_slot": None
        }
        if not slot_value:
            return {"pickup_address": None}
        val = slot_value.strip()
        if len(val) < 10:
            dispatcher.utter_message(
                text="🏠 Please enter a more complete pickup address.\n"
                     "Example: *12A, Sai Nagar, Link Road, Borivali West*"
            )
            return {"pickup_address": None}
        return {"pickup_address": val}

    def validate_pickup_date(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {
            "pickup_date":   None,
            "pickup_time":  None,    
            "requested_slot": None
        }

        if not slot_value:
            return {"pickup_date": None}
        try:
            pickup_date = parser.parse(slot_value).date()
            today = datetime.today().date()
            if pickup_date < today:
                dispatcher.utter_message(text="📅 Pickup date cannot be in the past. Please enter a future date.")
                return {"pickup_date": None}
            return {"pickup_date": pickup_date.strftime("%d %b %Y")}
        except Exception:
            dispatcher.utter_message(text="📅 Invalid date. Please enter like: *12 March 2026* or *2026-03-12*")
            return {"pickup_date": None}

    def validate_pickup_time(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {"pickup_time": None, "requested_slot": None}
        if not slot_value:
            return {"pickup_time": None}
        try:
            pickup_time = parser.parse(slot_value).time()
            start = datetime.strptime("09:00", "%H:%M").time()
            end   = datetime.strptime("18:00", "%H:%M").time()
            if pickup_time < start or pickup_time > end:
                dispatcher.utter_message(text="🕐 Pickup is available only between *9:00 AM and 6:00 PM*. Please choose a valid time.")
                return {"pickup_time": None}
            return {"pickup_time": parser.parse(slot_value).strftime("%I:%M %p")}
        except Exception:
            dispatcher.utter_message(text="🕐 Invalid time. Please enter like: *10 AM*, *2:30 PM*, or *14:30*")
            return {"pickup_time": None}

#------------- Cancel Any Active Form --------------------------
class ActionCancelActiveForm(Action):
    def name(self):
        return "action_cancel_active_form"

    def run(self, dispatcher, tracker, domain):
        log_conversation(tracker)
        dispatcher.utter_message(
            text="❌ Current process cancelled.\n\nHow can I help you next?",
            buttons=[
                {"title": "📦 Track Shipment",  "payload": "/track_shipment"},
                {"title": "🚚 Book Shipment",    "payload": "/book_shipment"},
                {"title": "💰 Get Rates",        "payload": "/get_shipping_rates"},
                {"title": "📍 Nearest Branch",   "payload": "/nearest_branch"},
                {"title": "🔄 Schedule Pickup",  "payload": "/schedule_pickup"},
            ]
        )
        return (
            _clear(BOOKING_SLOTS)
            + _clear(PICKUP_SLOTS)
            + _clear(RATES_SLOTS)
            + [SlotSet("tracking_id", None), SlotSet("nearest_branch", None)]
        )
    
#---------------- Maintain Logs ------------
LOG_FILE = "logibot_conversations.json"

def log_conversation(tracker):

    log_entry = {
        "session_id": tracker.sender_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_message": tracker.latest_message.get("text"),
        "intent": tracker.latest_message.get("intent", {}).get("name"),
        "bot_action": tracker.events[-1].get("name") if tracker.events else None,
        "slots": tracker.current_slot_values(),
        "active_form": tracker.active_loop.get("name") if tracker.active_loop else None
    }

    try:

        data = []

        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
            with open(LOG_FILE, "r") as f:
                data = json.load(f)

        data.append(log_entry)

        with open(LOG_FILE, "w") as f:
            json.dump(data, f, indent=4)

    except Exception as e:
        print("Logging error:", e)

#---------- Session Handling ---------
TRANSIENT_SLOTS = set(BOOKING_SLOTS + PICKUP_SLOTS + RATES_SLOTS + ["tracking_id", "nearest_branch"])

class ActionSessionStart(Action):

    def name(self):
        return "action_session_start"

    async def run(self, dispatcher, tracker, domain):

        events = [SessionStarted()]

        # carry over previous slots
        for key, value in tracker.current_slot_values().items():
            if value is not None:
                events.append(SlotSet(key, value))

        events.append(ActionExecuted("action_listen"))

        return events
    
#--------------- Reset -------------
class ActionResetLogisticsSlots(Action):

    def name(self):
        return "action_reset_logistics_slots"

    def run(self, dispatcher, tracker, domain):

        return [
            SlotSet("tracking_id", None),
            SlotSet("sender_name", None),
            SlotSet("sender_contact_number", None),
            SlotSet("sender_email", None),
            SlotSet("receiver_name", None),
            SlotSet("receiver_contact_number", None),
            SlotSet("delivery_address", None),
            SlotSet("delivery_city", None),
            SlotSet("delivery_pincode", None),
            SlotSet("from_location", None),
            SlotSet("to_location", None),
            SlotSet("nearest_branch", None),
            SlotSet("pickup_name", None),
            SlotSet("pickup_contact", None),
            SlotSet("pickup_address", None),
            SlotSet("pickup_date", None),
            SlotSet("pickup_time", None),
        ]