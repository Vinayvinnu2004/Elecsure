"""app/models/service.py — Service catalogue."""

import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, Numeric
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.security import ist_now

SERVICE_TAXONOMY = {
    "Electrical Appliance Repair": {
        
        "subcategories": {
            "Laundry Appliances": [
                "Washing machines (all types)", "Washer", "Dryer",
                "Electric iron (dry iron)", "Steam iron", "Geyser", "Vacuum cleaner",
            ],
            "Cooling Appliances": [
                "Refrigerator repair", "Deep freezer repair",
                "Air conditioner electrical repair", "Air cooler repair",
                "Water cooler repair", "Deep freezer", "Beverage cooler",
            ],
            "Kitchen Appliances": [
                "Microwave oven repair", "Induction stove repair", "Mixer grinder repair",
                "Electric kettle repair", "Rice cooker repair", "OTG oven repair",
                "Dishwasher repair", "Water purifier repair", "Food processor",
                "Blender", "Coffee maker", "Coffee grinder", "Toaster",
                "Air fryer", "Waffle maker",
            ],
            "Computing & IT Devices": [
                "Laptop electrical repair", "Desktop computer repair", "Monitor repair",
                "Printer repair", "Router / modem repair", "UPS repair",
                "Workstation", "All-in-one PC", "Mini PC",
                "Embedded system", "Point-of-sale (POS) system",
            ],
            "Entertainment Appliances": [
                "Television repair", "Set-top box repair", "Home theatre system repair",
                "Audio system repair", "Soundbar", "Speakers",
                "DVD / Blu-ray player", "Streaming media player", "Gaming console",
            ],
        },
    },
    "Wiring & Circuit Repairs": {
        
        "subcategories": {
            "Wiring Fault Repairs": [
                "Short circuit repair", "Loose wiring repair", "Neutral wire fault",
                "Phase wire fault", "Earth leakage fault", "Power failure diagnosis",
                "Power fluctuation issue", "Cable joint repair", "Main line fault repair",
            ],
            "Circuit Protection Repairs": [
                "Frequent MCB tripping fix", "MCB replacement", "Fuse replacement",
                "Distribution board repair", "ELCB / RCCB repair",
                "Main switch replacement", "Changeover switch repair", "Socket repair",
            ],
            "Wiring Replacement & Upgrades": [
                "Burnt wire replacement", "Partial wiring replacement",
                "Old wiring replacement", "Load capacity upgrade",
                "Concealed wiring repair", "Surface wiring repair",
                "Single-phase wiring repair", "Three-phase wiring repair",
                "Service line repair",
            ],
        },
    },
    "Lighting Services": {
        
        "subcategories": {
            "Lighting Repairs": [
                "LED bulb not working", "Tube light not working",
                "Flickering light repair", "Dim light issue",
                "Loose light holder repair", "Burnt holder replacement",
                "LED driver replacement", "Starter / choke replacement",
            ],
            "Lighting Installations": [
                "LED bulb installation", "Tube light installation",
                "Ceiling light installation", "Wall light installation",
                "Decorative light setup", "Outdoor / balcony lighting",
                "Garden lighting installation", "Smart light installation",
            ],
            "Lighting Upgrades": [
                "Conversion to LED lighting", "Energy-efficient lighting upgrade",
                "Smart lighting automation", "Dimming system installation",
            ],
        },
    },
    "Installations": {
        
        "subcategories": {
            "Basic Electrical Installations": [
                "Switch installation", "Power socket (5A / 15A)",
                "Switch board installation", "Plug point installation",
                "Extension board installation",
            ],
            "Appliance Installations": [
                "Ceiling fan installation", "Exhaust fan installation",
                "Geyser installation", "Air cooler installation",
                "Cooker / induction setup", "Microwave / OTG setup",
            ],
            "High-Load & Dedicated Lines": [
                "AC power point", "Geyser power point",
                "Oven / induction line", "Separate appliance circuits",
            ],
            "Safety Installations": [
                "MCB installation / replacement", "New room wiring",
                "Switchboard rewiring", "Distribution board installation",
            ],
            "Backup & Security Installations": [
                "UPS installation", "CCTV installation", "Electric meter installation",
            ],
        },
    },
    "Safety Checks & Inspections": {
        
        "subcategories": {
            "Electrical Safety Inspection": [
                "Electrical safety audit", "Short-circuit risk check",
                "Overload check", "Voltage fluctuation check",
                "Fire risk inspection", "Power quality inspection",
            ],
            "Earthing & Grounding Checks": [
                "Earthing repair", "Earthing continuity",
                "Earthing resistance", "Ground fault inspection",
            ],
            "Protection Device Testing": [
                "MCB condition check", "Fuse health check",
                "RCCB / ELCB test", "MCB trip test",
                "Surge protection assessment",
            ],
        },
    },
    "Power Backup Services": {
        
        "subcategories": {
            "Inverter Services": [
                "Inverter installation", "Inverter repair",
                "Inverter battery connection", "Inverter load configuration",
            ],
            "Battery Services": [
                "Battery replacement", "Battery health check",
                "Battery terminal cleaning", "Battery capacity testing",
            ],
            "Backup Switching Systems": [
                "Changeover switch setup",
                "Manual changeover switch installation",
                "Automatic changeover switch installation",
            ],
        },
    },
    "Electrical Service Packages": {
        
        "subcategories": {
            "Home Electrical Packages": [
                "Old house electrical upgrade", "Home renovation electrical package",
                "Complete home electrical wiring service",
                "Complete home lighting installation",
                "Complete home appliance installation",
            ],
            "Safety Packages": [
                "Complete home safety check",
                "Comprehensive electrical inspection",
                "Electrical safety audit package",
            ],
            "Energy Efficiency Packages": [
                "Home load balancing package",
                "Energy-efficient lighting conversion",
                "Power consumption optimization",
            ],
            "Festival & Event Packages": [
                "Festival lighting full-home package",
                "Wedding lighting setup",
                "Outdoor decorative lighting package",
            ],
            "Backup Power Packages": [
                "Full inverter backup setup",
                "Complete UPS + inverter setup",
                "Critical appliances backup system",
            ],
        },
    },
}


class Service(Base):
    __tablename__ = "services"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    category = Column(String(150), nullable=False, index=True)
    group = Column(String(150), nullable=False)
    service_type = Column(String(50), default="Standard")
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    base_price = Column(Numeric(10, 2), default=500.0)
    duration_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True) # Soft delete
    created_at = Column(DateTime, default=ist_now)

    bookings = relationship("Booking", back_populates="service")
