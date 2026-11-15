"""Clinical Obligation & Oversight Dashboard package for the Clinical Completion Engine."""

from cce.dashboard.db import DashboardDatabase
from cce.dashboard.server import DashboardApp

__all__ = ["DashboardApp", "DashboardDatabase"]
