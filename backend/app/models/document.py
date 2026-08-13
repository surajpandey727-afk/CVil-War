"""Central document library with immutable versions.

An application must always be able to show the *exact* document that was submitted with it.
That is the whole reason versions are immutable: if editing a CV mutated the stored file, an
application from three months ago would silently start claiming it used today's wording, and
the record of what an employer actually received would be lost.

So:

* :class:`Document` is the stable identity — "my AI Product CV".
* :class:`DocumentVersion` is an immutable snapshot. Editing creates a new version; the old
  one is never rewritten.
* Applications reference a **version**, never the document.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import DocumentType


class Document(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A logical document the user owns, independent of its revisions."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_document_user_type", "user_id", "doc_type"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(
        pg_enum(DocumentType, "document_type"), nullable=False, default=DocumentType.CV
    )
    #: Points at the version offered by default. Older versions stay reachable.
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Set when this document is derived from a résumé record (tailored CV per job).
    source_resume_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version.desc()",
    )

    def __repr__(self) -> str:
        return f"<Document({self.name!r} type={self.doc_type})>"


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """An immutable snapshot of a document.

    Never updated after creation. The storage key is content-addressed by version so a new
    revision cannot overwrite the bytes an earlier application relies on.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        Index("ix_docver_document", "document_id", "version", unique=True),
    )

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Storage keys, not filesystem paths — the storage layer resolves them per backend.
    storage_key_pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_key_docx: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Extracted text, kept for ATS scoring without re-parsing the binary.
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: sha256 of the source bytes — detects an identical re-upload so it is not versioned twice.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Job this version was tailored for, when it was generated rather than uploaded.
    tailored_for_job_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    ats_score: Mapped[float | None] = mapped_column(nullable=True)
    created_reason: Mapped[str] = mapped_column(String(120), nullable=False, default="upload")
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="versions")

    def __repr__(self) -> str:
        return f"<DocumentVersion(doc={self.document_id} v{self.version})>"
