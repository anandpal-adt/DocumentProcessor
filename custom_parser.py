import docx
from langchain_community.llms import Predibase
from pdfminer.high_level import extract_text
import re

def extract_text_from_pdf(file_path):
    return extract_text(file_path)

def extract_text_from_docx(file_path):
    doc = docx.Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def parse_response(response):
    # Extract name using regex
    name_match = re.search(r'\*\*Name:\*\*\s*(.*)', response)
    name = name_match.group(1).strip() if name_match else "Unknown"

    # Extract email using regex
    email_match = re.search(r'\*\*Email:\*\*\s*(.*)', response)
    email = email_match.group(1).strip() if email_match else "Unknown"

    # Extract phone using regex
    phone_match = re.search(r'\*\*Phone:\*\*\s*(.*)', response)
    phone = phone_match.group(1).strip() if phone_match else "Unknown"

    # Extract skills using regex and join them with commas
    skills_match = re.search(r'\*\*Skills:\*\*\n*(.*)', response, re.DOTALL)
    skills_text = skills_match.group(1).strip() if skills_match else "Unknown"

    # Split skills by line breaks or commas, and clean up whitespace
    skills = re.split(r'[\n,]', skills_text)
    skills = [skill.strip() for skill in skills if skill.strip()]
    skills = ', '.join(skills)

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "skills": skills,
    }


def parse_resume_text(text):
    # In a real-world scenario, you would use NLP or regex here
    model = Predibase(
        model="llama-3-8b-instruct",
        predibase_api_key="pb_y_JOJ2toWf-hewNLR3yY_Q",
        predibase_sdk_version=None,
    )
#     prompt=("""<|begin_of_text|><|start_header_id|>system<|end_header_id|>
# You are a helpful, detailed, and polite artificial intelligence assistant. Your answers are clear and suitable for a professional environment.
# If context is provided, answer using only the provided contextual information.<|eot_id|><|start_header_id|>user<|end_header_id|>
# This is the resume. Please get the name, contact details, skills and organization from this resume."""+text+"""
# <|eot_id|><|start_header_id|>assistant<|end_header_id|>""")
    prompt = (
            "system\n"
            "You are a helpful, detailed, and polite artificial intelligence assistant. "
            "Your answers are clear and suitable for a professional environment.\n"
            "If context is provided, answer using only the provided contextual information.\n"
            "user\n"
            "This is the resume. Please get name, email, phone and skills from this resume:\n"
            f"{text}\n"
            "assistant"
        )
        
    
    response = model.invoke(prompt)
    # print(response)    
    return response
