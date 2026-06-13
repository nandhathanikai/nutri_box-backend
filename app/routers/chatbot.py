import logging
import os
import json
import math
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from pypdf import PdfReader
import google.generativeai as genai

from app.routers.auth import require_admin, get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chatbot", tags=["Chatbot"])

KNOWLEDGE_FILE = "static/uploads/chatbot_knowledge.json"

class QueryRequest(BaseModel):
    question: str

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_api_key() -> str:
    """Read Gemini API key from environment."""
    api_key = os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API key is not configured in the backend environment."
        )
    return api_key

def extract_pdf_chunks(pdf_path: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """Extract text from PDF and split into overlapping chunks."""
    try:
        reader = PdfReader(pdf_path)
        full_text = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
        
        if not full_text.strip():
            return []
            
        chunks = []
        start = 0
        text_len = len(full_text)
        
        while start < text_len:
            end = min(start + chunk_size, text_len)
            # Try to find a word boundary in the last 50 characters
            if end < text_len:
                boundary = full_text.rfind(" ", end - 50, end)
                if boundary != -1:
                    end = boundary
            chunks.append(full_text[start:end].strip())
            start = end - overlap
            if start >= text_len - overlap:
                break
                
        return [c for c in chunks if c]
    except Exception as e:
        logger.error(f"Error parsing PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse PDF document: {str(e)}")

def generate_embeddings(chunks: List[str], api_key: str) -> List[dict]:
    """Generate vectors using gemini-embedding-2 in batches."""
    genai.configure(api_key=api_key)
    
    knowledge_base = []
    batch_size = 50
    
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        try:
            response = genai.embed_content(
                model="models/gemini-embedding-2",
                content=batch,
                task_type="retrieval_document"
            )
            embeddings = response.get('embedding', [])
            for j, emb in enumerate(embeddings):
                knowledge_base.append({
                    "chunk_index": i + j,
                    "text_content": batch[j],
                    "embedding": emb
                })
        except Exception as e:
            logger.warning(f"Batch embedding failed: {e}. Falling back to single chunk requests.")
            # Fallback to single requests
            for j, chunk in enumerate(batch):
                try:
                    response = genai.embed_content(
                        model="models/gemini-embedding-2",
                        content=chunk,
                        task_type="retrieval_document"
                    )
                    knowledge_base.append({
                        "chunk_index": i + j,
                        "text_content": chunk,
                        "embedding": response['embedding']
                    })
                except Exception as ex:
                    logger.error(f"Failed to embed chunk {i+j}: {ex}")
                    
    return knowledge_base

def calculate_cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two lists of floats."""
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)

# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/pdf-status")
def get_pdf_status():
    """Retrieve status of the uploaded chatbot FAQ/Policy PDF."""
    if not os.path.exists(KNOWLEDGE_FILE):
        return {
            "uploaded": False,
            "filename": None,
            "uploaded_at": None,
            "total_chunks": 0
        }
    
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return {
            "uploaded": True,
            "filename": data.get("filename", "knowledge.pdf"),
            "uploaded_at": data.get("uploaded_at"),
            "total_chunks": len(data.get("chunks", []))
        }
    except Exception as e:
        logger.error(f"Error reading knowledge status: {e}")
        return {
            "uploaded": False,
            "filename": None,
            "uploaded_at": None,
            "total_chunks": 0,
            "error": "Failed to read knowledge file"
        }

@router.post("/upload-pdf", dependencies=[Depends(require_admin)])
def upload_pdf(file: UploadFile = File(...)):
    """Upload PDF, parse into overlapping chunks, generate embeddings, and save locally."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF documents are supported.")
    
    api_key = get_api_key()
    
    # Save the file temporarily
    os.makedirs("static/uploads", exist_ok=True)
    temp_path = f"static/uploads/temp_{file.filename}"
    try:
        with open(temp_path, "wb") as f:
            f.write(file.file.read())
            
        chunks = extract_pdf_chunks(temp_path)
        if not chunks:
            raise HTTPException(status_code=400, detail="The PDF appears to be empty or contains no extractable text.")
            
        logger.info(f"Extracted {len(chunks)} chunks from PDF. Generating embeddings...")
        knowledge_base = generate_embeddings(chunks, api_key)
        
        if not knowledge_base:
            raise HTTPException(status_code=500, detail="Failed to generate embeddings for the PDF text chunks.")
            
        # Write to JSON storage
        knowledge_data = {
            "filename": file.filename,
            "uploaded_at": datetime.now().isoformat(),
            "chunks": knowledge_base
        }
        
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(knowledge_data, f, ensure_ascii=False, indent=2)
            
        return {
            "message": "PDF uploaded and parsed successfully.",
            "filename": file.filename,
            "total_chunks": len(knowledge_base)
        }
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

@router.post("/query")
def query_chatbot(req: QueryRequest, current_user: User = Depends(get_current_user)):
    """RAG-based chat query using cosine similarity retrieval over locally saved embeddings."""
    if not os.path.exists(KNOWLEDGE_FILE):
        return {
            "answer": "Hello! I don't have my PDF knowledge base configured yet. Please ask an admin to upload a reference policy PDF in Settings."
        }
        
    api_key = get_api_key()
    
    # 1. Load Knowledge base
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            kb = json.load(f)
        chunks = kb.get("chunks", [])
        if not chunks:
            return {"answer": "My knowledge base is empty. Please re-upload the PDF."}
    except Exception as e:
        logger.error(f"Failed to read knowledge base file: {e}")
        raise HTTPException(status_code=500, detail="Failed to read the chatbot knowledge base.")
        
    # 2. Embed user question
    try:
        genai.configure(api_key=api_key)
        response = genai.embed_content(
            model="models/gemini-embedding-2",
            content=req.question,
            task_type="retrieval_query"
        )
        query_vector = response['embedding']
    except Exception as e:
        logger.error(f"Failed to embed query: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini API connection error: {str(e)}")
        
    # 3. Calculate similarity and fetch top 4 chunks
    scored_chunks = []
    for chunk in chunks:
        sim = calculate_cosine_similarity(query_vector, chunk["embedding"])
        scored_chunks.append((sim, chunk["text_content"]))
        
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    top_chunks = scored_chunks[:4]
    
    # 4. Construct LLM prompt
    context_str = "\n---\n".join([text for _, text in top_chunks])
    
    system_instruction = (
        "You are the Nutribox Virtual Assistant, a friendly and premium customer support AI.\n"
        "Your goal is to answer the customer's question based strictly on the provided context.\n"
        "Ensure your tone is polite, professional, and helpful. Follow the context details precisely.\n"
        "If the answer cannot be found in the provided context, politely explain that you do not have "
        "that specific information in your policies yet and guide them to contact support via the WhatsApp link.\n\n"
        f"Context:\n{context_str}"
    )
    
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_instruction
        )
        
        chat = model.start_chat()
        response = chat.send_message(req.question)
        
        return {
            "answer": response.text,
            "references": [text[:100] + "..." for _, text in top_chunks]
        }
    except Exception as e:
        logger.error(f"Generative API failed: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini generative model error: {str(e)}")
