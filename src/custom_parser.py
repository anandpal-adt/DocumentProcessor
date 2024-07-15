import re
import docx
import yaml
from pdfminer.high_level import extract_text
from langchain_community.llms import Predibase

config_path = 'config.yaml'
with open(config_path, 'r') as file:
    config = yaml.safe_load(file)

api_key = config['credentials']['api_key']
model_name = config['credentials']['model_name']

def extract_text_from_pdf(file_path):
    return extract_text(file_path)

def extract_text_from_docx(file_path):
    doc = docx.Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def parse_response(response):
    # Extract name using regex
    name_match = re.search(r'(?:\*\*Name:\*\*|Name:)\s*(.*)', response)
    name = name_match.group(1).strip() if name_match else "Unknown"

    # Extract email using regex
    email_match = re.search(r'(?:\*\*Email:\*\*|Email:)\s*(.*)', response)
    email = email_match.group(1).strip() if email_match else "Unknown"

    # Extract phone using regex
    phone_match = re.search(r'(?:\*\*Phone:\*\*|Phone:)\s*(.*)', response)
    phone = phone_match.group(1).strip() if phone_match else "Unknown"

    # Extract skills using regex and join them with commas
    skills_match = re.search(r'(?:\*\*Skills:\*\*|Skills:)\n*(.*?)(?:\n\n|$)', response, re.DOTALL)
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
        model=model_name,
        predibase_api_key=api_key,
        predibase_sdk_version=None,
    )

    prompt = (
            "system\n"
            "You are a helpful, detailed, and polite artificial intelligence assistant. "
            "Your answers are clear and suitable for a professional environment.\n"
            "If context is provided, answer using only the provided contextual information.\n"
            "Only provide the requested information without any additional comments. Do not add any extra sentences like 'Let me know if you need any further assistance.'\n"
            "user\n"
            "This is the resume. Please get name, email, skills and phone from this resume:\n"
            f"{text}\n"
            "assistant"
        )
        
    
    response = model.invoke(prompt)
    # cleaned_response = re.sub(r'(Let me know if you need any further assistance!|Please let me know if you need any further assistance|Let me know if you need anything else!|Please note that this information is based on the provided resume and may not be exhaustive or up-to-date. If you need further assistance, please let me know!)', '', response).strip()
    # print(cleaned_response)    
    return response
