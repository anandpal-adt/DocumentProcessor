import os
import tempfile
from typing import Optional
import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException,Query
from pymongo import MongoClient, ASCENDING, errors
from pydantic import BaseModel
import yaml
from custom_parser import extract_text_from_pdf, extract_text_from_docx, parse_resume_text, parse_response
from models import ResumeData
from policy_details import extract_policy_details,load_and_save_documents
from image_parser import extract_invoice_details,parse_invoice_response
from imagemodel import ImageData
import base64
from bson import ObjectId  # For MongoDB ObjectId generation
import shutil


config_path = 'config.yaml'
with open(config_path, 'r') as file:
    config = yaml.safe_load(file)

    # Connect to local MongoDB server
client = MongoClient('mongodb://localhost:27017/')   
db = client['local']  
collection = db['invoice_details']

app = FastAPI()

class QuestionResponse(BaseModel):
    answer: str    

@app.get("/getPolicyDetails", response_model=QuestionResponse)
async def get_vehicle_policy(question: str = Query(..., description="The question to ask regarding the internal policy of the company")):
    answer=extract_policy_details(question)
    return answer


@app.post("/getInvoiceDetails", response_model=ImageData)
async def get_invoice_details(file: UploadFile = File(...)):
    if file.content_type not in ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"]:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    # Save the uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file: 
        temp_file.write(await file.read())
        temp_file_path = temp_file.name
        
    response=extract_invoice_details(temp_file_path) 
    image_data=parse_invoice_response(response)

    
    invoice_id = str(ObjectId())
    image_data_dict = image_data.dict()
    image_data_dict['ID'] = invoice_id
    image_data.ID =f"{invoice_id}"

    image_base64 = convert_image_to_base64(temp_file_path)
    image_data.IMAGE_BASE64 = f"data:{file.content_type};base64,{image_base64}"

    
    # Insert the parsed data into the collection
    collection.insert_one(image_data_dict)
    return image_data


@app.put("/updateInvoice", response_model=ImageData)
async def update_invoice(update_data: ImageData):
    # Check if the record exists
    existing_record = collection.find_one({"ID": update_data.ID})
    if not existing_record:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Prepare update fields from the provided data
    update_fields = {k: v for k, v in update_data.dict().items() if v is not None}


    # Update the record in MongoDB
    collection.update_one({"ID": update_data.ID}, {"$set": update_fields})

    # Fetch the updated record
    updated_record = collection.find_one({"ID": update_data.ID})
    if not updated_record:
        raise HTTPException(status_code=404, detail="Invoice not found after update")

    return ImageData(**updated_record)

def convert_image_to_base64(file_path: str) -> str:
    with open(file_path, "rb") as image_file:
        # Read the image file and encode to Base64
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        return encoded_string

@app.post("/upload", response_model=ResumeData)
async def upload_resume(file: UploadFile = File(...)):
    if file.content_type not in ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(await file.read())
        temp_file_path = temp_file.name
    
    try:
        if file.content_type == "application/pdf":
            text = extract_text_from_pdf(temp_file_path)
        elif file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text = extract_text_from_docx(temp_file_path)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type")

        response = parse_resume_text(text)
        resume_data = parse_response(response)
        
        save_resume_to_db(resume_data)

        return resume_data
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    finally:
        os.remove(temp_file_path)

def save_resume_to_db(resume_data):

    url=config['credentials']['db_url']
    db_name=config['credentials']['db_name']
    collection_name=config['credentials']['collection_name']

    # Establish a connection to the MongoDB server
    client = MongoClient(url)
    db = client[db_name]
    resume_collection = db[collection_name]

    try:
        resume_collection.create_index([('phone', ASCENDING), ('email', ASCENDING)], unique=True)
    except errors.OperationFailure as e:
        print(f"Index creation failed: {e}")

    phone = resume_data.get('phone')
    email = resume_data.get('email')
 
    filter_query = {'phone': phone, 'email': email}

    try:
        resume_collection.update_one(filter_query, {'$set': resume_data}, upsert=True)
        print("Resume data upserted successfully.")
    except errors.DuplicateKeyError as e:
        print(f"Duplicate entry found: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    # load_and_save_documents()
    uvicorn.run(app, host="0.0.0.0", port=8000)
 


