from sales import summarize

source = 'region,amount\n"North, East",0.10\nSouth,2.00\n\n"North, East",0.20\nSouth,-0.75\n'
assert summarize(source) == {"North, East": "0.30", "South": "1.25"}
assert summarize("region,amount\n") == {}
assert summarize("region,amount\nx,100000000.01\nx,-100000000.00\n") == {"x": "0.01"}
