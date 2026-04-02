import re
import math
import json
import random
import difflib
import uuid
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop, AllSlotsReset
from rasa_sdk import FormValidationAction
from rasa_sdk.types import DomainDict
from typing import Any, Text, Dict, List, Optional
from datetime import datetime, timedelta
from dateutil import parser
from rasa_sdk.events import EventType
import logging
import os
from rasa_sdk.events import SessionStarted, ActionExecuted
from actions.db_helper import close_session, ensure_session, log_chat, get_tracking, insert_booking, insert_pickup, get_branch

# ─── DB helper  ───────────
logger = logging.getLogger(__name__)

CITY_TO_PINCODE = {
    "mumbai":    "400001",
    "delhi":     "110001",
    "bangalore": "560001",
    "bengaluru": "560001",
    "ahmedabad": "380001",
    "pune":      "411001",
    "hyderabad": "500001",
    "chennai":   "600001",
    "kolkata":   "700001",
    "surat":     "395001",
    "jaipur":    "302001",
}

BOOKING_SLOTS = [
    "sender_name", "sender_contact_number", "sender_email",
    "receiver_name", "receiver_contact_number", "delivery_address",
    "delivery_city", "delivery_pincode",
]

PICKUP_SLOTS = [
    "pickup_name", "pickup_contact", "pickup_address", "pickup_date", "pickup_time",
]

RATES_SLOTS = [
    "destination_country", "from_pincode", "to_pincode",
    "shipment_type", "weight_grams", "length_cm", "width_cm", "height_cm",
]

CANCEL_INTENTS   = {"deny", "stop", "cancel_booking", "cancel_shipment"}
CANCEL_KEYWORDS  = {
    "cancel", "stop", "quit", "exit", "no", "nope", "never mind",
    "forget it", "not now", "leave it", "abort", "back", "drop it",
    "cancel for now", "i want to cancel", "cancel this", "cancel please",
    "nevermind", "skip it", "i changed my mind", "close this"
}

def _clear(slots):
    return [SlotSet(s, None) for s in slots]

def _is_cancel(tracker: Tracker) -> bool:
    intent = tracker.latest_message.get("intent", {}).get("name", "")
    text   = (tracker.latest_message.get("text") or "").lower()
    return intent in CANCEL_INTENTS or text in CANCEL_KEYWORDS


#--------------------- TRACK SHIPMENT ------------------------

class ActionTrackShipment(Action):
    def name(self):
        return "action_track_shipment"

    def run(self, dispatcher, tracker, domain):

        tracking_id = tracker.get_slot("tracking_id")

        if not tracking_id:
            dispatcher.utter_message(text="❗ Please provide a valid tracking ID.")
            return []

        tracking_id = tracking_id.strip().upper()

        shipment = get_tracking(tracking_id)

        if shipment:
            status_emoji = {
                "In Transit":       "🚚",
                "Delivered":        "✅",
                "Out for Delivery": "🛵",
                "Pending":          "⏳",
            }.get(shipment["status"], "📦")

            response = (
                f"📦 *Shipment Tracking Details*\n\n"
                f"🔖 Tracking ID : `{tracking_id}`\n"
                f"{status_emoji} Status     : {shipment['status']}\n"
                f"📍 Location    : {shipment['location']}\n"
                f"📅 ETA         : {shipment['eta']}\n\n"
                f"Is there anything else I can help you with?"
            )
        else:
            response = (
                f"❌ Tracking ID *{tracking_id}* not found.\n"
                f"Please double-check and try again."
            )

        dispatcher.utter_message(text=response)

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )

        return [
            ActiveLoop(None),
            SlotSet("requested_slot", None),
            SlotSet("tracking_id", None),
        ]

#---------------------- BOOKING FORM – VALIDATION ------------------------

class ValidateBookingForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_booking_form"

    def _is_cancel_intent(self, tracker) -> bool:
        intent = tracker.latest_message.get("intent", {}).get("name")
        return intent in ["deny", "stop", "cancel_booking", "cancel_shipment"]

    def validate_sender_name(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in BOOKING_SLOTS + ["requested_slot"]}
        if not slot_value:
            return {"sender_name": None}
        val = slot_value.strip()
        if len(val) < 2:
            dispatcher.utter_message(text="👤 Please enter a valid sender name (at least 2 characters).")
            return {"sender_name": None}
        return {"sender_name": val}

    def validate_sender_contact_number(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["sender_contact_number", "sender_email", "receiver_name",
                                       "receiver_contact_number", "delivery_address",
                                       "delivery_city", "delivery_pincode", "requested_slot"]}
        if not slot_value:
            return {"sender_contact_number": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{10}", val):
            dispatcher.utter_message(text="📵 Mobile number must be exactly 10 digits. Please re-enter.")
            return {"sender_contact_number": None}
        return {"sender_contact_number": val}

    def validate_sender_email(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["sender_email", "receiver_name", "receiver_contact_number",
                                       "delivery_address", "delivery_city", "delivery_pincode", "requested_slot"]}
        if not slot_value:
            return {"sender_email": None}
        val = slot_value.strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", val):
            dispatcher.utter_message(text="📧 Invalid email format. Please enter a valid email (e.g. name@example.com).")
            return {"sender_email": None}
        return {"sender_email": val.lower()}

    def validate_receiver_name(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["receiver_name", "receiver_contact_number",
                                       "delivery_address", "delivery_city", "delivery_pincode", "requested_slot"]}
        if not slot_value:
            return {"receiver_name": None}
        val = slot_value.strip()
        if len(val) < 2:
            dispatcher.utter_message(text="👤 Please enter a valid receiver name (at least 2 characters).")
            return {"receiver_name": None}
        return {"receiver_name": val}

    def validate_receiver_contact_number(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["receiver_contact_number", "delivery_address",
                                       "delivery_city", "delivery_pincode", "requested_slot"]}
        if not slot_value:
            return {"receiver_contact_number": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{10}", val):
            dispatcher.utter_message(text="📵 Receiver's mobile number must be exactly 10 digits. Please re-enter.")
            return {"receiver_contact_number": None}
        return {"receiver_contact_number": val}

    def validate_delivery_address(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["delivery_address", "delivery_city", "delivery_pincode", "requested_slot"]}
        if not slot_value:
            return {"delivery_address": None}
        val = slot_value.strip()
        if len(val) < 10:
            dispatcher.utter_message(text="🏠 Please enter a more complete address (e.g. Flat 5B, Shiv Nagar, MG Road).")
            return {"delivery_address": None}
        return {"delivery_address": val}

    def validate_delivery_city(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["delivery_city", "delivery_pincode", "requested_slot"]}
        if not slot_value:
            return {"delivery_city": None}
        val = slot_value.strip()
        if len(val) < 2 or not re.fullmatch(r"[A-Za-z\s\-]+", val):
            dispatcher.utter_message(text="🏙️ Please enter a valid city name.")
            return {"delivery_city": None}
        return {"delivery_city": val.title()}

    def validate_delivery_pincode(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {"delivery_pincode": None, "requested_slot": None}
        if not slot_value:
            return {"delivery_pincode": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{6}", val):
            dispatcher.utter_message(text="📮 Pincode must be exactly 6 digits. Please re-enter.")
            return {"delivery_pincode": None}
        return {"delivery_pincode": val}


#-------------------- BOOK SHIPMENT -----------------------
class ActionBookShipment(Action):
    def name(self):
        return "action_book_shipment"

    def run(self, dispatcher, tracker, domain):
        intent_name = tracker.latest_message.get("intent", {}).get("name")
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

        booking_id   = "LGX" + datetime.now().strftime("%m%d") + str(random.randint(100000, 999999))
        full_address = f"{address}, {city} - {pincode}"
        total_cost   = 150

        success = insert_booking(
            booking_id      = booking_id,
            sender_name     = sender,
            sender_number   = sender_number,
            sender_email    = sender_email,
            receiver_name   = receiver,
            receiver_number = receiver_number,
            delivery_address= full_address,
            cost            = total_cost,
        )

        if not success:
            logger.warning("Booking DB insert failed for %s — booking still shown to user", booking_id)

        booked_at = datetime.now().strftime("%d %b %Y %H:%M")

        response = (
            f"📦 Shipment Booked Successfully!\n\n"
            f"Booking ID: {booking_id}\n\n"
            f"👤 Sender: {sender}\n"
            f"📞 Contact: {sender_number}\n"
            f"📧 Email: {sender_email}\n\n"
            f"📍 Receiver: {receiver}\n"
            f"📞 Contact: {receiver_number}\n"
            f"🏠 Address: {full_address}\n\n"
            f"💰 Cost: ₹{total_cost}\n"
            f"📅 Booked On: {booked_at}\n\n"
            f"Thank you for choosing LogiExpress!"
        )

        dispatcher.utter_message(text=response)
        dispatcher.utter_message(
            text="How else can I help you?",
            buttons=[
                {"title": "📦 Track Shipment", "payload": "/track_shipment"},
                {"title": "🚚 Book Shipment",  "payload": "/book_shipment"},
                {"title": "💰 Shipping Rates", "payload": "/check_rates"},
            ]
        )
        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )

        return [ActiveLoop(None), SlotSet("requested_slot", None)] + _clear(BOOKING_SLOTS)


#-------------------- CONFIRM BOOKING -------------------------------

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
                text="❌ Booking cancelled.\n\nHow else can I assist you?",
                buttons=[
                    {"title": "🚚 Book Shipment", "payload": "/book_shipment"},
                    {"title": "🏠 Main Menu",     "payload": "/greet"},
                ]
            )
            return _clear(BOOKING_SLOTS)

        dispatcher.utter_message(
            text=(
                f"📋 Please review your shipment details:\n\n"
                f"┌─ SENDER ────────────────────────────\n"
                f"👤 Name    : {required['sender_name']}\n"
                f"📞 Contact : {required['sender_contact_number']}\n"
                f"📧 Email   : {required['sender_email']}\n\n"
                f"┌─ RECEIVER ──────────────────────────\n"
                f"👤 Name    : {required['receiver_name']}\n"
                f"📞 Contact : {required['receiver_contact_number']}\n\n"
                f"┌─ DELIVERY ──────────────────────────\n"
                f"🏠 Address : {required['delivery_address']}\n"
                f"🏙️ City    : {required['delivery_city']}\n"
                f"📮 Pincode : {required['delivery_pincode']}\n\n"
                f"Confirm booking?"
            ),
            buttons=[
                {"title": "✅ Yes, Confirm", "payload": "/confirm_booking"},
                {"title": "❌ No, Cancel",   "payload": "/cancel_booking"},
            ]
        )
        return []

#-------------------------- CANCEL BOOKING -----------------------
class ActionCancelBooking(Action):
    def name(self):
        return "action_cancel_booking"

    def run(self, dispatcher, tracker, domain):
        response = "❌ Booking cancelled.\n\nHow else can I assist you?"
        dispatcher.utter_message(
            text=response,
            buttons=[
                {"title": "📦 Track Shipment", "payload": "/track_shipment"},
                {"title": "💰 Get Rates",       "payload": "/check_rates"},
                {"title": "📍 Nearest Branch",  "payload": "/nearest_branch"},
            ]
        )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )

        return [ActiveLoop(None), SlotSet("requested_slot", None)] + _clear(BOOKING_SLOTS)


#--------------------- SHIPPING RATES --------------------

INTERNATIONAL_CARRIERS = ["UPS", "FedEx", "DHL", "WorldWyde Express Standard"]
INTL_BASE_RATES = {
    "Europe":        {"UPS": 1900, "FedEx": 2100, "DHL": 2200, "WorldWyde Express Standard": 2050},
    "USA/Canada":    {"UPS": 1800, "FedEx": 2000, "DHL": 2150, "WorldWyde Express Standard": 1950},
    "Asia Pacific":  {"UPS": 1400, "FedEx": 1600, "DHL": 1700, "WorldWyde Express Standard": 1550},
    "Middle East":   {"UPS": 1300, "FedEx": 1500, "DHL": 1600, "WorldWyde Express Standard": 1450},
    "Rest of World": {"UPS": 2000, "FedEx": 2200, "DHL": 2300, "WorldWyde Express Standard": 2100},
}
DOMESTIC_CARRIERS   = ["DTDC", "BlueDart", "Delhivery", "Ekart Logistics"]
DOMESTIC_BASE_RATES = {
    "same_city":  {"DTDC": 50,  "BlueDart": 70,  "Delhivery": 55,  "Ekart Logistics": 48},
    "metro":      {"DTDC": 80,  "BlueDart": 100, "Delhivery": 85,  "Ekart Logistics": 75},
    "rest_india": {"DTDC": 100, "BlueDart": 130, "Delhivery": 110, "Ekart Logistics": 95},
}
COUNTRY_TO_ZONE = {
    "germany": "Europe", "france": "Europe", "uk": "Europe",
    "united kingdom": "Europe", "italy": "Europe", "spain": "Europe",
    "netherlands": "Europe", "sweden": "Europe", "norway": "Europe",
    "switzerland": "Europe", "poland": "Europe", "austria": "Europe",
    "usa": "USA/Canada", "united states": "USA/Canada",
    "america": "USA/Canada", "canada": "USA/Canada",
    "australia": "Asia Pacific", "new zealand": "Asia Pacific",
    "japan": "Asia Pacific", "singapore": "Asia Pacific",
    "malaysia": "Asia Pacific", "thailand": "Asia Pacific",
    "indonesia": "Asia Pacific", "philippines": "Asia Pacific",
    "south korea": "Asia Pacific", "china": "Asia Pacific",
    "uae": "Middle East", "dubai": "Middle East",
    "saudi arabia": "Middle East", "qatar": "Middle East",
    "bahrain": "Middle East", "kuwait": "Middle East", "oman": "Middle East",
}

def get_zone(country: str) -> str:
    return COUNTRY_TO_ZONE.get(country.strip().lower(), "Rest of World")

def chargeable_weight_g(actual_g, l, w, h, is_doc):
    if is_doc:
        return actual_g
    return max(actual_g, (l * w * h / 5000) * 1000)

def slabs(weight_g):
    return max(1, math.ceil(weight_g / 500))

def calc_intl_rates(zone, weight_g):
    base = INTL_BASE_RATES.get(zone, INTL_BASE_RATES["Rest of World"])
    n = slabs(weight_g)
    return {c: r * n for c, r in base.items()}

def calc_domestic_rates(from_pin, to_pin, weight_g):
    f, t = from_pin[0], to_pin[0]
    tier = "same_city" if from_pin == to_pin else ("metro" if f == t else "rest_india")
    n = slabs(weight_g)
    return {c: r * n for c, r in DOMESTIC_BASE_RATES[tier].items()}


class ActionGetShippingRates(Action):
    def name(self):
        return "action_get_shipping_rates"

    def run(self, dispatcher, tracker, domain):
        country   = (tracker.get_slot("destination_country") or "").strip()
        from_pin  = (tracker.get_slot("from_pincode") or "").strip()
        to_pin    = (tracker.get_slot("to_pincode") or "").strip()
        ship_type = (tracker.get_slot("shipment_type") or "document").lower()
        weight_g  = float(tracker.get_slot("weight_grams") or 500)
        is_doc    = ship_type == "document"
        is_intl   = bool(country) and country.lower() != "india"
        l = float(tracker.get_slot("length_cm") or 0)
        w = float(tracker.get_slot("width_cm")  or 0)
        h = float(tracker.get_slot("height_cm") or 0)
        chargeable = chargeable_weight_g(weight_g, l, w, h, is_doc)

        if is_intl:
            zone  = get_zone(country)
            rates = calc_intl_rates(zone, chargeable)
            dest_label = f"{to_pin}, {country.title()}"
        else:
            zone  = "Domestic"
            rates = calc_domestic_rates(from_pin, to_pin, chargeable)
            dest_label = f"{to_pin}, India"

        rates_lines = "\n".join(
            f"  • {carrier:<32}: ₹{amount:,}"
            for carrier, amount in sorted(rates.items(), key=lambda x: x[1])
        )
        dim_line = f"📐 Dimensions : {int(l)}×{int(w)}×{int(h)} cm\n" if not is_doc else ""
        vol_note = (
            f"⚖️  Chargeable  : {chargeable:.0f} g (volumetric applied)\n"
            if (not is_doc and chargeable != weight_g) else
            f"⚖️  Weight      : {weight_g:.0f} g\n"
        )

        response = (
            f"📦 *Shipping Rate Estimate*\n\n"
            f"📍 From       : {from_pin}\n"
            f"📍 To         : {dest_label}\n"
            f"🏷️  Type       : {'Document' if is_doc else 'Non-Document'}\n"
            f"🌍 Zone       : {zone}\n"
            f"{vol_note}"
            f"{dim_line}\n"
            f"*Carrier Rates:*\n{rates_lines}\n\n"
            f"_Rates are estimates. Final charges depend on actual pickup scan._\n\n"
            f"Would you like to book a shipment?"
        )

        dispatcher.utter_message(
            text=response,
            buttons=[
                {"title": "✅ Book Now",  "payload": "/book_shipment"},
                {"title": "🔙 Main Menu", "payload": "/greet"},
            ]
        )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )

        return [ActiveLoop(None), SlotSet("requested_slot", None)] + _clear(RATES_SLOTS)

#------------------------ RATES FORM VALIDATION -------------------------
class ValidateRatesForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_rates_form"
    
    async def required_slots(
        self,
        domain_slots: List[Text],
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> List[Text]:

        shipment_type = tracker.get_slot("shipment_type")

        if shipment_type == "document":
            return [
                "destination_country",
                "from_pincode",
                "to_pincode",
                "shipment_type",
                "weight_grams"
            ]

        return domain_slots

    def validate_destination_country(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"destination_country": None}
        if _is_cancel(tracker):
            return {s: None for s in RATES_SLOTS}
        val = (slot_value or "").strip().lower()
        if val in ("india", "in", "domestic", "within india", "same country"):
            return {"destination_country": "India"}
        if not re.fullmatch(r"[a-zA-Z\s\-]+", val) or len(val) < 2:
            dispatcher.utter_message(text="🌍 Please enter a valid destination country name.")
            return {"destination_country": None}
        return {"destination_country": val.title()}

    def validate_from_pincode(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"from_pincode": None}
        if _is_cancel(tracker):
            return {s: None for s in RATES_SLOTS}
        val = (slot_value or "").strip()
        if not re.fullmatch(r"\d{6}", val):
            dispatcher.utter_message(text="📍 Please enter a valid 6-digit sender pincode.")
            return {"from_pincode": None}
        return {"from_pincode": val}

    def validate_to_pincode(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"to_pincode": None}
        if _is_cancel(tracker):
            return {s: None for s in RATES_SLOTS}
        val = (slot_value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9\s\-]{3,10}", val):
            dispatcher.utter_message(text="📍 Please enter a valid receiver postal/pincode.")
            return {"to_pincode": None}
        return {"to_pincode": val.upper()}

    def validate_shipment_type(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"shipment_type": None}
        if _is_cancel(tracker):
            return {s: None for s in RATES_SLOTS}
        val = (slot_value or "").strip().lower()
        if val in ("document", "doc", "documents"):
            return {"shipment_type": "document"}
        if val in ("non-document", "non document", "nondocument", "parcel", "package", "non_document"):
            return {"shipment_type": "non_document"}
        dispatcher.utter_message(
            text="📋 Please specify: *Document* or *Non-Document*?",
            buttons=[
                {"title": "📄 Document",     "payload": "document"},
                {"title": "📦 Non-Document", "payload": "non-document"},
            ]
        )
        return {"shipment_type": None}

    def validate_weight_grams(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"weight_grams": None}
        if _is_cancel(tracker):
            return {s: None for s in RATES_SLOTS}
        raw = str(slot_value).strip().lower()
        kg_match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*kg", raw)
        g_match  = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:g|grams?)?", raw)
        if kg_match:
            grams = float(kg_match.group(1)) * 1000
        elif g_match:
            grams = float(g_match.group(1))
        else:
            dispatcher.utter_message(text="⚖️ Please enter a valid weight (e.g. 220 grams, 1.5 kg, 500).")
            return {"weight_grams": None}
        if grams <= 0 or grams > 70000:
            dispatcher.utter_message(text="⚖️ Weight must be between 1g and 70kg.")
            return {"weight_grams": None}
        return {"weight_grams": str(grams)}

    def _validate_dimension(self, slot_value, dispatcher, field_name):
        if slot_value is None:
            return {f"{field_name}_cm": None}
        raw = str(slot_value).strip().lower()
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:cm)?", raw)
        if not m or float(m.group(1)) <= 0:
            dispatcher.utter_message(text=f"📐 Please enter a valid {field_name} in cm (e.g. 30).")
            return {f"{field_name}_cm": None}
        return {f"{field_name}_cm": str(float(m.group(1)))}

    def validate_length_cm(self, slot_value, dispatcher, tracker, domain):
        if _is_cancel(tracker): return {s: None for s in RATES_SLOTS}
        return self._validate_dimension(slot_value, dispatcher, "length")

    def validate_width_cm(self, slot_value, dispatcher, tracker, domain):
        if _is_cancel(tracker): return {s: None for s in RATES_SLOTS}
        return self._validate_dimension(slot_value, dispatcher, "width")

    def validate_height_cm(self, slot_value, dispatcher, tracker, domain):
        if _is_cancel(tracker): return {s: None for s in RATES_SLOTS}
        return self._validate_dimension(slot_value, dispatcher, "height")


#-------------- To Prefill Rates ------------------
def correct_country(name):
    countries = list(CITY_TO_COUNTRY.values()) + ["india", "usa"]
    countries = [c.lower() for c in countries]
    match = difflib.get_close_matches(name.lower(), countries, n=1, cutoff=0.7)
    return match[0] if match else name  
   
CITY_TO_COUNTRY = {
    "berlin": "Germany",
    "paris": "France",
    "london": "United Kingdom",
    "dubai": "UAE",
}
class ActionPrefillRates(Action):

    def name(self):
        return "action_prefill_rates"

    def run(self, dispatcher, tracker, domain):

        text = tracker.latest_message.get("text", "").lower()
        events = []

        match = re.search(r"from\s+([a-zA-Z\s]+?)\s+to\s+([a-zA-Z\s]+)", text)

        #--------------- CASE 1: USER TYPED "from → to" --------------
        if match:
            from_city = match.group(1).strip().lower().split()[-1]
            to_city = match.group(2).strip().lower().split()[-1]

            events.append(SlotSet("from_city", from_city.title()))
            events.append(SlotSet("to_city", to_city.title()))

            # DOMESTIC
            if to_city in CITY_TO_PINCODE:
                dispatcher.utter_message(
                    text=(
                        f"I'll help you calculate shipping rates from {from_city.title()} to {to_city.title()}.\n\n"
                        f"🇮🇳 Domestic shipment selected."
                    )
                )
                events.append(SlotSet("destination_country", "India"))

            # INTERNATIONAL
            else:
                country = CITY_TO_COUNTRY.get(to_city, to_city.title())

                dispatcher.utter_message(
                    text=(
                        f"I'll help you calculate shipping rates from {from_city.title()} to {to_city.title()}.\n\n"
                        f"🌍 Destination country detected: {country}"
                    )
                )
                events.append(SlotSet("destination_country", country))

        #-------------- CASE 2: USER CLICKED "Rates" --------------------
        else:
            dispatcher.utter_message(
                text="📦 Let's calculate shipping rates."
            )

        return events


#-------------------- CANCEL RATES FORM ----------------------
class ActionCancelRatesForm(Action):
    def name(self):
        return "action_cancel_rates_form"

    def run(self, dispatcher, tracker, domain):
        response = "No problem! 👋 Feel free to ask whenever you're ready to check shipping rates. I'm here to help! 🚚"
        dispatcher.utter_message(text=response)
        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )
        return [ActiveLoop(None), SlotSet("requested_slot", None)] + _clear(RATES_SLOTS)

#-------------------- NEAREST BRANCH --------------------------
class ActionNearestBranch(Action):
    def name(self):
        return "action_get_nearest_branch"

    def run(self, dispatcher, tracker, domain):
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
            "ahmedabad": "ahmedabad",   
        }
        city_key = city_aliases.get(city_key, city_key)

        branch = get_branch(city_key)

        if branch:
            response = (
                f"🏢 *Nearest Branch – {city.strip().title()}*\n\n"
                f"📍 Address       : {branch['address']}\n"
                f"📞 Phone         : {branch['phone']}\n"
                f"📧 Email         : {branch['email']}\n"
                f"🕐 Working Hours : {branch['working_hours']}\n\n"
                f"Would you like to book a shipment or schedule a pickup?"
            )
            dispatcher.utter_message(
                text=response,
                buttons=[
                    {"title": "🚚 Book Shipment",   "payload": "/book_shipment"},
                    {"title": "📦 Schedule Pickup", "payload": "/schedule_pickup"},
                ]
            )
        else:
            response = (
                f"😔 Sorry, no branch found in *{city.strip().title()}* yet.\n"
                f"We currently have branches in Mumbai, Delhi, Bangalore, and Ahmedabad."
            )
        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )

        return [
            ActiveLoop(None),
            SlotSet("requested_slot", None),
            SlotSet("nearest_branch", None),
        ]


#-------------------- SCHEDULE PICKUP -------------------
class ActionSchedulePickup(Action):
    def name(self):
        return "action_schedule_pickup"

    def run(self, dispatcher, tracker, domain):
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
                text="❌ Pickup could not be scheduled — some details are missing.\nPlease start again.",
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

        success = insert_pickup(
            pickup_id  = pickup_id,
            name       = name,
            contact    = contact,
            address    = address,
            pickup_date= date,
            pickup_time= time,
        )

        if not success:
            logger.warning("Pickup DB insert failed for %s — still shown to user", pickup_id)

        response = (
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

        dispatcher.utter_message(text=response)

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )
        return [ActiveLoop(None), SlotSet("requested_slot", None)] + _clear(PICKUP_SLOTS)


#--------------------- PICKUP FORM VALIDATION ---------------------
class ValidatePickupForm(FormValidationAction):
    def name(self):
        return "validate_pickup_form"

    def _is_cancel_intent(self, tracker) -> bool:
        intent = tracker.latest_message.get("intent", {}).get("name")
        return intent in ["deny", "stop", "cancel_booking", "cancel_shipment"]

    def validate_pickup_name(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in PICKUP_SLOTS + ["requested_slot"]}
        if not slot_value:
            return {"pickup_name": None}
        val = slot_value.strip()
        if len(val) < 2:
            dispatcher.utter_message(text="👤 Please enter a valid name.")
            return {"pickup_name": None}
        return {"pickup_name": val}

    def validate_pickup_contact(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["pickup_contact", "pickup_address",
                                       "pickup_date", "pickup_time", "requested_slot"]}
        if not slot_value:
            return {"pickup_contact": None}
        val = slot_value.strip()
        if not re.fullmatch(r"\d{10}", val):
            dispatcher.utter_message(text="📵 Contact number must be exactly 10 digits. Please re-enter.")
            return {"pickup_contact": None}
        return {"pickup_contact": val}

    def validate_pickup_address(self, slot_value, dispatcher, tracker, domain):
        if self._is_cancel_intent(tracker):
            return {s: None for s in ["pickup_address", "pickup_date", "pickup_time", "requested_slot"]}
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
            return {s: None for s in ["pickup_date", "pickup_time", "requested_slot"]}
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
                dispatcher.utter_message(text="🕐 Pickup is available only between *9:00 AM and 6:00 PM*.")
                return {"pickup_time": None}
            return {"pickup_time": parser.parse(slot_value).strftime("%I:%M %p")}
        except Exception:
            dispatcher.utter_message(text="🕐 Invalid time. Please enter like: *10 AM*, *2:30 PM*, or *14:30*")
            return {"pickup_time": None}


#--------------------- CANCEL ANY ACTIVE FORM ----------------------------

class ActionCancelActiveForm(Action):
    def name(self):
        return "action_cancel_active_form"

    def run(self, dispatcher, tracker, domain):
        response = "❌ Current process cancelled.\n\nHow can I help you next?"
        dispatcher.utter_message(
            text=response,
            buttons=[
                {"title": "📦 Track Shipment", "payload": "/track_shipment"},
                {"title": "🚚 Book Shipment",  "payload": "/book_shipment"},
                {"title": "💰 Get Rates",       "payload": "/check_rates"},
                {"title": "📍 Nearest Branch",  "payload": "/nearest_branch"},
                {"title": "🔄 Schedule Pickup", "payload": "/schedule_pickup"},
            ]
        )
        # # Log USER message
        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=tracker.latest_message.get("text"),
        #     role="user",
        #     intent=tracker.latest_message.get("intent", {}).get("name"),
        #     confidence=tracker.latest_message.get("intent", {}).get("confidence"),
        # )

        # log_chat(
        #     session_id=tracker.get_slot("session_id") or tracker.sender_id,
        #     message=response,
        #     role="bot",
        #     intent=None,
        #     confidence=None,
        # )
        return (
            _clear(BOOKING_SLOTS)
            + _clear(PICKUP_SLOTS)
            + _clear(RATES_SLOTS)
            + [SlotSet("tracking_id", None), SlotSet("nearest_branch", None)]
        )


#--------------------- SESSION START ----------------------

TRANSIENT_SLOTS = set(BOOKING_SLOTS + PICKUP_SLOTS + RATES_SLOTS + ["tracking_id", "nearest_branch"])

class ActionSessionStart(Action):
    def name(self):
        return "action_session_start"

    async def run(self, dispatcher, tracker, domain):

        session_id = tracker.sender_id   

        print("SESSION FROM FRONTEND:", session_id)

        ensure_session(session_id)

        return [
            SessionStarted(),
            SlotSet("session_id", session_id),
            ActionExecuted("action_listen")
        ]
#------------------ RESET SLOTS ------------------ 

class ActionResetLogisticsSlots(Action):
    def name(self):
        return "action_reset_logistics_slots"

    def run(self, dispatcher, tracker, domain):
        return (
            _clear(BOOKING_SLOTS)
            + _clear(PICKUP_SLOTS)
            + _clear(RATES_SLOTS)
            + [SlotSet("tracking_id", None), SlotSet("nearest_branch", None)]
        )
    
# #---------------- Log All msg -------------------
# class ActionLogAllMessages(Action):
#     def name(self):
#         return "action_log_all_messages"

#     def run(self, dispatcher, tracker, domain):

#         session_id = tracker.get_slot("session_id") or tracker.sender_id

#         user_text = tracker.latest_message.get("text")

#         last_logged_user = tracker.get_slot("last_logged_user")

#         if user_text and user_text != last_logged_user:
#             log_chat(
#                 session_id=session_id,
#                 message=user_text,
#                 role="user",
#                 intent=tracker.latest_message.get("intent", {}).get("name"),
#                 confidence=tracker.latest_message.get("intent", {}).get("confidence")
#             )

#         bot_text = None
#         for e in reversed(tracker.events):
#             if e.get("event") == "bot" and e.get("text"):
#                 bot_text = e.get("text")
#                 break
#     
#         last_logged_bot = tracker.get_slot("last_logged_bot")

#         if bot_text and bot_text != last_logged_bot:
#             log_chat(
#                 session_id=session_id,
#                 message=bot_text,
#                 role="bot"
#             )

#         return [
#             SlotSet("last_logged_user", user_text),
#             SlotSet("last_logged_bot", bot_text)
#         ]
    

    
