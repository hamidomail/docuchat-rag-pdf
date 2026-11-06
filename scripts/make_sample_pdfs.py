"""Generate the two fictional demo PDFs in sample_docs/.

    python scripts/make_sample_pdfs.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "sample_docs"
styles = getSampleStyleSheet()
H1, H2, P = styles["Title"], styles["Heading2"], styles["BodyText"]


def build(filename, title, sections):
    OUT.mkdir(exist_ok=True)
    doc = SimpleDocTemplate(str(OUT / filename), pagesize=A4, title=title, author="Demo content",
                            leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    story = [Paragraph(title, H1), Spacer(1, 12)]
    for item in sections:
        if item == "PAGE":
            story.append(PageBreak())
        elif isinstance(item, Table):
            story += [item, Spacer(1, 10)]
        elif item.startswith("## "):
            story.append(Paragraph(item[3:], H2))
        else:
            story += [Paragraph(item, P), Spacer(1, 4)]

    def footer(canvas, d):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2.2 * cm, 1.2 * cm, f"{title} - fictional document for demonstration purposes")
        canvas.drawRightString(A4[0] - 2.2 * cm, 1.2 * cm, f"Page {d.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def table(rows, widths):
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


handbook = [
    "## 1. Welcome to Northwind Logistics",
    "This handbook explains how we work together at Northwind Logistics. It applies to all permanent and "
    "fixed-term employees in Europe from 1 January 2026. Where local law gives you more favourable terms, local law applies. "
    "Questions about this handbook can be sent to the People Team at people@northwind.example.",
    "## 2. Working hours",
    "The standard working week is 37.5 hours, usually Monday to Friday. Core collaboration hours are 10:00 to 15:00 local time; "
    "outside those hours you may organise your day freely as long as your team agrees. Overtime must be approved in advance by "
    "your manager and is compensated either with time off in lieu (1.25 hours per hour worked) or paid at 125% of the hourly rate.",
    "## 3. Remote and hybrid work",
    "Most office-based roles are hybrid. Employees may work remotely up to three days per week, agreed with their manager. "
    "Warehouse and fleet roles are on-site by nature and are not eligible for regular remote work.",
    "Working from another country is allowed for up to 20 working days per calendar year. You must request it at least "
    "two weeks in advance and obtain approval from both your manager and the People Team, because tax and social security rules "
    "can apply. Working from a country under international sanctions is never permitted.",
    "Remote workers receive a home-office allowance of 30 EUR per month, paid with salary, to cover internet and electricity.",
    "PAGE",
    "## 4. Paid time off",
    "New full-time employees receive 25 days of paid vacation per year, in addition to public holidays. After five years of "
    "service the allowance rises to 28 days. Part-time employees receive a pro-rated allowance based on their contracted hours.",
    "Vacation accrues at 2.08 days per month of employment. Up to 5 unused days may be carried over into the next year, "
    "but carried-over days must be taken before 31 March or they are lost. Requests of more than 5 consecutive days should be "
    "submitted at least four weeks in advance in the HR portal.",
    "## 5. Sick leave",
    "If you are ill, tell your manager before 10:00 on the first day of absence. A medical certificate is required from the "
    "fourth consecutive day of sickness. Northwind tops up statutory sick pay to 100% of base salary for up to 60 calendar days per year.",
    "## 6. Parental leave",
    "Birthing parents receive 20 weeks of fully paid parental leave. Non-birthing parents, including adoptive parents, receive "
    "12 weeks of fully paid leave that can be taken in up to three blocks within the first 18 months. A phased return of four weeks "
    "at 80% working time and 100% pay is offered after any parental leave.",
    "PAGE",
    "## 7. Expenses and travel",
    "Business expenses must be submitted in the expense tool with a receipt within 30 days of being incurred. Expenses submitted "
    "later than 90 days will not be reimbursed.",
    table([
        ["Category", "Limit", "Notes"],
        ["Meals while travelling", "45 EUR per day", "Alcohol is not reimbursed"],
        ["Hotel", "160 EUR per night", "220 EUR in London, Paris and Zurich"],
        ["Train", "Standard class", "First class for journeys over 4 hours"],
        ["Flights", "Economy", "Must be booked through the travel portal"],
        ["Mileage (own car)", "0.30 EUR per km", "Only when no train option exists"],
    ], [4.5 * cm, 4 * cm, 7.5 * cm]),
    "## 8. Equipment",
    "Every employee receives a laptop, a headset and, for hybrid roles, a monitor for home use. Equipment remains company "
    "property and must be returned within 5 working days of your last day. Lost or stolen devices must be reported to the IT "
    "Service Desk within 24 hours.",
    "## 9. Information security",
    "Multi-factor authentication is mandatory on all company accounts. Never share passwords, including with colleagues or IT staff. "
    "Customer data may only be stored in approved systems; copying customer data to personal devices or personal cloud storage is a "
    "serious breach of policy. Suspected phishing emails should be reported with the Report button in the mail client.",
    "## 10. Code of conduct",
    "We expect respectful, honest behaviour toward colleagues, customers and partners. Gifts from suppliers worth more than 50 EUR "
    "must be declared to your manager. Concerns about misconduct can be raised confidentially through the Speak Up line, and "
    "retaliation against anyone who raises a concern in good faith is prohibited.",
]

manual = [
    "## 1. In the box",
    "Aurora X2 thermostat, wall plate, trim plate, 4 screws and anchors, wire labels, C-wire adapter, quick start card.",
    "## 2. Before you install",
    "Turn off power to your heating and cooling system at the breaker before removing your old thermostat. The Aurora X2 works "
    "with most 24 V systems: gas, oil and electric furnaces, heat pumps with auxiliary heat, and boilers. It is not compatible "
    "with 120 V or 240 V line-voltage systems such as electric baseboard heaters.",
    "A common wire (C-wire) is strongly recommended. If your system has no C-wire, install the included C-wire adapter at the "
    "furnace control board; see section 4.",
    "## 3. Wiring",
    table([
        ["Terminal", "Typical wire colour", "Function"],
        ["R / Rh", "Red", "24 V power"],
        ["C", "Blue or black", "Common (return path for power)"],
        ["W1", "White", "Heat stage 1"],
        ["Y1", "Yellow", "Cooling stage 1 / compressor"],
        ["G", "Green", "Fan"],
        ["O/B", "Orange or dark blue", "Heat pump reversing valve"],
    ], [3 * cm, 5 * cm, 8 * cm]),
    "Insert each wire into the terminal that matches the label you put on it when removing the old thermostat. Wire colours are "
    "conventions only; always follow the labels rather than the colours.",
    "PAGE",
    "## 4. Installing the C-wire adapter",
    "Connect the adapter to the R, C, W and Y terminals on the furnace control board as shown on the adapter label, then connect "
    "the existing thermostat wires to the adapter. The adapter lets the Aurora X2 draw steady power without needing a new cable.",
    "## 5. Connecting to the Aurora app",
    "Download the Aurora Home app, create an account and tap Add device. Hold the Menu button on the thermostat for 3 seconds until "
    "the screen shows a pairing code, then enter the code in the app. The thermostat supports 2.4 GHz Wi-Fi networks only.",
    "## 6. Schedules and Eco mode",
    "The default schedule keeps 21 °C from 06:30 to 22:00 and 17 °C overnight. You can create up to 6 temperature periods per day in "
    "the app. Eco mode lowers the heating setpoint by 3 °C (or raises the cooling setpoint by 3 °C) while everyone is away, using "
    "phone geofencing. Households in the pilot programme saved on average 14% on heating costs with Eco mode enabled.",
    "PAGE",
    "## 7. Error codes",
    table([
        ["Code", "Meaning", "What to do"],
        ["E1", "Temperature sensor fault", "Restart the thermostat. If it persists, contact support."],
        ["E2", "Wi-Fi connection lost", "Check your router, then re-pair from the app."],
        ["E3", "Wiring mismatch detected", "Turn off power and check wires against the labels."],
        ["E4", "Low or unstable power (below 18 V)", "Check that the C-wire is connected at both ends, or install the C-wire adapter."],
        ["E5", "Heat pump lockout", "Wait 5 minutes; the compressor protection delay will clear."],
    ], [1.5 * cm, 5 * cm, 9.5 * cm]),
    "## 8. Factory reset",
    "To restore factory settings, hold the Menu and Down buttons together for 10 seconds until the screen shows RESET, then "
    "release. All schedules, Wi-Fi credentials and the link to your account are erased. You will need to pair the thermostat again.",
    "## 9. Warranty and support",
    "The Aurora X2 has a 3-year limited warranty from the date of purchase covering manufacturing defects. Damage caused by "
    "incorrect wiring or line-voltage connection is not covered. Support is available by chat in the app, seven days a week.",
    "## 10. Specifications",
    "Display: 3.5-inch colour touchscreen. Sensors: temperature (accuracy ±0.3 °C), humidity, occupancy. Power: 24 V AC, 2 W. "
    "Connectivity: Wi-Fi 2.4 GHz, Bluetooth LE. Dimensions: 92 × 92 × 24 mm.",
]

if __name__ == "__main__":
    build("northwind_employee_handbook.pdf", "Northwind Logistics Employee Handbook 2026", handbook)
    build("aurora_x2_thermostat_manual.pdf", "Aurora X2 Smart Thermostat User Manual", manual)
    print(f"Wrote sample PDFs to {OUT}")
