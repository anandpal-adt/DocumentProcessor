from paddleocr import PaddleOCR
import cv2
import json
from langchain_community.llms import HuggingFaceHub
from transformers import GPT2LMHeadModel, GPT2Tokenizer
import yaml     
from langchain_community.llms import Predibase
import numpy as np
import re
from imagemodel import ImageData
from typing import Optional
from pydantic import BaseModel

class ImageData(BaseModel):
    INVOICE_HEADER: str
    ADDRESS: str
    GST_NO: str
    ACCOUNT_NO: Optional[str] = None
    TOTAL_AMOUNT: str
    IMAGE_BASE64: str
    ID: str
    
    
config_path = 'config.yaml'
with open(config_path, 'r') as file:
    config = yaml.safe_load(file)

api_key = config['credentials']['api_key']
model_name = config['credentials']['model_name']

# Initialize PaddleOCR
ocr = PaddleOCR(use_angle_cls=False, lang='en')  # Disable angle classification

# Set your Hugging Face API token
huggingfacehub_api_token = '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'
def extract_invoice_details(img_path):

    if is_image_bright(img_path):
       print("Image is bright")
    else:
      print("Image is dark")
    
    
    image = cv2.imread(img_path)
    if len(image.shape) == 2:
       print("Image is grayscale")
    else:
       print("Image is not grayscale")
       gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
       cv2.imwrite('processed_invoice.jpg', gray)
  
    result = ocr.ocr('processed_invoice.jpg', cls=True)

    print(result)


    model = Predibase(
        model='llama-3-1-8b-instruct',
        # model='mixtral-8x7b-instruct-v0-1',
        predibase_api_key=api_key,
        predibase_sdk_version=None,
        max_tokens=800,
        temperature=2
    )

    prompt = (
            "system\n"
            "You are a helpful, detailed, and polite artificial intelligence assistant. "
            "Your answers are clear and suitable for a professional environment.\n"
            "If context is provided, answer using only the provided contextual information.\n"
            "user\n"    
            "This is the output of paddle OCR on certain invoice/bill please us.\n"
            "Based on the Bounding box cordinates Please extract GST_NO, ACCOUNT_NO, INVOICE_HEADER, TOTAL_AMOUNT, ADDRESS details  with confidence score.\n"
            "Note:address/location is generally found at the top after header name like nagar/indore or 1/2 like this ,"
            "Invoice header is the first top header in the image i.e the name of the image,"
            "Total amount is the amount of money that is calculated as total amount to be paid for the invoice , written in from of key total/total amount/amount,"
            "account number is exactly  with a/c or account number as prefix and that has only numberic not alphanumeric\n"
            f"{result}\n"
            "assistant"
        )
    # input = 'Health is wealth, but is it the order of priority for most of us?'
    # llm = HuggingFaceHub(repo_id='meta-llama/Llama-2-7b-hf', huggingfacehub_api_token=huggingfacehub_api_token)

    response = model.invoke(prompt)    

    print(response)
    
    return response


def is_image_bright(image_path):

  brightness_threshold=150

  img = cv2.imread(image_path, 0)  # Load image in grayscale
  avg_intensity = np.mean(img)

  return avg_intensity >= brightness_threshold


def parse_invoice_response(text: str) -> ImageData:

     # Extract INVOICE_HEADER
    invoice_header_match = re.search(r'\*\*INVOICE_HEADER\*\*:\s*(.*)', text)
    invoice_header = invoice_header_match.group(1).strip() if invoice_header_match else "Unknown"

    # Extract ADDRESS
    address_match = re.search(r'\*\*ADDRESS\*\*:\s*(.*)', text)
    address = address_match.group(1).strip() if address_match else "Unknown"

    # Extract GST_NO
    gst_no_match = re.search(r'\*\*GST_NO\*\*:\s*(.*)', text)
    gst_no = gst_no_match.group(1).strip() if gst_no_match else "Unknown"

    # Extract ACCOUNT_NO
    account_no_match = re.search(r'\*\*ACCOUNT_NO\*\*:\s*(.*)', text)
    account_no = account_no_match.group(1).strip() if account_no_match else None

    # Extract TOTAL_AMOUNT
    total_amount_match = re.search(r'\*\*TOTAL_AMOUNT\*\*:\s*(.*)', text)
    total_amount = total_amount_match.group(1).strip() if total_amount_match else "Unknown"

    # Create an instance of the ImageData model
    image_data = ImageData(
        INVOICE_HEADER=invoice_header,
        ADDRESS=address,
        GST_NO=gst_no,
        ACCOUNT_NO=account_no,
        TOTAL_AMOUNT=total_amount,
        IMAGE_BASE64="",
        ID="" 
    )
    
    return image_data
