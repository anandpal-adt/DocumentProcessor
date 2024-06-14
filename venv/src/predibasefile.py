# import requests
# import socket

# # Set your API endpoint and access key
# api_endpoint = "https://api.predibase.com"
# access_key = "pb_y_JOJ2toWf-hewNLR3yY_Q"  # Replace with your actual access key

# # Define headers for the HTTP request
# headers = {
#     "Authorization": f"Bearer {access_key}",
#     "Content-Type": "application/json"
# }

# # Define your prompt
# prompt = "Can you help me?"

# # Define the data payload
# data = {"prompt": prompt}

# # Function to make the API call
# def call_predibase_api(api_endpoint, headers, data):
#     try:
#         response = requests.post(api_endpoint, headers=headers, json=data)
#         response.raise_for_status()  # Check for HTTP errors
#         return response.json().get("text", "")
#     except requests.exceptions.RequestException as e:
#         print("An error occurred:", e)
#         return None

# # Test DNS resolution
# def test_dns_resolution(hostname):
#     try:
#         ip = socket.gethostbyname(hostname)
#         print(f"Resolved {hostname} to {ip}")
#     except socket.gaierror as e:
#         print(f"Failed to resolve {hostname}: {e}")

# # Test DNS resolution for api.predibase.com
# test_dns_resolution("api.predibase.com")

# # Call the function and print the result
# generated_text = call_predibase_api(api_endpoint, headers, data)
# if generated_text:
#     print("Generated text:", generated_text)
# else:
#     print("Failed to generate text.")
# import os
# os.environ["PREDIBASE_API_TOKEN"] = "{PREDIBASE_API_TOKEN}"
from langchain_community.llms import Predibase

# The fine-tuned adapter is hosted at Predibase (adapter_version must be specified).    
model = Predibase(
    model="mistral-7b",
    # predibase_api_key=os.environ.get("PREDIBASE_API_TOKEN"),
    predibase_api_key="pb_y_JOJ2toWf-hewNLR3yY_Q",  
    predibase_sdk_version=None,  # optional parameter (defaults to the latest Predibase SDK version if omitted)
    adapter_id="predibase/e2e_nlg",
)

response = model.invoke("Can you recommend me a nice dry wine?")
print(response)

