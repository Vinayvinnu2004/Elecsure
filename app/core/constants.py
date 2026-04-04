"""app/core/constants.py — Business constants: pincodes, services taxonomy, time slots."""

# ── Karimnagar District Pincodes with Center Coordinates ──────────────
KARIMNAGAR_PINCODES = {
    "505001": { "area": "Karimnagar Head PO", "lat": 18.4386, "lng": 79.1288 },
    "505002": { "area": "Market Area/Ramnagar", "lat": 18.4418, "lng": 79.1364 },
    "505003": { "area": "Kamanpur", "lat": 18.4326, "lng": 79.1352 },
    "505004": { "area": "Karimnagar Rural", "lat": 18.4486, "lng": 79.1088 },
    "505005": { "area": "Industrial Area", "lat": 18.4186, "lng": 79.1388 },
    "505122": { "area": "Jammikunta", "lat": 18.3000, "lng": 79.4300 },
    "505184": { "area": "Huzurabad", "lat": 18.2300, "lng": 79.3800 },
    "505208": { "area": "Ramagundam", "lat": 18.7600, "lng": 79.4600 },
    "505215": { "area": "Gangadhara", "lat": 18.5700, "lng": 79.0300 },
    "505305": { "area": "Manakondur", "lat": 18.4100, "lng": 79.1900 },
    "505402": { "area": "Kodurpaka", "lat": 18.5100, "lng": 78.9600 },
    "505445": { "area": "Veenavanka", "lat": 18.3600, "lng": 79.3100 },
    "505450": { "area": "Kothapalli", "lat": 18.4700, "lng": 79.0800 },
    "505460": { "area": "Thimmapur", "lat": 18.3500, "lng": 79.1200 },
    "505469": { "area": "Ganneruvaram", "lat": 18.2800, "lng": 79.2400 },
    "505471": { "area": "Mulkanur", "lat": 18.1700, "lng": 79.2800 },
    "505472": { "area": "Ramadugu", "lat": 18.5500, "lng": 79.0700 },
    "505481": { "area": "Nustulapur", "lat": 18.3700, "lng": 79.1600 },
    "505501": { "area": "Husnabad", "lat": 18.1300, "lng": 79.1200 },
    "505531": { "area": "Huzurabad (Alt)", "lat": 18.2320, "lng": 79.3850 },
}

# ── Geofencing Constants ─────────────────────────────────────────────
GEOFENCE_RADIUS_KM = 5.0
KARIMNAGAR_BOUNDS = {
    "min_lat": 17.5, "max_lat": 19.5,
    "min_lng": 78.5, "max_lng": 80.5
}

# ── Time Slot Definitions ─────────────────────────────────────────────
TIME_SLOTS = [
    {"id": "06-09", "label": "6:00 AM – 9:00 AM",  "start": "06:00", "end": "09:00", "type": "normal",    "surcharge": 0},
    {"id": "09-11", "label": "9:00 AM – 11:00 AM", "start": "09:00", "end": "11:00", "type": "peak",      "surcharge": 0},
    {"id": "11-13", "label": "11:00 AM – 1:00 PM", "start": "11:00", "end": "13:00", "type": "peak",      "surcharge": 0},
    {"id": "13-16", "label": "1:00 PM – 4:00 PM",  "start": "13:00", "end": "16:00", "type": "normal",    "surcharge": 0},
    {"id": "16-19", "label": "4:00 PM – 7:00 PM",  "start": "16:00", "end": "19:00", "type": "normal",    "surcharge": 0},
    {"id": "19-20", "label": "7:00 PM – 8:00 PM",  "start": "19:00", "end": "20:00", "type": "normal",    "surcharge": 0},
    {"id": "20-22", "label": "8:00 PM – 10:00 PM", "start": "20:00", "end": "22:00", "type": "peak",      "surcharge": 0},
    {"id": "22-24", "label": "10:00 PM – 12:00 AM","start": "22:00", "end": "00:00", "type": "peak",      "surcharge": 0},
    {"id": "00-03", "label": "12:00 AM – 3:00 AM", "start": "00:00", "end": "03:00", "type": "midnight",  "surcharge": 50},
    {"id": "03-06", "label": "3:00 AM – 6:00 AM",  "start": "03:00", "end": "06:00", "type": "midnight",  "surcharge": 50},
]

SLOT_TYPE_LABELS = {
    "normal":   "",
    "peak":     "⭐ Peak Slot",
    "midnight": "🌙 Midnight Slot (+₹50)",
}

# ── Services Taxonomy ─────────────────────────────────────────────────
SERVICES_TAXONOMY = {
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
