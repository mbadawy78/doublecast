"""Discovery: learn what is sensitive from a company's own systems.

Instead of typing lists by hand, `doublecast discover` connects to the
sources a company already has (Power BI, Microsoft 365, Dynamics 365,
SharePoint, SQL databases, Excel/CSV folders), reads their structure,
classifies every column (customer, supplier, person, product, site,
email, phone, VAT ID, money...) and turns the sensitive values into
protection rules. Nothing it reads leaves the machine; the rules are
stored encrypted next to the vault.
"""

from .profiler import ColumnVerdict, classify_column, classify_header  # noqa: F401
from .rules import RulesStore  # noqa: F401
