from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "LPU_Scheduling_Conflict_Resolution_Project_Report.docx"
PURPLE = "30265B"
LIGHT_PURPLE = "EFEDF7"
MUTED = "686777"
ASSETS = ROOT / "report_assets"


def load_font(size: int, bold=False):
    candidates = (
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def report_evaluation() -> dict:
    from backend.app import db
    from backend.app.detection.sweep import detect, summarise
    from backend.app.ml.features import extract
    from backend.app.ml.forest import RandomForest
    from backend.app.ml.metrics import classification_metrics
    from backend.app.ml.train import HYPERPARAMETERS, build_dataset

    context = db.load_context()
    features, labels, _ = build_dataset(context, sample_count=700, seed=2026)
    positives = [
        entry["payload"]["patch"]
        for entry in db.list_audit(200)
        if entry["action"] in {"apply", "manual-move"} and entry["payload"].get("patch")
    ]
    for patch in positives:
        try:
            features.append(extract(context, patch))
            labels.append(1)
        except (KeyError, TypeError):
            continue

    split = int(len(features) * 0.8)
    model = RandomForest(**HYPERPARAMETERS).fit(features[:split], labels[:split])
    test_features = features[split:]
    test_labels = labels[split:]
    probabilities = [model.predict_proba(row) for row in test_features]
    metrics = classification_metrics(probabilities, test_labels)
    tn = fp = fn = tp = 0
    for probability, actual in zip(probabilities, test_labels):
        predicted = int(probability >= 0.5)
        if actual == 0 and predicted == 0:
            tn += 1
        elif actual == 0 and predicted == 1:
            fp += 1
        elif actual == 1 and predicted == 0:
            fn += 1
        else:
            tp += 1
    conflicts = detect(context)
    summary = summarise(conflicts)
    affected_sessions = {sid for conflict in conflicts for sid in conflict.get("session_ids", [])}
    regular_slots = [slot for slot in context.slots.values() if not slot.is_exam]
    regular_rooms = [room for room in context.rooms.values() if room.kind != "exam_hall"]
    occupied_room_slots = {
        (session.room_id, session.slot_id)
        for session in context.sessions.values()
        if session.kind != "exam"
    }
    utilization = round(100 * len(occupied_room_slots) / max(len(regular_slots) * len(regular_rooms), 1))
    return {
        "context": context,
        "metrics": metrics,
        "matrix": ((tn, fp), (fn, tp)),
        "train_count": split,
        "test_count": len(test_labels),
        "conflicts": summary,
        "conflict_free_sessions": len(context.sessions) - len(affected_sessions),
        "room_utilization": utilization,
        "model": model,
    }


def draw_bar_chart(path: Path, title: str, labels: list[str], values: list[float], value_format="{:.0f}") -> None:
    width, height = 1200, 620
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(31, True)
    label_font = load_font(20)
    value_font = load_font(20, True)
    draw.text((72, 42), title, font=title_font, fill="#30265B")
    left, top, right, bottom = 90, 130, 1140, 510
    draw.line((left, bottom, right, bottom), fill="#858391", width=2)
    max_value = max(values, default=1) or 1
    slot = (right - left) / max(len(values), 1)
    bar_width = min(74, slot * 0.58)
    palette = ["#6557B8", "#D65A63", "#E2A545", "#4E9A76", "#6389C7", "#9A6BB5", "#548C98", "#C47B4B"]
    for index, (label, value) in enumerate(zip(labels, values)):
        center = left + slot * (index + 0.5)
        bar_height = (bottom - top) * (value / max_value)
        x0, x1 = center - bar_width / 2, center + bar_width / 2
        y0 = bottom - bar_height
        draw.rounded_rectangle((x0, y0, x1, bottom), radius=9, fill=palette[index % len(palette)])
        formatted = value_format.format(value)
        bounds = draw.textbbox((0, 0), formatted, font=value_font)
        draw.text((center - (bounds[2] - bounds[0]) / 2, y0 - 32), formatted, font=value_font, fill="#252438")
        bounds = draw.textbbox((0, 0), label, font=label_font)
        draw.text((center - (bounds[2] - bounds[0]) / 2, bottom + 20), label, font=label_font, fill="#4F4D5C")
    image.save(path)


def draw_confusion_matrix(path: Path, matrix, sample_count: int) -> None:
    width, height = 1100, 720
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(32, True)
    label_font = load_font(20, True)
    value_font = load_font(42, True)
    note_font = load_font(17)
    draw.text((80, 42), "Confusion Matrix - Acceptance Prediction", font=title_font, fill="#30265B")
    draw.text((80, 92), f"Report-time hold-out set: {sample_count} examples | threshold = 0.50", font=note_font, fill="#686777")
    x0, y0, cell_w, cell_h = 345, 210, 300, 180
    draw.text((x0 + 80, 150), "Predicted class", font=label_font, fill="#30265B")
    draw.text((x0 + 42, 185), "Rejected (0)", font=note_font, fill="#4F4D5C")
    draw.text((x0 + cell_w + 42, 185), "Accepted (1)", font=note_font, fill="#4F4D5C")
    draw.text((85, 345), "Actual", font=label_font, fill="#30265B")
    draw.text((85, 375), "class", font=label_font, fill="#30265B")
    draw.text((205, 275), "Rejected (0)", font=note_font, fill="#4F4D5C")
    draw.text((205, 455), "Accepted (1)", font=note_font, fill="#4F4D5C")
    values = [matrix[0][0], matrix[0][1], matrix[1][0], matrix[1][1]]
    maximum = max(values) or 1
    colors = ((70, 61, 128), (220, 226, 239))
    for row in range(2):
        for col in range(2):
            value = matrix[row][col]
            intensity = value / maximum
            base = colors[0] if row == col else colors[1]
            if row == col:
                fill = (int(226 - 100 * intensity), int(222 - 105 * intensity), int(248 - 100 * intensity))
            else:
                fill = (int(242 - 28 * intensity), int(240 - 30 * intensity), int(248 - 20 * intensity))
            x1, y1 = x0 + col * cell_w, y0 + row * cell_h
            draw.rectangle((x1, y1, x1 + cell_w - 8, y1 + cell_h - 8), fill=fill, outline="#FFFFFF", width=4)
            text = str(value)
            bounds = draw.textbbox((0, 0), text, font=value_font)
            draw.text((x1 + (cell_w - 8 - (bounds[2] - bounds[0])) / 2, y1 + 57), text, font=value_font, fill="#241F41")
    draw.text((80, 625), f"TN = {matrix[0][0]}   FP = {matrix[0][1]}   FN = {matrix[1][0]}   TP = {matrix[1][1]}", font=label_font, fill="#30265B")
    image.save(path)


def create_report_figures(evaluation: dict) -> dict[str, Path]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    conflict_counts = evaluation["conflicts"]["by_code"]
    severity_counts = evaluation["conflicts"]["by_severity"]
    matrix_path = ASSETS / "confusion-matrix.png"
    draw_confusion_matrix(matrix_path, evaluation["matrix"], evaluation["test_count"])
    metrics_path = ASSETS / "model-metrics.png"
    metric_names = ["Accuracy", "Precision", "Recall", "F1", "ROC-AUC"]
    metric_keys = ["accuracy", "precision", "recall", "f1", "auc"]
    draw_bar_chart(metrics_path, "Held-out Model Metrics", metric_names, [evaluation["metrics"][key] for key in metric_keys], "{:.3f}")
    conflict_path = ASSETS / "conflict-profile.png"
    conflict_labels = [f"C{index}" for index in range(1, 9)]
    draw_bar_chart(conflict_path, "Detected Conflicts by Rule Code", conflict_labels, [conflict_counts.get(label, 0) for label in conflict_labels])
    scale_path = ASSETS / "dataset-scale.png"
    context = evaluation["context"]
    draw_bar_chart(scale_path, "Demonstration Dataset Scale", ["Classes", "Faculty", "Sections", "Rooms"], [len(context.sessions), len(context.faculty), len(context.groups), len(context.rooms)])
    return {"matrix": matrix_path, "metrics": metrics_path, "conflicts": conflict_path, "scale": scale_path}


def add_figure(doc: Document, path: Path, caption: str, width=6.1) -> None:
    if not path.exists():
        return
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.add_run().add_picture(str(path), width=Inches(width))
    caption_paragraph = doc.add_paragraph()
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_paragraph.paragraph_format.space_after = Pt(10)
    set_run(caption_paragraph.add_run(caption), size=9, italic=True, color=MUTED)


def set_cell_fill(cell, color: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shade = OxmlElement("w:shd")
    shade.set(qn("w:fill"), color)
    properties.append(shade)


def set_run(run, size=10, bold=False, color="252438", name="Times New Roman", italic=False) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor.from_string(color)


def add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    value = OxmlElement("w:t")
    value.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instruction, separate, value, end):
        run._r.append(element)


def add_toc_field(paragraph) -> None:
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), 'TOC \\o "1-2" \\h \\z \\u')
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Open in Word and update this table to populate page numbers."
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def add_body(doc: Document, text: str, *, italic=False, align=None):
    paragraph = doc.add_paragraph(style="Normal")
    if align is not None:
        paragraph.alignment = align
    run = paragraph.add_run(text)
    run.italic = italic
    return paragraph


def add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.left_indent = Inches(0.28)
        set_run(paragraph.add_run(item), size=11)


def add_numbered(doc: Document, items: list[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph(style="List Number")
        paragraph.paragraph_format.left_indent = Inches(0.28)
        set_run(paragraph.add_run(item), size=11)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for index, label in enumerate(headers):
        cell = table.rows[0].cells[index]
        set_cell_fill(cell, PURPLE)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_after = Pt(0)
        set_run(paragraph.add_run(label), size=9, bold=True, color="FFFFFF")
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for index, value in enumerate(values):
            cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if row_index % 2 == 1:
                set_cell_fill(cells[index], "F7F6FA")
            paragraph = cells[index].paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            set_run(paragraph.add_run(str(value)), size=9)
    if widths:
        for row in table.rows:
            for index, width in enumerate(widths):
                row.cells[index].width = Inches(width)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return table


def add_callout(doc: Document, label: str, text: str) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    set_cell_fill(cell, LIGHT_PURPLE)
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(2)
    set_run(paragraph.add_run(f"{label}: "), size=10, bold=True, color=PURPLE)
    set_run(paragraph.add_run(text), size=10)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_section(doc: Document, title: str, paragraphs: list[str] | None = None) -> None:
    doc.add_heading(title, level=2)
    for text in paragraphs or []:
        add_body(doc, text)


def set_document_format(doc: Document) -> None:
    for section in doc.sections:
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1.25)
        section.right_margin = Inches(1)
        section.different_first_page_header_footer = True
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(footer.add_run("LPU SCHEDULING CONFLICT RESOLUTION  |  Page "), size=8, color=MUTED)
        add_page_field(footer)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    title = doc.styles["Title"]
    title.font.name = "Times New Roman"
    title.font.size = Pt(25)
    title.font.bold = True
    title.font.color.rgb = RGBColor.from_string(PURPLE)
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    heading1 = doc.styles["Heading 1"]
    heading1.font.name = "Times New Roman"
    heading1.font.size = Pt(16)
    heading1.font.bold = True
    heading1.font.color.rgb = RGBColor.from_string(PURPLE)
    heading1.paragraph_format.space_before = Pt(8)
    heading1.paragraph_format.space_after = Pt(10)
    heading1.paragraph_format.keep_with_next = True
    heading1.paragraph_format.page_break_before = True

    heading2 = doc.styles["Heading 2"]
    heading2.font.name = "Times New Roman"
    heading2.font.size = Pt(13)
    heading2.font.bold = True
    heading2.font.color.rgb = RGBColor.from_string("29263F")
    heading2.paragraph_format.space_before = Pt(9)
    heading2.paragraph_format.space_after = Pt(4)
    heading2.paragraph_format.keep_with_next = True

    for name in ("List Bullet", "List Number"):
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        style.font.size = Pt(11)
        style.paragraph_format.line_spacing = 1.25
        style.paragraph_format.space_after = Pt(3)

    settings = doc.settings._element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)


def build_report() -> Path:
    evaluation = report_evaluation()
    figures = create_report_figures(evaluation)
    context = evaluation["context"]
    conflict_counts = evaluation["conflicts"]["by_code"]
    severity_counts = evaluation["conflicts"]["by_severity"]
    metrics = evaluation["metrics"]
    matrix = evaluation["matrix"]
    doc = Document()
    set_document_format(doc)
    doc.core_properties.title = "Agentic AI for University Scheduling Conflict Detection and Resolution"
    doc.core_properties.subject = "Large-scale timetable conflict detection and alternative schedule recommendation"
    doc.core_properties.author = "[Student Name]"
    doc.core_properties.keywords = "university timetabling, conflict detection, constraint satisfaction, supervised learning"

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(62)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("A PROJECT REPORT"), size=16, bold=True, color=PURPLE)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("ON"), size=12, bold=True)
    p = doc.add_paragraph(style="Title")
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(10)
    p.add_run("AGENTIC AI FOR UNIVERSITY SCHEDULING\nCONFLICT DETECTION AND RESOLUTION")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(32)
    set_run(p.add_run("Large-scale timetable validation and alternative schedule recommendation"), size=13, italic=True, color=MUTED)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("Submitted in partial fulfilment of the requirements for the award of"), size=11)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("[Programme / Degree]"), size=13, bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(18)
    set_run(p.add_run("Submitted by"), size=11, bold=True)
    add_table(doc, ["Student Details", "Project Details"], [
        ["Name: [Your Name]", "Project Guide: [Guide Name]"],
        ["Registration No.: [Registration Number]", "Department: [Department]"],
        ["Roll No.: [Roll Number]", "Academic Year: 2026-2027"],
        ["Section: [Section]", "Institution: Lovely Professional University"],
    ], widths=[3.0, 3.2])
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(18)
    set_run(p.add_run("LOVELY PROFESSIONAL UNIVERSITY\nPHAGWARA, PUNJAB, INDIA\n2026"), size=12, bold=True, color=PURPLE)

    doc.add_heading("DECLARATION", level=1)
    add_body(doc, "I hereby declare that the project report entitled \"Agentic AI for University Scheduling Conflict Detection and Resolution\" is prepared for academic purposes and describes the implementation available in the accompanying project workspace. The report distinguishes implemented functionality from proposed future work and identifies generated demonstration data wherever applicable.")
    add_body(doc, "The large-campus schedule used for the demonstration contains generated faculty, sections, rooms, sessions, and deliberately seeded conflict cases. It is not an official Lovely Professional University timetable or staff roster. Results from the synthetic schedule must not be interpreted as findings about actual institutional operations.")
    add_body(doc, "I acknowledge the use of software documentation and published research cited in the references. Student and guide details on the title page are placeholders and must be completed by the submitting student.")
    add_body(doc, "Place: Phagwara, Punjab\nDate: [Submission Date]\nName: [Your Name]\nSignature: ______________________________")

    doc.add_heading("TABLE OF CONTENTS", level=1)
    add_toc_field(doc.add_paragraph())
    add_body(doc, "If the contents list is not populated automatically, open the document in Microsoft Word, select the table, and choose Update Field / Update entire table.", italic=True)

    doc.add_heading("CHAPTER 1: INTRODUCTION", level=1)
    add_section(doc, "1.1 Background of the Domain", [
        "University timetabling assigns teaching and examination sessions to time slots, rooms, faculty members, and student sections. A valid schedule must coordinate limited physical resources and people while avoiding overlaps and respecting institutional policies. The task becomes harder as enrolments, departments, facilities, and one-off changes grow.",
        "This project treats a timetable as structured data rather than a static spreadsheet. Sessions reference courses, groups, faculty, rooms, and time slots. A deterministic constraint engine checks placements, while a web application presents conflicts and candidate repairs to a scheduler.",
    ])
    add_section(doc, "1.2 Motivation for the Study", [
        "A schedule can become invalid when a room is unavailable, an instructor is double-booked, a section is assigned two simultaneous classes, or a room is too small for enrolment. Manual inspection of a large weekly timetable is error-prone. A useful decision-support tool should explain what is wrong, generate feasible alternatives, compare their trade-offs, and retain human approval over schedule changes.",
    ])
    add_section(doc, "1.3 Problem Statement", [
        "The project implements a system that detects timetable conflicts and generates ranked alternative placements while considering room capacity and features, faculty availability, student-group overlap, exam windows, curriculum limits, and institution-defined preferences. The system must validate every proposed change against the same hard-rule registry used by conflict detection.",
    ])
    add_section(doc, "1.4 Significance and Contribution of the Project", [
        "The contribution is a working, inspectable prototype rather than a claim of deployment at the university. Its main value is the integration of a conflict taxonomy, a shared feasibility validator, a bounded repair search, policy-based ranking, a supervised acceptance estimate, and an audit-aware web workflow.",
    ])
    add_table(doc, ["Contribution", "Implemented evidence"], [
        ["Conflict detection", "Sweep-based resource overlap checks and per-session hard-rule validation."],
        ["Feasible repair", "Candidate domains, hard-rule filtering, and bounded linked-session repair."],
        ["Recommendation", "Five policy criteria blended with a supervised acceptance probability."],
        ["Human control", "Preview, version-checked apply, snapshots, audit history, and rollback."],
        ["Large-scale demonstration", "1,020 sessions, 320 faculty, 98 sections, and 51 rooms in generated data."],
    ])
    add_section(doc, "1.5 Organisation of the Report", [
        "Chapter 1 introduces the problem. Chapter 2 defines objectives, scope, users, assumptions, and the project gap. Chapter 3 documents the implemented data model, constraints, detection, resolution, ranking, and technology. Chapter 4 presents the current demonstration dataset, conflict profile, model metrics, tests, and limitations. Chapter 5 outlines future work. References and implementation appendices follow.",
    ])

    doc.add_heading("CHAPTER 2: SCOPE, OBJECTIVES AND RESEARCH GAP", level=1)
    add_section(doc, "2.1 Scope of the Study", [
        "The prototype supports a single term with recurring weekday sessions and Saturday examination slots. It models lecture, tutorial, laboratory, and exam sessions; rooms with capacities and feature sets; faculty; student sections; course records; faculty leave; and configurable soft-policy weights. A scheduler can inspect conflicts, request repairs, preview impact, apply a feasible option, and review the audit history.",
        "The current demonstration data is synthetic. The project does not connect to a university ERP, authenticate institutional users, ingest a verified staff roster, or claim that its generated schedule reflects real course demand.",
    ])
    add_section(doc, "2.2 Objectives of the Project", [
        "The project objectives are to represent schedule entities in a relational database, detect and explain hard-rule violations, propose feasible repairs, rank alternatives using institutional preferences and a supervised model, and provide a usable dashboard for review and approval.",
    ])
    add_table(doc, ["ID", "Objective", "Status in prototype"], [
        ["O1", "Represent terms, slots, rooms, faculty, sections, courses, and sessions.", "Implemented with SQLite and normalized relational tables."],
        ["O2", "Detect and classify scheduling conflicts.", "Implemented for eight hard-conflict codes."],
        ["O3", "Generate feasible alternatives for a selected conflict.", "Implemented as bounded candidate search and linked repair."],
        ["O4", "Explain and compare alternative placements.", "Implemented with score breakdowns and impact preview."],
        ["O5", "Learn scheduler acceptance patterns.", "Prototype random forest uses policy-derived bootstrap labels and applied repairs."],
        ["O6", "Keep a human in control of schedule changes.", "Preview, explicit apply, version check, audit, and rollback are implemented."],
    ])
    add_section(doc, "2.3 Identification of the Research Gap", [
        "Batch timetabling systems primarily focus on producing a complete schedule. The operational workflow addressed here is incremental: after a change, the scheduler needs to know which constraints failed and what minimally disruptive repairs remain feasible. This project combines deterministic validation with ranked decision support. It does not claim that its search method is globally optimal or that its synthetic acceptance labels capture real institutional preferences.",
    ])
    add_section(doc, "2.4 Stakeholders and User Roles", [
        "The intended primary user is a timetable coordinator who reviews conflicts and approves changes. Faculty and student sections are represented as affected entities. Administrators would manage institutional data and policy weights in a production deployment; authentication and role-based permissions are future work.",
    ])
    add_section(doc, "2.5 Definitions and Conflict Semantics", [
        "A scheduled class is one session record in the weekly timetable, not a unique course. A conflict is one detector output describing a violated rule and its affected session identifiers. A session can participate in more than one conflict; therefore conflict count and conflict-free session count are not complements by simple subtraction unless unique affected sessions are counted.",
        "The current dataset contains 30 detected conflict records: 17 critical, 11 high, and 2 medium. Fourteen were deliberately added as large-campus stress cases (seven faculty clashes and seven capacity violations). These are synthetic test inputs, not naturally observed incidents.",
    ])
    add_section(doc, "2.6 Assumptions and Scope Limitations", [
        "The schedule uses weekly recurring slots and a single teaching week for demonstration. The sample roster, section strengths, rooms, and courses are generated. The current model has no verified real-world labels. The interface displays a Winter 2026 semester badge while the seeded schedule metadata identifies the demonstration term as Monsoon 2026; institutional release should connect this label to the active term record.",
    ])

    doc.add_heading("CHAPTER 3: METHODOLOGY", level=1)
    add_section(doc, "3.1 Research Design and Workflow", [
        "The implementation follows a deterministic feasibility pipeline with an assistive ranking layer. New or existing schedule data is loaded into SQLite and materialized as an in-memory context. The detector emits conflicts. For a selected conflict, the resolver builds candidate placements, filters each candidate through the shared hard-rule registry, scores the surviving alternatives, and returns a ranked shortlist. A scheduler can preview and explicitly apply a selected repair; the workflow records a snapshot and audit event and then re-detects conflicts.",
    ])
    add_callout(doc, "Operational loop", "Load schedule -> detect -> explain -> generate feasible alternatives -> rank -> preview -> human approval -> apply -> audit -> re-detect")
    add_section(doc, "3.2 System Architecture", [
        "The frontend is a static HTML, CSS, and JavaScript single-page dashboard served by FastAPI. The API coordinates the SQLite persistence layer, schedule context, conflict detector, constraint registry, resolution engine, scoring functions, and pure-Python random forest. The database and algorithmic layers are intentionally inspectable for an academic prototype.",
    ])
    add_table(doc, ["Layer", "Technology / responsibility"], [
        ["User interface", "Vanilla HTML, CSS, and JavaScript; responsive dashboard, timetable, conflicts, resources, reports, and alternatives."],
        ["API", "FastAPI endpoints for statistics, schedule, constraints, conflicts, alternatives, policy, model, and audit."],
        ["Persistence", "SQLite tables for terms, time slots, rooms, faculty, sections, courses, sessions, conflicts, alternatives, audit, and metadata."],
        ["Feasibility", "Python constraint registry shared by detection and candidate validation."],
        ["Ranking", "Five-criterion policy score blended 70/30 with the random-forest acceptance estimate."],
    ])
    add_section(doc, "3.3 Dataset Description", [
        "The deterministic sample generator produces the dataset stored in data/sample_university.json. The current live database and generated sample use the same scale. The dataset is explicitly for demonstration and stress testing; generated names and assignments must not be treated as official university information.",
    ])
    add_table(doc, ["Entity", "Count", "Notes"], [
        ["Scheduled sessions", f"{len(context.sessions):,}", "Includes lectures, tutorials, labs, and examinations."],
        ["Faculty", f"{len(context.faculty):,}", "Synthetic demonstration roster; not an official staff list."],
        ["Student sections", f"{len(context.groups):,}", "Generated programme/semester sections with synthetic enrolments."],
        ["Rooms", f"{len(context.rooms):,}", "Lecture, seminar, lab, and examination resources."],
        ["Time slots", f"{len(context.slots):,}", "25 weekday teaching slots and two Saturday exam windows."],
        ["Detected conflicts", str(evaluation["conflicts"]["total"]), f"{severity_counts.get('critical', 0)} critical, {severity_counts.get('high', 0)} high, and {severity_counts.get('medium', 0)} medium."],
    ])
    add_section(doc, "3.4 Data Auditing and Preparation", [
        "The sample generator assigns stable integer identifiers and explicit foreign-key relationships between sessions and courses, faculty, rooms, time slots, and sections. New weekly classes are distributed across 90 additional sections. Room capacity is selected to accommodate section strength for the generated schedule, and faculty assignments are spread across the added roster. Fourteen deliberate stress violations are injected after the mostly feasible schedule is constructed so that conflict detection and severity views can be demonstrated at the larger scale.",
        "The deliberate injections are seven faculty double-bookings and seven room-capacity violations. The other existing demonstration conflicts cover room overlap, group overlap, equipment, availability, curriculum/day-load, and exam-window cases. No claim is made that this synthetic mixture represents a real university incident rate.",
    ])
    add_section(doc, "3.5 Data Model and Feature Definitions", [
        "The SQLite schema separates term, time slot, room, faculty, student_group, course, session, and session_group records. Availability, conflicts, alternatives, audit_log, and meta tables support validation and workflow. Session-to-group enrollment is many-to-many. The 11 model features describe schedule displacement, room/faculty changes, room fill, instructor load, continuity, start time, patch size, affected students, and equipment surplus.",
    ])
    add_section(doc, "3.6 Hard Constraints and Conflict Taxonomy", [
        "Hard constraints are pass/fail conditions for a placement. Conflict detection and repair validation share the same registered functions so a candidate cannot be considered feasible under different semantics from those used to detect the original violation.",
    ])
    add_table(doc, ["Code", "Rule", "Severity"], [
        ["C1 / H1", "Room double-booking for overlapping sessions.", "Critical"],
        ["C2 / H2", "Faculty double-booking for overlapping sessions.", "Critical"],
        ["C3 / H3", "Overlapping sessions for a shared student section.", "Critical"],
        ["C4 / H4", "Section enrolment exceeds room capacity.", "High"],
        ["C5 / H5", "Room lacks required equipment or lab capability.", "High"],
        ["C6 / H6", "Faculty leave or declared availability is violated.", "High"],
        ["C7 / H7", "Daily section load or same-course-per-day limit is exceeded.", "Medium"],
        ["C8 / H8", "Exam is outside an exam slot or a regular class uses an exam slot.", "High"],
    ])
    add_section(doc, "3.7 Detection and Alternative Generation", [
        "Pairwise room, faculty, and section overlaps are found with a sweep over sessions grouped by resource and day. Single-session checks evaluate capacity, equipment, availability, curriculum/day load, and exam windows. This avoids comparing every pair of all sessions indiscriminately.",
        "For a selected conflict, the resolver orders candidate slots, rooms, and instructors according to basic suitability preferences. It validates candidates through the hard-rule registry, bounds the single-move candidate set, and can attempt a linked-group repair for a small related conflict set. The current implementation is a bounded heuristic search, not a proof of globally optimal timetable repair and not a CP-SAT or simulated-annealing solver.",
    ])
    add_section(doc, "3.8 Scoring and Supervised Recommendation", [
        "Feasible alternatives are scored on student disruption, faculty impact, room adequacy, continuity, and rule margin. The configurable policy score contributes 70 percent of the final score; the supervised random-forest acceptance probability contributes 30 percent. The classifier is advisory and does not determine feasibility. A repair must pass hard constraints before ranking and is checked again on preview and apply.",
    ])
    add_table(doc, ["Model item", "Current implementation"], [
        ["Task", "Binary classification: estimate acceptance of an already feasible repair."],
        ["Model", "Pure-Python random forest; 80 trees, maximum depth 7, minimum leaf size 6; seed 2026."],
        ["Training labels", "Policy-derived bootstrap labels with noise, supplemented by applied repairs; not a verified historical LPU decision set."],
        ["Report-time split", f"{evaluation['train_count']} training rows and {evaluation['test_count']} held-out rows; freshly fit in memory for this report."],
        ["Ranking blend", "0.70 x policy score + 0.30 x predicted acceptance probability."],
    ])
    add_section(doc, "3.9 Data Governance and Ethics", [
        "The demonstration contains synthetic names and schedule records. It must not be used to make real decisions about named staff or students. A production deployment would require verified data provenance, access control, privacy review, retention rules, stakeholder approval, and monitoring for uneven impacts across departments and groups. The human approval step is retained because a high score is not a substitute for institutional judgement.",
    ])
    add_section(doc, "3.10 Implementation and Technology Stack", [
        "The backend uses Python, FastAPI, and SQLite. The user interface uses static HTML, CSS, and JavaScript without a frontend build process. Tests use pytest and FastAPI's test client. The deterministic data generator recreates the large sample and its bounded stress cases. The app can be started with the commands in Appendix B.",
    ])

    doc.add_heading("CHAPTER 4: RESULTS AND DISCUSSION", level=1)
    add_section(doc, "4.1 Experimental Setup", [
        "Validation was performed against the expanded sample dataset and the live demonstration database. The sample generator was run and the resulting JSON was seeded into a temporary SQLite database to verify entity counts and conflict totals. The API, engine, and model test modules were run with pytest. Browser checks exercised the dashboard, all-groups timetable, conflict list, alternative generation, resource searches, and mobile layout.",
    ])
    add_section(doc, "4.2 Large-Campus Dataset Profile", [
        "The generated weekly schedule contains enough sessions and resources to exercise large-list behavior in the interface. All-groups timetable mode is the default overview; section filtering remains available. Resources tables use search and pagination so the complete roster can be inspected without rendering hundreds of rows at once.",
    ])
    add_table(doc, ["Measure", "Observed result"], [
        ["Sessions", f"{len(context.sessions):,}"], ["Faculty", f"{len(context.faculty):,}"], ["Student sections", f"{len(context.groups):,}"],
        ["Rooms", f"{len(context.rooms):,}"], ["Timetable slots", f"{len(context.slots):,}"], ["Room-slot utilization", f"{evaluation['room_utilization']}%"],
    ])
    add_figure(doc, figures["scale"], "Figure 4.1. Relative scale of the generated demonstration dataset.")
    add_section(doc, "4.3 Conflict Detection Results", [
        f"The detector reports {evaluation['conflicts']['total']} conflict records: {severity_counts.get('critical', 0)} critical, {severity_counts.get('high', 0)} high, and {severity_counts.get('medium', 0)} medium. Fourteen conflicts are deliberate large-campus stress cases, added to exercise faculty-clash and room-capacity paths at scale.",
    ])
    add_table(doc, ["Code", "Count", "Severity"], [
        ["C1 - Room overlap", str(conflict_counts.get("C1", 0)), "Critical"], ["C2 - Faculty overlap", str(conflict_counts.get("C2", 0)), "Critical"],
        ["C3 - Section overlap", str(conflict_counts.get("C3", 0)), "Critical"], ["C4 - Capacity", str(conflict_counts.get("C4", 0)), "High"],
        ["C5 - Equipment", str(conflict_counts.get("C5", 0)), "High"], ["C6 - Availability", str(conflict_counts.get("C6", 0)), "High"],
        ["C7 - Curriculum / load", str(conflict_counts.get("C7", 0)), "Medium"], ["C8 - Exam window", str(conflict_counts.get("C8", 0)), "High"],
        ["Total", str(evaluation["conflicts"]["total"]), f"{severity_counts.get('critical', 0)} critical; {severity_counts.get('high', 0)} high; {severity_counts.get('medium', 0)} medium"],
    ])
    add_callout(doc, "Interpretation", f"{evaluation['conflicts']['total']} is the number of detector records, not necessarily the number of distinct classes. A class may participate in more than one conflict. The dashboard calculates conflict-free classes from unique affected session identifiers; the current value is {evaluation['conflict_free_sessions']} of {len(context.sessions):,}.")
    add_figure(doc, figures["conflicts"], "Figure 4.2. Detected conflict records by hard-rule code.")
    add_section(doc, "4.4 Alternative Schedule Workflow", [
        "The conflict-resolution interface accepts a selected conflict and requests a bounded set of ranked alternatives from the API. Each card presents the repair strategy, policy score, criterion breakdown, model estimate where available, and preview/apply actions. The preview endpoint revalidates the proposed patch; application is version-checked and audited.",
        "The number of alternatives is bounded and depends on the conflict and candidate domains. It is not a guarantee that every conflict has a repair or that the top-ranked result is globally optimal.",
    ])
    add_section(doc, "4.5 Report-Time Model Evaluation", [
        f"For this report, a fresh random forest was fit in memory using the same deterministic training procedure, current schedule context, seed 2026, and policy-derived bootstrap labels. The split contains {evaluation['train_count']} training rows and {evaluation['test_count']} held-out rows. This run was not persisted to the live application. The target labels are synthetic proxies, not verified historical institutional decisions; the metrics therefore measure agreement with that proxy process only.",
    ])
    add_table(doc, ["Metric", "Report-time evaluation"], [
        ["Accuracy", f"{metrics['accuracy']:.3f}"], ["Precision", f"{metrics['precision']:.3f}"], ["Recall", f"{metrics['recall']:.3f}"],
        ["F1 score", f"{metrics['f1']:.3f}"], ["ROC-AUC", f"{metrics['auc']:.3f}"], ["Log-loss", f"{metrics['log_loss']:.3f}"],
    ])
    tn, fp = matrix[0]
    fn, tp = matrix[1]
    add_table(doc, ["Actual / Predicted", "Rejected (0)", "Accepted (1)"], [
        ["Rejected (0)", str(tn), str(fp)],
        ["Accepted (1)", str(fn), str(tp)],
    ])
    add_figure(doc, figures["matrix"], "Figure 4.3. Confusion matrix on the report-time 141-example held-out split.")
    add_figure(doc, figures["metrics"], "Figure 4.4. Classification metrics on the same held-out split.")
    add_section(doc, "4.6 Application Pages and Scale Checks", [
        "The dashboard provides large-count KPIs and an all-groups timetable overview. The dedicated timetable page supports week and section filters. Conflict Detection presents severity filters and repair details. Optimization shows stored model metrics and feature importance. Alternative Schedules presents ranked candidates. Resources supports searchable, paginated room and faculty tables. Reports summarizes sessions, sections, rooms, and conflict severity.",
    ])
    add_table(doc, ["Page / workflow", "Scale-aware behavior verified"], [
        ["Dashboard", f"Displays {len(context.sessions):,} sessions, {len(context.faculty):,} faculty, {evaluation['conflicts']['total']} conflicts, and {severity_counts.get('critical', 0)} critical conflicts."],
        ["Timetable", "All-groups view fills busy time slots and summarizes overflow within cells; individual section filters remain available."],
        ["Resources", "Faculty and room tables are searchable and paginated."],
        ["Conflict repair", "Generates feasible alternatives for selected conflicts at the expanded schedule size."],
        ["Responsive layout", "Checked at desktop and 390-pixel viewport width without page-level horizontal overflow."],
    ])
    screenshot_figures = [
        ("dashboard-view.png", "Figure 4.5. Dashboard overview with large-campus KPIs and all-groups timetable."),
        ("timetable-view.png", "Figure 4.6. Weekly timetable with week and section controls."),
        ("conflicts-view.png", "Figure 4.7. Conflict Detection page with severity filters."),
        ("alternatives-view.png", "Figure 4.8. Ranked alternative schedule recommendations."),
        ("resources-view.png", "Figure 4.9. Searchable and paginated campus resource tables."),
    ]
    available_screenshots = [(ASSETS / file, caption) for file, caption in screenshot_figures if (ASSETS / file).exists()]
    if available_screenshots:
        doc.add_page_break()
        for index, (image_path, caption) in enumerate(available_screenshots):
            if index and index % 2 == 0:
                doc.add_page_break()
            add_figure(doc, image_path, caption, width=5.9)
    add_section(doc, "4.7 Software Test Results", [
        "The complete backend suite contains 39 tests across the API/workflow, scheduling engine, and supervised model. The latest run completed with 39 passed. One Starlette deprecation warning was emitted by the test-client dependency; it did not fail the suite.",
    ])
    add_section(doc, "4.8 Discussion of Findings", [
        "The implementation demonstrates that a 1,020-session sample can be loaded, scanned, filtered, and presented in the browser while preserving an explainable rule registry. The 14 seeded stress conflicts intentionally raise the reported total from the earlier 16-conflict dataset to 30. The counts are a test configuration, not an estimate of the real institution's conflict rate. Resource search/pagination and the all-groups timetable are important for keeping the interface usable at this scale.",
    ])
    add_section(doc, "4.9 Threats to Validity and Limitations", [
        "The dataset is generated and does not represent actual LPU staffing or course assignments. Conflict cases are deliberately injected. Model labels are bootstrapped from the scoring policy, so the hold-out metrics measure agreement with a proxy label process rather than actual scheduler acceptance. The resolver is bounded and heuristic; a feasible alternative may not be found even if one exists. The app is a local prototype without production authentication, ERP integration, concurrency controls for multiple users, or a formal security assessment. The UI semester badge and the schedule term metadata should be unified before deployment.",
    ])

    doc.add_heading("CHAPTER 5: FUTURE WORK", level=1)
    add_section(doc, "5.1 Verification of Data Provenance", [
        "Replace generated records with a documented, authorized institutional dataset. Validate identities, enrolment counts, faculty availability, room capacities, course requirements, exam rules, and term dates with the relevant university owners before evaluating operational performance.",
    ])
    add_section(doc, "5.2 Institutional Data Integration and Validation", [
        "Develop authenticated import pipelines for the timetable or ERP source, add schema/version checks, and compare detected issues against coordinator-reviewed ground truth. Report precision and recall for real conflicts separately from synthetic regression tests.",
    ])
    add_section(doc, "5.3 Solver and Scale Improvements", [
        "Profile conflict resolution on larger real schedules, add incremental indexing, and evaluate a constraint-programming backend for linked repairs. Keep the existing shared validator as the final feasibility authority. Add cancellation, time budgets, and progress feedback to long-running solve requests.",
    ])
    add_section(doc, "5.4 Model, Explainability and Fairness", [
        "Collect opt-in decisions from schedulers, separate training and test data by term or time, recalibrate probabilities, and compare learned ranking against policy-only ranking. Audit how recommendations affect departments, faculty workload, accessibility needs, and student sections. Do not treat generated bootstrap metrics as production evidence.",
    ])
    add_section(doc, "5.5 Security, Privacy and Lifecycle", [
        "Add authentication and role-based authorization, secure audit access, backup and recovery procedures, data-retention controls, monitoring, and an explicit model/version lifecycle. Apply privacy review to any personal staff or student records before integration.",
    ])
    add_section(doc, "5.6 Deployment and Roadmap", [
        "A practical sequence is: (1) confirm real data ownership and schema; (2) deploy a read-only conflict dashboard; (3) validate constraints with coordinators; (4) pilot preview-only repairs; (5) enable version-checked approval and rollback; and (6) evaluate the model only after sufficient labelled decisions are collected.",
    ])
    add_section(doc, "5.7 Summary", [
        "This project implements a web-based scheduling conflict and repair prototype with 1,020 generated sessions, 320 generated faculty records, 98 generated sections, and 51 rooms. Its deterministic rules detect and explain conflicts; its bounded resolver proposes feasible repairs; a policy/model blend ranks those repairs; and human approval controls application. The next step is validation with authorized real institutional data, not treating the demonstration profile as a real university operational report.",
    ])

    doc.add_heading("REFERENCES", level=1)
    references = [
        "Schaerf, A. (1999). A survey of automated timetabling. Artificial Intelligence Review, 13, 87-127.",
        "Burke, E. K., and Petrovic, S. (2002). Recent research directions in automated timetabling. European Journal of Operational Research, 140(2), 266-280.",
        "Carter, M. W., and Laporte, G. (1998). Recent developments in practical course timetabling. In E. K. Burke and M. W. Carter (Eds.), Practice and Theory of Automated Timetabling II, Lecture Notes in Computer Science 1408, 3-21.",
        "Breiman, L. (2001). Random forests. Machine Learning, 45, 5-32.",
        "FastAPI. (2026). FastAPI documentation. https://fastapi.tiangolo.com/ (accessed November 15, 2026).",
        "Python Software Foundation. (2026). Python 3 documentation. https://docs.python.org/3/ (accessed November 15, 2026).",
        "SQLite Consortium. (2026). SQLite documentation. https://www.sqlite.org/docs.html (accessed November 15, 2026).",
    ]
    add_numbered(doc, references)

    doc.add_heading("APPENDIX A: SYSTEM API", level=1)
    add_table(doc, ["Endpoint", "Purpose"], [
        ["GET /api/stats", "Schedule totals, version, and conflict summary."],
        ["GET /api/schedule", "Term, sessions, rooms, and time slots."],
        ["GET /api/conflicts", "Open conflicts with severity and affected sessions."],
        ["POST /api/conflicts/{id}/resolve", "Generate and rank repair candidates."],
        ["POST /api/alternatives/{id}/preview", "Preview and revalidate a candidate patch."],
        ["POST /api/alternatives/{id}/apply", "Apply an approved, version-checked repair."],
        ["GET /api/model and POST /api/model/train", "Read model report and request supervised retraining."],
        ["GET /api/audit and POST /api/rollback/{id}", "Read change history and restore a saved schedule snapshot."],
    ])

    doc.add_heading("APPENDIX B: REPRODUCIBILITY", level=1)
    add_body(doc, "From the project root, install the dependencies, regenerate the deterministic demonstration data, and start the API:")
    for command in ("pip install -r requirements.txt", "python data/generate_sample.py", "python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.3)
        p.paragraph_format.space_after = Pt(3)
        set_run(p.add_run(command), size=10, name="Consolas", color=PURPLE)
    add_body(doc, "Run the backend verification suite with: python -m pytest backend/tests -q. The report-preparation run completed 39 tests successfully. The generated JSON and seeded conflict cases are demonstration fixtures and should be replaced or approved before any operational use.")

    doc.add_heading("APPENDIX C: AUTHOR AND DATA FIELDS", level=1)
    add_table(doc, ["Field", "Complete before submission"], [
        ["Student name / registration / roll / section", "[Enter the submitting student's details]"],
        ["Project guide", "[Enter the assigned guide's name and designation]"],
        ["Department and programme", "[Enter the official department and degree]"],
        ["Submission date", "[Enter the final submission date]"],
    ])

    doc.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build_report())
