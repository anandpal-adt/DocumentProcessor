from fastapi import FastAPI, File, UploadFile, HTTPException
import os
import tempfile
from custom_parser import extract_text_from_pdf, extract_text_from_docx, parse_resume_text, parse_response
from models import ResumeData
from pymongo import MongoClient

app = FastAPI()
    
    
@app.get("/")
def read_root():
    return {"Hello": "World"}

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

        ##save to database
        client = MongoClient('mongodb://localhost:27017')
        db = client['local']
        resume_collection = db['resume_details']

        # Insert the resume data into the collection
        resume_collection.insert_one(resume_data)
        print("Resume data saved successfully!")
        return resume_data
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    finally:
        client.close()
        os.remove(temp_file_path)




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
