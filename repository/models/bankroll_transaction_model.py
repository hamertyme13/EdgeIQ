from sqlalchemy import Column, DateTime, Float, Integer, String, func

from repository.database import Base


class BankrollTransactionModel(Base):
    __tablename__ = "bankroll_transactions"

    id = Column(Integer, primary_key=True)
    transaction_type = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    note = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
