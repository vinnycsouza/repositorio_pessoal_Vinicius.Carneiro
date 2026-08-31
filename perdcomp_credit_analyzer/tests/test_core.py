from decimal import Decimal
from src.parsers import money
def test_money(): assert money("18.245,95") == Decimal("18245.95")
