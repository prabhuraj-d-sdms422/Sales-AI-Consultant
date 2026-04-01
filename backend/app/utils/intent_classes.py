from enum import Enum


class IntentClass(str, Enum):
    GREETING = "GREETING"
    DISCOVERY_RESPONSE = "DISCOVERY_RESPONSE"
    PROBLEM_STATED = "PROBLEM_STATED"        # Client has clearly described what they need/want to build
    SOLUTION_REQUEST = "SOLUTION_REQUEST"    # Client explicitly asks what solutions exist
    PRICING_INQUIRY = "PRICING_INQUIRY"
    OBJECTION = "OBJECTION"
    ESCALATION_REQUEST = "ESCALATION_REQUEST"
    LEAD_INFO_SHARED = "LEAD_INFO_SHARED"
    BUYING_SIGNAL = "BUYING_SIGNAL"
    CONVERSATION_ENDED = "CONVERSATION_ENDED"
    OFF_TOPIC = "OFF_TOPIC"
    MANIPULATION_ATTEMPT = "MANIPULATION_ATTEMPT"
    GENERAL_INQUIRY = "GENERAL_INQUIRY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


CONFIDENCE_THRESHOLD = 0.70

CONVERSATIONAL_INTENTS = {
    IntentClass.GREETING,
    IntentClass.GENERAL_INQUIRY,
    IntentClass.LOW_CONFIDENCE,
}

AMBIGUOUS_INTENT_SIGNALS = [
    "think about",
    "not sure",
    "maybe",
    "interesting",
    "hmm",
    "okay",
    "fine",
    "whatever",
    "I guess",
    "perhaps",
]
