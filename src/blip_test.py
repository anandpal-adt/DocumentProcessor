# import torch
# from PIL import Image
# from transformers import Blip2Processor, Blip2ForConditionalGeneration

# # Load the model and processor
# model_name = "Salesforce/blip2-opt-2.7b"  # This is the model name on Hugging Face
    
# token ="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"    
# processor = Blip2Processor.from_pretrained(model_name, token=token)
# model = Blip2ForConditionalGeneration.from_pretrained(model_name, token=token)    


# image_path = "E:/parsing/DocumentProcessor/BOMBAYINV.jpg"

# # Extract details from the image
# image = Image.open(image_path).convert("RGB")

# # Preprocess the image and prepare it for the model
# inputs = processor(images=image, return_tensors="pt")

# # Generate the details from the image
# with torch.no_grad():
#     outputs = model.generate(**inputs)

# # Decode the generated output to text
# details = processor.decode(outputs[0], skip_special_tokens=True)
# print("Extracted Details:")
# print(details)

# # Filter details based on a keyword
# keyword = "specific_keyword"  # Replace with your keyword
# filtered_lines = [line for line in details.split('\n') if keyword.lower() in line.lower()]

# filtered_details = '\n'.join(filtered_lines)
# print("\nFiltered Details:")
# print(filtered_details)
import pytesseract
from PIL import Image
from transformers import BertTokenizer, BertForTokenClassification, pipeline
import os

# Set your Hugging Face token here
HUGGINGFACE_TOKEN = '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'

def ocr_extract_text(image_path):
    """Use OCR to extract text from an image."""
    image = Image.open(image_path).convert("RGB")
    text = pytesseract.image_to_string(image)
    return text

def extract_entities(text):
    """Extract entities from the text using a pre-trained BERT NER model with authentication."""
    # Load tokenizer and model with the token
    tokenizer = BertTokenizer.from_pretrained('dbmdz/bert-large-cased-finetuned-conll03-english', use_auth_token=HUGGINGFACE_TOKEN)
    model = BertForTokenClassification.from_pretrained('dbmdz/bert-large-cased-finetuned-conll03-english', use_auth_token=HUGGINGFACE_TOKEN)
    
    # Initialize the NER pipeline
    nlp_ner = pipeline('ner', model=model, tokenizer=tokenizer, aggregation_strategy='simple')
    
    # Process the text
    ner_results = nlp_ner(text)
    
    # Extract entities
    entities = {}
    for entity in ner_results:
        label = entity['entity_group']
        word = entity['word']
        if label not in entities:
            entities[label] = []
        entities[label].append(word)
    
    return entities

def main():
    image_path = "path_to_your_invoice_image.jpg"
    
    # Extract text from the image using OCR
    text = ocr_extract_text(image_path)
    print("Extracted Text:")
    print(text)
    
    # Extract entities using BERT NER model
    entities = extract_entities(text)
    print("\nExtracted Entities:")
    for label, words in entities.items():
        print(f"{label}: {' '.join(words)}")

if __name__ == "__main__":
    main()






