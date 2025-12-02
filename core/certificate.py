from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from datetime import datetime
import os

def generate_certificate(user, course):
    """
    Generate a professional PDF certificate for course completion
    """
    buffer = BytesIO()
    
    # Register fonts that support UTF-8 (Arial)
    # Windows font path
    font_path = r"C:\Windows\Fonts\arial.ttf"
    font_bold_path = r"C:\Windows\Fonts\arialbd.ttf"
    
    try:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('Arial', font_path))
        if os.path.exists(font_bold_path):
            pdfmetrics.registerFont(TTFont('Arial-Bold', font_bold_path))
        
        # Set fonts to Arial if available, otherwise fallback (though fallback might still show squares)
        title_font = 'Arial-Bold' if os.path.exists(font_bold_path) else 'Helvetica-Bold'
        text_font = 'Arial' if os.path.exists(font_path) else 'Helvetica'
        
    except Exception:
        # Fallback if something goes wrong with font loading
        title_font = 'Helvetica-Bold'
        text_font = 'Helvetica'

    # Create the PDF object using A4 size (landscape)
    width, height = A4[1], A4[0]  # Landscape orientation
    c = canvas.Canvas(buffer, pagesize=(width, height))
    
    # Draw border
    c.setStrokeColor(colors.HexColor('#4F46E5'))  # Indigo
    c.setLineWidth(3)
    c.rect(0.5*inch, 0.5*inch, width - inch, height - inch)
    
    # Inner decorative border
    c.setStrokeColor(colors.HexColor('#818CF8'))  # Light indigo
    c.setLineWidth(1)
    c.rect(0.6*inch, 0.6*inch, width - 1.2*inch, height - 1.2*inch)
    
    # Title
    c.setFont(title_font, 48)
    c.setFillColor(colors.HexColor('#4F46E5'))
    c.drawCentredString(width/2, height - 1.5*inch, "Certificate of Completion")
    
    # Subtitle
    c.setFont(text_font, 16)
    c.setFillColor(colors.HexColor('#6B7280'))
    c.drawCentredString(width/2, height - 2*inch, "This is to certify that")
    
    # User name
    c.setFont(title_font, 36)
    c.setFillColor(colors.HexColor('#111827'))
    user_name = f"{user.first_name} {user.last_name}" if user.first_name else user.username
    c.drawCentredString(width/2, height - 2.8*inch, user_name)
    
    # Has successfully completed
    c.setFont(text_font, 16)
    c.setFillColor(colors.HexColor('#6B7280'))
    c.drawCentredString(width/2, height - 3.3*inch, "has successfully completed the course")
    
    # Course title
    c.setFont(title_font, 28)
    c.setFillColor(colors.HexColor('#4F46E5'))
    c.drawCentredString(width/2, height - 4.1*inch, course.title)
    
    # Date
    c.setFont(text_font, 14)
    c.setFillColor(colors.HexColor('#6B7280'))
    completion_date = datetime.now().strftime("%B %d, %Y")
    c.drawCentredString(width/2, height - 4.8*inch, f"Completed on {completion_date}")
    
    c.setFont(title_font, 25)  # Changed from Helvetica-Oblique to regular Arial as Arial-Oblique might not be standard
    c.setFillColor(colors.HexColor('#4F46E5'))
    c.drawCentredString(width/2, height - 5.7*inch, "StuDy Education Platform")

    # Signature line
    c.setStrokeColor(colors.HexColor('#D1D5DB'))
    c.setLineWidth(1)
    c.line(width/2 - 2*inch, height - 5.8*inch, width/2 + 2*inch, height - 5.8*inch)
    
    # Signature label
    
    # Footer
    c.setFont(text_font, 10)
    c.setFillColor(colors.HexColor('#D1D5DB'))
    c.drawCentredString(width/2, 0.7*inch, f"Certificate ID: {course.id}-{user.id}-{datetime.now().strftime('%Y%m%d')}")
    
    # Add decorative elements (corner ornaments)
    c.setFillColor(colors.HexColor('#818CF8'))
    # Top left corner
    c.circle(1*inch, height - 1*inch, 0.1*inch, fill=1)
    # Top right corner
    c.circle(width - 1*inch, height - 1*inch, 0.1*inch, fill=1)
    # Bottom left corner
    c.circle(1*inch, 1*inch, 0.1*inch, fill=1)
    # Bottom right corner
    c.circle(width - 1*inch, 1*inch, 0.1*inch, fill=1)
    
    # Save the PDF
    c.showPage()
    c.save()
    
    # Get the value of the BytesIO buffer
    pdf = buffer.getvalue()
    buffer.close()
    
    return pdf
