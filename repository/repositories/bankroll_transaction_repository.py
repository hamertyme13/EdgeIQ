from sqlalchemy.orm import Session

from repository.database import SessionLocal, initialize_database
from repository.models.bankroll_transaction_model import BankrollTransactionModel
from utils.time import iso_utc


class BankrollTransactionRepository:
    _schema_ready = False

    @staticmethod
    def _ensure_schema() -> None:
        if BankrollTransactionRepository._schema_ready:
            return
        initialize_database()
        BankrollTransactionRepository._schema_ready = True

    @staticmethod
    def save(transaction_type: str, amount: float, note: str = "") -> dict:
        BankrollTransactionRepository._ensure_schema()
        if transaction_type not in {"Deposit", "Withdrawal"}:
            raise ValueError("transaction_type must be Deposit or Withdrawal.")
        session: Session = SessionLocal()
        try:
            model = BankrollTransactionModel(
                transaction_type=transaction_type,
                amount=round(float(amount), 2),
                note=note,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            return BankrollTransactionRepository._serialize(model)
        finally:
            session.close()

    @staticmethod
    def all() -> list[dict]:
        BankrollTransactionRepository._ensure_schema()
        with SessionLocal() as session:
            rows = (
                session.query(BankrollTransactionModel)
                .order_by(BankrollTransactionModel.created_at.desc(), BankrollTransactionModel.id.desc())
                .all()
            )
            return [BankrollTransactionRepository._serialize(row) for row in rows]

    @staticmethod
    def summary() -> dict:
        rows = BankrollTransactionRepository.all()
        deposits = sum(row["amount"] for row in rows if row["transaction_type"] == "Deposit")
        withdrawals = sum(row["amount"] for row in rows if row["transaction_type"] == "Withdrawal")
        return {
            "deposits": round(deposits, 2),
            "withdrawals": round(withdrawals, 2),
            "net": round(deposits - withdrawals, 2),
            "count": len(rows),
            "transactions": rows[:10],
        }

    @staticmethod
    def _serialize(model: BankrollTransactionModel) -> dict:
        return {
            "id": model.id,
            "transaction_type": model.transaction_type,
            "amount": model.amount,
            "note": model.note or "",
            "created_at": iso_utc(model.created_at),
        }
