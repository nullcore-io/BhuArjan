"""Event type enum — the complete vocabulary of the ledger (Docs/Backend.md §3).

The ledger accepts only these types. Which of them are *legal* at a given moment is a
rule-set question (see app/domain/rules/engine.py), never a code question.
"""

from enum import Enum


class EventType(str, Enum):
    # --- Project ---
    PROJECT_CREATED = "PROJECT_CREATED"
    PROPOSAL_SUBMITTED = "PROPOSAL_SUBMITTED"
    PROPOSAL_SCRUTINY = "PROPOSAL_SCRUTINY"
    PROPOSAL_APPROVED = "PROPOSAL_APPROVED"
    PROPOSAL_RETURNED = "PROPOSAL_RETURNED"

    # --- SIA ---
    SIA_NOTIFIED = "SIA_NOTIFIED"
    SIA_PUBLIC_HEARING = "SIA_PUBLIC_HEARING"
    SIA_REPORT_PUBLISHED = "SIA_REPORT_PUBLISHED"
    EXPERT_GROUP_APPRAISAL = "EXPERT_GROUP_APPRAISAL"
    GOVT_DECISION_S8 = "GOVT_DECISION_S8"
    SIA_EXEMPTED_S40 = "SIA_EXEMPTED_S40"

    # --- Notification ---
    PRELIM_NOTIFICATION_S11 = "PRELIM_NOTIFICATION_S11"
    NOTIFICATION_3A = "NOTIFICATION_3A"
    SURVEY_COMPLETED_S12 = "SURVEY_COMPLETED_S12"
    OBJECTION_RECEIVED = "OBJECTION_RECEIVED"
    OBJECTIONS_DISPOSED = "OBJECTIONS_DISPOSED"

    # --- R&R scheme ---
    RR_SCHEME_DRAFTED_S16 = "RR_SCHEME_DRAFTED_S16"
    RR_SCHEME_APPROVED_S17 = "RR_SCHEME_APPROVED_S17"
    RR_SCHEME_PUBLISHED_S18 = "RR_SCHEME_PUBLISHED_S18"

    # --- Declaration ---
    COST_DEPOSITED_S19_2 = "COST_DEPOSITED_S19_2"
    DECLARATION_S19 = "DECLARATION_S19"
    DECLARATION_3D = "DECLARATION_3D"
    EXTENSION_GRANTED = "EXTENSION_GRANTED"  # {clock_id, authority, order_ref, reasons, new_due_date}

    # --- Award ---
    NOTICE_S21 = "NOTICE_S21"
    CLAIMS_RECEIVED = "CLAIMS_RECEIVED"
    AWARD_S23 = "AWARD_S23"
    AWARD_3G = "AWARD_3G"
    RR_AWARD_S31 = "RR_AWARD_S31"
    COMPENSATION_ASSESSED = "COMPENSATION_ASSESSED"

    # --- Payment ---
    PAYMENT_MADE = "PAYMENT_MADE"  # {pfms_ref, amount_paise, payee_ref, mode}
    COMPENSATION_PAID_FULL = "COMPENSATION_PAID_FULL"

    # --- Possession ---
    POSSESSION_TAKEN_S38 = "POSSESSION_TAKEN_S38"
    POSSESSION_3E = "POSSESSION_3E"
    URGENCY_S40_INVOKED = "URGENCY_S40_INVOKED"

    # --- R&R delivery ---
    RR_ENTITLEMENT_DELIVERED = "RR_ENTITLEMENT_DELIVERED"

    # --- Legal ---
    REFERENCE_FILED_S64 = "REFERENCE_FILED_S64"
    COURT_STAY = "COURT_STAY"
    STAY_VACATED = "STAY_VACATED"
    ARBITRATION_3G5 = "ARBITRATION_3G5"

    # --- Closure ---
    LAND_UTILISED = "LAND_UTILISED"
    LAND_RETURNED_S101 = "LAND_RETURNED_S101"
    CASE_CLOSED = "CASE_CLOSED"
    CASE_LAPSED = "CASE_LAPSED"
    NOTIFICATION_RESCINDED = "NOTIFICATION_RESCINDED"

    # --- Parcel / people ---
    PARCEL_ADDED = "PARCEL_ADDED"
    PARCEL_UPDATED = "PARCEL_UPDATED"
    FAMILY_ENUMERATED = "FAMILY_ENUMERATED"

    # --- Control ---
    EVENT_REVERSED = "EVENT_REVERSED"  # {reversed_event_id, reason}


EVENT_TYPES: set[str] = {e.value for e in EventType}

EVENT_GROUPS: dict[str, list[str]] = {
    "Project": [
        EventType.PROJECT_CREATED, EventType.PROPOSAL_SUBMITTED, EventType.PROPOSAL_SCRUTINY,
        EventType.PROPOSAL_APPROVED, EventType.PROPOSAL_RETURNED,
    ],
    "SIA": [
        EventType.SIA_NOTIFIED, EventType.SIA_PUBLIC_HEARING, EventType.SIA_REPORT_PUBLISHED,
        EventType.EXPERT_GROUP_APPRAISAL, EventType.GOVT_DECISION_S8, EventType.SIA_EXEMPTED_S40,
    ],
    "Notification": [
        EventType.PRELIM_NOTIFICATION_S11, EventType.NOTIFICATION_3A,
        EventType.SURVEY_COMPLETED_S12, EventType.OBJECTION_RECEIVED, EventType.OBJECTIONS_DISPOSED,
    ],
    "R&R scheme": [
        EventType.RR_SCHEME_DRAFTED_S16, EventType.RR_SCHEME_APPROVED_S17,
        EventType.RR_SCHEME_PUBLISHED_S18,
    ],
    "Declaration": [
        EventType.COST_DEPOSITED_S19_2, EventType.DECLARATION_S19, EventType.DECLARATION_3D,
        EventType.EXTENSION_GRANTED,
    ],
    "Award": [
        EventType.NOTICE_S21, EventType.CLAIMS_RECEIVED, EventType.AWARD_S23, EventType.AWARD_3G,
        EventType.RR_AWARD_S31, EventType.COMPENSATION_ASSESSED,
    ],
    "Payment": [EventType.PAYMENT_MADE, EventType.COMPENSATION_PAID_FULL],
    "Possession": [
        EventType.POSSESSION_TAKEN_S38, EventType.POSSESSION_3E, EventType.URGENCY_S40_INVOKED,
    ],
    "R&R delivery": [EventType.RR_ENTITLEMENT_DELIVERED],
    "Legal": [
        EventType.REFERENCE_FILED_S64, EventType.COURT_STAY, EventType.STAY_VACATED,
        EventType.ARBITRATION_3G5,
    ],
    "Closure": [
        EventType.LAND_UTILISED, EventType.LAND_RETURNED_S101, EventType.CASE_CLOSED,
        EventType.CASE_LAPSED, EventType.NOTIFICATION_RESCINDED,
    ],
    "Parcel/people": [
        EventType.PARCEL_ADDED, EventType.PARCEL_UPDATED, EventType.FAMILY_ENUMERATED,
    ],
    "Control": [EventType.EVENT_REVERSED],
}

# Operational bookkeeping: referenced by rule-sets but not a statutory instrument, so no
# document/reason is demanded (Docs/rules.md C1).
NON_STATUTORY: set[str] = {
    EventType.PARCEL_ADDED.value,
    EventType.FAMILY_ENUMERATED.value,
    EventType.PAYMENT_MADE.value,
}

# Consequence events the clock engine emits by itself as the system actor.
SYSTEM_EMITTED: set[str] = {
    EventType.NOTIFICATION_RESCINDED.value,
    EventType.CASE_LAPSED.value,
}

NOTIFICATION_EVENTS: set[str] = {
    EventType.PRELIM_NOTIFICATION_S11.value,
    EventType.NOTIFICATION_3A.value,
}

POSSESSION_EVENTS: set[str] = {
    EventType.POSSESSION_TAKEN_S38.value,
    EventType.POSSESSION_3E.value,
}

AWARD_EVENTS: set[str] = {EventType.AWARD_S23.value, EventType.AWARD_3G.value}

TERMINAL_STAGES: set[str] = {"LAPSED", "CLOSED"}
