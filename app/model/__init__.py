"""ORM models package — imports every model so SQLAlchemy registers all tables."""

from app.model.user import User
from app.model.group import Group
from app.model.message_template import MessageTemplate
from app.model.schedule import Schedule
