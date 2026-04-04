from app.models.user import (User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN, 
                             ServiceArea, TOOLKIT_NONE, TOOLKIT_BASIC, TOOLKIT_ADVANCED, TOOLKIT_BOTH,
                             PendingUser, CustomerProfile, ElectricianProfile)
from app.models.service import Service, SERVICE_TAXONOMY
from app.models.booking import (Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, 
                                 STATUS_ARRIVED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
                                 CANCEL_MANUAL, CANCEL_SYSTEM, CANCEL_ELECTRICIAN,
                                 TimeSlot, SLOT_AVAILABLE, SLOT_BOOKED, SLOT_COMPLETED, SLOT_FAILED, SLOT_CANCELLED, SLOT_OVER,
                                 Review, ActionToken, BookingHistory)
from app.models.payment import Payment, PAYMENT_PENDING, PAYMENT_COMPLETED, PAYMENT_FAILED, PAYMENT_REFUNDED, PaymentLog
from app.models.notification import Notification, NotificationType, NotificationEvent
from app.models.el_score import ELScoreLog, ELScoreEvent, SCORE_DELTAS
from app.models.earnings import WeeklyReport, ElectricianEarning
# Legacy export for backwards compatibility where possible (mapping to constants)
UserRole = type('UserRole', (), {'CUSTOMER': ROLE_CUSTOMER, 'ELECTRICIAN': ROLE_ELECTRICIAN, 'ADMIN': ROLE_ADMIN})
BookingStatus = type('BookingStatus', (), {
    'REQUESTED': STATUS_REQUESTED, 'ASSIGNED': STATUS_ASSIGNED, 'ACCEPTED': STATUS_ACCEPTED,
    'ARRIVED': STATUS_ARRIVED, 'STARTED': STATUS_STARTED, 'COMPLETED': STATUS_COMPLETED,
    'REVIEWED': STATUS_REVIEWED, 'CANCELLED': STATUS_CANCELLED
})
CancellationType = type('CancellationType', (), {'MANUAL': CANCEL_MANUAL, 'SYSTEM': CANCEL_SYSTEM, 'ELECTRICIAN': CANCEL_ELECTRICIAN})
SlotStatus = type('SlotStatus', (), {
    'AVAILABLE': SLOT_AVAILABLE, 'BOOKED': SLOT_BOOKED, 'COMPLETED': SLOT_COMPLETED, 
    'FAILED': SLOT_FAILED, 'CANCELLED': SLOT_CANCELLED, 'OVER': SLOT_OVER
})
PaymentStatus = type('PaymentStatus', (), {
    'PENDING': PAYMENT_PENDING, 'COMPLETED': PAYMENT_COMPLETED, 'FAILED': PAYMENT_FAILED, 'REFUNDED': PAYMENT_REFUNDED
})
ToolKit = type('ToolKit', (), {
    'BASIC': TOOLKIT_BASIC, 'ADVANCED': TOOLKIT_ADVANCED, 'BOTH': TOOLKIT_BOTH, 'NONE': TOOLKIT_NONE
})

__all__ = [
    "User", "ROLE_CUSTOMER", "ROLE_ELECTRICIAN", "ROLE_ADMIN", "ServiceArea", "PendingUser",
    "CustomerProfile", "ElectricianProfile", "TOOLKIT_NONE", "TOOLKIT_BASIC", "TOOLKIT_ADVANCED", "TOOLKIT_BOTH",
    "Service", "SERVICE_TAXONOMY",
    "Booking", "STATUS_REQUESTED", "STATUS_ASSIGNED", "STATUS_ACCEPTED", "STATUS_ARRIVED", 
    "STATUS_STARTED", "STATUS_COMPLETED", "STATUS_REVIEWED", "STATUS_CANCELLED",
    "CANCEL_MANUAL", "CANCEL_SYSTEM", "CANCEL_ELECTRICIAN",
    "TimeSlot", "SLOT_AVAILABLE", "SLOT_BOOKED", "SLOT_COMPLETED", "SLOT_FAILED", "SLOT_CANCELLED", "SLOT_OVER",
    "Review", "ActionToken", "BookingHistory",
    "Payment", "PAYMENT_PENDING", "PAYMENT_COMPLETED", "PAYMENT_FAILED", "PAYMENT_REFUNDED", "PaymentLog",
    "Notification", "NotificationType", "NotificationEvent",
    "ELScoreLog", "ELScoreEvent", "SCORE_DELTAS",
    "WeeklyReport", "ElectricianEarning",
    "UserRole", "BookingStatus", "CancellationType", "SlotStatus", "PaymentStatus", "ToolKit"
]
