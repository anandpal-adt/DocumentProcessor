import os
import yaml
from langchain.chains import RetrievalQA
from langchain_community.llms import Predibase
from langchain_community.document_loaders.word_document import Docx2txtLoader
from langchain_community.document_loaders import Docx2txtLoader, DirectoryLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Pinecone
from langchain_pinecone import PineconeVectorStore
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone, ServerlessSpec

config_path = 'config.yaml'
with open(config_path, 'r') as file:
    config = yaml.safe_load(file)

os.environ['PINECONE_API_KEY'] = config['credentials']['PINECONE_API_KEY']
api_key = config['credentials']['api_key']
model_name = config['credentials']['model_name']
PINECONE_API_KEY = config['credentials']['PINECONE_API_KEY']
# Initialize Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)

index_name = "predibase-demo-hf"
index_dimension = 768
index_metric = "cosine"
model = SentenceTransformer('all-mpnet-base-v2')

# Check if the index already exists before creating it
if index_name not in pc.list_indexes().names():
    pc.create_index(
        name=index_name,
        dimension=index_dimension,
        metric=index_metric,
        spec=ServerlessSpec(cloud='aws', region='us-east-1')  
    )
index = pc.Index(index_name)
embeddings = HuggingFaceEmbeddings()

def load_and_save_documents():
    loader = DirectoryLoader('./documents', glob="**/*.docx", loader_cls=Docx2txtLoader)
    data = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=0)
    all_splits = text_splitter.split_documents(data)

    for i, doc in enumerate(all_splits):
        content = doc.page_content 
        embedding = model.encode(content).tolist()
        embedding =  [float(e) for e in embedding]
        index.upsert([(str(i), embedding, {'text': content})])
        
def extract_policy_details(question):
    predibase_llm =  Predibase(model='llama-3-8b-instruct', predibase_api_key=api_key)
    pinecone_retriever = PineconeVectorStore.from_existing_index(
        index_name=index_name,
        embedding=embeddings
    )

    qa_chain = RetrievalQA.from_chain_type(llm=predibase_llm, retriever=pinecone_retriever.as_retriever())
    result = qa_chain({"query": question})
    answer = result["result"]
    
    return {"answer": answer}

