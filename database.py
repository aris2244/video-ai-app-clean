import os

from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# Falls back to a local SQLite file if DATABASE_URL isn't set, so the app
# can still run for local development without a Postgres instance.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


Base = declarative_base()

# --- 1. Ο ΧΡΗΣΤΗΣ ---
# --- 1. Ο ΧΡΗΣΤΗΣ ---
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_verified = Column(Boolean, default=False)

    # 🔐 ΝΕΑ ΠΕΔΙΑ ΓΙΑ VERIFICATION & RESET PASSWORD
    verification_token = Column(String, nullable=True, index=True)
    reset_password_token = Column(String, nullable=True, index=True)
    reset_password_expires = Column(DateTime, nullable=True)

    # 💰 ΣΥΣΤΗΜΑ CREDITS (Αλλαγή σε 0. Τα δίνουμε ΜΕΤΑ το verify)
    credits = Column(Integer, default=0) 
    
    # 💳 STRIPE INTEGRATION
    stripe_customer_id = Column(String, nullable=True, index=True) 
    stripe_subscription_id = Column(String, nullable=True)         
    subscription_plan = Column(String, default="free")             
    is_premium = Column(Boolean, default=False)                    

    projects = relationship("Project", back_populates="owner")


# --- 2. ΤΟ PROJECT (Βίντεο) ---
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    filename = Column(String) 
    upload_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="processing") 
    
    # 👇 ΝΕΑ ΠΕΔΙΑ ΓΙΑ ΤΟ CHAT 👇
    mode = Column(String, default="video") # "video" ή "chat"
    history_json = Column(Text, default="[]") # Εδώ θα σώζουμε όλη τη συζήτηση
    # ---------------------------

    ai_response_json = Column(Text, nullable=True) # Για τα αποτελέσματα του βίντεο
    output_path = Column(String, nullable=True)

    

    owner = relationship("User", back_populates="projects")

# --- 3. CHAT HISTORY (Για να θυμάται το chat ανά project) ---
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    sender = Column(String) # 'user' or 'bot'
    text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Βοηθητική συνάρτηση για Dependency Injection στο FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()