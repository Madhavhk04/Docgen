from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import uuid
import logging
from typing import Optional, Dict
from dotenv import load_dotenv
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta

load_dotenv(override=False)

from .template_renderer import render_docx
from .ai_client import generate_structured_with_gemini, GeminiError
from .database import get_db
from .models import User, Document
from .auth import get_password_hash, verify_password, create_access_token, get_current_user
from fastapi.middleware.cors import CORSMiddleware
# Init Database Tables
# Base.metadata.create_all(bind=engine) # Removed for Cosmos DB
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def health():
    return {"status": "running"}


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docgen")

BASE_DIR = Path(__file__).resolve().parent         # backend/app

# Use same persistent storage logic as database
import os
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR.parent / "data"))
GENERATED = STORAGE_DIR / "generated"           # backend/generated or /home/data/generated
TEMPLATES_DIR = BASE_DIR / "templates"              # backend/app/templates

GENERATED.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Docorator Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or your static web app URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# @app.get("/")
# async def read_index():
#     return FileResponse("../frontend/index.html")

@app.get("/")
def health_check():
    return {"status": "ok"}

# --- AUTH ROUTER ---

class UserSchema(BaseModel):
    email: str
    password: str
    full_name: str
    profession: str
    security_question: str
    security_answer: str

@app.post("/auth/signup")
def signup(user: UserSchema, db: dict = Depends(get_db)):
    users_container = db["users"]
    
    # Check if exists
    query = "SELECT * FROM c WHERE c.email = @email"
    items = list(users_container.query_items(
        query=query, 
        parameters=[{"name": "@email", "value": user.email}],
        enable_cross_partition_query=True
    ))
    
    if items:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create User Model
    new_user = User(
        email=user.email,
        hashed_password=get_password_hash(user.password),
        full_name=user.full_name,
        profession=user.profession,
        security_question=user.security_question,
        security_answer_hash=get_password_hash(user.security_answer),
        partitionKey=user.email # Set partition key
    )
    
    # Save to Cosmos (dump model to dict)
    users_container.create_item(body=new_user.dict(by_alias=True))
    
    return {"msg": "User created successfully"}

class UserProfile(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    profession: Optional[str] = None
    security_question: Optional[str] = None

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    profession: Optional[str] = None

@app.get("/auth/me", response_model=UserProfile)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.put("/auth/me", response_model=UserProfile)
def update_user_me(user_update: UserUpdate, current_user: User = Depends(get_current_user), db: dict = Depends(get_db)):
    users_container = db["users"]
    
    # Update fields if provided
    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name
    if user_update.profession is not None:
        current_user.profession = user_update.profession
    
    # Check partition key presence
    if not current_user.partitionKey:
        current_user.partitionKey = current_user.email
        
    # Upsert in Cosmos
    users_container.upsert_item(body=current_user.dict(by_alias=True))
    
    return current_user

class GetQuestionRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    security_answer: str
    new_password: str

@app.post("/auth/get-question")
def get_security_question(req: GetQuestionRequest, db: dict = Depends(get_db)):
    users_container = db["users"]
    query = "SELECT * FROM c WHERE c.email = @email"
    items = list(users_container.query_items(
        query=query, 
        parameters=[{"name": "@email", "value": req.email}],
        enable_cross_partition_query=True
    ))
    
    if not items:
        raise HTTPException(status_code=404, detail="User not found")
        
    user = User(**items[0])
    
    if not user.security_question:
         raise HTTPException(status_code=400, detail="User has no security question set")
    return {"question": user.security_question}

@app.post("/auth/reset-password")
def reset_password(req: ResetPasswordRequest, db: dict = Depends(get_db)):
    users_container = db["users"]
    query = "SELECT * FROM c WHERE c.email = @email"
    items = list(users_container.query_items(
        query=query, 
        parameters=[{"name": "@email", "value": req.email}],
        enable_cross_partition_query=True
    ))
    
    if not items:
         raise HTTPException(status_code=404, detail="User not found")
    
    user = User(**items[0])
    
    if not user.security_answer_hash:
          raise HTTPException(status_code=400, detail="User has no security answer set")
          
    if not verify_password(req.security_answer, user.security_answer_hash):
         raise HTTPException(status_code=400, detail="Incorrect security answer")
         
    # Reset Password
    user.hashed_password = get_password_hash(req.new_password)
    
    if not user.partitionKey:
        user.partitionKey = user.email

    users_container.upsert_item(body=user.dict(by_alias=True))
    
    return {"msg": "Password reset successfully"}

@app.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: dict = Depends(get_db)):
    users_container = db["users"]
    query = "SELECT * FROM c WHERE c.email = @email"
    items = list(users_container.query_items(
        query=query, 
        parameters=[{"name": "@email", "value": form_data.username}],
        enable_cross_partition_query=True
    ))
    
    user = User(**items[0]) if items else None
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(days=7)
    )
    return {"access_token": access_token, "token_type": "bearer"}


# --- DASHBOARD ROUTER ---

# --- STARTUP DB MIGRATION CHECK ---
@app.on_event("startup")
def check_db_schema():
    # Deprecated for Cosmos DB
    pass

# --- DASHBOARD ROUTER ---

@app.get("/dashboard/documents")
def get_user_documents(current_user: User = Depends(get_current_user), db: dict = Depends(get_db)):
    documents_container = db["documents"]
    # Query docs for user
    query = "SELECT * FROM c WHERE c.user_id = @uid ORDER BY c.created_at DESC"
    items = list(documents_container.query_items(
        query=query,
        parameters=[{"name": "@uid", "value": current_user.id}],
        enable_cross_partition_query=True
    ))
    return items

@app.get("/dashboard/doc/{doc_id}")
def get_document_details(doc_id: str, current_user: User = Depends(get_current_user), db: dict = Depends(get_db)):
    documents_container = db["documents"]
    # Doc ID is string now (uuid)
    query = "SELECT * FROM c WHERE c.id = @id AND c.user_id = @uid"
    items = list(documents_container.query_items(
        query=query,
        parameters=[
            {"name": "@id", "value": doc_id},
            {"name": "@uid", "value": current_user.id}
        ],
        enable_cross_partition_query=True
    ))
    
    if not items:
        raise HTTPException(status_code=404, detail="Document not found")
        
    return items[0]

@app.delete("/dashboard/delete/{doc_id}")
def delete_document(doc_id: str, current_user: User = Depends(get_current_user), db: dict = Depends(get_db)):
    documents_container = db["documents"]
    
    # 1. Get doc to find file paths
    query = "SELECT * FROM c WHERE c.id = @id AND c.user_id = @uid"
    items = list(documents_container.query_items(
        query=query,
        parameters=[
            {"name": "@id", "value": doc_id},
            {"name": "@uid", "value": current_user.id}
        ],
        enable_cross_partition_query=True
    ))
    
    if not items:
        raise HTTPException(status_code=404, detail="Document not found")
        
    doc = Document(**items[0])
    
    # Try to delete physical files
    stored_path = BASE_DIR / doc.file_path
    stem = stored_path.stem
    
    # ... (Keep existing file deletion logic) ...
    paths_to_check = [
        stored_path,
        GENERATED / f"{stem}.docx",
        GENERATED / f"{stem}.pdf",
        GENERATED / f"{doc.doc_type}_{stem}.docx",
        GENERATED / f"{doc.doc_type}_{stem}.pdf",
    ]
    if "_" in stem:
        uid = stem.split("_")[-1]
        paths_to_check.append(GENERATED / f"{uid}.pdf")
        
    for p in paths_to_check:
        try:
             if p.exists():
                 os.remove(p)
                 logger.info(f"Deleted file: {p}")
        except Exception as e:
            logger.error(f"Failed to delete {p}: {e}")
            
    # Delete from DB
    # Cosmos delete requires partition key
    documents_container.delete_item(item=doc_id, partition_key=doc.partitionKey)
    
    return {"msg": "Document deleted"}

@app.get("/dashboard/download/{doc_id}")
def download_dashboard_doc(doc_id: str, format: str = "pdf", current_user: User = Depends(get_current_user), db: dict = Depends(get_db)):
    documents_container = db["documents"]
    
    query = "SELECT * FROM c WHERE c.id = @id AND c.user_id = @uid"
    items = list(documents_container.query_items(
        query=query,
        parameters=[
            {"name": "@id", "value": doc_id},
            {"name": "@uid", "value": current_user.id}
        ],
        enable_cross_partition_query=True
    ))
    
    if not items:
         raise HTTPException(status_code=404, detail="Document not found")
         
    doc = Document(**items[0])
    
    # Robust File Finding Strategy
    # stored 'doc.file_path' might be relative to BASE_DIR (backend/app), but files are scattered.
    # We will search in known directories.
    
    search_dirs = [
        GENERATED,                          # backend/data/generated (Current Standard)
        BASE_DIR.parent / "generated",      # backend/generated (Legacy)
        BASE_DIR / Path(doc.file_path).parent if doc.file_path else None # Fix: path is string, need Path()
    ]
    # Filter valid dirs
    search_dirs = [d for d in search_dirs if d and d.exists()]
    
    # Candidate filenames
    candidates = []
    
    # 1. Exact match for requested format by filename stems
    base_name = Path(doc.filename).stem
    
    if format == "docx":
        candidates.append(f"{base_name}.docx")
        # Legacy: {doc_type}_{uid}.docx if stem is just uid?
        candidates.append(f"{doc.doc_type}_{base_name}.docx")
        
    elif format == "pdf":
        candidates.append(f"{base_name}.pdf")
        # Legacy: uid.pdf if stem is doc_type_uid? 
        if "_" in base_name:
             uid = base_name.split("_")[-1]
             candidates.append(f"{uid}.pdf")

    target_file = None
    
    for folder in search_dirs:
        for fname in candidates:
            p = folder / fname
            if p.exists():
                target_file = p
                break
        if target_file: break

    if not target_file:
         # Last resort: Try resolving doc.file_path directly vs BASE_DIR
         p = BASE_DIR / doc.file_path
         if p.exists() and p.suffix == f".{format}":
             target_file = p
         
    if not target_file or not target_file.exists():
         raise HTTPException(status_code=404, detail=f"File ({format}) not found on server")
         
    return FileResponse(
            path=str(target_file),
            filename=target_file.name,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document' if format=='docx' else 'application/pdf'
        )

# --- GENERATION ---



class GenerateRequest(BaseModel):
    doc_type: str
    fields: Optional[Dict] = None
    use_gemini: bool = False
    ai_context: Optional[str] = None
    return_docx: bool = False


@app.post("/generate")
def generate(req: GenerateRequest, current_user: User = Depends(get_current_user), db: dict = Depends(get_db)):
    doc_type = (req.doc_type or "").strip().lower()
    if not doc_type:
        raise HTTPException(status_code=400, detail="doc_type is required")

    template_path = TEMPLATES_DIR / f"{doc_type}_template.docx"
    if not template_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Template for '{doc_type}' not found at {template_path}"
        )

    # Get fields from client or Gemini
    if req.use_gemini:
        try:
            fields = generate_structured_with_gemini(
                doc_type,
                req.fields or {},
                req.ai_context
            )

            if not isinstance(fields, dict):
                raise ValueError("AI returned non-dict fields")

            # Merge user-provided fields (like Name, Email) into AI fields
            # User fields take precedence if they are explicitly provided (non-empty)
            if req.fields:
                skip_keys = {"experience_list", "projects", "education", "achievements", "skills"}
                for k, v in req.fields.items():
                    if v and k not in skip_keys:
                        fields[k] = v

        except GeminiError as ge:
            logger.exception("Gemini generation failed")
            raise HTTPException(status_code=502, detail=f"AI generation failed: {str(ge)}")
        except Exception as e:
            logger.exception("Unexpected AI error")
            raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")

    else:
        # Manual mode
        if not req.fields:
            raise HTTPException(
                status_code=400,
                detail="fields is required when use_gemini is false"
            )
        fields = req.fields


    # Render DOCX
    unique_id = uuid.uuid4().hex[:8]
    fname = f"{doc_type}_{unique_id}.docx"
    out_docx = GENERATED / fname
    try:
        render_docx(str(template_path), fields or {}, str(out_docx))
        logger.info("Rendered DOCX: %s", out_docx)
    except Exception as e:
        logger.exception("Template rendering failed")
        raise HTTPException(status_code=500, detail=f"Template rendering failed: {str(e)}")

    # Force DOCX return (PDF conversion logic removed)
    final_file = out_docx
    media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

    if not out_docx.exists():
        raise HTTPException(status_code=500, detail="DOCX was not created")

    # --- SAVE TO DATABASE ---
    rel_path = f"../data/generated/{final_file.name}"
    

    
    new_doc = Document(
        user_id=current_user.id,
        filename=final_file.name,
        file_path=rel_path,
        doc_type=doc_type,
        input_data=fields, # Store inputs for editing
        partitionKey=current_user.id # Set partition key
    )
    
    # Save to Cosmos
    db["documents"].create_item(body=new_doc.dict(by_alias=True))
    # db.commit() # Not needed

    return FileResponse(
        path=str(final_file),
        filename=final_file.name,
        media_type=media_type
    )