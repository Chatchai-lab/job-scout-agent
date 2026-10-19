"""Job sources: each turns one company board or feed into JobPostings."""

from job_scout.sources.registry import fetch_for, supported_ats

__all__ = ["fetch_for", "supported_ats"]
