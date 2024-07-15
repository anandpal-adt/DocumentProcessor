import os
import tempfile
import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException,Query
from pymongo import MongoClient, ASCENDING, errors
from pydantic import BaseModel
import yaml
from custom_parser import extract_text_from_pdf, extract_text_from_docx, parse_resume_text, parse_response
from models import ResumeData
from policy_details import extract_policy_details,load_and_save_documents

config_path = 'config.yaml'
with open(config_path, 'r') as file:
    config = yaml.safe_load(file)

app = FastAPI()

class QuestionResponse(BaseModel):
    answer: str    

@app.get("/getPolicyDetails", response_model=QuestionResponse)
async def get_vehicle_policy(question: str = Query(..., description="The question to ask regarding the internal policy of the company")):
    answer=extract_policy_details(question)
    return answer

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
 






#
# aiohttp
# aiosignal
# annotated-types
# anyio
# asttokens
# attrs
# beautifulsoup4
# Brotli
# certifi
# cffi
# charset-normalizer
# click
# colorama
# cryptography
# cuda-python
# dataclasses-json
# decorator
# Deprecated
# deprecation
# dirtyjson
# distro
# dnspython
# email_validator
# eval_type_backport
# executing
# fastapi
# fastapi-cli
# filelock
# frozenlist
# fsspec
# gevent
# geventhttpclient
# greenlet
# grpcio
# httpcore
# httptools
# httpx
# huggingface-hub
# idna
# intel-openmp
# ipyplot
# ipython
# jedi
# Jinja2
# joblib
# jsonpatch
# jsonpointer
# langchain
# langchain-community
# langchain-core
# langchain-pinecone
# langchain-text-splitters
# langsmith
# llama-cloud
# llama-index
# llama-index-agent-openai
# llama-index-cli
# llama-index-core
# llama-index-embeddings-openai
# llama-index-indices-managed-llama-cloud
# llama-index-legacy
# llama-index-llms-openai
# llama-index-multi-modal-llms-openai
# llama-index-program-openai
# llama-index-question-gen-openai
# llama-index-readers-file
# llama-index-readers-llama-parse
# llama-parse
# lorax-client
# lxml
# markdown-it-py
# MarkupSafe
# marshmallow
# marshmallow-enum
# matplotlib-inline
# mdurl
# mkl
# mpmath
# multidict
# mypy-extensions
# nest-asyncio
# networkx
# nltk
# numpy
# openai
# orjson
# packaging
# pandas
# parso
# pdfminer.six
# pillow
# pinecone-client
# pinecone-plugin-interface
# predibase
# predibase-api
# progress-table
# prompt_toolkit
# protobuf
# pure-eval
# pyarrow
# pycparser
# pydantic
# pydantic_core
# Pygments
# PyJWT
# pymongo
# pypdf
# python-dateutil
# python-docx
# python-dotenv
# python-multipart
# python-rapidjson
# pytz
# PyYAML
# regex
# requests
# rich
# safetensors
# scikit-learn
# scipy
# semantic-version
# sentence-transformers
# shellingham
# shortuuid
# six
# sniffio
# soupsieve
# SQLAlchemy
# stack-data
# starlette
# striprtf
# sympy
# tabulate
# tbb
# tenacity
# threadpoolctl
# tiktoken
# tokenizers
# torch
# tqdm
# traitlets
# transformers
# tritonclient
# typer
# typing-inspect
# typing_extensions
# tzdata
# ujson
# urllib3
# uvicorn
# watchfiles
# wcwidth
# websockets
# wrapt
# yarl
# zope.event
# zope.interface

#

