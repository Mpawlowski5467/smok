from decimal import Decimal

from invoices.reader import read_rows
from invoices.summary import totals

text = (
    "status,amount,customer,unused\n PAID ,1.005, z ,x\n"
    "paid,-0.005,z,x\npaid,0,a,x\ncancelled,99,a,x\n"
)
assert totals(text) == {"a": "0.00", "z": "1.00"}
assert list(totals(text)) == ["a", "z"]
assert totals("customer,amount,status\nx,1.005,paid\n") == {"x": "1.01"}
assert totals("customer,amount,status\nx,-1.005,paid\n") == {"x": "-1.01"}
assert totals("customer,amount,status\n") == {}
assert isinstance(read_rows("customer,amount,status\nx,1,paid\n")[0]["amount"], Decimal)
for text in [
    "",
    "customer,amount\nx,1\n",
    "customer,amount,status\n,1,paid\n",
    "customer,amount,status\nx,1\n",
]:
    try:
        read_rows(text)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid CSV accepted")
for amount in ["NaN", "Infinity", "-Infinity", "bad", ""]:
    try:
        totals(f"customer,amount,status\nx,{amount},cancelled\n")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid amount accepted")
