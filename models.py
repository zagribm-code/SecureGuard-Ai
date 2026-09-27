import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional
from sqlalchemy import String, Text, Boolean, Float, DateTime, ForeignKey, Enum, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

class KYCStatus(str, PyEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class DocumentType(str, PyEnum):
    NATIONAL_ID = "NATIONAL_ID"
    PASSPORT = "PASSPORT"

class FraudRiskLevel(str, PyEnum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_kyc_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    kyc_requests: Mapped[List["KYCRequest"]] = relationship(back_populates="user")

class KYCRequest(Base):
    __tablename__ = "kyc_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    extracted_id_number: Mapped[Optional[str]] = mapped_column(String(100))
    face_match_score: Mapped[Optional[float]] = mapped_column(Float)
    is_live_selfie: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[KYCStatus] = mapped_column(Enum(KYCStatus), default=KYCStatus.PENDING)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    user: Mapped["User"] = relationship(back_populates="kyc_requests")
    documents: Mapped[List["VerificationDocument"]] = relationship(back_populates="kyc_request")
    fraud_logs: Mapped[List["FraudLog"]] = relationship(back_populates="kyc_request")

class VerificationDocument(Base):
    __tablename__ = "verification_documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kyc_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kyc_requests.id", ondelete="CASCADE"), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_ocr_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    kyc_request: Mapped["KYCRequest"] = relationship(back_populates="documents")

class FraudLog(Base):
    __tablename__ = "fraud_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kyc_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kyc_requests.id", ondelete="SET NULL"), nullable=True)
    risk_level: Mapped[FraudRiskLevel] = mapped_column(Enum(FraudRiskLevel), nullable=False)
    fraud_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_screen_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    technical_details: Mapped[Optional[dict]] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kyc_request: Mapped[Optional["KYCRequest"]] = relationship(back_populates="fraud_logs")
