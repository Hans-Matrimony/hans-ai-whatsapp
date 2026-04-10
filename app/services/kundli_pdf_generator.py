"""
Kundli PDF Generator
Generate professional Kundli PDF reports using ReportLab
"""

import os
import logging
from io import BytesIO
from typing import Dict, Any, List
from base64 import b64decode

# ReportLab imports
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


logger = logging.getLogger(__name__)


class KundliPDFGenerator:
    """Generate professional Kundli PDF reports"""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        self._setup_fonts()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles for PDF"""

        # Title style
        self.styles.add(ParagraphStyle(
            name='TitleStyle',
            fontSize=28,
            textColor=colors.whitesmoke,
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName='Helvetica-Bold'
        ))

        # Section header
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            fontSize=18,
            textColor=colors.gold,
            spaceAfter=12,
            spaceBefore=20,
            fontName='Helvetica-Bold'
        ))

        # Subsection header
        self.styles.add(ParagraphStyle(
            name='SubsectionHeader',
            fontSize=14,
            textColor=colors.gold,
            spaceAfter=10,
            spaceBefore=15,
            fontName='Helvetica-Bold'
        ))

        # Update existing BodyText style instead of adding it again
        if 'BodyText' in self.styles:
            self.styles['BodyText'].fontSize = 11
            self.styles['BodyText'].textColor = colors.whitesmoke
            self.styles['BodyText'].alignment = TA_LEFT
            self.styles['BodyText'].spaceAfter = 8
            self.styles['BodyText'].fontName = 'Helvetica'
            self.styles['BodyText'].leading = 14

        # Bold text
        self.styles.add(ParagraphStyle(
            name='BoldText',
            fontSize=11,
            textColor=colors.whitesmoke,
            alignment=TA_LEFT,
            spaceAfter=8,
            fontName='Helvetica-Bold'
        ))

    def _setup_fonts(self):
        """Setup custom fonts if available"""
        try:
            font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts", "NotoSansDevanagari-Regular.ttf")
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('Devanagari', font_path))
                logger.info("[PDF] Registered Devanagari font.")
            else:
                logger.warning(f"[PDF] Font not found at {font_path}")
        except Exception as e:
            logger.warning(f"Could not register custom fonts: {e}")

    def _draw_background(self, canvas, doc):
        """Draw custom background and border for each page"""
        canvas.saveState()
        
        # Draw background color (deep maroon red)
        bg_color = colors.HexColor('#8b0000')
        canvas.setFillColor(bg_color)
        canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
        
        # Draw Om bordered pattern
        try:
            canvas.setFont('Devanagari', 14)
            has_font = True
        except KeyError:
            canvas.setFont('Helvetica', 14)
            has_font = False
            
        canvas.setFillColor(colors.gold)
        om_char = "\u0950" if has_font else "*"
        
        width = doc.pagesize[0]
        height = doc.pagesize[1]
        margin = 35
        
        step = 25
        # Top and bottom borders
        for x in range(margin + 5, int(width - margin) - 10, step):
            canvas.drawString(x, height - margin + 8, om_char)
            canvas.drawString(x, margin - 18, om_char)
            
        # Left and right borders
        for y in range(margin - 10, int(height - margin) + 15, step):
            canvas.drawString(margin - 20, y, om_char)
            canvas.drawString(width - margin + 8, y, om_char)
            
        canvas.restoreState()

    def generate_pdf(
        self,
        user_data: Dict[str, Any],
        kundli_data: Dict[str, Any],
        charts: Dict[str, str],
        openclaw_url: str = None,
        openclaw_token: str = None
    ) -> bytes:
        """
        Generate complete Kundli PDF

        Args:
            user_data: User profile (name, gender, birth details)
            kundli_data: Calculated kundli data
            charts: Dict containing birth_chart and navamsa_chart base64 images
            openclaw_url: OpenClaw API URL (for AI predictions)
            openclaw_token: OpenClaw API token

        Returns:
            PDF as bytes
        """
        try:
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=0.75*inch,
                leftMargin=0.75*inch,
                topMargin=0.75*inch,
                bottomMargin=0.75*inch
            )

            # Build PDF content
            content = []

            # 1. Title Page
            content.extend(self._create_title_page(user_data, kundli_data))

            # 2. Charts Page
            content.extend(self._create_charts_page(charts))

            # Page break
            content.append(PageBreak())

            # 3. Planetary Details Table
            content.extend(self._create_planetary_table(kundli_data))

            # Page break
            content.append(PageBreak())

            # 4. Life Predictions (using AI if available)
            predictions = self._generate_predictions(kundli_data, openclaw_url, openclaw_token)
            content.extend(self._create_predictions_section(predictions))

            # Page break
            content.append(PageBreak())

            # 5. Remedies
            remedies = self._generate_remedies(kundli_data)
            content.extend(self._create_remedies_section(remedies))

            # Build PDF
            doc.build(
                content,
                onFirstPage=self._draw_background,
                onLaterPages=self._draw_background
            )

            # Get PDF bytes
            pdf_bytes = buffer.getvalue()
            buffer.close()

            logger.info(f"[PDF] Generated PDF: {len(pdf_bytes)} bytes")

            return pdf_bytes

        except Exception as e:
            logger.error(f"[PDF] Generation failed: {e}", exc_info=True)
            raise

    def _create_title_page(self, user_data: Dict, kundli_data: Dict) -> List:
        """Create title page with user details"""
        content = []

        # Title
        content.append(Paragraph("Janam Kundli Report", self.styles['TitleStyle']))
        content.append(Spacer(1, 0.3*inch))

        # Subtitle
        content.append(Paragraph(
            "Vedic Birth Chart Analysis",
            ParagraphStyle(
                'Subtitle',
                fontSize=14,
                textColor=colors.gold,
                alignment=TA_CENTER,
                spaceAfter=30
            )
        ))

        # User details table
        details = [
            ["Name", user_data.get("name", "User")],
            ["Date of Birth", self._format_date(user_data.get("dateOfBirth", "N/A"))],
            ["Time of Birth", user_data.get("timeOfBirth", "N/A")],
            ["Place of Birth", user_data.get("birthPlace", "N/A")],
        ]

        details_table = Table(details, colWidths=[2*inch, 4*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#600000')),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.gold),
            ('BACKGROUND', (1, 0), (-1, -1), colors.HexColor('#a00000')),
            ('TEXTCOLOR', (1, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.gold)
        ]))

        content.append(details_table)
        content.append(Spacer(1, 0.5*inch))

        # Key kundli details
        lagna = kundli_data.get("lagna", "Unknown")
        moon_sign = kundli_data.get("moon_sign", "Unknown")
        nakshatra = kundli_data.get("nakshatra", "Unknown")

        key_points = f"""
        <b>Lagna (Ascendant):</b> {lagna}<br/>
        <b>Moon Sign (Rashi):</b> {moon_sign}<br/>
        <b>Birth Nakshatra:</b> {nakshatra}<br/>
        """

        content.append(Paragraph(key_points, self.styles['BodyText']))
        content.append(Spacer(1, 0.5*inch))

        # Disclaimer
        disclaimer = """
        <i>This report is based on Vedic astrology principles.
        The predictions and remedies provided are for guidance purposes.
        For major life decisions, please consult multiple astrologers.</i>
        """

        content.append(Paragraph(disclaimer, ParagraphStyle(
            'Disclaimer',
            fontSize=9,
            textColor=colors.whitesmoke,
            alignment=TA_CENTER
        )))

        return content

    def _create_charts_page(self, charts: Dict) -> List:
        """Create page with birth chart (Lagna Kundli only)"""
        content = []

        content.append(Paragraph("Birth Chart (Lagna Kundli)", self.styles['SectionHeader']))

        # Birth chart
        if 'birth_chart' in charts:
            try:
                birth_chart_img = self._base64_to_image(charts['birth_chart'], width=5.0)
                # Center the chart
                content.append(Spacer(1, 0.2*inch))
                content.append(birth_chart_img)
                content.append(Spacer(1, 0.2*inch))
            except Exception as e:
                logger.error(f"Failed to create birth chart image: {e}")
                content.append(Paragraph("Chart image not available", self.styles['BodyText']))
        else:
            content.append(Paragraph("Chart not available", self.styles['BodyText']))

        return content

    def _base64_to_image(self, base64_data: str, width: float = 3.0) -> Image:
        """Convert base64 image data to ReportLab Image"""
        try:
            # Remove data URL prefix if present
            if ',' in base64_data:
                base64_data = base64_data.split(',')[1]

            image_data = b64decode(base64_data)
            img = Image(BytesIO(image_data))

            # Set size
            img.drawWidth = width * inch
            img.drawHeight = width * inch

            return img

        except Exception as e:
            logger.error(f"Failed to convert base64 to image: {e}")
            raise

    def _create_planetary_table(self, kundli_data: Dict) -> List:
        """Create detailed planetary positions table"""
        content = []

        content.append(Paragraph("Planetary Positions", self.styles['SectionHeader']))

        planets = kundli_data.get("planet_positions", {})

        # Table header
        table_data = [["Planet", "Sign", "House", "Degree", "Nakshatra"]]

        # Planet names in English and Hindi
        planet_names = {
            "sun": "Surya (Sun)",
            "moon": "Chandra (Moon)",
            "mars": "Mangal (Mars)",
            "mercury": "Budh (Mercury)",
            "jupiter": "Guru (Jupiter)",
            "venus": "Shukra (Venus)",
            "saturn": "Shani (Saturn)",
            "rahu": "Rahu",
            "ketu": "Ketu"
        }

        # Add planets (traditional 9 planets)
        for planet_key, planet_name in planet_names.items():
            if planet_key in planets:
                planet_data = planets[planet_key]
                row = [
                    planet_name,
                    self._format_sign(planet_data.get("sign", "N/A")),
                    str(planet_data.get("house", "N/A")),
                    self._format_degree(planet_data.get("degree", "0")),
                    planet_data.get("nakshatra", "N/A")
                ]
                table_data.append(row)

        # Create table
        table = Table(table_data, colWidths=[1.2*inch, 1.2*inch, 0.8*inch, 1.2*inch, 1.6*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.gold),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.darkred),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.gold),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#a00000'), colors.HexColor('#8b0000')]),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.whitesmoke)
        ]))

        content.append(table)
        content.append(Spacer(1, 0.3*inch))

        return content

    def _generate_predictions(self, kundli_data: Dict, openclaw_url: str = None, openclaw_token: str = None) -> Dict:
        """Generate life predictions using OpenClaw AI or fallback to static"""
        from app.services.prediction_engine import PredictionEngine
        import asyncio

        engine = PredictionEngine()

        # Try AI predictions first
        if openclaw_url:
            try:
                # Run async prediction in sync context
                loop = asyncio.get_event_loop()
                if loop and loop.is_running():
                    # If there's a running loop, create task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            engine.generate_all_predictions(kundli_data, openclaw_url, openclaw_token)
                        )
                        predictions = future.result(timeout=30)
                else:
                    # No running loop, run directly
                    predictions = asyncio.run(engine.generate_all_predictions(kundli_data, openclaw_url, openclaw_token))

                if predictions and all(predictions.values()):
                    logger.info("[PDF] Using AI-generated predictions")
                    return predictions
            except Exception as e:
                logger.warning(f"[PDF] AI predictions failed: {e}, using static predictions")

        # Fallback to static predictions
        logger.info("[PDF] Using static rule-based predictions")
        return engine._generate_static_predictions(kundli_data)

    def _create_predictions_section(self, predictions: Dict) -> List:
        """Create predictions section with formatted text"""
        content = []

        content.append(Paragraph("Life Predictions", self.styles['SectionHeader']))

        # Career predictions
        if "career" in predictions:
            content.append(Paragraph("<b>Career & Profession:</b>", self.styles['SubsectionHeader']))
            content.append(Paragraph(predictions["career"], self.styles['BodyText']))
            content.append(Spacer(1, 0.2*inch))

        # Marriage predictions
        if "marriage" in predictions:
            content.append(Paragraph("<b>Marriage & Love:</b>", self.styles['SubsectionHeader']))
            content.append(Paragraph(predictions["marriage"], self.styles['BodyText']))
            content.append(Spacer(1, 0.2*inch))

        # Health predictions
        if "health" in predictions:
            content.append(Paragraph("<b>Health & Wellness:</b>", self.styles['SubsectionHeader']))
            content.append(Paragraph(predictions["health"], self.styles['BodyText']))
            content.append(Spacer(1, 0.2*inch))

        # Wealth predictions
        if "wealth" in predictions:
            content.append(Paragraph("<b>Wealth & Finance:</b>", self.styles['SubsectionHeader']))
            content.append(Paragraph(predictions["wealth"], self.styles['BodyText']))

        return content

    def _generate_remedies(self, kundli_data: Dict) -> Dict:
        """Generate astrological remedies"""
        from app.services.prediction_engine import PredictionEngine

        engine = PredictionEngine()
        return engine.generate_remedies(kundli_data)

    def _create_remedies_section(self, remedies: Dict) -> List:
        """Create remedies section"""
        content = []

        content.append(Paragraph("Astrological Remedies (Upay)", self.styles['SectionHeader']))

        # Gemstones
        if remedies.get("gemstones"):
            content.append(Paragraph("<b>Recommended Gemstones:</b>", self.styles['SubsectionHeader']))
            content.append(Paragraph(remedies["gemstones"], self.styles['BodyText']))
            content.append(Spacer(1, 0.2*inch))

        # Mantras
        if remedies.get("mantras"):
            content.append(Paragraph("<b>Mantras to Chant:</b>", self.styles['SubsectionHeader']))
            content.append(Paragraph(remedies["mantras"], self.styles['BodyText']))
            content.append(Spacer(1, 0.2*inch))

        # General remedies
        if remedies.get("general"):
            content.append(Paragraph("<b>General Remedies:</b>", self.styles['SubsectionHeader']))

            # Use plain Unicode bullet points (no HTML formatting)
            general_lines = remedies["general"].split("•")
            for line in general_lines:
                line = line.strip()
                if line:
                    content.append(Paragraph(f"• {line}", self.styles['BodyText']))

        return content

    def _format_date(self, date_str: str) -> str:
        """Format date string for display"""
        try:
            from datetime import datetime

            # Try different formats
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime("%d %B %Y")  # 15 January 1990
                except ValueError:
                    continue

            return date_str

        except Exception:
            return date_str

    def _format_sign(self, sign: str) -> str:
        """Format zodiac sign name"""
        return sign.title() if sign else "Unknown"

    def _format_degree(self, degree: Any) -> str:
        """Format planetary degree"""
        if isinstance(degree, (int, float)):
            # Convert decimal degrees to DMS format
            degrees = int(degree)
            minutes = int((degree - degrees) * 60)
            return f"{degrees}°{minutes:02d}'"
        else:
            return str(degree)
