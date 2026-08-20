"""Data models for Nanofossil research output."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
import json


@dataclass
class Source:
    title: str
    url: str
    type: str
    snippet: str = ""
    fetched_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "type": self.type,
            "snippet": self.snippet
        }


@dataclass
class Finding:
    title: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"title": self.title, "content": self.content}


@dataclass
class Comparison:
    headers: List[str]
    rows: List[List[str]]

    def to_dict(self) -> Dict[str, Any]:
        return {"headers": self.headers, "rows": self.rows}


@dataclass
class ResearchReport:
    title: str
    executive_summary: str
    key_findings: List[Finding]
    comparison: Optional[Comparison] = None
    evidence_assessment: str = ""
    confidence_notes: str = ""
    sources: List[Source] = field(default_factory=list)
    question: str = ""
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "title": self.title,
            "executive_summary": self.executive_summary,
            "key_findings": [f.to_dict() for f in self.key_findings],
            "evidence_assessment": self.evidence_assessment,
            "confidence_notes": self.confidence_notes,
            "sources": [s.to_dict() for s in self.sources],
            "question": self.question,
            "generated_at": self.generated_at
        }
        if self.comparison:
            result["comparison"] = self.comparison.to_dict()
        return result

    def to_json(self) -> str:
        return json.dumps({"report": self.to_dict()}, indent=2, ensure_ascii=False)


@dataclass
class ResearchJob:
    question: str
    plan: List[str] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    status: str = "pending"
    error: Optional[str] = None
